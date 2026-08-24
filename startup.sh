#!/usr/bin/env bash
# Start the private Spider_XHS read API. Run from any directory.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${APP_DIR}/.env"
RUNTIME_DIR="${APP_DIR}/.runtime"
LOG_DIR="${APP_DIR}/logs"
PID_FILE="${RUNTIME_DIR}/internal-api.pid"
HOST="${SPIDER_XHS_API_HOST:-127.0.0.1}"
PORT="${SPIDER_XHS_API_PORT:-8088}"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[错误] 缺少 ${ENV_FILE}；请配置 DATABASE_URL、DATAS_BASE_PATH 等运行变量。" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[错误] ${ENV_FILE} 未配置 DATABASE_URL。" >&2
    exit 1
fi

if [[ -f "${PID_FILE}" ]] && kill -0 "$(<"${PID_FILE}")" 2>/dev/null; then
    echo "[提示] Spider_XHS API 已运行，PID: $(<"${PID_FILE}")"
    exit 0
fi
rm -f "${PID_FILE}"
mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
    if [[ -z "${PYTHON_BIN}" ]]; then
        echo "[错误] 未找到 python3，无法创建虚拟环境。" >&2
        exit 1
    fi
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check -q -r "${APP_DIR}/requirements.txt"

nohup "${VENV_DIR}/bin/python" -m uvicorn internal_api:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --env-file "${ENV_FILE}" \
    >> "${LOG_DIR}/internal-api.log" 2>&1 &
PID=$!
echo "${PID}" > "${PID_FILE}"

sleep 2
if ! kill -0 "${PID}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "[错误] Spider_XHS API 启动失败，请查看 ${LOG_DIR}/internal-api.log" >&2
    exit 1
fi

echo "[完成] Spider_XHS API 已启动：PID=${PID}，监听 ${HOST}:${PORT}"
