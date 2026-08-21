# Hermes Browser Harness

Cross-platform Hermes Agent plugin with a bundled, version-locked Browser Harness runtime and a production Linux host package.

- Plugin: **1.4.6**
- Browser Harness runtime: **0.1.9**
- Model-facing tool: plugin-owned `browser_exec` in the dedicated `browser_harness` toolset
- Browser transport: one managed Chrome through loopback CDP
- Supported plugin hosts: Windows and Linux
- Supported Linux installer target: Debian/Ubuntu amd64 VPS

## Plugin installation

```bash
hermes plugins install tim-toothed/hermes-browser-harness
hermes plugins enable browser-harness --allow-tool-override
```

Enable `browser_harness` and disable the built-in `browser` toolset on every platform used by the agent. Restart the active Hermes process after installation.

```bash
hermes tools enable browser_harness --platform cli
hermes tools disable browser --platform cli
```

The same boundary must be applied to Telegram or another active platform. Do not expose the granular built-in browser tools beside `browser_exec`.

## Linux host installation

The Linux package owns Google Chrome, Xvfb, Openbox, systemd lifecycle, managed profiles, uBlock Origin Lite, idle shutdown, and optional temporary Remote Access.

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
- enables `browser_harness`, disables built-in `browser`, and disables `computer_use` for CLI and Telegram;
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
  → browser_harness toolset
  → plugin-owned browser_exec
  → managed Chrome readiness / extension reconciliation
  → bundled Browser Harness 0.1.9
  → loopback CDP
  → one managed Chrome
```

`browser_exec` accepts Python using Browser Harness helpers. Browser state and workspace persist across calls, but Python variables do not.

Configured extensions are accepted only after browser-level read-back confirms exact ID, version, enabled state, and path. Package/config presence alone is not activation evidence.

## Managed profiles and concurrency

- Only one managed profile can be active on a node at a time.
- Switching profiles replaces the Chrome process on the single CDP endpoint.
- Tasks requiring different profiles must not overlap.
- Tasks using the same profile may run concurrently in separate Browser Harness session/tab namespaces; Linux acceptance verified this with two real simultaneous cron tasks.
- No queue is promised or required by the contract. Acceptance checks the user-visible result and tab isolation.

## Linux-only lifecycle

Linux uses Xvfb → Openbox → Chrome under systemd. `browser_exec` holds a shared activity lock so idle shutdown cannot stop Chrome during a task. Temporary Remote Access uses the same display/profile through loopback-only X11VNC, noVNC, and Caddy defaults. It must restore Chrome/CDP before returning a share URL; an empty display is not a successful recovery.

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

The main remaining Windows parity work is to deploy and verify the `1.4.6` dedicated-toolset boundary and run the same-profile concurrency test there. Historical Windows installers are not the source for new installations.

## Development

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m py_compile __init__.py tool.py tests/test_plugin.py tests/test_linux_runtime.py \
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

The plugin adapter and Linux orchestration are MIT licensed by Timur Sharifullin / PROCVETAEV. Third-party components retain their own licenses.
