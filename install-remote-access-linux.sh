#!/usr/bin/env bash
# Node-local HTTPS and OTP Remote Access, owned by the Linux Browser Harness package.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for stage in https remote_access; do
  python3 "$ROOT/linux/standalone/$stage.py" "$@"
done
install -d -m 0755 "${HERMES_HOME:-/root/.hermes}/skills/browser-human-access"
install -m 0644 "$ROOT/linux/standalone/skills/browser-human-access/SKILL.md" "${HERMES_HOME:-/root/.hermes}/skills/browser-human-access/SKILL.md"
