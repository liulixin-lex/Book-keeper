from importlib.resources import files

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AccountType, CategoryKind
from app.models import (
    Account,
    AIProvider,
    AIWorkspaceSettings,
    Category,
    Workspace,
)

ACCOUNT_SEEDS = [
    ("1002", "银行存款", AccountType.ASSET, "system_funds"),
    ("2202", "应付账款", AccountType.LIABILITY, "payable"),
    ("3104", "利润分配", AccountType.EQUITY, "opening_balance"),
    ("5001", "主营业务收入", AccountType.REVENUE, "operating_revenue"),
    ("5051", "其他业务收入", AccountType.REVENUE, "other_revenue"),
    ("5401", "主营业务成本", AccountType.EXPENSE, "operating_cost"),
    ("5602", "管理费用", AccountType.EXPENSE, "administrative_expense"),
    ("5603", "财务费用", AccountType.EXPENSE, "processing_fee"),
]

CATEGORY_SEEDS = [
    ("主营业务收入", CategoryKind.INCOME, "5001"),
    ("其他业务收入", CategoryKind.INCOME, "5051"),
    ("上游采购", CategoryKind.EXPENSE, "5401"),
    ("账号采购", CategoryKind.EXPENSE, "5401"),
    ("云服务", CategoryKind.EXPENSE, "5602"),
    ("软件订阅", CategoryKind.EXPENSE, "5602"),
    ("交易手续费", CategoryKind.EXPENSE, "5603"),
    ("其他支出", CategoryKind.EXPENSE, "5602"),
]


def get_or_create_workspace(session: Session) -> Workspace:
    workspace = session.scalar(select(Workspace).limit(1))
    if workspace:
        return workspace
    settings = get_settings()
    workspace = Workspace(name="中转站运营账本", base_currency=settings.base_currency)
    session.add(workspace)
    session.flush()
    return workspace


def seed_defaults(session: Session) -> Workspace:
    workspace = get_or_create_workspace(session)
    accounts_by_code: dict[str, Account] = {}
    for code, name, account_type, subtype in ACCOUNT_SEEDS:
        account = session.scalar(
            select(Account).where(Account.workspace_id == workspace.id, Account.code == code)
        )
        if account is None:
            account = Account(
                workspace_id=workspace.id,
                code=code,
                name=name,
                account_type=account_type,
                subtype=subtype,
                currency=(
                    "CNY" if account_type in (AccountType.ASSET, AccountType.LIABILITY) else None
                ),
            )
            session.add(account)
            session.flush()
        accounts_by_code[code] = account

    for name, kind, code in CATEGORY_SEEDS:
        exists = session.scalar(
            select(Category).where(Category.workspace_id == workspace.id, Category.name == name)
        )
        if exists is None:
            session.add(
                Category(
                    workspace_id=workspace.id,
                    account_id=accounts_by_code[code].id,
                    name=name,
                    kind=kind,
                )
            )

    ai_settings = session.get(AIWorkspaceSettings, workspace.id)
    if ai_settings is None:
        session.add(
            AIWorkspaceSettings(
                workspace_id=workspace.id,
                agents_md=(
                    files("app")
                    .joinpath("defaults", "AGENTS.md")
                    .read_text(encoding="utf-8")
                ),
                web_access_enabled=False,
            )
        )

    settings = get_settings()
    if settings.openai_api_key and settings.ai_default_model:
        # Environment bootstrap intentionally creates no secret row.
        existing_provider = session.scalar(
            select(AIProvider).where(
                AIProvider.workspace_id == workspace.id,
                AIProvider.name == "环境变量默认模型",
            )
        )
        if existing_provider is None:
            session.add(
                AIProvider(
                    workspace_id=workspace.id,
                    name="环境变量默认模型",
                    protocol=settings.ai_default_protocol,
                    base_url=settings.ai_default_base_url,
                    model=settings.ai_default_model,
                    encrypted_api_key=None,
                    api_key_source="environment",
                    reasoning_effort=settings.ai_default_effort,
                    capabilities_json={},
                )
            )

    session.commit()
    return workspace
