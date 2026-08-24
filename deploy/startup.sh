#!/usr/bin/env bash
# Spider_XHS API 与公网反向代理启动脚本。使用方式：./startup.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NGINX_CONF="${APP_DIR}/deploy/spider-xhs-api.winzyy.com.conf"
NGINX_TARGET="/etc/nginx/conf.d/spider-xhs-api.winzyy.com.conf"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${APP_DIR}/.env"
RUNTIME_DIR="${APP_DIR}/.runtime"
LOG_DIR="${APP_DIR}/logs"
PID_FILE="${RUNTIME_DIR}/internal-api.pid"
HOST="127.0.0.1"
PORT="8088"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[错误] 缺少 ${ENV_FILE}；请在服务器上配置运行变量后重试。" >&2
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

echo "=== 启动 Spider_XHS ==="
echo "[API] 重启本机 API（${HOST}:${PORT}）..."
"${APP_DIR}/deploy/stop.sh"

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

echo "[Nginx] 发布配置并校验..."
install -d -m 755 /etc/nginx/conf.d
BACKUP_CONF="$(mktemp)"
RESTORE_CONF=false
if [[ -f "${NGINX_TARGET}" ]]; then
    install -m 644 "${NGINX_TARGET}" "${BACKUP_CONF}"
    RESTORE_CONF=true
fi
install -m 644 "${NGINX_CONF}" "${NGINX_TARGET}"
if ! nginx -t; then
    if [[ "${RESTORE_CONF}" == true ]]; then
        install -m 644 "${BACKUP_CONF}" "${NGINX_TARGET}"
    else
        rm -f "${NGINX_TARGET}"
    fi
    rm -f "${BACKUP_CONF}"
    echo "[错误] Nginx 配置校验失败，已恢复原配置。" >&2
    exit 1
fi
rm -f "${BACKUP_CONF}"
systemctl restart nginx

echo "[完成] Spider_XHS API 已启动：PID=${PID}，监听 ${HOST}:${PORT}"
echo "[完成] Spider_XHS 公网地址：https://spider-xhs-api.winzyy.com"
