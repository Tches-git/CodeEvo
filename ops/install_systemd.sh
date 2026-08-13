#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${1:-}" == "--enable" ]] || { echo "用法: sudo $0 --enable" >&2; exit 2; }
[[ "${EUID}" -eq 0 ]] || { echo "必须以 root 运行" >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m 0644 "${SCRIPT_DIR}"/systemd/codeevo-*.service "${SCRIPT_DIR}"/systemd/codeevo-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now codeevo-backup.timer codeevo-health.timer codeevo-disk.timer
systemctl list-timers 'codeevo-*' --no-pager
