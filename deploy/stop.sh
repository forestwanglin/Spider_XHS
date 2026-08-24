#!/usr/bin/env bash
# Stop the API and crawl worker processes recorded by deploy/startup.sh.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${APP_DIR}/.runtime"

stop_process() {
    local label="$1"
    local pid_file="$2"

    if [[ ! -f "${pid_file}" ]]; then
        echo "[提示] Spider_XHS ${label} 未运行（没有 PID 文件）。"
        return
    fi

    local pid
    pid="$(<"${pid_file}")"
    if ! [[ "${pid}" =~ ^[0-9]+$ ]]; then
        echo "[警告] ${label} PID 文件内容无效，已删除。" >&2
        rm -f "${pid_file}"
        return
    fi

    if ! kill -0 "${pid}" 2>/dev/null; then
        rm -f "${pid_file}"
        echo "[提示] Spider_XHS ${label} 进程已不存在。"
        return
    fi

    kill "${pid}"
    for _ in $(seq 1 10); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${pid_file}"
            echo "[完成] Spider_XHS ${label} 已停止。"
            return
        fi
        sleep 1
    done

    echo "[警告] ${label} 进程 ${pid} 未在 10 秒内退出，发送 SIGKILL。" >&2
    kill -9 "${pid}"
    rm -f "${pid_file}"
    echo "[完成] Spider_XHS ${label} 已强制停止。"
}

stop_process "API" "${RUNTIME_DIR}/internal-api.pid"
stop_process "worker" "${RUNTIME_DIR}/crawl-worker.pid"
