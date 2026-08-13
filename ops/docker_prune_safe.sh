#!/usr/bin/env bash
set -Eeuo pipefail

before="$(docker system df --format '{{json .}}' 2>/dev/null || true)"
docker image prune --force --filter dangling=true
docker builder prune --force --filter 'until=168h'
after="$(docker system df --format '{{json .}}' 2>/dev/null || true)"
echo "safe_prune_ok volumes_untouched=true"
[[ -n "${before}" ]] && printf 'before=%s\n' "${before}"
[[ -n "${after}" ]] && printf 'after=%s\n' "${after}"
