from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import AuthContext, get_current_user, require_csrf
from app.enums import ActorType, UserRole
from app.models import AuditEvent, Invitation, User, Workspace
from app.security import (
    as_utc,
    clear_auth_cookies,
    create_user_session,
    hash_password,
    normalize_email,
    password_needs_rehash,
    set_auth_cookies,
    token_digest,
    utc_now,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    username: str
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class AuthView(BaseModel):
    user: UserView
    csrf_token: str
    expires_at: datetime


class AuthStatusView(BaseModel):
    initialized: bool


class BootstrapRequest(BaseModel):
    workspace_name: str = Field(min_length=1, max_length=200)
    username: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=512)

    @model_validator(mode="after")
    def require_username(self) -> BootstrapRequest:
        if not (self.username or self.display_name):
            raise ValueError("请输入用户名")
        return self


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, min_length=1, max_length=320)
    email: EmailStr | None = None
    password: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def require_identifier(self) -> LoginRequest:
        if not (self.identifier or self.email):
            raise ValueError("请输入用户名或邮箱")
        return self


class RegisterRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    username: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=512)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    display_name: str = Field(min_length=1, max_length=120)
    username: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    password: str = Field(min_length=12, max_length=512)


class ProfileUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    new_password: str | None = Field(default=None, min_length=12, max_length=512)
    current_password: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_change(self) -> ProfileUpdateRequest:
        if not ({"username", "email", "new_password"} & self.model_fields_set):
            raise ValueError("至少需要提供一项修改")
        if (self.email is not None or self.new_password is not None) and not self.current_password:
            raise ValueError("修改邮箱或密码前请输入当前密码")
        return self


def _username(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="用户名不能为空")
    return normalized


def _audit(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )


def _identity_conflict(
    db: Session, *, username: str, email: str, exclude_user_id: str | None = None
) -> str | None:
    statement = select(User.id, User.username, User.email).where(
        or_(func.lower(User.username) == username.casefold(), func.lower(User.email) == email)
    )
    if exclude_user_id:
        statement = statement.where(User.id != exclude_user_id)
    existing = db.execute(statement).first()
    if existing is None:
        return None
    if existing.email.casefold() == email:
        return "该邮箱已有账号"
    return "该用户名已被使用"


def _auth_view(
    db: Session,
    response: Response,
    user: User,
    settings: Settings,
) -> AuthView:
    user_session, session_token, csrf_token = create_user_session(
        db, user_id=user.id, settings=settings
    )
    db.flush()
    set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        settings=settings,
    )
    return AuthView(
        user=UserView.model_validate(user),
        csrf_token=csrf_token,
        expires_at=user_session.expires_at,
    )


@router.get("/status", response_model=AuthStatusView)
def auth_status(db: Annotated[Session, Depends(get_db)]) -> AuthStatusView:
    return AuthStatusView(initialized=bool(db.scalar(select(User.id).limit(1))))


@router.post("/bootstrap", response_model=AuthView, status_code=status.HTTP_201_CREATED)
def bootstrap(
    payload: BootstrapRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthView:
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="系统已完成初始化")

    workspace = db.scalar(select(Workspace).order_by(Workspace.created_at, Workspace.id).limit(1))
    if workspace is None:
        workspace = Workspace(
            name=payload.workspace_name.strip(), base_currency=settings.base_currency
        )
        db.add(workspace)
        db.flush()
    else:
        workspace.name = payload.workspace_name.strip()
    username = _username(payload.username or payload.display_name or "")
    user = User(
        workspace_id=workspace.id,
        username=username,
        email=normalize_email(str(payload.email)),
        display_name=username,
        password_hash=hash_password(payload.password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.flush()
    auth = _auth_view(db, response, user, settings)
    _audit(
        db,
        workspace_id=workspace.id,
        actor_id=user.id,
        action="auth.bootstrap",
        entity_type="user",
        entity_id=user.id,
        after={"role": UserRole.ADMIN.value, "username": username},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="系统已完成初始化"
        ) from exc
    return auth


@router.post("/login", response_model=AuthView)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthView:
    identifier = str(payload.identifier or payload.email or "").strip().casefold()
    user = db.scalar(
        select(User).where(
            or_(func.lower(User.username) == identifier, func.lower(User.email) == identifier)
        )
    )
    password_hash = user.password_hash if user else None
    if not verify_password(payload.password, password_hash) or user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱或密码错误",
            headers={"WWW-Authenticate": "Session"},
        )

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    auth = _auth_view(db, response, user, settings)
    _audit(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="auth.login",
        entity_type="user_session",
        entity_id=auth.user.id,
    )
    db.commit()
    return auth


def _register_with_invitation(
    *,
    token: str,
    username: str,
    email: str,
    password: str,
    response: Response,
    db: Session,
    settings: Settings,
) -> AuthView:
    if db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    digest = token_digest(token, settings, "invitation")
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest))
    if (
        invitation is None
        or invitation.accepted_at is not None
        or as_utc(invitation.expires_at) <= utc_now()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请令牌无效、已使用或已过期",
        )

    normalized_username = _username(username)
    normalized_email = normalize_email(email)
    conflict = _identity_conflict(db, username=normalized_username, email=normalized_email)
    if conflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict)

    user = User(
        workspace_id=invitation.workspace_id,
        username=normalized_username,
        email=normalized_email,
        display_name=normalized_username,
        password_hash=hash_password(password),
        role=invitation.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    invitation.accepted_at = utc_now()
    auth = _auth_view(db, response, user, settings)
    _audit(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="invitation.accept",
        entity_type="invitation",
        entity_id=invitation.id,
        after={"user_id": user.id, "role": str(user.role), "username": normalized_username},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在"
        ) from exc
    return auth


@router.post("/register", response_model=AuthView, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthView:
    return _register_with_invitation(
        token=payload.token,
        username=payload.username,
        email=str(payload.email),
        password=payload.password,
        response=response,
        db=db,
        settings=settings,
    )


@router.post("/accept-invitation", response_model=AuthView, status_code=status.HTTP_201_CREATED)
def accept_invitation(
    payload: AcceptInvitationRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthView:
    digest = token_digest(payload.token, settings, "invitation")
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest))
    email = str(payload.email) if payload.email else None
    if email is None and invitation and not invitation.email.endswith("@invite.invalid"):
        email = invitation.email
    if email is None:
        raise HTTPException(status_code=422, detail="请输入邮箱")
    return _register_with_invitation(
        token=payload.token,
        username=payload.username or payload.display_name,
        email=email,
        password=payload.password,
        response=response,
        db=db,
        settings=settings,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    context.session.revoked_at = utc_now()
    _audit(
        db,
        workspace_id=context.user.workspace_id,
        actor_id=context.user.id,
        action="auth.logout",
        entity_type="user_session",
        entity_id=context.session.id,
    )
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response, settings)
    return response


@router.get("/me", response_model=UserView)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.patch("/profile", response_model=UserView)
def update_profile(
    payload: ProfileUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    before: dict[str, object] = {"username": user.username, "email": user.email}
    next_username = _username(payload.username) if payload.username is not None else user.username
    next_email = normalize_email(str(payload.email)) if payload.email is not None else user.email

    if payload.email is not None or payload.new_password is not None:
        if not verify_password(payload.current_password or "", user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")

    conflict = _identity_conflict(
        db,
        username=next_username,
        email=next_email,
        exclude_user_id=user.id,
    )
    if conflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict)

    user.username = next_username
    user.display_name = next_username
    user.email = next_email
    if payload.new_password is not None:
        user.password_hash = hash_password(payload.new_password)
    _audit(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="user.profile.update",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after={
            "username": user.username,
            "email": user.email,
            "password_changed": payload.new_password is not None,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在"
        ) from exc
    db.refresh(user)
    return user
