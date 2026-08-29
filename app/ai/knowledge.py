from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
import sqlite_vec  # type: ignore[import-untyped]
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.ai.crypto import decrypt_api_key, encrypt_api_key
from app.ai.workflow_schemas import EmbeddingProviderCreate, EmbeddingProviderPatch
from app.amounts import from_e8
from app.config import Settings
from app.models import (
    Account,
    AIEmbeddingProvider,
    AuditEvent,
    BusinessRecord,
    JournalEntry,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexJob,
    RecordLink,
    User,
)
from app.services.idempotency import request_digest

CHUNK_SIZE = 1_200
CHUNK_OVERLAP = 120
MAX_INDEX_ATTEMPTS = 5


class KnowledgeError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


class KnowledgeVectorStore(Protocol):
    backend: str

    def upsert(
        self,
        session: Session,
        chunk_id: str,
        vector: list[float],
        index_version: int,
    ) -> None: ...

    def delete(self, session: Session, chunk_id: str, index_version: int) -> None: ...

    def search(
        self,
        session: Session,
        query_vector: list[float],
        index_version: int,
        limit: int,
    ) -> list[tuple[str, float]]: ...


def _driver_connection(session: Session) -> sqlite3.Connection | None:
    raw = session.connection().connection
    driver = getattr(raw, "driver_connection", raw)
    return driver if isinstance(driver, sqlite3.Connection) else None


class SQLiteVecStore:
    backend = "sqlite-vec"

    def _table(self, index_version: int) -> str:
        if index_version < 1:
            raise KnowledgeError("向量索引版本无效")
        return f"knowledge_vec_v{index_version}"

    def _ensure(self, session: Session, index_version: int, dimension: int) -> sqlite3.Connection:
        connection = _driver_connection(session)
        if connection is None:
            raise KnowledgeError("当前数据库不支持 sqlite-vec")
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        table = self._table(index_version)
        connection.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "
            f"USING vec0(chunk_id TEXT PRIMARY KEY, embedding float[{int(dimension)}])"
        )
        return connection

    def upsert(
        self,
        session: Session,
        chunk_id: str,
        vector: list[float],
        index_version: int,
    ) -> None:
        connection = self._ensure(session, index_version, len(vector))
        table = self._table(index_version)
        connection.execute(f"DELETE FROM {table} WHERE chunk_id = ?", (chunk_id,))
        connection.execute(
            f"INSERT INTO {table}(chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, json.dumps(vector, separators=(",", ":"))),
        )

    def delete(self, session: Session, chunk_id: str, index_version: int) -> None:
        connection = _driver_connection(session)
        if connection is None:
            return
        table = self._table(index_version)
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists:
            connection.execute(f"DELETE FROM {table} WHERE chunk_id = ?", (chunk_id,))

    def search(
        self,
        session: Session,
        query_vector: list[float],
        index_version: int,
        limit: int,
    ) -> list[tuple[str, float]]:
        connection = self._ensure(session, index_version, len(query_vector))
        rows = connection.execute(
            f"SELECT chunk_id, distance FROM {self._table(index_version)} "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (json.dumps(query_vector, separators=(",", ":")), limit),
        ).fetchall()
        return [(str(row[0]), float(row[1])) for row in rows]


class JSONVectorStore:
    backend = "json-cosine-fallback"

    def upsert(
        self,
        session: Session,
        chunk_id: str,
        vector: list[float],
        index_version: int,
    ) -> None:
        chunk = session.get(KnowledgeChunk, chunk_id)
        if chunk:
            chunk.embedding_json = vector
            chunk.embedding_index_version = index_version

    def delete(self, session: Session, chunk_id: str, index_version: int) -> None:
        del session, chunk_id, index_version

    def search(
        self,
        session: Session,
        query_vector: list[float],
        index_version: int,
        limit: int,
    ) -> list[tuple[str, float]]:
        chunks = session.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.embedding_index_version == index_version,
                KnowledgeChunk.embedding_json.is_not(None),
            )
        ).all()
        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        scored: list[tuple[str, float]] = []
        for chunk in chunks:
            vector = chunk.embedding_json or []
            if len(vector) != len(query_vector):
                continue
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            similarity = sum(a * b for a, b in zip(query_vector, vector, strict=True))
            similarity /= query_norm * norm
            scored.append((chunk.id, 1 - similarity))
        return sorted(scored, key=lambda item: item[1])[:limit]


def vector_store(session: Session) -> KnowledgeVectorStore:
    try:
        connection = _driver_connection(session)
        if connection is None:
            return JSONVectorStore()
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.execute("SELECT vec_version()").fetchone()
        return SQLiteVecStore()
    except (sqlite3.Error, OSError):
        return JSONVectorStore()


def _embedding_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    if path.endswith("/embeddings"):
        return normalized
    if not path:
        return f"{normalized}/v1/embeddings"
    return f"{normalized}/embeddings"


def _provider_key(provider: AIEmbeddingProvider, settings: Settings) -> str | None:
    if provider.encrypted_api_key:
        return decrypt_api_key(provider.encrypted_api_key, settings.app_secret_key)
    if provider.api_key_source == "environment":
        return settings.embedding_api_key
    return None


def create_embeddings(
    provider: AIEmbeddingProvider,
    texts: list[str],
    settings: Settings,
) -> list[list[float]]:
    if not texts:
        return []
    headers = {"Content-Type": "application/json"}
    api_key = _provider_key(provider, settings)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.post(
            _embedding_url(provider.base_url),
            headers=headers,
            json={"model": provider.model, "input": texts},
            timeout=provider.timeout_seconds,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise KnowledgeError("嵌入服务请求失败", status_code=502) from exc
    if response.is_error:
        raise KnowledgeError(f"嵌入服务返回 HTTP {response.status_code}", status_code=502)
    try:
        body = response.json()
        rows = body["data"]
        vectors = [row["embedding"] for row in sorted(rows, key=lambda row: row["index"])]
    except (KeyError, TypeError, ValueError) as exc:
        raise KnowledgeError("嵌入服务返回了无效结构", status_code=502) from exc
    if len(vectors) != len(texts) or any(
        not isinstance(vector, list) or len(vector) != provider.dimension for vector in vectors
    ):
        raise KnowledgeError("嵌入维度与配置不一致", status_code=409)
    return [[float(value) for value in vector] for vector in vectors]


def embedding_provider_view(provider: AIEmbeddingProvider) -> dict[str, Any]:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "model": provider.model,
        "dimension": provider.dimension,
        "timeout_seconds": provider.timeout_seconds,
        "batch_size": provider.batch_size,
        "is_active": provider.is_active,
        "version": provider.version,
        "index_version": provider.index_version,
        "pending_index_version": provider.pending_index_version,
        "has_api_key": provider.api_key_source != "none",
        "api_key_source": provider.api_key_source,
        "last_tested_at": provider.last_tested_at,
        "last_test_status": provider.last_test_status,
        "last_test_error": provider.last_test_error,
    }


def create_embedding_provider(
    session: Session,
    user: User,
    payload: EmbeddingProviderCreate,
    settings: Settings,
) -> AIEmbeddingProvider:
    duplicate = session.scalar(
        select(AIEmbeddingProvider.id).where(
            AIEmbeddingProvider.workspace_id == user.workspace_id,
            AIEmbeddingProvider.name == payload.name.strip(),
        )
    )
    if duplicate:
        raise KnowledgeError("嵌入供应商名称已存在", status_code=409)
    key_source = "none"
    encrypted = None
    if payload.api_key is not None:
        encrypted = encrypt_api_key(payload.api_key.get_secret_value(), settings.app_secret_key)
        key_source = "database"
    elif payload.use_environment_api_key:
        if not settings.embedding_api_key:
            raise KnowledgeError("EMBEDDING_API_KEY 未配置")
        key_source = "environment"
    if payload.is_active:
        session.query(AIEmbeddingProvider).filter(
            AIEmbeddingProvider.workspace_id == user.workspace_id
        ).update({"is_active": False})
    provider = AIEmbeddingProvider(
        workspace_id=user.workspace_id,
        name=payload.name.strip(),
        base_url=payload.base_url,
        model=payload.model.strip(),
        dimension=payload.dimension,
        encrypted_api_key=encrypted,
        api_key_source=key_source,
        timeout_seconds=payload.timeout_seconds,
        batch_size=payload.batch_size,
        is_active=payload.is_active,
    )
    session.add(provider)
    session.commit()
    session.refresh(provider)
    return provider


def update_embedding_provider(
    session: Session,
    user: User,
    provider: AIEmbeddingProvider,
    payload: EmbeddingProviderPatch,
    settings: Settings,
) -> AIEmbeddingProvider:
    if provider.version != payload.expected_version:
        raise KnowledgeError("嵌入供应商配置已变更", status_code=409)
    before_signature = (provider.model, provider.dimension)
    for name in ("name", "base_url", "model", "dimension", "timeout_seconds", "batch_size"):
        value = getattr(payload, name)
        if value is not None:
            setattr(provider, name, value.strip() if isinstance(value, str) else value)
    if payload.api_key is not None:
        provider.encrypted_api_key = encrypt_api_key(
            payload.api_key.get_secret_value(), settings.app_secret_key
        )
        provider.api_key_source = "database"
    elif payload.use_environment_api_key is True:
        if not settings.embedding_api_key:
            raise KnowledgeError("EMBEDDING_API_KEY 未配置")
        provider.encrypted_api_key = None
        provider.api_key_source = "environment"
    elif payload.clear_api_key or payload.use_environment_api_key is False:
        provider.encrypted_api_key = None
        provider.api_key_source = "none"
    if payload.is_active is True:
        session.query(AIEmbeddingProvider).filter(
            AIEmbeddingProvider.workspace_id == user.workspace_id,
            AIEmbeddingProvider.id != provider.id,
        ).update({"is_active": False})
        provider.is_active = True
    elif payload.is_active is False:
        provider.is_active = False
    provider.version += 1
    if before_signature != (provider.model, provider.dimension):
        enqueue_full_rebuild(session, user.workspace_id, provider)
    session.commit()
    session.refresh(provider)
    return provider


def test_embedding_provider(
    session: Session, provider: AIEmbeddingProvider, settings: Settings
) -> dict[str, Any]:
    started = datetime.now(UTC)
    try:
        create_embeddings(provider, ["记账知识库连接测试"], settings)
        provider.last_test_status = "ok"
        provider.last_test_error = None
        ok = True
        error = None
    except KnowledgeError as exc:
        provider.last_test_status = "failed"
        provider.last_test_error = str(exc)[:500]
        ok = False
        error = str(exc)
    provider.last_tested_at = datetime.now(UTC)
    session.commit()
    return {
        "ok": ok,
        "provider_id": provider.id,
        "dimension": provider.dimension,
        "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        "error": error,
    }


def _ensure_fts(session: Session) -> None:
    session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
            "document_id UNINDEXED, workspace_id UNINDEXED, content_text, "
            "tokenize='unicode61')"
        )
    )


def _record_document(session: Session, workspace_id: str, record_id: str) -> dict[str, Any]:
    record = session.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
            selectinload(BusinessRecord.created_by_user),
        )
        .where(
            BusinessRecord.id == record_id,
            BusinessRecord.workspace_id == workspace_id,
        )
    )
    if record is None:
        raise KnowledgeError("知识实体已不存在", status_code=404)
    entry = (
        session.scalar(
            select(JournalEntry)
            .options(selectinload(JournalEntry.lines))
            .where(JournalEntry.id == record.posted_entry_id)
        )
        if record.posted_entry_id
        else None
    )
    accounts = {
        account.id: {"code": account.code, "name": account.name}
        for account in session.scalars(
            select(Account).where(Account.workspace_id == workspace_id)
        ).all()
    }
    links = session.execute(
        select(
            RecordLink.source_record_id, RecordLink.target_record_id, RecordLink.relation_type
        ).where(
            (RecordLink.source_record_id == record.id) | (RecordLink.target_record_id == record.id)
        )
    ).all()
    audits = session.execute(
        select(AuditEvent.action, AuditEvent.created_at)
        .where(
            AuditEvent.workspace_id == workspace_id,
            AuditEvent.entity_type == "business_record",
            AuditEvent.entity_id == record.id,
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(20)
    ).all()
    payload = {
        "record": {
            "id": record.id,
            "version": record.version,
            "type": str(record.record_type),
            "status": str(record.status),
            "accounting_date": record.accounting_date.isoformat(),
            "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
            "description": record.description,
            "category": (
                {"id": record.category.id, "name": record.category.name}
                if record.category
                else None
            ),
            "provider": (
                {"id": record.counterparty.id, "name": record.counterparty.name}
                if record.counterparty
                else None
            ),
            "channel": record.source_channel,
            "external_id": record.external_id,
            "business_fingerprint": record.business_fingerprint,
            "creator": record.created_by_user.username if record.created_by_user else "AI/system",
            "source_locator": record.source_locator_json,
            "metadata": record.metadata_json,
        },
        "amounts": [
            {
                "role": str(item.role),
                "currency": item.currency,
                "amount": from_e8(item.amount_e8),
                "amount_cny": from_e8(item.amount_cny_e8),
                "fx_rate_id": item.fx_rate_id,
            }
            for item in record.amounts
        ],
        "journal": (
            {
                "entry_id": entry.id,
                "status": str(entry.status),
                "lines": [
                    {
                        "account": accounts.get(line.account_id),
                        "debit_cny": from_e8(line.debit_cny_e8),
                        "credit_cny": from_e8(line.credit_cny_e8),
                        "description": line.description,
                    }
                    for line in entry.lines
                ],
            }
            if entry
            else None
        ),
        "links": [
            {"source_id": row[0], "target_id": row[1], "relation_type": row[2]} for row in links
        ],
        "audit_summary": [{"action": row[0], "at": row[1].isoformat()} for row in audits],
    }
    return {
        "entity_type": "business_record",
        "entity_id": record.id,
        "entity_version": record.version,
        "content": json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        "metadata": {
            "record_type": str(record.record_type),
            "status": str(record.status),
            "accounting_date": record.accounting_date.isoformat(),
        },
    }


def _chunks(content: str) -> list[str]:
    if len(content) <= CHUNK_SIZE:
        return [content]
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        chunks.append(content[start:end])
        if end == len(content):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _active_provider(session: Session, workspace_id: str) -> AIEmbeddingProvider | None:
    return session.scalar(
        select(AIEmbeddingProvider)
        .where(
            AIEmbeddingProvider.workspace_id == workspace_id,
            AIEmbeddingProvider.is_active.is_(True),
        )
        .order_by(AIEmbeddingProvider.updated_at.desc())
    )


def _remove_vectors(
    session: Session, chunks: list[KnowledgeChunk], store: KnowledgeVectorStore
) -> None:
    for chunk in chunks:
        if chunk.embedding_index_version:
            store.delete(session, chunk.id, chunk.embedding_index_version)


def upsert_record_document(
    session: Session,
    workspace_id: str,
    record_id: str,
    settings: Settings,
    *,
    target_index_version: int | None = None,
) -> KnowledgeDocument:
    data = _record_document(session, workspace_id, record_id)
    content_hash = request_digest(data["content"])
    document = session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.entity_type == data["entity_type"],
            KnowledgeDocument.entity_id == record_id,
        )
    )
    if document is None:
        document = KnowledgeDocument(
            workspace_id=workspace_id,
            entity_type=data["entity_type"],
            entity_id=record_id,
            entity_version=data["entity_version"],
            content_hash=content_hash,
            content_text=data["content"],
            metadata_json=data["metadata"],
        )
        session.add(document)
        session.flush()
    else:
        document.entity_version = data["entity_version"]
        document.content_hash = content_hash
        document.content_text = data["content"]
        document.metadata_json = data["metadata"]
        document.deleted_at = None
    store = vector_store(session)
    old_chunks = list(document.chunks)
    _remove_vectors(session, old_chunks, store)
    for chunk in old_chunks:
        session.delete(chunk)
    session.flush()
    content_chunks = _chunks(data["content"])
    provider = _active_provider(session, workspace_id)
    index_version = target_index_version or (provider.index_version if provider else None)
    vectors: list[list[float]] = []
    if provider and index_version:
        for offset in range(0, len(content_chunks), provider.batch_size):
            vectors.extend(
                create_embeddings(
                    provider,
                    content_chunks[offset : offset + provider.batch_size],
                    settings,
                )
            )
    for index, content in enumerate(content_chunks):
        chunk = KnowledgeChunk(
            document_id=document.id,
            chunk_index=index,
            content_text=content,
            content_hash=request_digest(content),
            metadata_json={"start": max(0, index * (CHUNK_SIZE - CHUNK_OVERLAP))},
            embedding_index_version=index_version if vectors else None,
            embedding_json=vectors[index] if vectors else None,
        )
        session.add(chunk)
        session.flush()
        if vectors and index_version:
            store.upsert(session, chunk.id, vectors[index], index_version)
    _ensure_fts(session)
    session.execute(
        text("DELETE FROM knowledge_fts WHERE document_id = :document_id"),
        {"document_id": document.id},
    )
    session.execute(
        text(
            "INSERT INTO knowledge_fts(document_id, workspace_id, content_text) "
            "VALUES (:document_id, :workspace_id, :content_text)"
        ),
        {
            "document_id": document.id,
            "workspace_id": workspace_id,
            "content_text": document.content_text,
        },
    )
    return document


def tombstone_document(
    session: Session, workspace_id: str, entity_type: str, entity_id: str
) -> None:
    document = session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.entity_type == entity_type,
            KnowledgeDocument.entity_id == entity_id,
        )
    )
    if document is None:
        return
    store = vector_store(session)
    _remove_vectors(session, list(document.chunks), store)
    document.deleted_at = datetime.now(UTC)
    _ensure_fts(session)
    session.execute(
        text("DELETE FROM knowledge_fts WHERE document_id = :document_id"),
        {"document_id": document.id},
    )


def enqueue_full_rebuild(
    session: Session,
    workspace_id: str,
    provider: AIEmbeddingProvider | None = None,
) -> dict[str, Any]:
    provider = provider or _active_provider(session, workspace_id)
    target = None
    if provider:
        target = max(provider.index_version + 1, provider.pending_index_version or 0)
        provider.pending_index_version = target
    record_ids = session.scalars(
        select(BusinessRecord.id).where(BusinessRecord.workspace_id == workspace_id)
    ).all()
    now = datetime.now(UTC)
    session.add_all(
        KnowledgeIndexJob(
            workspace_id=workspace_id,
            entity_type="business_record",
            entity_id=record_id,
            action="upsert",
            status="pending",
            available_at=now,
            target_index_version=target,
        )
        for record_id in record_ids
    )
    return {"queued": len(record_ids), "target_index_version": target}


def process_next_index_job(session: Session, settings: Settings) -> bool:
    now = datetime.now(UTC)
    job = session.scalar(
        select(KnowledgeIndexJob)
        .where(
            KnowledgeIndexJob.status == "pending",
            (KnowledgeIndexJob.available_at.is_(None)) | (KnowledgeIndexJob.available_at <= now),
        )
        .order_by(KnowledgeIndexJob.created_at)
        .limit(1)
    )
    if job is None:
        return False
    job.status = "processing"
    job.attempts += 1
    session.commit()
    try:
        if job.action == "tombstone":
            tombstone_document(session, job.workspace_id, job.entity_type, job.entity_id)
        elif job.entity_type == "business_record":
            upsert_record_document(
                session,
                job.workspace_id,
                job.entity_id,
                settings,
                target_index_version=job.target_index_version,
            )
        else:
            raise KnowledgeError("不支持的知识实体类型")
        job.status = "completed"
        job.last_error = None
        if job.target_index_version:
            remaining = session.scalar(
                select(func.count(KnowledgeIndexJob.id)).where(
                    KnowledgeIndexJob.workspace_id == job.workspace_id,
                    KnowledgeIndexJob.target_index_version == job.target_index_version,
                    KnowledgeIndexJob.id != job.id,
                    KnowledgeIndexJob.status != "completed",
                )
            )
            if not remaining:
                provider = session.scalar(
                    select(AIEmbeddingProvider).where(
                        AIEmbeddingProvider.workspace_id == job.workspace_id,
                        AIEmbeddingProvider.pending_index_version == job.target_index_version,
                    )
                )
                if provider:
                    provider.index_version = job.target_index_version
                    provider.pending_index_version = None
        session.commit()
        return True
    except Exception as exc:
        session.rollback()
        failed = session.get(KnowledgeIndexJob, job.id)
        if failed:
            failed.last_error = str(exc)[:2000]
            if failed.attempts >= MAX_INDEX_ATTEMPTS:
                failed.status = "failed"
            else:
                failed.status = "pending"
                failed.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(300, 2**failed.attempts)
                )
            session.commit()
        return True


def knowledge_status(session: Session, workspace_id: str) -> dict[str, Any]:
    document_count = session.scalar(
        select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    chunk_count = session.scalar(
        select(func.count(KnowledgeChunk.id))
        .join(KnowledgeDocument)
        .where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    job_rows = session.execute(
        select(KnowledgeIndexJob.status, func.count(KnowledgeIndexJob.id))
        .where(KnowledgeIndexJob.workspace_id == workspace_id)
        .group_by(KnowledgeIndexJob.status)
    ).all()
    jobs: dict[str, int] = {str(row[0]): int(row[1]) for row in job_rows}
    provider = _active_provider(session, workspace_id)
    return {
        "documents": int(document_count or 0),
        "chunks": int(chunk_count or 0),
        "jobs": jobs,
        "vector_backend": vector_store(session).backend,
        "embedding_provider": embedding_provider_view(provider) if provider else None,
        "fallback_available": True,
    }


def _fts_query(value: str) -> str:
    tokens = [token.replace('"', '""') for token in value.split() if token]
    return " AND ".join(f'"{token}"' for token in tokens)


def search_knowledge(
    session: Session,
    user: User,
    query: str,
    settings: Settings,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    workspace_id = user.workspace_id
    ranks: dict[str, float] = {}
    methods: dict[str, set[str]] = {}

    def add_rank(document_id: str, rank: int, method: str) -> None:
        ranks[document_id] = ranks.get(document_id, 0.0) + 1.0 / (60 + rank)
        methods.setdefault(document_id, set()).add(method)

    exact_records = session.scalars(
        select(BusinessRecord)
        .where(
            BusinessRecord.workspace_id == workspace_id,
            (BusinessRecord.id == query)
            | (BusinessRecord.external_id == query)
            | (BusinessRecord.description.contains(query)),
        )
        .limit(limit)
    ).all()
    exact_ids = [record.id for record in exact_records]
    if exact_ids:
        exact_documents = session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.entity_type == "business_record",
                KnowledgeDocument.entity_id.in_(exact_ids),
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).all()
        by_entity = {document.entity_id: document for document in exact_documents}
        for rank, record_id in enumerate(exact_ids, start=1):
            if record_id in by_entity:
                add_rank(by_entity[record_id].id, rank, "exact_sql")

    _ensure_fts(session)
    fts = _fts_query(query)
    if fts:
        try:
            rows = session.execute(
                text(
                    "SELECT document_id FROM knowledge_fts "
                    "WHERE knowledge_fts MATCH :query AND workspace_id = :workspace_id "
                    "ORDER BY bm25(knowledge_fts) LIMIT :limit"
                ),
                {"query": fts, "workspace_id": workspace_id, "limit": limit * 2},
            ).all()
            for rank, row in enumerate(rows, start=1):
                add_rank(str(row[0]), rank, "fts5")
        except sqlite3.OperationalError:
            pass

    provider = _active_provider(session, workspace_id)
    if provider and provider.last_test_status == "ok":
        vector = create_embeddings(provider, [query], settings)[0]
        for rank, (chunk_id, _distance) in enumerate(
            vector_store(session).search(session, vector, provider.index_version, limit * 2),
            start=1,
        ):
            document_id = session.scalar(
                select(KnowledgeChunk.document_id).where(KnowledgeChunk.id == chunk_id)
            )
            if document_id:
                add_rank(document_id, rank, "vector")

    ordered = sorted(ranks, key=lambda document_id: ranks[document_id], reverse=True)[:limit]
    document_map = {
        item.id: item
        for item in session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id.in_(ordered),
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).all()
    }
    related_ids: set[str] = set()
    entity_ids = [document_map[item].entity_id for item in ordered if item in document_map]
    if entity_ids:
        links = session.execute(
            select(RecordLink.source_record_id, RecordLink.target_record_id).where(
                (RecordLink.source_record_id.in_(entity_ids))
                | (RecordLink.target_record_id.in_(entity_ids))
            )
        ).all()
        for source_id, target_id in links:
            related_ids.update((source_id, target_id))
    results: list[dict[str, Any]] = []
    for document_id in ordered:
        document = document_map.get(document_id)
        if not document:
            continue
        try:
            live = _record_document(session, workspace_id, document.entity_id)
        except KnowledgeError:
            continue
        results.append(
            {
                "entity_type": document.entity_type,
                "entity_id": document.entity_id,
                "entity_version": live["entity_version"],
                "score": ranks[document_id],
                "methods": sorted(methods[document_id]),
                "source": {
                    "document_id": document.id,
                    "content_hash": document.content_hash,
                    "metadata": live["metadata"],
                },
                "related_entity_ids": sorted(related_ids - {document.entity_id}),
                "content": live["content"],
            }
        )
    return {
        "query": query,
        "results": results,
        "authority": "live_sql",
        "vector_used": bool(provider and provider.last_test_status == "ok"),
    }
