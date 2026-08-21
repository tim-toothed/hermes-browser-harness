# Changelog

## 1.4.7 - 2026-08-21

- Require the `browser-harness` plugin to be enabled with explicit tool-override consent before any privileged Linux host mutation.
- Fail fast instead of reaching toolset configuration with an installed-but-disabled plugin.

## 1.4.6 - 2026-08-21

### Changed

- Remote Access authorization lifetime is 30 minutes (`1800` seconds).
- Remote Access creation requires an absolute HTTP(S) `target_url` and opens one dedicated owned Chrome tab.

### Fixed

- Revoke, expiry, replacement, and failed AUTH registration close only the Remote Access-owned tab while preserving manual and unrelated Browser Harness tabs.
- Caddy uses the stable `vps-broker.local` TLS identity with a separate safe-default `bind` directive.
- The broker waits for the Caddy listener socket before central AUTH route registration, removing the startup race behind intermittent noVNC connection failures.
- Expiry revokes the central route, removes only matching sessions, and shuts down the temporary noVNC stack when no shares remain.

### Deployment note

- Direct central ingress must explicitly set `BROWSER_SHARE_BIND=0.0.0.0` and protect port `8791`; the package default remains loopback.
- The central AUTH gateway must allow at least `1800` seconds for temporary-route registration.

## 1.4.5 — 2026-08-21

### Added

- Production Linux host package for Debian/Ubuntu amd64.
- systemd lifecycle for Xvfb, Openbox, managed Chrome, idle shutdown, and temporary Remote Access.
- Persistent managed-profile registry and selector with one active profile per node.
- Pinned uBlock Origin Lite `2026.812.1211` installation and exact browser-level reconciliation.
- Linux package ownership manifest, update preservation, and bounded uninstall.
- Linux ↔ Windows parity inventory and revised B1–B6 acceptance state.

### Changed

- `browser_exec` now belongs to the dedicated `browser_harness` toolset instead of built-in `browser`.
- Linux Browser Harness starts both the systemd target and Chrome service, waits for CDP, and holds an activity lock during execution.
- Same-profile tasks are allowed to run in separate Browser Harness session/tab namespaces; different managed profiles must not overlap.
- Deprecated `browser.backend` configuration is removed during Linux migration.

### Fixed

- Chrome recovery when the systemd target remained active but the Chrome service had stopped.
- Remote Access returning a usable share only after Chrome/CDP recovery.
- Linux unpacked-extension ownership and permissions.
- Chrome Web Store `_metadata` incompatibility in the managed uBlock payload.
- Extension acceptance now requires exact ID, version, enabled state, and path read-back.
- Unowned skills and pre-install Hermes config/toolset state are preserved instead of being deleted or blindly unset.
- Caddy defaults to loopback and the package no longer embeds a private AUTH endpoint.
- SQLite access is serialized so OTP verification remains single-consumer under concurrent requests.
- The installer resolves the Hermes Python interpreter from the installed CLI instead of one fixed venv path.

### Deferred / not shipped

- CAPTCHA extension installation and CAPTCHA0–2 acceptance.
- The non-working bundled/unpacked NopeCHA artifact.
- B5 until the `web_search + web_extract` contract is accepted.
- Windows deployment verification for the new toolset boundary and same-profile concurrency.
