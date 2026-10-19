"""Command line: ``bookkeeper <command>`` (docs/10-security-operations.md §5)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.request
from collections.abc import Sequence

from bookkeeper import __version__


def _cli_context(book_id: str | None = None):  # type: ignore[no-untyped-def]
    from bookkeeper.services.context import Actor, RequestContext

    return RequestContext(actor=Actor.system(), channel="cli", book_id=book_id)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "bookkeeper.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
        access_log=False,
        log_config=None,
    )
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from bookkeeper.config import get_settings
    from bookkeeper.db.session import get_sessionmaker
    from bookkeeper.jobs.worker import Worker
    from bookkeeper.logging import configure_logging

    settings = get_settings()
    settings.ensure_deployable()
    configure_logging(settings.log_level, settings.log_json)
    worker = Worker(
        get_sessionmaker(),
        poll_seconds=settings.worker_poll_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
    )
    worker.run_forever()
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    from bookkeeper.paths import ALEMBIC_INI

    command.upgrade(Config(str(ALEMBIC_INI)), args.revision)
    from sqlalchemy import create_engine

    from bookkeeper.config import get_settings
    from bookkeeper.db.roles import grant_app_role

    engine = create_engine(get_settings().effective_migration_url())
    with engine.begin() as conn:
        granted = grant_app_role(conn)
    engine.dispose()
    print("migrated; app role grants " + ("applied" if granted else "skipped (role bk_app absent)"))
    return 0


def _read_password(env_var: str) -> str:
    value = os.environ.get(env_var)
    if value:
        return value
    first = getpass.getpass("密码: ")
    if first != getpass.getpass("再次输入: "):
        raise SystemExit("两次输入的密码不一致")
    return first


def cmd_create_user(args: argparse.Namespace) -> int:
    from bookkeeper.db.session import session_scope
    from bookkeeper.services import identity

    password = _read_password("BK_NEW_PASSWORD")
    with session_scope() as session:
        user = identity.create_user(
            session,
            _cli_context(),
            email=args.email,
            display_name=args.name,
            password=password,
            is_superadmin=args.superadmin,
        )
        print(json.dumps(identity.user_view(user), ensure_ascii=False))
    return 0


def cmd_create_book(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from bookkeeper.db.models import User
    from bookkeeper.db.session import session_scope
    from bookkeeper.services import books

    with session_scope() as session:
        owner = session.execute(select(User).where(User.email == args.owner_email.lower())).scalar_one()
        book = books.create_book(
            session,
            _cli_context(),
            name=args.name,
            base_commodity=args.base,
            timezone=args.timezone,
            owner_user_id=owner.id,
        )
        print(json.dumps(books.book_view(book), ensure_ascii=False))
    return 0


def cmd_create_token(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from bookkeeper.db.models import User
    from bookkeeper.db.session import session_scope
    from bookkeeper.domain.scopes import ROLE_CAPS, Preset
    from bookkeeper.services import identity, tokens
    from bookkeeper.services.context import Actor, RequestContext

    with session_scope() as session:
        user = session.execute(select(User).where(User.email == args.user_email.lower())).scalar_one()
        role = identity.member_role(session, args.book, user.id)
        if role is None:
            raise SystemExit("该用户不是账套成员")
        ctx = RequestContext(
            actor=Actor(type="user", user_id=user.id, role=role, scopes=ROLE_CAPS[role]),
            channel="cli",
            book_id=args.book,
        )
        issued = tokens.create_token(
            session,
            ctx,
            name=args.name,
            preset=Preset(args.preset),
            mcp_enabled=args.mcp,
            expires_in_days=args.days,
        )
        print(json.dumps(tokens.token_view(issued.token) | {"token": issued.plaintext}, ensure_ascii=False))
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    from bookkeeper.db.session import session_scope
    from bookkeeper.services import identity

    password = _read_password("BK_NEW_PASSWORD")
    with session_scope() as session:
        user = identity.reset_password(session, _cli_context(), args.email, password)
        print(json.dumps(identity.user_view(user), ensure_ascii=False))
    return 0


def cmd_run_checks(args: argparse.Namespace) -> int:
    """Run ledger checks for one book or all books; exit 1 when any error-level check fails."""
    from sqlalchemy import select

    from bookkeeper.db.models import Book
    from bookkeeper.db.session import session_scope
    from bookkeeper.services import checks

    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None
    failed = False
    with session_scope() as session:
        book_ids = (
            [args.book] if args.book else list(session.execute(select(Book.id).order_by(Book.created_at)).scalars())
        )
        for book_id in book_ids:
            run = checks.run_checks(session, _cli_context(book_id), codes, trigger="manual")
            failed |= run.status != "passed"
            print(json.dumps(checks.run_view(session, run), ensure_ascii=False, default=str))
    return 1 if failed else 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write an export of one book to a file (stdout when --output is '-')."""
    from datetime import date

    from bookkeeper.db.session import session_scope
    from bookkeeper.services import exports

    date_from = date.fromisoformat(args.date_from) if args.date_from else None
    date_to = date.fromisoformat(args.date_to) if args.date_to else None
    with session_scope() as session:
        if args.output == "-":
            info = exports.export_to(
                session, _cli_context(args.book), args.format, sys.stdout.buffer, date_from, date_to
            )
        else:
            with open(args.output, "wb") as fh:
                info = exports.export_to(session, _cli_context(args.book), args.format, fh, date_from, date_to)
    print(f"导出 {info['lines']} 行 → {args.output}", file=sys.stderr)
    return 0


def cmd_verify_audit(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from bookkeeper.db.models import AuditHead
    from bookkeeper.db.session import session_scope
    from bookkeeper.services import audit

    failed = False
    with session_scope() as session:
        scopes = [args.scope] if args.scope else list(session.execute(select(AuditHead.scope)).scalars())
        for scope in scopes:
            result = audit.verify_chain(session, scope)
            failed |= not result.ok
            print(json.dumps(result.__dict__, ensure_ascii=False))
    return 1 if failed else 0


def cmd_legacy_migrate(args: argparse.Namespace) -> int:
    """v1 SQLite → v2 book. Dry run by default; --apply commits. Writes a Markdown + JSON report."""
    from pathlib import Path

    from bookkeeper.config import get_settings
    from bookkeeper.db.session import get_sessionmaker
    from bookkeeper.files.storage import ContentStore
    from bookkeeper.migration import legacy_v1

    source = Path(args.source)
    if not source.is_file():
        print(f"找不到旧库文件：{source}", file=sys.stderr)
        return 2
    session = get_sessionmaker()()
    try:
        session.begin()
        report = legacy_v1.migrate(
            session,
            source,
            book_id=args.book_id,
            book_name=args.book_name,
            owner_email=args.owner_email,
            dry_run=not args.apply,
            subcent_policy=args.subcent,
            files_dir=Path(args.files_dir) if args.files_dir else None,
            names=legacy_v1.Names.load(Path(args.mappings) if args.mappings else None),
            store=ContentStore(get_settings().files_dir) if args.apply else None,
        )
        if args.apply and all(c["ok"] for c in report.checks.values()):
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = "apply" if args.apply else "dry-run"
    (out / f"migration-{stamp}.md").write_text(legacy_v1.render_markdown(report), encoding="utf-8")
    (out / f"migration-{stamp}.json").write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    failed = [code for code, check in report.checks.items() if not check["ok"]]
    print(
        f"{'正式迁移' if args.apply else '试迁移'}完成：账套 {report.book_id}，"
        f"迁移 {report.counts.get('migrated', 0)} / {report.counts.get('records', 0)}，未迁移 {len(report.anomalies)}"
    )
    if failed:
        print(f"核对未通过：{', '.join(failed)}" + ("（未提交）" if args.apply else ""), file=sys.stderr)
        return 1
    print(f"报告：{out}/migration-{stamp}.md")
    return 0


def cmd_healthcheck(args: argparse.Namespace) -> int:
    if args.worker:  # the worker has no HTTP endpoint: healthy when this host's heartbeat is recent
        import socket
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import func, select

        from bookkeeper.config import get_settings
        from bookkeeper.db.models import WorkerHeartbeat
        from bookkeeper.db.session import session_scope

        limit = timedelta(seconds=3 * get_settings().worker_heartbeat_seconds + 10)
        try:
            with session_scope() as session:
                last = session.execute(
                    select(func.max(WorkerHeartbeat.beat_at)).where(WorkerHeartbeat.hostname == socket.gethostname())
                ).scalar_one()
        except Exception:  # any failure (database down, …) means unhealthy
            return 1
        return 0 if last is not None and datetime.now(UTC) - last < limit else 1
    try:
        with urllib.request.urlopen(args.url, timeout=5) as response:  # noqa: S310
            return 0 if response.status == 200 else 1
    except OSError:
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bookkeeper", description="bookkeeper v2")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="启动 API 服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    p.set_defaults(fn=cmd_serve)

    sub.add_parser("worker", help="启动后台任务进程").set_defaults(fn=cmd_worker)

    p = sub.add_parser("migrate", help="执行数据库迁移")
    p.add_argument("revision", nargs="?", default="head")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("create-user", help="创建用户（密码取自 BK_NEW_PASSWORD 或交互输入）")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--superadmin", action="store_true")
    p.set_defaults(fn=cmd_create_user)

    p = sub.add_parser("create-book", help="创建账套")
    p.add_argument("--name", required=True)
    p.add_argument("--owner-email", required=True)
    p.add_argument("--base", default="CNY")
    p.add_argument("--timezone", default="Asia/Shanghai")
    p.set_defaults(fn=cmd_create_book)

    p = sub.add_parser("create-token", help="为账套成员创建 API 令牌")
    p.add_argument("--book", required=True)
    p.add_argument("--user-email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--preset", default="reader", choices=["reader", "bookkeeper", "admin"])
    p.add_argument("--mcp", action="store_true")
    p.add_argument("--days", type=int, default=None)
    p.set_defaults(fn=cmd_create_token)

    p = sub.add_parser("reset-password", help="重置用户密码并解除锁定（密码取自 BK_NEW_PASSWORD 或交互输入）")
    p.add_argument("--email", required=True)
    p.set_defaults(fn=cmd_reset_password)

    p = sub.add_parser("run-checks", help="运行账套检查（默认全部账套、全部检查）")
    p.add_argument("--book", default=None)
    p.add_argument("--codes", default=None, help="逗号分隔的检查代码")
    p.set_defaults(fn=cmd_run_checks)

    p = sub.add_parser("export", help="导出账本（csv / xlsx / beancount / json）")
    p.add_argument("--book", required=True)
    p.add_argument("--format", required=True, choices=["csv", "xlsx", "beancount", "json"])
    p.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD")
    p.add_argument("--output", required=True, help="输出文件；- 表示标准输出")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("verify-audit", help="校验审计哈希链")
    p.add_argument("--scope", default=None)
    p.set_defaults(fn=cmd_verify_audit)

    p = sub.add_parser("legacy-migrate", help="把 v1 账本（SQLite）迁移到 v2 账套（默认试迁移）")
    p.add_argument("--source", required=True, help="v1 数据库文件")
    p.add_argument("--book-id", help="写入已有的空账套；省略则新建")
    p.add_argument("--book-name", help="新建账套的名称")
    p.add_argument("--owner-email", help="账套所有者（默认 v1 的管理员）")
    p.add_argument(
        "--subcent",
        choices=["round", "anomaly"],
        default="round",
        help="超出分位的金额：舍入并列入报告，或不迁移并列入问题清单",
    )
    p.add_argument("--files-dir", default=None, help="v1 来源文件原件所在目录（按文件名与 SHA-256 核验后附加）")
    p.add_argument("--mappings", default=None, help="本地往来方映射 JSON（自有的改名与站点别名，不放进代码库）")
    p.add_argument("--apply", action="store_true", help="正式迁移（核对全部通过才提交）")
    p.add_argument("--report-dir", default="migration-report", help="报告输出目录")
    p.set_defaults(fn=cmd_legacy_migrate)

    p = sub.add_parser("healthcheck", help="容器健康检查")
    p.add_argument("--url", default="http://127.0.0.1:8000/healthz")
    p.add_argument("--worker", action="store_true", help="检查本容器 worker 的心跳（无 HTTP 服务）")
    p.set_defaults(fn=cmd_healthcheck)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from bookkeeper.domain.errors import DomainError

    args = build_parser().parse_args(argv)
    try:
        result: int = args.fn(args)
    except DomainError as exc:
        print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    sys.exit(main())
