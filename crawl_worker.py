"""Database-queued Spider_XHS crawl-job worker."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from hashlib import sha256
from hmac import new as hmac_new
from typing import Any
from uuid import uuid4

import requests
from cryptography.fernet import Fernet

from xhs_utils.database import connect, load_database_config


LEASE_SECONDS = 300


def build_crawl_command(job: dict[str, Any], credential: str) -> list[str]:
    """Translate a durable job to the existing Spider_XHS CLI contract."""
    parameters = dict(job.get("parameters") or {})
    command = [sys.executable, "-m", "spider.spider"]
    if job.get("crawl_type") == "direct_note":
        for url in parameters.get("urls") or []:
            command.extend(["--noteUrl", str(url)])
    else:
        command.extend(["--query", str(parameters.get("query") or ""), "--num", str(parameters.get("num") or 20)])
    command.extend(["--taskId", str(job["job_id"]), "--cookies", credential])
    return command


def _cipher() -> Fernet:
    key = os.getenv("CRAWL_JOB_CREDENTIAL_KEY")
    if not key:
        raise RuntimeError("CRAWL_JOB_CREDENTIAL_KEY 未配置")
    return Fernet(key.encode("ascii"))


def claim_next_job(config: dict[str, object]) -> dict[str, Any] | None:
    """Lease one queued job atomically; abandoned running jobs are reclaimed."""
    connection = connect(config, dict_cursor=True)
    try:
        with connection.cursor() as cursor:
            connection.begin()
            cursor.execute(
                "SELECT job_id, client_id, client_task_id, crawl_type, parameters_json, credential_ciphertext, attempt_count "
                "FROM crawl_job WHERE status='queued' OR (status='running' AND lease_until < NOW()) "
                "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
            job = cursor.fetchone()
            if not job:
                connection.commit()
                return None
            job["attempt_number"] = int(job["attempt_count"]) + 1
            cursor.execute(
                "UPDATE crawl_job SET status='running', attempt_count=%s, started_at=COALESCE(started_at,NOW()), "
                "lease_until=DATE_ADD(NOW(), INTERVAL %s SECOND), error_message=NULL WHERE job_id=%s",
                (job["attempt_number"], LEASE_SECONDS, job["job_id"]),
            )
            cursor.execute(
                "INSERT INTO crawl_job_attempt (job_id, attempt_number, status) VALUES (%s,%s,'running')",
                (job["job_id"], job["attempt_number"]),
            )
            connection.commit()
            job["parameters"] = json.loads(job.pop("parameters_json") or "{}")
            return job
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def execute_one_job(config: dict[str, object]) -> bool:
    job = claim_next_job(config)
    if job is None:
        return False
    credential = _cipher().decrypt(job["credential_ciphertext"]).decode("utf-8")
    try:
        # Never log this command because it contains the transient Cookie.
        result = subprocess.run(build_crawl_command(job, credential), check=False)
        _finish_job(config, job, "completed" if result.returncode == 0 else "failed", None if result.returncode == 0 else f"crawler exited with code {result.returncode}")
    except Exception as exc:
        _finish_job(config, job, "failed", str(exc))
    finally:
        credential = ""
    return True


def _finish_job(config: dict[str, object], job: dict[str, Any], status: str, error: str | None) -> None:
    connection = connect(config)
    try:
        with connection.cursor() as cursor:
            connection.begin()
            message = (error or "")[:1024] or None
            cursor.execute(
                "UPDATE crawl_job SET status=%s, completed_at=NOW(), lease_until=NULL, error_message=%s, credential_ciphertext=NULL WHERE job_id=%s",
                (status, message, job["job_id"]),
            )
            cursor.execute(
                "UPDATE crawl_job_attempt SET status=%s, completed_at=NOW(), error_message=%s WHERE job_id=%s AND attempt_number=%s",
                (status, message, job["job_id"], job["attempt_number"]),
            )
            cursor.execute("INSERT INTO crawl_job_delivery (event_id, job_id, status) VALUES (%s,%s,'pending')", (str(uuid4()), job["job_id"]))
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def dispatch_pending_callbacks(config: dict[str, object], limit: int = 50) -> int:
    """Send terminal events with an HMAC; failed requests remain retryable in MySQL."""
    connection = connect(config, dict_cursor=True, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT d.id,d.event_id,d.attempt_count,j.job_id,j.client_task_id,j.status AS job_status,j.error_message,"
                "c.callback_url,c.webhook_secret_ciphertext FROM crawl_job_delivery d "
                "JOIN crawl_job j ON j.job_id=d.job_id JOIN crawl_client c ON c.client_id=j.client_id "
                "WHERE d.status='pending' AND d.next_attempt_at <= NOW() ORDER BY d.id LIMIT %s",
                (limit,),
            )
            deliveries = list(cursor.fetchall())
    finally:
        connection.close()
    delivered = 0
    for item in deliveries:
        payload = {"event_id": item["event_id"], "job_id": item["job_id"], "client_task_id": item["client_task_id"], "status": item["job_status"], "error_message": item["error_message"], "timestamp": int(time.time())}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        secret = _cipher().decrypt(item["webhook_secret_ciphertext"])
        signature = hmac_new(secret, f"{payload['timestamp']}.".encode("utf-8") + body, sha256).hexdigest()
        try:
            response = requests.post(item["callback_url"], data=body, headers={"Content-Type": "application/json", "X-Spider-Timestamp": str(payload["timestamp"]), "X-Spider-Signature": f"sha256={signature}"}, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            _retry_delivery(config, item["id"], int(item["attempt_count"]) + 1)
        else:
            _mark_delivery_delivered(config, item["id"])
            delivered += 1
    return delivered


def _retry_delivery(config: dict[str, object], delivery_id: int, attempts: int) -> None:
    delay = min(3600, 2 ** min(attempts, 10))
    connection = connect(config, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE crawl_job_delivery SET attempt_count=%s,next_attempt_at=DATE_ADD(NOW(), INTERVAL %s SECOND),last_error='callback delivery failed' WHERE id=%s", (attempts, delay, delivery_id))
    finally:
        connection.close()


def _mark_delivery_delivered(config: dict[str, object], delivery_id: int) -> None:
    connection = connect(config, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE crawl_job_delivery SET status='delivered',delivered_at=NOW(),last_error=NULL WHERE id=%s", (delivery_id,))
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    config = load_database_config()
    while True:
        ran = execute_one_job(config)
        dispatch_pending_callbacks(config)
        if args.once:
            return
        if not ran:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
