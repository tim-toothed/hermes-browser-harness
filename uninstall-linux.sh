#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "run as root" >&2; exit 1; }
HERMES_HOME=${HERMES_HOME:-/root/.hermes}
command -v hermes >/dev/null || { echo "Hermes CLI is required" >&2; exit 1; }

resolve_hermes_python() {
  local candidate shebang
  if [[ -n ${HERMES_PYTHON:-} ]]; then
    [[ -x "$HERMES_PYTHON" ]] || return 1
    "$HERMES_PYTHON" -c 'import hermes_cli' >/dev/null 2>&1 || return 1
    printf '%s\n' "$HERMES_PYTHON"
    return
  fi
  shebang=$(head -n 1 "$(command -v hermes)" 2>/dev/null || true)
  if [[ "$shebang" == '#!'/* ]]; then
    candidate=${shebang#\#!}
    if [[ -x "$candidate" ]] && "$candidate" -c 'import hermes_cli' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return
    fi
  fi
  for candidate in /usr/local/lib/hermes-agent/venv/bin/python python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import hermes_cli' >/dev/null 2>&1; then
      command -v "$candidate"
      return
    fi
  done
  return 1
}
HERMES_PYTHON=$(resolve_hermes_python) || { echo "Cannot find the Python interpreter that owns hermes_cli" >&2; exit 1; }
RUNTIME_DST=/usr/local/libexec/procvetaev-browser-harness
install_state="$HERMES_HOME/skills/browser-harness/.linux-browser-harness-install-state.json"
if [[ -f "$install_state" ]]; then
  [[ -x "$RUNTIME_DST/browser-install-state" ]] || { echo "Install-state exists but restore helper is missing; refusing destructive uninstall" >&2; exit 1; }
  "$HERMES_PYTHON" "$RUNTIME_DST/browser-install-state" restore "$install_state"
fi

hermes plugins disable browser-harness >/dev/null 2>&1 || true
systemctl disable --now procvetaev-share-broker.service procvetaev-browser-idle.timer procvetaev-browser-share-expire.timer >/dev/null 2>&1 || true
systemctl stop procvetaev-browser-share.service procvetaev-novnc.service procvetaev-x11vnc.service procvetaev-browser.target >/dev/null 2>&1 || true
install -d -m 0755 /run/procvetaev-browser
exec 9>/run/procvetaev-browser/activity.lock
flock -x 9
pkill -TERM -f '[p]ython.*-m browser_harness.daemon' >/dev/null 2>&1 || true

for path in \
  /etc/systemd/system/procvetaev-browser-idle.service \
  /etc/systemd/system/procvetaev-browser-idle.timer \
  /etc/systemd/system/procvetaev-browser-share-expire.service \
  /etc/systemd/system/procvetaev-browser-share-expire.timer \
  /etc/systemd/system/procvetaev-browser-share.service \
  /etc/systemd/system/procvetaev-browser.target \
  /etc/systemd/system/procvetaev-chrome.service \
  /etc/systemd/system/procvetaev-novnc.service \
  /etc/systemd/system/procvetaev-openbox.service \
  /etc/systemd/system/procvetaev-share-broker.service \
  /etc/systemd/system/procvetaev-x11vnc.service \
  /etc/systemd/system/procvetaev-xvfb.service \
  /etc/tmpfiles.d/procvetaev-browser.conf \
  /etc/caddy/procvetaev-browser-share.Caddyfile; do
  rm -f -- "$path"
done
rm -rf -- "$RUNTIME_DST"
if [[ -f "$HERMES_HOME/skills/browser-harness/.linux-browser-harness-owned" ]]; then
  rm -f -- \
    "$HERMES_HOME/skills/browser-harness/SKILL.md" \
    "$HERMES_HOME/skills/browser-harness/.linux-browser-harness-install-state.json" \
    "$HERMES_HOME/skills/browser-harness/.linux-browser-harness-owned"
  rmdir -- "$HERMES_HOME/skills/browser-harness" >/dev/null 2>&1 || true
fi
systemctl daemon-reload
systemctl reset-failed >/dev/null 2>&1 || true

printf '%s\n' "Linux Browser Harness host runtime removed."
printf '%s\n' "Persistent profile registry, profile data and node credentials remain in the skill, /var/lib/procvetaev-browser and /etc/procvetaev-browser."
printf '%s\n' "Chrome and shared OS packages were not removed."
