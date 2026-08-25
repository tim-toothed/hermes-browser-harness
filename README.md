# Hermes Browser Harness

Cross-platform Hermes Agent plugin with a bundled, version-locked Browser Harness runtime and managed Chrome host packages for Windows and Linux.

- Plugin: **1.4.13**
- Browser Harness runtime: **0.1.9**
- Model-facing tool: plugin-owned `browser_exec` in Hermes' canonical `browser` toolset
- Browser transport: one managed Chrome through loopback CDP
- Supported plugin hosts: Windows and Linux
- Supported Linux installer target: Debian/Ubuntu amd64 VPS

## Plugin installation

```bash
hermes plugins install tim-toothed/hermes-browser-harness
hermes plugins enable browser-harness --allow-tool-override
```

Enable the canonical `browser` toolset on every platform used by the agent. The plugin overrides `browser_exec` and suppresses granular built-in browser actions. Restart the active Hermes process after installation.

```bash
hermes tools enable browser --platform cli
```

The same boundary must be applied to Telegram or another active platform. Do not expose the granular built-in browser tools beside `browser_exec`.

## Windows host installation

The Windows package uses normal Google Chrome with one agent-owned persistent profile and loopback CDP at `127.0.0.1:9222`. It does not install Linux lifecycle dependencies, Remote Access, a watchdog, Hermes core patches, a separate Browser Harness `uv tool`, or a global tab limit.

Install and enable the plugin first, then run the host installer from the installed checkout:

```powershell
hermes plugins install tim-toothed/hermes-browser-harness --force
hermes plugins enable browser-harness --allow-tool-override
cd "$env:LOCALAPPDATA\hermes\plugins\browser-harness"
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" .\install-windows.py
```

`v1.4.11` is the first release containing the Windows host installer. The earlier `v1.4.10` tag remains unchanged.

The installer:

- preserves the existing `%LOCALAPPDATA%\hermes\Hermes Automation` profile, its active Chrome subprofile such as `Profile 2`, and the managed-profile registry;
- configures Chrome and uBlock Origin Lite `2026.812.1211` through Hermes config;
- creates an interactive, Limited, `IgnoreNew` logon task for managed Chrome;
- enables canonical `browser`, suppresses its granular built-in actions through the plugin, and disables `computer_use` for CLI and Telegram;
- removes the obsolete `browser.backend`, `BU_NAME`/`BU_CDP_URL` user variables, and exact legacy `browser-harness 0.1.9` uv-tool install;
- restores inherited ACLs on the plugin, extension, and installed skill trees so the Limited interactive Gateway/Chrome token can read them;
- supports idempotent update installation and `--check-only` preflight.

Restart Hermes through the node's supported interactive Gateway path after installation. Acceptance requires a real Hermes `browser_exec` page operation; config, process, package, or CDP checks alone are insufficient.

## Linux host installation

The Linux package owns Google Chrome, Xvfb, Openbox, systemd lifecycle, managed profiles, uBlock Origin Lite, idle shutdown, and optional temporary Remote Access.

The plugin must already be enabled with tool-override consent. `install-linux.sh` verifies this before package installation or host mutation and fails closed otherwise.

```bash
cd /root/.hermes/plugins/browser-harness
sudo ./install-linux.sh
hermes gateway restart
```

The installer:

- installs the Debian/Ubuntu amd64 browser/display dependencies;
- creates a dedicated service account and persistent profile storage;
- starts Chrome on demand through systemd and waits for loopback CDP readiness;
- installs a persistent managed-profile registry and selector;
- enables canonical `browser`, suppresses its granular built-in actions through the plugin, and disables `computer_use` for CLI and Telegram;
- installs pinned uBlock Origin Lite `2026.812.1211` as a managed unpacked extension;
- preserves profile data, registry, node-local Chrome arguments, credentials, and share state during update;
- moves an unowned pre-existing `browser-harness` skill to a timestamped backup instead of deleting it;
- records pre-install Hermes config and toolset membership for conditional restoration on uninstall.

Uninstall only package-owned Linux runtime files:

```bash
sudo ./uninstall-linux.sh
```

Persistent profiles and node credentials are not removed automatically.

## Runtime contract

```text
Hermes model
  → canonical browser toolset
  → plugin-owned browser_exec
  → managed Chrome readiness / extension reconciliation
  → bundled Browser Harness 0.1.9
  → loopback CDP
  → one managed Chrome
```

`browser_exec` accepts Python using Browser Harness helpers. Browser state and workspace persist across calls, but Python variables do not. During one invocation the runtime keeps an in-memory set of the current target, explicitly created targets, target changes, and recursive `openerId` descendants. After success or exception it closes only that invocation-owned set; unrelated concurrent-session and manual tabs are untouched.

Configured extensions are accepted only after browser-level read-back confirms exact ID, version, enabled state, and path. Package/config presence alone is not activation evidence.

## Managed profiles and concurrency

- Only one managed profile can be active on a node at a time.
- Switching profiles replaces the Chrome process on the single CDP endpoint.
- Tasks requiring different profiles must not overlap.
- Tasks using the same profile may run concurrently in separate Browser Harness session/tab namespaces; Linux acceptance verified this with two real simultaneous cron tasks.
- No queue is promised or required by the contract. Acceptance checks the user-visible result and tab isolation.

## Linux-only lifecycle

Linux uses Xvfb → Openbox → Chrome under systemd. `browser_exec` holds a shared activity lock so idle shutdown cannot stop Chrome during a task. Managed Chrome shuts down after 60 minutes without Browser Harness or Remote Access activity by default. Temporary Remote Access uses the same display/profile through loopback-only X11VNC, noVNC, and Caddy defaults. It must restore Chrome/CDP before returning a share URL; an empty display is not a successful recovery.

Remote Access requires deployment-specific credentials and external ingress configuration. Credentials, TLS private keys, egress routes, proxy settings, central AUTH deployment, and public listeners are not included in this repository.

Configure `/etc/procvetaev-browser/.env` explicitly before using Remote Access:

```dotenv
SHARE_AUTH_BASE_URL=https://your-auth-gateway.example
SHARE_MAX_TTL_SECONDS=1800
BROWSER_SHARE_BIND=127.0.0.1
BROWSER_SHARE_PORT=8791
```

Keep the default loopback bind unless the central AUTH gateway connects directly to this VPS. For that deployment, set `BROWSER_SHARE_BIND=0.0.0.0` and restrict port `8791` to the trusted ingress path with the host/provider firewall. The central gateway must accept a route TTL of at least `1800` seconds. Any broader bind is an explicit deployment decision; it is never enabled by the package default.

Creating Remote Access requires a concrete target and opens one owned Chrome tab:

```bash
curl -fsS -X POST http://127.0.0.1:8790/v1/shares \
  -H 'Content-Type: application/json' \
  --data '{"kind":"remote_access","target_url":"https://target.example/","ttl_seconds":1800}'
```

Revoke, expiry, and replacement close only that owned tab. Existing manual tabs and unrelated `browser_exec` tabs are preserved. The broker waits for the Caddy listener to become reachable before registering the temporary route with AUTH.

## CAPTCHA boundary

The package manages only uBlock Origin Lite. The previously tested bundled/unpacked NopeCHA artifact is not shipped. CAPTCHA extension installation and credentials are deployment-specific and currently deferred; no CAPTCHA acceptance PASS is claimed by this release.

## Platform parity

See [`docs/PLATFORM_PARITY.md`](docs/PLATFORM_PARITY.md) for the complete Linux ↔ Windows inventory, shared fixes, platform-specific behavior, and current B1–B6 status.

Release changes are recorded in [`CHANGELOG.md`](CHANGELOG.md).

Windows runtime `1.4.10` was update-installed and real-Hermes accepted on the D2 pilot. Release `1.4.11` adds the reviewed Windows migration installer; fleet rollout remains a separate operator-approved step. Historical Windows installers are not the source for new installations.

## Development

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m py_compile __init__.py tool.py install-windows.py tests/test_plugin.py tests/test_linux_runtime.py \
  linux/scripts/install-browser-extensions linux/scripts/browser-install-state
bash -n install-linux.sh uninstall-linux.sh \
  linux/scripts/browser-chrome-launch linux/scripts/browser-profile \
  linux/scripts/procvetaev-browser-idle-check linux/scripts/procvetaev-browser-share
cd runtime
uv lock --check
uv run --frozen browser-harness --version
```

Functional release acceptance additionally requires a real Hermes session and browser-level read-back; unit tests alone are insufficient.

## Third-party components

The bundled Browser Harness runtime remains MIT licensed by Browser Use; see `runtime/BROWSER_HARNESS_LICENSE`. The pinned uBlock Origin Lite archive contains its upstream license and notices. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## License

The plugin adapter plus Windows and Linux orchestration are MIT licensed by Timur Sharifullin / PROCVETAEV. Third-party components retain their own licenses.
