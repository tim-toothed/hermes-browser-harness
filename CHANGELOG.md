# Changelog

## 1.4.12 - 2026-08-25

- Preserve task-owned browser targets across separate `browser_exec` calls.
- Scope daemon ownership to Hermes `task_id` instead of model-generated session labels.
- Align the model-facing tool schema with target reuse: inspect/reuse the current target, navigate it with `goto_url`, and reserve `new_tab` for an additional concurrent tab.

## 1.4.11 - 2026-08-24

- Add the Windows host installer for managed Chrome, persistent profile/registry preservation, pinned uBlock Origin Lite, interactive logon task, and dedicated `browser_harness` toolset configuration.
- Remove the legacy Windows `browser.backend`, user-level Browser Harness environment variables, separate `browser-harness 0.1.9` uv-tool runtime, Hermes core patches, and global tab-limit dependency.
- Restore inherited ACLs on Windows plugin, extension, and skill trees so Limited interactive Gateway and Chrome processes can read SSH/elevated installations.
- Verify extension config semantically after Hermes normalizes JSON input to YAML read-back.
- Preserve the active Chrome subprofile such as `Profile 2`, create the Task Scheduler folder before registration, and retire only a verified legacy Chrome task.
- Reconcile every pinned extension payload byte, fail closed on legacy/config command errors, and verify inherited ACLs recursively.
- Start managed Chrome minimized on Windows for logon, plugin cold-start, and model-directed profile-switch paths.
- Scope persistent Browser Harness daemons to Hermes `task_id`, preventing model-generated per-step session labels from creating unbounded daemon processes; document session reuse and condition-based waits for sequential browser work.

Distribution ref: `v1.4.11`. The existing `v1.4.10` tag remains immutable at the previously published Linux-ready source commit.

## 1.4.10 - 2026-08-23

- Replace global post-exec page cleanup with invocation-owned target cleanup: track the current target, explicit target creation, target changes, and recursive `openerId` descendants in process memory; never close unrelated concurrent-session tabs.
- Preserve one neutral page only when an invocation owns every remaining page, so cleanup cannot terminate managed Chrome.
- Reduce the default Linux managed-Chrome idle shutdown from 120 to 60 minutes.

## 1.4.9 - 2026-08-23

- Restore post-exec page cleanup: preserve the current ordinary page and close every other ordinary page target after success or exception.
- Clarify that temporary Remote Access routes are session leases, not persistent Leaf Node registrations, and require independent health evidence before reporting a lost node.

## 1.4.8

- Linux installer now fails before mutation when legacy Chrome units, target symlinks, or multiple running profile roots would violate the single-instance contract.
- Reinstallation accepts only Chrome-generated `_metadata` drift in the pinned unpacked uBOL directory while still rejecting any shipped payload change.

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
