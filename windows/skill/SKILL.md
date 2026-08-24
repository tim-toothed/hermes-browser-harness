---
name: browser-harness
description: Use managed Google Chrome through the Browser Harness plugin on Windows.
version: 1.4.10
author: Timur Sharifullin (tim_toothed), Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [browser, browser-harness, chrome, cdp, profiles, windows]
    related_skills: []
---

# Browser Harness — Windows

Use the plugin-provided `browser_exec` tool for browser work. The plugin owns the bundled Browser Harness runtime, default Chrome cold start, extension reconciliation, and per-invocation tab cleanup. Do not run a separate Browser Harness `uv tool`, patch Hermes core, or reintroduce a global tab limit.

## Routing

- Use `browser_exec` for a known URL, rendered UI, clicks, typing, uploads/downloads, screenshots, or an existing authenticated browser session.
- Use direct web/search tools for public discovery and static retrieval when browser interaction is unnecessary.
- Never fall back to `computer_use`, the built-in `browser` toolset, an employee's ordinary Chrome profile, or anonymous scraping after a Browser Harness failure. Diagnose the managed route.
- Page actions go through `browser_exec(code=...)`. Use terminal only for operator diagnostics and managed-profile lifecycle work.

## Managed Profile Contract

The registry is `browser-profiles.json` beside this file. Select its `default` entry unless the user explicitly identifies another profile.

Rules:

1. Every `user_data_dir` must be an absolute path to a separate agent-owned directory. Never point at, copy, reset, inspect, or delete an employee's ordinary Chrome profile.
2. Only one managed Chrome profile may own `127.0.0.1:9222` at a time. `BU_NAME` remains `agent`; Browser Harness sessions isolate daemon/tab namespaces, not Chrome profiles.
3. Before a page operation, if port `9222` is already listening, verify the owning Chrome command line uses the selected registry entry's `user_data_dir`.
4. If the default profile is selected and port `9222` is free, call `browser_exec`; plugin code owns cold startup using the configured executable, profile, and loopback CDP endpoint.
5. If another registered profile is active, close it through CDP, verify its exact process tree exited and port `9222` became free, then launch the selected registered profile with:
   - `--remote-debugging-address=127.0.0.1`
   - `--remote-debugging-port=9222`
   - its registered `--user-data-dir`
   - `--profile-directory=Default`
   - `--disable-background-mode`
   - `--no-first-run`
   - `--no-default-browser-check`
6. Never terminate unrelated `chrome.exe` processes.
7. Create or change profiles only on an explicit user request. Preserve existing registry entries and change `default` only when explicitly requested.
8. Write the registry atomically with Python JSON parsing and `os.replace`; never edit it with string replacement.

When the user creates a scheduled browser task for a named profile, warn once that tasks requiring different profiles must not overlap. Same-profile tasks may use separate Browser Harness sessions.

## Page Workflow

- Prefer `goto_url(url)` in the current page, then `wait_for_load()`. Use `new_tab(url)` only when multiple pages are needed inside one call.
- Batch coherent navigation/read/action work into one bounded call. Python variables do not survive calls; workspace files and the browser session do.
- Prefer the accessibility tree (`cdp("Accessibility.getFullAXTree")`) for semantic interaction; verify every state-changing action.
- Use screenshots when layout, imagery, canvas, or animation matters.
- Stop for passwords, MFA/OTP, payment, permission grants, or ambiguous account selection. Existing unambiguous SSO may be used.
- Do not expose cookies, browser databases, credentials, account identifiers, or the CDP WebSocket URL.

## CAPTCHA

The plugin and configured Chrome extensions own extension loading before the LLM browser program. Do not choose or load extensions from `browser_exec` or this skill.

If a CAPTCHA or bot challenge appears, stop the active page program and let the user solve it in the managed Chrome window. Resume with a new `browser_exec` call only after the user confirms completion. Do not call CAPTCHA provider APIs directly and do not switch browser backends or profiles as an automatic fallback.

## Diagnostics

- A successful plugin version check or `/json/version` response is not acceptance.
- If `browser_exec` cannot connect, verify the configured endpoint, the Chrome process command line, and the selected `user_data_dir`; then inspect the plugin/runtime error.
- Do not install a separate `browser-harness` executable to mask a bundled-runtime error.
- A native Chrome remote-debugging permission prompt requires user action; do not click it or retry in a loop.

## Acceptance

A Windows installation is accepted only when all of the following are proven:

1. Plugin version is `1.4.10` and bundled Browser Harness runtime is `0.1.9`.
2. Toolset `browser_harness` is enabled; built-in `browser` and `computer_use` are disabled for CLI and Telegram.
3. Chrome listens only on loopback `127.0.0.1:9222` with the selected registry `user_data_dir`.
4. The pinned extension is loaded from the configured agent-owned path with the expected id/version.
5. `browser_exec` completes a real page operation through Hermes.
6. Existing managed profile data survives an update install.
7. An authenticated business-service scenario succeeds without exposing session data.

Run acceptance sequentially and stop at the first failure. Fix that cause before continuing dependent scenarios.
