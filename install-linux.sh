#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "run as root" >&2; exit 1; }
command -v hermes >/dev/null || { echo "Hermes CLI is required" >&2; exit 1; }
[[ $(dpkg --print-architecture) == amd64 ]] || { echo "Only amd64 Linux VPS is currently supported" >&2; exit 1; }

resolve_hermes_python() {
  local candidate shebang
  if [[ -n ${HERMES_PYTHON:-} ]]; then
    [[ -x "$HERMES_PYTHON" ]] || { echo "HERMES_PYTHON is not executable: $HERMES_PYTHON" >&2; return 1; }
    "$HERMES_PYTHON" -c 'import hermes_cli' >/dev/null 2>&1 || { echo "HERMES_PYTHON cannot import hermes_cli" >&2; return 1; }
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
  echo "Cannot find the Python interpreter that owns hermes_cli; set HERMES_PYTHON" >&2
  return 1
}
HERMES_PYTHON=$(resolve_hermes_python)

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
LINUX="$ROOT/linux"
RUNTIME_DST=/usr/local/libexec/procvetaev-browser-harness
HERMES_HOME=${HERMES_HOME:-/root/.hermes}
SERVICE_USER=procvetaev-browser
SERVICE_HOME=/var/lib/procvetaev-browser

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y xvfb openbox x11vnc novnc websockify caddy curl ca-certificates
if ! command -v google-chrome-stable >/dev/null; then
  chrome_deb=$(mktemp --suffix=.deb)
  trap 'rm -f "$chrome_deb"' EXIT
  curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o "$chrome_deb"
  apt-get install -y "$chrome_deb"
  rm -f "$chrome_deb"
  trap - EXIT
fi

# Remove only the proven legacy wrapper/global runtime. Shared Linux packages,
# the persistent profile and Remote Access state are reused by this package.
for legacy_link in /usr/local/bin/browser-harness /root/.local/bin/browser-harness /root/.local/bin/browser-harness-real; do
  if [[ -L "$legacy_link" ]]; then
    legacy_target=$(readlink -f "$legacy_link" || true)
    case "$legacy_target" in
      /root/.hermes/skills/browser-harness/*|/root/.local/share/uv/tools/browser-harness/*)
        rm -f -- "$legacy_link"
        ;;
    esac
  fi
done
if [[ -x /root/.local/bin/uv ]] && /root/.local/bin/uv tool list 2>/dev/null | grep -q '^browser-harness v0\.1\.8$'; then
  /root/.local/bin/uv tool uninstall browser-harness >/dev/null
fi
unowned_skill_backup=""
restore_unowned_skill() {
  if [[ -n "$unowned_skill_backup" && -d "$unowned_skill_backup" ]]; then
    state_file="$HERMES_HOME/skills/browser-harness/.linux-browser-harness-install-state.json"
    if [[ -f "$state_file" && -x "$RUNTIME_DST/browser-install-state" ]]; then
      "$HERMES_PYTHON" "$RUNTIME_DST/browser-install-state" restore "$state_file" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$HERMES_HOME/skills/browser-harness"
    mv -- "$unowned_skill_backup" "$HERMES_HOME/skills/browser-harness"
  fi
}
if [[ -d "$HERMES_HOME/skills/browser-harness" && ! -f "$HERMES_HOME/skills/browser-harness/.linux-browser-harness-owned" ]]; then
  backup_root="$HERMES_HOME/backups"
  install -d -o root -g root -m 0700 "$backup_root"
  unowned_skill_backup="$backup_root/browser-harness.pre-1.4.5.$(date +%Y%m%d%H%M%S).$$"
  mv -- "$HERMES_HOME/skills/browser-harness" "$unowned_skill_backup"
  trap restore_unowned_skill EXIT
fi
rm -f -- /usr/local/libexec/procvetaev-browser-idle-check /usr/local/libexec/procvetaev-browser-share

if ! getent passwd "$SERVICE_USER" >/dev/null; then
  useradd --system --user-group --home-dir "$SERVICE_HOME" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$SERVICE_HOME" "$SERVICE_HOME/chrome-profile"
install -d -o root -g root -m 0700 /var/lib/procvetaev-browser-share /etc/procvetaev-browser
install -d -o root -g root -m 0755 \
  "$RUNTIME_DST" \
  "$RUNTIME_DST/temporary-share" \
  "$RUNTIME_DST/extension-artifacts/ublock-origin-lite/2026.812.1211" \
  /etc/caddy /etc/tmpfiles.d
install -d -o root -g root -m 0755 "$HERMES_HOME/skills/browser-harness"

# A legacy node-specific SOCKS/PAC drop-in replaced the complete Chrome
# ExecStart and therefore pinned the old profile path. Preserve only its
# non-owned Chrome flags, then return process/profile ownership to the package.
legacy_chrome_dropin=/etc/systemd/system/procvetaev-chrome.service.d/temporary-d1-socks.conf
chrome_args_file="$SERVICE_HOME/chrome-args.json"
if [[ -f /etc/procvetaev-browser/chrome-args.json && ! -e "$chrome_args_file" ]]; then
  mv -- /etc/procvetaev-browser/chrome-args.json "$chrome_args_file"
fi
if [[ -f "$legacy_chrome_dropin" ]]; then
  python3 - "$legacy_chrome_dropin" "$chrome_args_file" <<'PY'
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

dropin = Path(sys.argv[1])
destination = Path(sys.argv[2])
lines = dropin.read_text(encoding="utf-8").splitlines()
commands = [line.removeprefix("ExecStart=") for line in lines if line.startswith("ExecStart=/usr/bin/google-chrome-stable ")]
if len(commands) != 1:
    raise SystemExit("refusing unknown procvetaev-chrome legacy drop-in")
argv = shlex.split(commands[0])
required = {
    "--user-data-dir=/var/lib/procvetaev-browser/chrome-profile",
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1920,1080",
}
present = set(argv[1:])
if not required.issubset(present):
    raise SystemExit("refusing legacy Chrome drop-in with unknown ownership contract")
extra = [arg for arg in argv[1:] if arg not in required and arg != "about:blank"]
if any(arg.split("=", 1)[0] in {"--user-data-dir", "--remote-debugging-address", "--remote-debugging-port", "--remote-allow-origins"} for arg in extra):
    raise SystemExit("refusing legacy Chrome drop-in with duplicate ownership flags")
if destination.exists():
    current = json.loads(destination.read_text(encoding="utf-8"))
    if current.get("extra_args") != extra:
        raise SystemExit("existing chrome-args.json differs from legacy drop-in")
else:
    fd, temporary = tempfile.mkstemp(prefix=".chrome-args.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"extra_args": extra}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
PY
  rm -f -- "$legacy_chrome_dropin"
  rmdir --ignore-fail-on-non-empty -- "$(dirname -- "$legacy_chrome_dropin")" || true
fi
if [[ -f "$chrome_args_file" ]]; then
  chown root:"$SERVICE_USER" "$chrome_args_file"
  chmod 0640 "$chrome_args_file"
fi

for unit in procvetaev-browser-share.service procvetaev-x11vnc.service procvetaev-novnc.service; do
  systemctl is-active --quiet "$unit" && { echo "Remote Access is active; refusing Browser Harness update" >&2; exit 1; }
done
install -d -o root -g root -m 0755 /run/procvetaev-browser
exec 9>/run/procvetaev-browser/activity.lock
flock -x 9
pkill -TERM -f '[p]ython.*-m browser_harness.daemon' >/dev/null 2>&1 || true

install -m 0755 "$LINUX/scripts/procvetaev-browser-idle-check" "$RUNTIME_DST/browser-idle-check"
install -m 0755 "$LINUX/scripts/procvetaev-browser-share" "$RUNTIME_DST/browser-share"
install -m 0755 "$LINUX/scripts/browser-profile" "$RUNTIME_DST/browser-profile"
install -m 0755 "$LINUX/scripts/browser-chrome-launch" "$RUNTIME_DST/browser-chrome-launch"
install -m 0755 "$LINUX/scripts/install-browser-extensions" "$RUNTIME_DST/install-browser-extensions"
install -m 0755 "$LINUX/scripts/browser-install-state" "$RUNTIME_DST/browser-install-state"
install -m 0755 "$LINUX/scripts/temporary-share/broker.py" "$RUNTIME_DST/temporary-share/broker.py"
install -m 0644 "$LINUX/scripts/temporary-share/core.py" "$RUNTIME_DST/temporary-share/core.py"
install -m 0644 "$LINUX/scripts/temporary-share/store.py" "$RUNTIME_DST/temporary-share/store.py"
install -m 0644 "$ROOT/extensions/ublock-origin-lite/2026.812.1211/ublock-origin-lite-unpacked.zip" \
  "$RUNTIME_DST/extension-artifacts/ublock-origin-lite/2026.812.1211/ublock-origin-lite-unpacked.zip"
install -m 0644 "$LINUX/caddy/procvetaev-browser-share.Caddyfile" /etc/caddy/procvetaev-browser-share.Caddyfile
install -m 0644 "$LINUX/systemd/tmpfiles-procvetaev-browser.conf" /etc/tmpfiles.d/procvetaev-browser.conf
install -m 0644 "$ROOT/skill/SKILL.md" "$HERMES_HOME/skills/browser-harness/SKILL.md"
if [[ -n "$unowned_skill_backup" && -f "$unowned_skill_backup/browser-profiles.json" ]]; then
  install -m 0644 "$unowned_skill_backup/browser-profiles.json" "$HERMES_HOME/skills/browser-harness/browser-profiles.json"
elif [[ ! -f "$HERMES_HOME/skills/browser-harness/browser-profiles.json" ]]; then
  install -m 0644 "$ROOT/skill/browser-profiles.json" "$HERMES_HOME/skills/browser-harness/browser-profiles.json"
fi
printf '%s\n' 'browser-harness-linux 1.4.6' > "$HERMES_HOME/skills/browser-harness/.linux-browser-harness-owned"
for unit in "$LINUX"/systemd/procvetaev-*.service "$LINUX"/systemd/procvetaev-*.timer "$LINUX"/systemd/procvetaev-browser.target; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done

if [[ ! -f /etc/procvetaev-browser/.env ]]; then
  install -m 0600 "$LINUX/config/share.env.example" /etc/procvetaev-browser/.env
fi
if [[ ! -s /etc/procvetaev-browser/share.pepper ]]; then
  python3 - <<'PY'
from pathlib import Path
import os, secrets
p=Path('/etc/procvetaev-browser/share.pepper')
p.write_bytes(secrets.token_bytes(32))
os.chmod(p, 0o600)
PY
fi

systemd-tmpfiles --create /etc/tmpfiles.d/procvetaev-browser.conf
"$RUNTIME_DST/browser-profile" status >/dev/null
systemctl daemon-reload
systemctl enable --now procvetaev-share-broker.service procvetaev-browser-idle.timer

default_profile_path=$("$RUNTIME_DST/browser-profile" status | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["profiles"][d["default"]]["user_data_dir"])')
install_state="$HERMES_HOME/skills/browser-harness/.linux-browser-harness-install-state.json"
"$HERMES_PYTHON" "$RUNTIME_DST/browser-install-state" capture "$install_state" "$default_profile_path"
hermes config unset browser.backend >/dev/null 2>&1 || true
hermes config set --force browser.cloud_provider local
hermes config set --force browser.cdp_url http://127.0.0.1:9222
hermes config set --force browser.harness.executable /usr/bin/google-chrome-stable
hermes config set --force browser.harness.user_data_dir "$default_profile_path"
hermes config set --force browser.harness.profile_directory Default
"$HERMES_PYTHON" "$RUNTIME_DST/install-browser-extensions" --configure-hermes >/dev/null
hermes tools disable computer_use --platform cli >/dev/null
hermes tools disable computer_use --platform telegram >/dev/null
for platform in cli telegram; do
  hermes tools enable browser_harness --platform "$platform" >/dev/null
  hermes tools disable browser --platform "$platform" >/dev/null
  hermes tools list --platform "$platform" \
    | grep -i 'computer_use' \
    | grep -qi 'disabled' \
    || { echo "computer_use remains enabled for $platform" >&2; exit 1; }
  hermes tools list --platform "$platform" \
    | grep -i 'browser_harness' \
    | grep -qi 'enabled' \
    || { echo "browser_harness remains disabled for $platform" >&2; exit 1; }
  hermes tools list --platform "$platform" \
    | grep -E '(^|[[:space:]])browser([[:space:]]|$)' \
    | grep -qi 'disabled' \
    || { echo "built-in browser remains enabled for $platform" >&2; exit 1; }
done

trap - EXIT

printf '%s\n' "Linux Browser Harness host runtime installed."
if [[ -n "$unowned_skill_backup" ]]; then
  printf '%s\n' "Previous unowned skill preserved at: $unowned_skill_backup"
fi
printf '%s\n' "Enable the browser-harness plugin with tool override, then restart Hermes Gateway."
printf '%s\n' "Remote Access additionally requires node-specific broker.crt and broker.key."
