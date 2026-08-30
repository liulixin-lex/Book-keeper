from fastapi import APIRouter

from app.api import (
    ai,
    ai_workbench,
    approvals,
    audit,
    auth,
    backups,
    catalog,
    records,
    reports,
    subscriptions,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(backups.router)
api_router.include_router(users.router)
api_router.include_router(records.router)
api_router.include_router(reports.router)
api_router.include_router(catalog.router)
api_router.include_router(audit.router)
api_router.include_router(ai.router)
api_router.include_router(ai_workbench.router)
api_router.include_router(approvals.router)
api_router.include_router(subscriptions.router)
