#!/usr/bin/env python3
"""Safely copy Spider_XHS source tables into the isolated database.

Stop crawler writes first. Connections are read solely from SOURCE_DATABASE_URL
and TARGET_DATABASE_URL; reports and state never contain credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from collections.abc import Callable
from typing import Any

# Allow both ``python scripts/...`` and module-style execution from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xhs_utils.database import connect, database_config_from_url

TABLES = (("spider_xhs_note", "note_id"), ("spider_xhs_note_snapshot", "id"))


def _config(name: str) -> dict[str, object]:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"环境变量 {name} 未配置")
    return database_config_from_url(value)


def _state(path: Path) -> dict[str, int]:
    if not path.exists():
        return {table: 0 for table, _ in TABLES}
    content = json.loads(path.read_text(encoding="utf-8"))
    return {table: int(content.get(table, 0)) for table, _ in TABLES}


def _save_state(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")


def _table_exists(connection, table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES LIKE %s", (table,))
        return cursor.fetchone() is not None


def _count(connection, table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        return int(cursor.fetchone()[0])


def _assert_snapshot_ids_are_compatible(target, columns: list[str], rows: list[tuple]) -> None:
    """Reject an unrelated target row before an id-based snapshot upsert."""
    id_index = columns.index("id")
    note_id_index = columns.index("note_id")
    task_id_index = columns.index("crawl_task_id")
    source_rows = {int(row[id_index]): row for row in rows}
    placeholders = ", ".join(["%s"] * len(source_rows))
    with target.cursor() as cursor:
        cursor.execute(
            "SELECT id, note_id, crawl_task_id FROM spider_xhs_note_snapshot "
            f"WHERE id IN ({placeholders})",
            tuple(source_rows),
        )
        existing_rows = cursor.fetchall()
    conflicts = []
    for snapshot_id, note_id, crawl_task_id in existing_rows:
        source = source_rows[int(snapshot_id)]
        if str(note_id) != str(source[note_id_index]) or str(crawl_task_id) != str(source[task_id_index]):
            conflicts.append(str(snapshot_id))
    if conflicts:
        raise ValueError(
            "目标库存在与源快照不一致的主键，拒绝覆盖: "
            + ", ".join(conflicts[:10])
        )


def _verify(source, target) -> dict[str, Any]:
    report = {"verified": True, "tables": {}}
    for table, unique_key in TABLES:
        source_count, target_count = _count(source, table), _count(target, table)
        with source.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(DISTINCT `{unique_key}`) FROM `{table}`")
            source_unique = int(cursor.fetchone()[0])
        with target.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(DISTINCT `{unique_key}`) FROM `{table}`")
            target_unique = int(cursor.fetchone()[0])
        result = {"source_count": source_count, "target_count": target_count, "source_unique": source_unique, "target_unique": target_unique}
        result["match"] = source_count == target_count and source_unique == target_unique
        report["tables"][table] = result
        report["verified"] = report["verified"] and result["match"]
    for connection_name, connection in (("source", source), ("target", target)):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(DISTINCT crawl_task_id), COUNT(*), "
                "COALESCE(SUM(liked_count), 0), COALESCE(SUM(collected_count), 0), "
                "COALESCE(SUM(comment_count), 0), COALESCE(SUM(share_count), 0) "
                "FROM spider_xhs_note_snapshot"
            )
            task_count, snapshot_count, liked, collected, comment, share = cursor.fetchone()
        report[f"{connection_name}_snapshot_summary"] = {
            "task_count": int(task_count),
            "snapshot_count": int(snapshot_count),
            "liked_count": int(liked),
            "collected_count": int(collected),
            "comment_count": int(comment),
            "share_count": int(share),
        }
    report["snapshot_summary_match"] = (
        report["source_snapshot_summary"] == report["target_snapshot_summary"]
    )
    report["verified"] = report["verified"] and report["snapshot_summary_match"]
    return report


def _copy_table(
    source,
    target,
    table: str,
    cursor_key: str,
    batch_size: int,
    last_id: int,
    dry_run: bool,
    on_batch_committed: Callable[[int], None] | None = None,
) -> tuple[int, int]:
    copied = 0
    while True:
        with source.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{table}` WHERE id > %s ORDER BY id LIMIT %s", (last_id, batch_size))
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description] if rows else []
        if not rows:
            break
        last_id = int(rows[-1][columns.index("id")])
        copied += len(rows)
        if dry_run:
            continue
        # Notes are deduplicated by their business key.  Do not import the old
        # auto-increment value, which may collide with already-created target rows.
        if table == "spider_xhs_note":
            id_index = columns.index("id")
            rows = [tuple(value for index, value in enumerate(row) if index != id_index) for row in rows]
            columns = [column for column in columns if column != "id"]
        else:
            _assert_snapshot_ids_are_compatible(target, columns, rows)
        placeholders = ", ".join(["%s"] * len(columns))
        quoted_columns = ", ".join(f"`{column}`" for column in columns)
        updates = ", ".join(f"`{column}`=VALUES(`{column}`)" for column in columns if column not in {"id", "created_at"})
        sql = f"INSERT INTO `{table}` ({quoted_columns}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
        with target.cursor() as cursor:
            cursor.executemany(sql, rows)
        target.commit()
        if on_batch_committed:
            on_batch_committed(last_id)
    return copied, last_id


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 Spider_XHS 历史数据（先停止写入）")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--state-file", default=".migration/spider_xhs_progress.json")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 5000:
        parser.error("--batch-size 必须在 1 到 5000 之间")
    source, target = connect(_config("SOURCE_DATABASE_URL")), connect(_config("TARGET_DATABASE_URL"))
    try:
        for table, _ in TABLES:
            if not _table_exists(source, table) or not _table_exists(target, table):
                raise ValueError(f"源库或目标库缺少数据表: {table}")
        if args.verify_only:
            print(json.dumps(_verify(source, target), ensure_ascii=False, sort_keys=True))
            return 0
        state_path, state = Path(args.state_file), _state(Path(args.state_file))
        report: dict[str, Any] = {"dry_run": args.dry_run, "copied": {}}
        for table, key in TABLES:
            def save_progress(last_id: int, *, table: str = table) -> None:
                state[table] = last_id
                _save_state(state_path, state)

            copied, last_id = _copy_table(
                source, target, table, key, args.batch_size, state[table], args.dry_run,
                None if args.dry_run else save_progress,
            )
            report["copied"][table] = copied
            if not args.dry_run:
                state[table] = last_id
                _save_state(state_path, state)
        report["verification"] = _verify(source, target)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["verification"]["verified"] else 2
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    raise SystemExit(main())
