"""HTTP side of the OAuth 2.1 server (``BK_OAUTH_ENABLED``): discovery metadata, the MCP SDK's
authorize / token / register / revoke handlers on top of ``services.oauth``, and the sign-in and
consent page. Remote MCP clients discover it from the ``WWW-Authenticate`` header of ``/mcp``.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import html
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar
from urllib.parse import unquote, urlsplit

import anyio
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler, ProtectedResourceMetadataHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken, ProtectedResourceMetadata
from pydantic import AnyHttpUrl, AnyUrl
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route, request_response
from starlette.types import ASGIApp

from bookkeeper.config import Settings
from bookkeeper.db.models import OAuthRefreshToken
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.scopes import ROLE_TIERS, TIER_TEXT, Tier
from bookkeeper.security.secrets import random_base62, token_hash
from bookkeeper.services import oauth, ratelimit

T = TypeVar("T")
REGISTRATIONS_PER_HOUR = 20
SIGNINS_PER_10_MIN = 20
BINDING_COOKIE = "bk_oauth"
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer",
}


def issuer(settings: Settings) -> str:
    return settings.public_url.rstrip("/")


def resource_metadata_url(settings: Settings) -> str:
    return issuer(settings) + "/.well-known/oauth-protected-resource/mcp"


class Database:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def _tx(self, fn: Callable[..., T], *args: Any) -> T:
        with self.factory() as session, session.begin():
            return fn(session, *args)

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        return await anyio.to_thread.run_sync(partial(self._tx, fn, *args))


class Provider:
    """``OAuthAuthorizationServerProvider`` backed by ``services.oauth`` (sync DB calls in a worker thread)."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = await self.db.run(oauth.load_client, client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        data = client_info.model_dump(mode="json", exclude_none=True)
        try:
            await self.db.run(oauth.register_client, data, None)
        except oauth.OAuthError as exc:
            raise RegistrationError(error="invalid_redirect_uri", error_description=exc.description) from exc

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        data = {
            "state": params.state,
            "scopes": params.scopes,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        }
        try:
            request = await self.db.run(oauth.create_request, client.client_id, data, self.settings)
        except oauth.OAuthError as exc:
            raise AuthorizeError(error="invalid_target", error_description=exc.description) from exc
        return f"{issuer(self.settings)}/oauth/login?request={request.id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, code: str) -> AuthorizationCode | None:
        def load(session: Session) -> AuthorizationCode | None:
            row = oauth.load_code(session, client.client_id or "", code)
            if row is None:
                return None
            return AuthorizationCode(
                code=code,
                scopes=[],
                expires_at=row.expires_at.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                resource=row.resource,
                subject=row.user_id,
            )

        return await self.db.run(load)

    @staticmethod
    def _token(issued: oauth.IssuedTokens) -> OAuthToken:
        return OAuthToken(
            access_token=issued.access_token,
            token_type="Bearer",  # noqa: S106 - the OAuth token type, not a secret
            expires_in=issued.expires_in,
            refresh_token=issued.refresh_token,
            scope=issued.scope,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        try:
            issued = await self.db.run(
                oauth.exchange_code, self.settings, client.client_id or "", authorization_code.code
            )
        except oauth.OAuthError as exc:
            raise TokenError(error="invalid_grant", error_description=exc.description) from exc
        return self._token(issued)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        def load(session: Session) -> RefreshToken | None:
            row = oauth.load_refresh(session, client.client_id or "", refresh_token)
            if row is None:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=[],
                expires_at=int(row.expires_at.timestamp()),
                resource=row.resource,
                subject=row.user_id,
            )

        return await self.db.run(load)

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        try:
            issued = await self.db.run(
                oauth.exchange_refresh, self.settings, client.client_id or "", refresh_token.token
            )
        except oauth.OAuthError as exc:
            raise TokenError(error="invalid_grant", error_description=exc.description) from exc
        return self._token(issued)

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Used by the revocation endpoint only; /mcp authenticates API tokens itself."""

        def load(session: Session) -> AccessToken | None:
            row = oauth.family_of_access_token(session, None, token)
            if row is None:
                return None
            return AccessToken(token=token, client_id=row.client_id, scopes=[], subject=row.user_id)

        return await self.db.run(load)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        def revoke(session: Session) -> None:
            if isinstance(token, RefreshToken):
                row = session.get(OAuthRefreshToken, token_hash(token.token))
            else:
                row = oauth.family_of_access_token(session, None, token.token)
            if row is not None:
                oauth.revoke_family(session, row.family_id, "client_revocation")

        await self.db.run(revoke)

    async def exchange_identity_assertion(self, client: OAuthClientInformationFull, params: Any) -> OAuthToken:
        raise TokenError(error="unsupported_grant_type", error_description="不支持该授权类型。")


class HashedClientAuthenticator(ClientAuthenticator):
    """Like the SDK authenticator, but the stored secret is a SHA-256 hash (``load_client`` returns it)."""

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        form = await request.form()
        client_id = form.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise AuthenticationError("Missing client_id")
        client = await self.provider.get_client(client_id)
        if client is None:
            raise AuthenticationError("Invalid client_id")
        method = client.token_endpoint_auth_method
        presented: str | None = None
        if method == "client_secret_basic":
            header = request.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                raise AuthenticationError("Missing Basic authentication")
            try:
                basic_id, _, presented = base64.b64decode(header[6:]).decode().partition(":")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise AuthenticationError("Invalid Basic authentication") from exc
            if unquote(basic_id) != client_id:
                raise AuthenticationError("Client ID mismatch")
            presented = unquote(presented)
        elif method == "client_secret_post":
            value = form.get("client_secret")
            presented = value if isinstance(value, str) else None
        elif method != "none":
            raise AuthenticationError(f"Unsupported auth method: {method}")
        if method != "none":
            if not client.client_secret or not presented:
                raise AuthenticationError("Client secret is required")
            if not hmac.compare_digest(token_hash(presented).encode(), client.client_secret.encode()):
                raise AuthenticationError("Invalid client_secret")
        return client


def _cors(handler: Callable[[Request], Any], methods: list[str]) -> ASGIApp:
    return CORSMiddleware(
        request_response(handler), allow_origins="*", allow_methods=methods, allow_headers=["mcp-protocol-version"]
    )


# ------------------------------------------------------------------ sign-in and consent page


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;margin:0;color:#1d2129}}
main{{max-width:420px;margin:8vh auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 12px #0001}}
h1{{font-size:20px;margin:0 0 6px}} p{{color:#4e5969;font-size:14px;line-height:1.6}}
label{{display:block;font-size:14px;margin:14px 0 6px}}
input,select{{width:100%;box-sizing:border-box;padding:10px;border:1px solid #c9cdd4;border-radius:8px;font-size:15px}}
.opt{{display:flex;gap:8px;align-items:flex-start;margin:8px 0;font-size:14px}} .opt input{{width:auto;margin-top:3px}}
.row{{display:flex;gap:10px;margin-top:20px}} button{{flex:1;padding:11px;border:0;border-radius:8px;font-size:15px}}
.primary{{background:#165dff;color:#fff}} .secondary{{background:#f2f3f5;color:#1d2129}}
.err{{background:#fff1f0;color:#cb2634;padding:10px;border-radius:8px;font-size:14px}}
.meta{{font-size:13px;color:#86909c;word-break:break-all}}
</style></head><body><main>{body}</main></body></html>"""
    return HTMLResponse(document, status_code=status, headers=PAGE_HEADERS)


def _header(name: str, redirect_uri: str) -> str:
    host = urlsplit(redirect_uri).netloc
    return (
        f"<h1>授权 {html.escape(name)}</h1>"
        f"<p>该应用请求访问你的 bookkeeper 账本。授权后它将以你的身份按所选级别读取或记账。</p>"
        f'<p class="meta">授权后跳转到：{html.escape(host)}</p>'
    )


def _hidden(request_id: str, csrf: str) -> str:
    return (
        f'<input type="hidden" name="request" value="{html.escape(request_id)}">'
        f'<input type="hidden" name="csrf" value="{html.escape(csrf)}">'
    )


def _signin_form(request_id: str, csrf: str, error: str | None = None) -> str:
    message = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""{message}<form method="post" action="/oauth/login">
{_hidden(request_id, csrf)}
<label>邮箱</label><input name="email" type="email" autocomplete="username" required autofocus>
<label>密码</label><input name="password" type="password" autocomplete="current-password" required>
<div class="row"><button class="secondary" name="action" value="deny" formnovalidate>拒绝</button>
<button class="primary" name="action" value="signin">登录</button></div></form>"""


def _consent_form(request_id: str, csrf: str, books: list[tuple[Any, Any]], days: int, error: str | None) -> str:
    message = f'<p class="err">{html.escape(error)}</p>' if error else ""
    if not books:
        return message + "<p class='err'>你还不是任何账套的成员，无法授权。</p>"
    options = "".join(
        f'<option value="{html.escape(book.id)}">{html.escape(book.name)}（{html.escape(role.value)}）</option>'
        for book, role in books
    )
    best_role = max((role for _b, role in books), key=lambda r: len(ROLE_TIERS[r]))
    allowed = ROLE_TIERS[best_role]
    default = Tier.USER_WRITE if Tier.USER_WRITE in allowed else allowed[0]
    tiers = "".join(
        f'<label class="opt"><input type="radio" name="tier" value="{t.value}"'
        f"{' checked' if t is default else ''}>"
        f"<span>{html.escape(TIER_TEXT[t][0])}：{html.escape(TIER_TEXT[t][1])}</span></label>"
        for t in allowed
    )
    return f"""{message}<form method="post" action="/oauth/login">
{_hidden(request_id, csrf)}
<label>账套</label><select name="book">{options}</select>
<label>权限档位</label>{tiers}
<p class="meta">访问令牌有效 {days} 天，到期自动续期；可随时在令牌管理中吊销。</p>
<div class="row"><button class="secondary" name="action" value="deny">拒绝</button>
<button class="primary" name="action" value="approve">授权</button></div></form>"""


class LoginPage:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.iss = str(AnyHttpUrl(issuer(settings)))  # rendered exactly like the metadata ``issuer``

    def _secure(self) -> bool:
        return self.settings.public_url.startswith("https://")

    async def handle(self, request: Request) -> Response:
        if request.method == "GET":
            return await self._show(request.query_params.get("request", ""), request.cookies.get(BINDING_COOKIE))
        form = await request.form()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        ip = request.client.host if request.client else None
        try:
            return await self._submit(fields, request.cookies.get(BINDING_COOKIE), ip)
        except DomainError as exc:
            return _page("授权失败", f'<h1>授权失败</h1><p class="err">{html.escape(exc.detail)}</p>', 400)

    async def _show(
        self, request_id: str, binding: str | None, error: str | None = None, status: int = 200
    ) -> Response:
        def load(session: Session) -> tuple[str, str, str, str | None, Any]:
            req = oauth.pending_request(session, request_id)
            bound = req.user_id is not None and binding is not None and req.params.get("binding") == token_hash(binding)
            books = oauth.memberships(session, req.user_id) if bound and req.user_id else None
            return req.id, req.csrf, req.params["redirect_uri"], oauth.client_name(session, req.client_id), books

        try:
            rid, csrf, redirect_uri, name, books = await self.db.run(load)
        except DomainError as exc:
            return _page("授权失败", f'<h1>授权失败</h1><p class="err">{html.escape(exc.detail)}</p>', 400)
        head = _header(name or "", redirect_uri)
        if books is None:
            return _page("登录以授权", head + _signin_form(rid, csrf, error), status)
        return _page("确认授权", head + _consent_form(rid, csrf, books, self.settings.oauth_access_days, error), status)

    async def _submit(self, fields: dict[str, str], binding: str | None, ip: str | None) -> Response:
        request_id, csrf, action = fields.get("request", ""), fields.get("csrf", ""), fields.get("action", "")
        if action == "deny":
            url = await self.db.run(lambda s: oauth.deny(s, oauth.pending_request(s, request_id, csrf), self.iss))
            return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})
        if action == "signin":
            secret = random_base62(32)

            def signin(session: Session) -> DomainError | None:
                req = oauth.pending_request(session, request_id, csrf)
                ratelimit.hit(session, f"oauth-signin:{ip}", SIGNINS_PER_10_MIN, window=600)  # spraying guard
                error = oauth.sign_in(
                    session, self.settings, req, fields.get("email", ""), fields.get("password", ""), ip
                )
                if error is None:
                    req.params = dict(req.params) | {"binding": token_hash(secret)}
                return error  # failures are committed too (lockout counters, audit)

            try:
                error = await self.db.run(signin)
            except DomainError as exc:
                if exc.code != "RATE_LIMITED":
                    raise
                return await self._show(request_id, None, "尝试次数过多，请稍后再试。", 429)
            if error is not None:
                return await self._show(request_id, None, error.detail, 429 if error.code == "ACCOUNT_LOCKED" else 401)
            response = RedirectResponse(f"/oauth/login?request={request_id}", status_code=303)
            response.set_cookie(
                BINDING_COOKIE, secret, max_age=600, httponly=True, secure=self._secure(), samesite="lax", path="/oauth"
            )
            return response
        if action == "approve":

            def approve(session: Session) -> str:
                req = oauth.pending_request(session, request_id, csrf)
                if binding is None or req.params.get("binding") != token_hash(binding):
                    raise DomainError("UNAUTHENTICATED", "登录状态已失效，请在本页重新登录。")
                return oauth.approve(session, req, fields.get("book", ""), fields.get("tier", ""), ip, self.iss)

            try:
                url = await self.db.run(approve)
            except DomainError as exc:
                if exc.code in ("FORBIDDEN_SCOPE", "VALIDATION_FAILED"):
                    return await self._show(request_id, binding, exc.detail, 403)
                raise
            response = RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})
            response.delete_cookie(BINDING_COOKIE, path="/oauth")
            return response
        raise DomainError("VALIDATION_FAILED", "未知操作。")


# ------------------------------------------------------------------ routes


def routes(factory: sessionmaker[Session], settings: Settings) -> list[Route]:
    db = Database(factory)
    provider = Provider(db, settings)
    authenticator = HashedClientAuthenticator(provider)
    base = issuer(settings)
    metadata = OAuthMetadata(
        issuer=AnyHttpUrl(base),
        authorization_endpoint=AnyHttpUrl(base + "/oauth/authorize"),
        token_endpoint=AnyHttpUrl(base + "/oauth/token"),
        registration_endpoint=AnyHttpUrl(base + "/oauth/register"),
        revocation_endpoint=AnyHttpUrl(base + "/oauth/revoke"),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post", "client_secret_basic"],
        revocation_endpoint_auth_methods_supported=["none", "client_secret_post", "client_secret_basic"],
        code_challenge_methods_supported=["S256"],
        authorization_response_iss_parameter_supported=True,
    )
    resource = ProtectedResourceMetadata(
        resource=AnyHttpUrl(oauth.mcp_resource(settings)),
        authorization_servers=[AnyHttpUrl(base)],
        resource_name="bookkeeper",
    )
    registration = RegistrationHandler(provider, options=ClientRegistrationOptions(enabled=True))

    async def register(request: Request) -> Response:
        ip = request.client.host if request.client else "unknown"
        try:
            await db.run(lambda s: ratelimit.hit(s, f"oauth-register:{ip}", REGISTRATIONS_PER_HOUR, window=3600))
        except DomainError:
            return JSONResponse(
                {"error": "temporarily_unavailable", "error_description": "注册过于频繁，请稍后再试。"}, status_code=429
            )
        return await registration.handle(request)

    async def revoke(request: Request) -> Response:
        """RFC 7009: revoke the whole grant behind an access or refresh token; unknown tokens are not an error.

        (The SDK handler requires a ``client_secret`` field even from public clients, so it is not used.)
        """
        try:
            client = await authenticator.authenticate_request(request)
        except AuthenticationError as exc:
            return JSONResponse({"error": "invalid_client", "error_description": exc.message}, status_code=401)
        form = await request.form()
        value = form.get("token")
        if not isinstance(value, str) or not value:
            return JSONResponse({"error": "invalid_request", "error_description": "缺少 token"}, status_code=400)

        def run(session: Session) -> None:
            row = session.get(OAuthRefreshToken, token_hash(value)) or oauth.family_of_access_token(
                session, None, value
            )
            if row is not None and row.client_id == client.client_id:
                oauth.revoke_family(session, row.family_id, "client_revocation")

        await db.run(run)
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    resource_handler = ProtectedResourceMetadataHandler(resource).handle
    return [
        Route("/.well-known/oauth-authorization-server", _cors(MetadataHandler(metadata).handle, ["GET", "OPTIONS"])),
        Route("/.well-known/oauth-protected-resource", _cors(resource_handler, ["GET", "OPTIONS"])),
        Route("/.well-known/oauth-protected-resource/mcp", _cors(resource_handler, ["GET", "OPTIONS"])),
        Route(
            "/oauth/authorize",
            AuthorizationHandler(provider).handle,
            methods=["GET", "POST"],
        ),
        Route(
            "/oauth/token",
            _cors(TokenHandler(provider, authenticator).handle, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        ),
        Route("/oauth/register", _cors(register, ["POST", "OPTIONS"]), methods=["POST", "OPTIONS"]),
        Route("/oauth/revoke", _cors(revoke, ["POST", "OPTIONS"]), methods=["POST", "OPTIONS"]),
        Route("/oauth/login", LoginPage(db, settings).handle, methods=["GET", "POST"]),
    ]
