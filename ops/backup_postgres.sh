#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_DIR="${CODEEVO_REPOSITORY_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BACKUP_DIR="${CODEEVO_BACKUP_DIR:-${REPOSITORY_DIR}/backups}"
RETENTION_DAYS="${CODEEVO_BACKUP_RETENTION_DAYS:-14}"
COMPOSE_PROJECT="${CODEEVO_COMPOSE_PROJECT:-codeevo}"
DATABASE="${CODEEVO_POSTGRES_DB:-codeevo}"
DATABASE_USER="${CODEEVO_POSTGRES_USER:-codeevo}"

[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || { echo "RETENTION_DAYS 必须是非负整数" >&2; exit 2; }
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"
umask 077

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_path="${BACKUP_DIR}/codeevo-${timestamp}.dump"
temp_path="${final_path}.partial"
trap 'rm -f -- "${temp_path}"' EXIT

compose=(docker compose --project-name "${COMPOSE_PROJECT}" --project-directory "${REPOSITORY_DIR}" --env-file "${REPOSITORY_DIR}/.env")
"${compose[@]}" exec -T postgres pg_dump \
  --username "${DATABASE_USER}" --dbname "${DATABASE}" --format custom >"${temp_path}"
[[ -s "${temp_path}" ]] || { echo "备份文件为空" >&2; exit 1; }
"${compose[@]}" exec -T postgres pg_restore --list <"${temp_path}" >/dev/null
chmod 600 "${temp_path}"
mv -- "${temp_path}" "${final_path}"
trap - EXIT

find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'codeevo-*.dump' \
  -mtime "+${RETENTION_DAYS}" -delete
echo "backup_ok path=${final_path} bytes=$(wc -c <"${final_path}" | tr -d ' ')"
