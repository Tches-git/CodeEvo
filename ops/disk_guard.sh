#!/usr/bin/env bash
set -Eeuo pipefail

TARGET="${CODEEVO_DISK_TARGET:-/}"
WARNING="${CODEEVO_DISK_WARNING_PERCENT:-80}"
CRITICAL="${CODEEVO_DISK_CRITICAL_PERCENT:-90}"
WEBHOOK_URL="${CODEEVO_ALERT_WEBHOOK_URL:-}"
[[ "${WARNING}" =~ ^[0-9]+$ && "${CRITICAL}" =~ ^[0-9]+$ && "${WARNING}" -lt "${CRITICAL}" ]] \
  || { echo "磁盘阈值必须是 warning < critical 的整数" >&2; exit 2; }

used="$(df -P "${TARGET}" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
[[ "${used}" =~ ^[0-9]+$ ]] || { echo "无法读取磁盘使用率" >&2; exit 1; }
state="ok"
exit_code=0
if ((used >= CRITICAL)); then state="critical"; exit_code=2
elif ((used >= WARNING)); then state="warning"; exit_code=1
fi
message="CodeEvo disk_${state}: target=${TARGET} used=${used}% warning=${WARNING}% critical=${CRITICAL}%"
echo "${message}"
if ((exit_code > 0)) && [[ -n "${WEBHOOK_URL}" ]]; then
  curl --fail --silent --show-error --max-time 10 -H 'Content-Type: application/json' \
    -d "{\"text\":\"${message}\"}" "${WEBHOOK_URL}" >/dev/null || true
fi
exit "${exit_code}"
