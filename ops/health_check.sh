#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_DIR="${CODEEVO_REPOSITORY_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMPOSE_PROJECT="${CODEEVO_COMPOSE_PROJECT:-codeevo}"
LOCAL_URL="${CODEEVO_HEALTH_LOCAL_URL:-http://127.0.0.1:8080}"
PUBLIC_URL="${CODEEVO_HEALTH_PUBLIC_URL:-}"
WEBHOOK_URL="${CODEEVO_ALERT_WEBHOOK_URL:-}"
failures=()

compose=(docker compose --project-name "${COMPOSE_PROJECT}" --project-directory "${REPOSITORY_DIR}")
running="$("${compose[@]}" ps --status running --services 2>/dev/null || true)"
for service in postgres redis codeevo; do
  grep -qx "${service}" <<<"${running}" || failures+=("container:${service}")
done
for endpoint in health/live health/ready; do
  curl --fail --silent --show-error --max-time 10 "${LOCAL_URL%/}/${endpoint}" >/dev/null \
    || failures+=("local:${endpoint}")
done
if [[ -n "${PUBLIC_URL}" ]]; then
  curl --fail --silent --show-error --max-time 15 "${PUBLIC_URL%/}/health/ready" >/dev/null \
    || failures+=("public:health/ready")
fi

if ((${#failures[@]})); then
  message="CodeEvo health_check_failed: ${failures[*]}"
  echo "${message}" >&2
  if [[ -n "${WEBHOOK_URL}" ]]; then
    payload="$(printf '%s' "${message}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    curl --fail --silent --show-error --max-time 10 -H 'Content-Type: application/json' \
      -d "{\"text\":\"${payload}\"}" "${WEBHOOK_URL}" >/dev/null || true
  fi
  exit 1
fi
echo "health_check_ok local=${LOCAL_URL} public=${PUBLIC_URL:-disabled}"
