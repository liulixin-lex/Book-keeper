from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.approvals import request_approval
from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import AuthContext, require_bookkeeper, require_csrf, require_viewer
from app.enums import ActorType, UserRole
from app.models import AuditEvent, Invitation, User
from app.schemas import ApprovalRequestRead
from app.security import (
    as_utc,
    generate_token,
    normalize_email,
    revoke_user_sessions,
    token_digest,
    utc_now,
)

router = APIRouter(prefix="/users", tags=["users"])


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InvitationCreate(BaseModel):
    email: EmailStr | None = None
    role: UserRole = UserRole.VIEWER


class InvitationView(BaseModel):
    id: str
    email: EmailStr | None
    role: UserRole
    invited_by_id: str
    expires_at: datetime
    accepted_at: datetime | None
    status: str


class InvitationCreated(InvitationView):
    token: str


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> UserUpdate:
        if not self.model_fields_set:
            raise ValueError("至少需要提供一项修改")
        return self


def _invitation_view(invitation: Invitation, now: datetime | None = None) -> InvitationView:
    now = now or utc_now()
    if invitation.accepted_at is not None:
        invitation_status = "accepted"
    elif as_utc(invitation.expires_at) <= now:
        invitation_status = "expired"
    else:
        invitation_status = "pending"
    return InvitationView(
        id=invitation.id,
        email=(None if invitation.email.endswith("@invite.invalid") else invitation.email),
        role=UserRole(invitation.role),
        invited_by_id=invitation.invited_by_id,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        status=invitation_status,
    )


def _audit(
    db: Session,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor_type=ActorType.USER,
            actor_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )


@router.get("", response_model=list[UserView])
def list_users(
    admin: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.workspace_id == admin.workspace_id, User.deleted_at.is_(None))
            .order_by(User.created_at, User.id)
        )
    )


@router.post("/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate,
    admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvitationCreated:
    if payload.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请先邀请为只读用户或记账员，再通过用户权限审批提升为管理员",
        )
    email = normalize_email(str(payload.email)) if payload.email else None
    if email and db.scalar(
        select(User.id).where(func.lower(User.email) == email, User.deleted_at.is_(None))
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已有账号")

    now = utc_now()
    invitation = None
    if email:
        invitation = db.scalar(
            select(Invitation)
            .where(
                Invitation.workspace_id == admin.workspace_id,
                func.lower(Invitation.email) == email,
                Invitation.accepted_at.is_(None),
            )
            .order_by(Invitation.created_at.desc())
        )
    token = generate_token()
    expires_at = now + timedelta(hours=settings.invitation_ttl_hours)
    if invitation is None:
        invitation = Invitation(
            workspace_id=admin.workspace_id,
            email=email or f"token-{token[:18]}@invite.invalid",
            role=payload.role,
            token_hash=token_digest(token, settings, "invitation"),
            invited_by_id=admin.id,
            expires_at=expires_at,
        )
        db.add(invitation)
    else:
        invitation.role = payload.role
        invitation.token_hash = token_digest(token, settings, "invitation")
        invitation.invited_by_id = admin.id
        invitation.expires_at = expires_at

    db.flush()
    _audit(
        db,
        actor=admin,
        action="invitation.issue",
        entity_type="invitation",
        entity_id=invitation.id,
        after={"role": payload.role.value, "expires_at": expires_at.isoformat()},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="无法创建邀请") from exc

    view = _invitation_view(invitation, now)
    return InvitationCreated(**view.model_dump(), token=token)


@router.get("/invitations", response_model=list[InvitationView])
def list_invitations(
    admin: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> list[InvitationView]:
    invitations = db.scalars(
        select(Invitation)
        .where(Invitation.workspace_id == admin.workspace_id)
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
    )
    now = utc_now()
    return [_invitation_view(invitation, now) for invitation in invitations]


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invitation(
    invitation_id: str,
    admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.workspace_id == admin.workspace_id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请不存在")

    before = _invitation_view(invitation).model_dump(mode="json")
    _audit(
        db,
        actor=admin,
        action="invitation.delete",
        entity_type="invitation",
        entity_id=invitation.id,
        before=before,
    )
    db.delete(invitation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class MemberOption(BaseModel):
    id: str
    username: str


@router.get("/options", response_model=list[MemberOption])
def list_member_options(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MemberOption]:
    members = db.scalars(
        select(User)
        .where(
            User.workspace_id == user.workspace_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .order_by(func.lower(User.username), User.id)
    )
    return [MemberOption(id=member.id, username=member.username) for member in members]


@router.patch(
    "/{user_id}",
    response_model=UserView | ApprovalRequestRead,
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": ApprovalRequestRead,
            "description": "角色或账号启停变更已进入审批",
        }
    },
)
def update_user(
    user_id: str,
    payload: UserUpdate,
    response: Response,
    admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> User | ApprovalRequestRead:
    target = db.scalar(
        select(User).where(
            User.id == user_id,
            User.workspace_id == admin.workspace_id,
            User.deleted_at.is_(None),
        )
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if target.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能停用当前账号")

    removes_active_admin = (
        target.is_active
        and UserRole(target.role) == UserRole.ADMIN
        and (payload.role not in (None, UserRole.ADMIN) or payload.is_active is False)
    )
    if removes_active_admin:
        active_admins = db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.workspace_id == admin.workspace_id,
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
        if active_admins == 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="必须保留至少一名有效管理员"
            )

    before = {
        "username": target.username,
        "email": target.email,
        "display_name": target.display_name,
        "role": str(target.role),
        "is_active": target.is_active,
    }
    normalized_username = payload.username.strip() if payload.username is not None else None
    normalized_email = normalize_email(str(payload.email)) if payload.email is not None else None
    if normalized_username is not None or normalized_email is not None:
        conditions = []
        if normalized_username is not None:
            conditions.append(func.lower(User.username) == normalized_username.casefold())
        if normalized_email is not None:
            conditions.append(func.lower(User.email) == normalized_email)
        conflict = db.execute(
            select(User.id, User.username, User.email).where(
                User.id != target.id,
                User.deleted_at.is_(None),
                or_(*conditions),
            )
        ).first()
        if conflict is not None:
            if normalized_email is not None and conflict.email.casefold() == normalized_email:
                detail = "该邮箱已有账号"
            else:
                detail = "该用户名已被使用"
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    if payload.role is not None or payload.is_active is not None:
        changes = payload.model_dump(mode="json", exclude_unset=True)
        if "username" in changes:
            changes["username"] = normalized_username
            changes["display_name"] = changes["username"]
        if "email" in changes:
            changes["email"] = normalized_email
        if "display_name" in changes:
            changes["display_name"] = str(changes["display_name"]).strip()
        response.status_code = status.HTTP_202_ACCEPTED
        return request_approval(
            db,
            requester=admin,
            kind="config.user_permissions.update",
            payload={
                "user_id": target.id,
                "expected": before,
                "changes": changes,
            },
        )

    if payload.username is not None or payload.display_name is not None:
        target.username = (normalized_username or payload.display_name or "").strip()
        target.display_name = target.username
    if normalized_email is not None:
        target.email = normalized_email
    after = {
        "username": target.username,
        "email": target.email,
        "display_name": target.display_name,
        "role": str(target.role),
        "is_active": target.is_active,
    }
    _audit(
        db,
        actor=admin,
        action="user.update",
        entity_type="user",
        entity_id=target.id,
        before=before,
        after=after,
    )
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    target = db.scalar(
        select(User).where(
            User.id == user_id,
            User.workspace_id == admin.workspace_id,
            User.deleted_at.is_(None),
        )
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能删除当前账号")
    if UserRole(target.role) not in (UserRole.BOOKKEEPER, UserRole.VIEWER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能删除记账员或只读用户",
        )

    before = {
        "username": target.username,
        "email": target.email,
        "role": str(target.role),
        "is_active": target.is_active,
    }
    deleted_at = utc_now()
    deleted_label = f"已删除用户-{target.id[:8]}"
    target.username = deleted_label
    target.display_name = deleted_label
    target.email = f"deleted-{target.id}@deleted.invalid"
    target.password_hash = ""
    target.is_active = False
    target.deleted_at = deleted_at
    revoke_user_sessions(db, target.id)
    _audit(
        db,
        actor=admin,
        action="user.delete",
        entity_type="user",
        entity_id=target.id,
        before=before,
        after={"role": str(target.role), "deleted_at": deleted_at.isoformat()},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
