"""Private, read-only HTTP API for the isolated Spider_XHS database."""

from __future__ import annotations

import json
import os
from base64 import urlsafe_b64encode
from datetime import date, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from xhs_utils.database import connect, load_database_config


class NoteIdsRequest(BaseModel):
    note_ids: list[str] = Field(default_factory=list, max_length=500)
    include_missing: bool = False


class TaskIdsRequest(BaseModel):
    crawl_task_ids: list[str] = Field(default_factory=list, max_length=500)
    latest_only: bool = False


class CrawlJobRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    client_task_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    crawl_type: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    credential: str = Field(min_length=1, max_length=4096)


class CrawlClientRegistration(BaseModel):
    client_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    callback_url: str = Field(min_length=1, max_length=1024, pattern=r"^https://")


class CookieValidationRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=4096)


class NoteRepository:
    def __init__(self, config: dict[str, object]):
        self.config = config

    def _rows(self, sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        connection = connect(self.config, dict_cursor=True, autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, values)
                return list(cursor.fetchall())
        finally:
            connection.close()

    def _one(self, sql: str, values: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, values)
        return rows[0] if rows else None

    def list_notes(self, page: int, page_size: int, note_id: str | None = None, crawl_task_id: str | None = None, keyword: str | None = None, sort_by: str | None = None, sort_order: str = "desc") -> tuple[list[dict[str, Any]], int]:
        where, values = [], []
        join = ""
        if note_id:
            where.append("n.note_id = %s")
            values.append(note_id)
        if crawl_task_id:
            join = " INNER JOIN (SELECT DISTINCT note_id FROM spider_xhs_note_snapshot WHERE crawl_task_id = %s) s ON s.note_id = n.note_id"
            values.insert(0, crawl_task_id)
        if keyword:
            where.append("(n.title LIKE %s OR n.`desc` LIKE %s OR n.nickname LIKE %s OR n.note_id LIKE %s OR n.user_id LIKE %s)")
            values.extend([f"%{keyword}%"] * 5)
        clause = " WHERE " + " AND ".join(where) if where else ""
        sortable = {"comment_count", "collected_count", "liked_count", "upload_time", "updated_at"}
        order_column = f"n.{sort_by}" if sort_by in sortable else "n.created_at"
        order_direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        total = self._one(f"SELECT COUNT(*) AS total FROM spider_xhs_note n{join}{clause}", tuple(values))["total"]
        rows = self._rows(
            f"SELECT n.* FROM spider_xhs_note n{join}{clause} ORDER BY {order_column} {order_direction}, n.id DESC LIMIT %s OFFSET %s",
            tuple(values + [page_size, (page - 1) * page_size]),
        )
        return rows, int(total)

    def get_note(self, note_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM spider_xhs_note WHERE note_id = %s", (note_id,))

    def get_note_by_id(self, id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM spider_xhs_note WHERE id = %s", (id,))

    def batch_notes(self, note_ids: list[str]) -> list[dict[str, Any]]:
        if not note_ids:
            return []
        placeholders = ", ".join(["%s"] * len(note_ids))
        return self._rows(f"SELECT * FROM spider_xhs_note WHERE note_id IN ({placeholders})", tuple(note_ids))

    def snapshots_by_task(self, task_ids: list[str], latest_only: bool) -> list[dict[str, Any]]:
        if not task_ids:
            return []
        placeholders = ", ".join(["%s"] * len(task_ids))
        if latest_only:
            return self._rows(
                f"SELECT s.* FROM spider_xhs_note_snapshot s INNER JOIN (SELECT crawl_task_id, note_id, MAX(id) AS id FROM spider_xhs_note_snapshot WHERE crawl_task_id IN ({placeholders}) GROUP BY crawl_task_id, note_id) latest ON latest.id = s.id ORDER BY s.crawl_task_id, s.id",
                tuple(task_ids),
            )
        return self._rows(f"SELECT * FROM spider_xhs_note_snapshot WHERE crawl_task_id IN ({placeholders}) ORDER BY crawl_task_id, id", tuple(task_ids))

    def aggregate_snapshots(self, crawl_task_id: str) -> dict[str, int]:
        row = self._one("SELECT COUNT(*) snapshot_count, COUNT(DISTINCT note_id) note_count, COALESCE(SUM(liked_count), 0) liked_count, COALESCE(SUM(collected_count), 0) collected_count, COALESCE(SUM(comment_count), 0) comment_count, COALESCE(SUM(share_count), 0) share_count, COALESCE(SUM(ai_title_filter_passed), 0) ai_title_filter_passed_count, COALESCE(SUM(cleaning_rule_passed), 0) cleaning_rule_passed_count, COALESCE(SUM(detail_crawl_succeeded), 0) detail_crawl_succeeded_count FROM spider_xhs_note_snapshot WHERE crawl_task_id = %s", (crawl_task_id,))
        return {key: int(value or 0) for key, value in row.items()}

    def overview(self) -> dict[str, int]:
        row = self._one("SELECT COUNT(*) total, COALESCE(SUM(DATE(created_at) = CURDATE()), 0) today_new, COALESCE(SUM(DATE(updated_at) = CURDATE()), 0) today_updated FROM spider_xhs_note")
        return {key: int(value or 0) for key, value in row.items()}

    def daily_count(self, days: int) -> dict[str, Any]:
        start = date.today() - timedelta(days=days - 1)
        before = self._one("SELECT COUNT(*) total_before_start FROM spider_xhs_note WHERE DATE(created_at) < %s", (start,))["total_before_start"]
        rows = self._rows("SELECT DATE(created_at) day, COUNT(*) count FROM spider_xhs_note WHERE DATE(created_at) >= %s GROUP BY DATE(created_at) ORDER BY day", (start,))
        counts = {str(row["day"]): int(row["count"]) for row in rows}
        return {"total_before_start": int(before), "items": [{"date": str(start + timedelta(days=index)), "count": counts.get(str(start + timedelta(days=index)), 0)} for index in range(days)]}

    def _credential_cipher(self) -> Fernet:
        configured = os.getenv("CRAWL_JOB_CREDENTIAL_KEY")
        if configured:
            return Fernet(configured.encode("ascii"))
        # A missing key must never result in plaintext persistence. This deterministic
        # development-only fallback is intentionally rejected outside DEBUG mode.
        if os.getenv("SPIDER_XHS_DEBUG") != "1":
            raise ValueError("CRAWL_JOB_CREDENTIAL_KEY 未配置")
        return Fernet(urlsafe_b64encode(sha256(b"spider-xhs-development-only").digest()))

    def register_client(self, client_id: str, callback_url: str) -> dict[str, str]:
        api_key = token_urlsafe(32)
        webhook_secret = token_urlsafe(32)
        encrypted_webhook_secret = self._credential_cipher().encrypt(webhook_secret.encode("utf-8"))
        connection = connect(self.config, autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO crawl_client (client_id, callback_url, api_key_hash, webhook_secret_ciphertext, is_active) VALUES (%s, %s, %s, %s, 1) "
                    "ON DUPLICATE KEY UPDATE callback_url = VALUES(callback_url), api_key_hash = VALUES(api_key_hash), webhook_secret_ciphertext = VALUES(webhook_secret_ciphertext), is_active = 1, updated_at = CURRENT_TIMESTAMP",
                    (client_id, callback_url, sha256(api_key.encode("utf-8")).hexdigest(), encrypted_webhook_secret),
                )
        finally:
            connection.close()
        return {"client_id": client_id, "callback_url": callback_url, "api_key": api_key, "webhook_secret": webhook_secret}

    def authenticate_client(self, client_id: str, api_key: str) -> bool:
        client = self._one(
            "SELECT api_key_hash FROM crawl_client WHERE client_id = %s AND is_active = 1",
            (client_id,),
        )
        return bool(client and compare_digest(client["api_key_hash"], sha256(api_key.encode("utf-8")).hexdigest()))

    def validate_xhs_cookie(self, credential: str) -> tuple[bool, str]:
        """Validate transient credentials without persisting or echoing them."""
        try:
            from spider.spider import validate_cookies

            valid, _, _ = validate_cookies(credential)
            return bool(valid), "OK" if valid else "AUTH_EXPIRED"
        except Exception:
            return False, "VALIDATION_UNAVAILABLE"

    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._one(
            "SELECT job_id, client_id, client_task_id, status FROM crawl_job "
            "WHERE client_id = %s AND idempotency_key = %s",
            (payload["client_id"], payload["idempotency_key"]),
        )
        if existing:
            return existing
        job_id = str(uuid4())
        encrypted = self._credential_cipher().encrypt(payload["credential"].encode("utf-8"))
        connection = connect(self.config, autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO crawl_job (job_id, client_id, client_task_id, idempotency_key, crawl_type, parameters_json, credential_ciphertext, status) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')",
                    (job_id, payload["client_id"], payload["client_task_id"], payload["idempotency_key"], payload["crawl_type"], json.dumps(payload["parameters"], ensure_ascii=False), encrypted),
                )
        finally:
            connection.close()
        return {"job_id": job_id, "client_id": payload["client_id"], "client_task_id": payload["client_task_id"], "status": "queued"}

    def get_job(self, job_id: str, client_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT job_id, client_task_id, status, result_cursor FROM crawl_job WHERE job_id = %s AND client_id = %s",
            (job_id, client_id),
        )

    def get_results(self, job_id: str, client_id: str, cursor: str | None, limit: int) -> dict[str, Any] | None:
        if not self.get_job(job_id, client_id):
            return None
        after_id = int(cursor or 0)
        rows = self._rows(
            "SELECT id, crawl_task_id, crawl_time, note_id, liked_count, collected_count, comment_count, share_count, ai_title_filter_passed, cleaning_rule_passed, detail_crawl_succeeded "
            "FROM spider_xhs_note_snapshot WHERE crawl_task_id = %s AND id > %s ORDER BY id LIMIT %s",
            (job_id, after_id, limit + 1),
        )
        more = len(rows) > limit
        items = [_serialize(item) for item in rows[:limit]]
        return {"items": items, "next_cursor": str(items[-1]["id"]) if more and items else None}


def _serialize(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("image_list", "tags", "raw_data"):
        if isinstance(result.get(key), str):
            try:
                result[key] = json.loads(result[key])
            except json.JSONDecodeError:
                pass
    for key in ("ai_title_filter_passed", "cleaning_rule_passed", "detail_crawl_succeeded"):
        if key in result:
            result[key] = bool(result[key])
    for key, value in result.items():
        if isinstance(value, (datetime, date)):
            result[key] = value.isoformat()
    return result


def create_app(
    config: dict[str, object] | None = None,
    repository: Any | None = None,
    bootstrap_token: str | None = None,
) -> FastAPI:
    repository = repository or NoteRepository(config or load_database_config())
    configured_bootstrap_token = bootstrap_token if bootstrap_token is not None else os.getenv("SPIDER_XHS_BOOTSTRAP_TOKEN", "")
    api = FastAPI(title="Spider_XHS internal API", docs_url=None, redoc_url=None, openapi_url=None)

    def require_client(
        x_internal_client: str = Header(default="", alias="X-Internal-Client"),
        x_internal_key: str = Header(default="", alias="X-Internal-Key"),
    ) -> str:
        if not x_internal_client or not x_internal_key or not repository.authenticate_client(x_internal_client, x_internal_key):
            raise HTTPException(status_code=401, detail="internal client authentication failed")
        return x_internal_client

    @api.post("/internal/v1/clients", status_code=201)
    def register_client(
        payload: CrawlClientRegistration,
        x_internal_bootstrap_token: str = Header(default="", alias="X-Internal-Bootstrap-Token"),
    ):
        if not configured_bootstrap_token or not compare_digest(x_internal_bootstrap_token, configured_bootstrap_token):
            raise HTTPException(status_code=403, detail="bootstrap access denied")
        return repository.register_client(payload.client_id, payload.callback_url)

    @api.get("/internal/v1/notes")
    def list_notes(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), note_id: str | None = None, crawl_task_id: str | None = None, keyword: str | None = None, sort_by: str | None = None, sort_order: str = Query("desc", pattern="^(asc|desc)$")):
        items, total = repository.list_notes(page, page_size, note_id, crawl_task_id, keyword, sort_by, sort_order)
        return {"items": [_serialize(item) for item in items], "page": page, "page_size": page_size, "total": total}

    @api.post("/internal/v1/crawl-jobs", status_code=202)
    def submit_crawl_job(payload: CrawlJobRequest, client_id: str = Header(default="", alias="X-Internal-Client"), api_key: str = Header(default="", alias="X-Internal-Key")):
        """Persist or return the caller's idempotent asynchronous job."""
        if not client_id or not api_key or not repository.authenticate_client(client_id, api_key):
            raise HTTPException(status_code=401, detail="internal client authentication failed")
        if payload.client_id != client_id:
            raise HTTPException(status_code=403, detail="client identity mismatch")
        job = repository.submit_job(payload.model_dump())
        return {
            "job_id": job["job_id"],
            "client_task_id": job["client_task_id"],
            "status": job["status"],
        }

    @api.post("/internal/v1/xhs/cookie-validations")
    def validate_xhs_cookie(
        payload: CookieValidationRequest,
        client_id: str = Header(default="", alias="X-Internal-Client"),
        api_key: str = Header(default="", alias="X-Internal-Key"),
    ):
        if not client_id or not api_key or not repository.authenticate_client(client_id, api_key):
            raise HTTPException(status_code=401, detail="internal client authentication failed")
        valid, reason_code = repository.validate_xhs_cookie(payload.credential)
        return {"valid": valid, "reason_code": reason_code}

    @api.get("/internal/v1/crawl-jobs/{job_id}")
    def get_crawl_job(job_id: str, x_internal_client: str = Header(default="", alias="X-Internal-Client"), x_internal_key: str = Header(default="", alias="X-Internal-Key")):
        if not repository.authenticate_client(x_internal_client, x_internal_key):
            raise HTTPException(status_code=401, detail="internal client authentication failed")
        job = repository.get_job(job_id, x_internal_client)
        if not job:
            raise HTTPException(status_code=404, detail="crawl job not found")
        return {
            "job_id": job["job_id"], "client_task_id": job["client_task_id"],
            "status": job["status"], "result_cursor": job.get("result_cursor"),
        }

    @api.get("/internal/v1/crawl-jobs/{job_id}/results")
    def get_crawl_job_results(
        job_id: str,
        cursor: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        x_internal_client: str = Header(default="", alias="X-Internal-Client"),
        x_internal_key: str = Header(default="", alias="X-Internal-Key"),
    ):
        if not repository.authenticate_client(x_internal_client, x_internal_key):
            raise HTTPException(status_code=401, detail="internal client authentication failed")
        result = repository.get_results(job_id, x_internal_client, cursor, limit)
        if result is None:
            raise HTTPException(status_code=404, detail="crawl job not found")
        return result

    @api.post("/internal/v1/notes/batch")
    def batch_notes(payload: NoteIdsRequest):
        requested = list(dict.fromkeys(item for item in payload.note_ids if item))
        found = {_serialize(item)["note_id"]: _serialize(item) for item in repository.batch_notes(requested)}
        return {"items": [found[item] for item in requested if item in found], "missing_note_ids": [item for item in requested if item not in found] if payload.include_missing else []}

    @api.get("/internal/v1/notes/by-id/{id}")
    def note_by_id(id: int):
        note = _serialize(repository.get_note_by_id(id))
        if not note:
            raise HTTPException(status_code=404, detail="note not found")
        return note

    @api.get("/internal/v1/notes/{note_id}")
    def note_detail(note_id: str):
        note = _serialize(repository.get_note(note_id))
        if not note:
            raise HTTPException(status_code=404, detail="note not found")
        return note

    @api.post("/internal/v1/snapshots/by-task")
    def snapshots_by_task(payload: TaskIdsRequest):
        return {"items": [_serialize(item) for item in repository.snapshots_by_task(list(dict.fromkeys(payload.crawl_task_ids)), payload.latest_only)]}

    @api.get("/internal/v1/snapshots/aggregate")
    def aggregate_snapshots(crawl_task_id: str = Query(min_length=1)):
        return {"crawl_task_id": crawl_task_id, **repository.aggregate_snapshots(crawl_task_id)}

    @api.get("/internal/v1/metrics/overview")
    def metrics_overview():
        return repository.overview()

    @api.get("/internal/v1/metrics/daily-count")
    def metrics_daily_count(days: int = Query(7, ge=1, le=365)):
        return {"days": days, **repository.daily_count(days)}

    return api


# ``uvicorn internal_api:app`` validates DATABASE_URL at process startup.  Keeping
# imports possible without deployment configuration also makes route tests cheap.
app = create_app() if os.getenv("DATABASE_URL") else FastAPI(title="Spider_XHS internal API", docs_url=None, redoc_url=None, openapi_url=None)
