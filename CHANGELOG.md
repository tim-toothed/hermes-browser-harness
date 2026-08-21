# Changelog

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
