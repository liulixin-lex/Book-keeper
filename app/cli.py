from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import select

from alembic import command
from app.db import SessionLocal, validate_sqlite_runtime
from app.enums import UserRole
from app.models import User
from app.services.backup import create_backup, restore_backup, verify_backup
from app.services.seed import seed_defaults


def run_upgrade() -> None:
    validate_sqlite_runtime()
    command.upgrade(Config("alembic.ini"), "head")
    with SessionLocal() as session:
        seed_defaults(session)


def create_admin(email: str, username: str, password: str | None) -> None:
    from app.security import hash_password

    run_upgrade()
    secret = password or getpass.getpass("Admin password: ")
    if len(secret) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    with SessionLocal() as session:
        workspace = seed_defaults(session)
        exists = session.scalar(select(User).where(User.email == email.lower()))
        if exists:
            raise SystemExit("A user with this email already exists")
        session.add(
            User(
                workspace_id=workspace.id,
                username=username.strip(),
                email=email.lower(),
                display_name=username.strip(),
                password_hash=hash_password(secret),
                role=UserRole.ADMIN,
            )
        )
        session.commit()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Transit ledger administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Run migrations and seed the chart of accounts")

    admin_parser = subparsers.add_parser("create-admin", help="Create the initial administrator")
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--name", required=True)
    admin_parser.add_argument("--password")

    subparsers.add_parser("backup", help="Create and verify an online SQLite backup")

    restore_parser = subparsers.add_parser(
        "restore", help="Restore a verified backup while the API is stopped"
    )
    restore_parser.add_argument("--file", type=Path, required=True)

    migrate_parser = subparsers.add_parser("migrate-legacy", help="Import the legacy workbooks")
    migrate_parser.add_argument("--source", type=Path, default=Path.cwd())

    args = parser.parse_args()
    if args.command == "init-db":
        run_upgrade()
        print("Database initialized")
    elif args.command == "create-admin":
        create_admin(args.email, args.name, args.password)
        print("Administrator created")
    elif args.command == "backup":
        path = create_backup()
        if not verify_backup(path):
            raise SystemExit("Backup verification failed")
        print(path)
    elif args.command == "restore":
        print(restore_backup(args.file))
    elif args.command == "migrate-legacy":
        from app.legacy.legacy_service import migrate_legacy_workbooks

        result = migrate_legacy_workbooks(args.source)
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
