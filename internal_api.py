"""Private, read-only HTTP API for the isolated Spider_XHS database."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from xhs_utils.database import connect, load_database_config


class NoteIdsRequest(BaseModel):
    note_ids: list[str] = Field(default_factory=list, max_length=500)
    include_missing: bool = False


class TaskIdsRequest(BaseModel):
    crawl_task_ids: list[str] = Field(default_factory=list, max_length=500)
    latest_only: bool = False


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


def create_app(config: dict[str, object] | None = None) -> FastAPI:
    repository = NoteRepository(config or load_database_config())
    api = FastAPI(title="Spider_XHS internal API", docs_url=None, redoc_url=None, openapi_url=None)

    @api.get("/internal/v1/notes")
    def list_notes(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), note_id: str | None = None, crawl_task_id: str | None = None, keyword: str | None = None, sort_by: str | None = None, sort_order: str = Query("desc", pattern="^(asc|desc)$")):
        items, total = repository.list_notes(page, page_size, note_id, crawl_task_id, keyword, sort_by, sort_order)
        return {"items": [_serialize(item) for item in items], "page": page, "page_size": page_size, "total": total}

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
