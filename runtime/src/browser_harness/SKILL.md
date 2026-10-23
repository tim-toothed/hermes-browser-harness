---
name: browser-harness
description: Use plugin-owned browser_exec with managed Chrome.
version: 1.4.17
---

# Bundled Browser Harness policy

This runtime is embedded in the Hermes Browser Harness plugin. Use the plugin-owned `browser_exec` tool, not a separate CLI installation, cloud browser, or alternate backend. The installed platform skill owns managed-profile selection and lifecycle.

- Each Hermes task starts with an isolated `about:blank` target. Navigate with `goto_url(url)` and wait for load or a targeted DOM condition before extraction.
- Combine navigation, interaction and extraction into 1–3 coherent calls where possible. Use only helpers listed in the tool schema.
- Hermes `task_id` owns daemon isolation and target persistence. `session` is an optional logical label, not a new daemon or profile selector.
- Python variables do not survive calls; task-owned browser state and workspace files do. Continue on the current target. Use `new_tab(url)` only for an additional concurrent page.
- Use `list_tabs()` and `switch_tab(id)` only when the task explicitly needs an already-open tab. Do not inspect unrelated authenticated tabs.
- Do not add fixed sleeps, unnecessary reloads, scrolling, screenshots or helper-discovery calls. Use screenshots when observed visual state requires them.
- Stop for credentials, MFA, payment or permission grants; follow the host's secure-input tools. Never expose cookies or CDP WebSocket addresses.
- Do not launch another Chrome, reset profiles, change configuration, use Browser Use cloud or perform global target cleanup as a fallback. Diagnose the managed path.
- Targets persist across calls within one task. The plugin's session-end hook closes only task-owned targets and its daemon, leaving concurrent tasks untouched.

The upstream runtime version remains `0.1.9`; plugin policy/version is `1.4.17`. Bundled implementation does not imply support for every upstream CLI/cloud workflow.
