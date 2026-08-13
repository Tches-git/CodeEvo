#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "用法: $0 --backup FILE --target-db NAME --confirm [--replace] [--keep]" >&2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_DIR="${CODEEVO_REPOSITORY_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMPOSE_PROJECT="${CODEEVO_COMPOSE_PROJECT:-codeevo}"
DATABASE_USER="${CODEEVO_POSTGRES_USER:-codeevo}"
backup=""
target_db=""
confirmed=false
replace=false
keep=true

while (($#)); do
  case "$1" in
    --backup) backup="${2:-}"; shift 2 ;;
    --target-db) target_db="${2:-}"; shift 2 ;;
    --confirm) confirmed=true; shift ;;
    --replace) replace=true; shift ;;
    --keep) keep=true; shift ;;
    --drop-after-check) keep=false; shift ;;
    *) usage; exit 2 ;;
  esac
done

[[ -n "${backup}" && -f "${backup}" && -n "${target_db}" ]] || { usage; exit 2; }
[[ "${target_db}" =~ ^[a-zA-Z][a-zA-Z0-9_]{0,62}$ ]] || { echo "目标数据库名不合法" >&2; exit 2; }
[[ "${confirmed}" == true ]] || { echo "必须显式传入 --confirm" >&2; exit 2; }
if [[ "${target_db}" == "codeevo" && "${CODEEVO_ALLOW_PRODUCTION_RESTORE:-false}" != "true" ]]; then
  echo "默认拒绝覆盖生产数据库；恢复演练请使用隔离数据库名" >&2
  exit 2
fi

compose=(docker compose --project-name "${COMPOSE_PROJECT}" --project-directory "${REPOSITORY_DIR}" --env-file "${REPOSITORY_DIR}/.env")
"${compose[@]}" exec -T postgres pg_restore --list <"${backup}" >/dev/null
exists="$("${compose[@]}" exec -T postgres psql -U "${DATABASE_USER}" -d postgres -Atc \
  "SELECT 1 FROM pg_database WHERE datname='${target_db}'")"
if [[ "${exists}" == "1" ]]; then
  [[ "${replace}" == true ]] || { echo "目标数据库已存在；如确认覆盖隔离库，请传入 --replace" >&2; exit 2; }
  "${compose[@]}" exec -T postgres dropdb -U "${DATABASE_USER}" --if-exists "${target_db}"
fi

"${compose[@]}" exec -T postgres createdb -U "${DATABASE_USER}" "${target_db}"
cleanup_failed() {
  "${compose[@]}" exec -T postgres dropdb -U "${DATABASE_USER}" --if-exists "${target_db}" >/dev/null 2>&1 || true
}
trap cleanup_failed ERR
"${compose[@]}" exec -T postgres pg_restore -U "${DATABASE_USER}" -d "${target_db}" \
  --no-owner --no-privileges <"${backup}"
table_count="$("${compose[@]}" exec -T postgres psql -U "${DATABASE_USER}" -d "${target_db}" -Atc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [[ "$("${compose[@]}" exec -T postgres psql -U "${DATABASE_USER}" -d "${target_db}" -Atc \
  "SELECT to_regclass('public.tasks') IS NOT NULL")" == "t" ]]; then
  task_count="$("${compose[@]}" exec -T postgres psql -U "${DATABASE_USER}" -d "${target_db}" -Atc \
    "SELECT count(*) FROM tasks")"
else
  task_count=-1
fi
trap - ERR

echo "restore_ok database=${target_db} tables=${table_count} tasks=${task_count}"
if [[ "${keep}" == false ]]; then
  "${compose[@]}" exec -T postgres dropdb -U "${DATABASE_USER}" "${target_db}"
  echo "restore_drill_cleanup_ok database=${target_db}"
fi
