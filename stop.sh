#!/usr/bin/env bash
# Stop only the process recorded by startup.sh.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${APP_DIR}/.runtime/internal-api.pid"

if [[ ! -f "${PID_FILE}" ]]; then
    echo "[提示] Spider_XHS API 未运行（没有 PID 文件）。"
    exit 0
fi

PID="$(<"${PID_FILE}")"
if ! [[ "${PID}" =~ ^[0-9]+$ ]]; then
    echo "[警告] PID 文件内容无效，已删除。" >&2
    rm -f "${PID_FILE}"
    exit 1
fi

if ! kill -0 "${PID}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "[提示] Spider_XHS API 进程已不存在。"
    exit 0
fi

kill "${PID}"
for _ in $(seq 1 10); do
    if ! kill -0 "${PID}" 2>/dev/null; then
        rm -f "${PID_FILE}"
        echo "[完成] Spider_XHS API 已停止。"
        exit 0
    fi
    sleep 1
done

echo "[警告] 进程 ${PID} 未在 10 秒内退出，发送 SIGKILL。" >&2
kill -9 "${PID}"
rm -f "${PID_FILE}"
echo "[完成] Spider_XHS API 已强制停止。"
