# Hermes Browser Harness

Cross-platform Hermes Agent plugin that replaces the built-in `browser_exec` handler with a bundled, version-locked Browser Harness runtime.

- Browser Harness runtime: **0.1.9**, vendored in this repository
- Supported hosts: Windows and Linux
- Browser transport: configured loopback Chrome DevTools Protocol endpoint
- Hermes core modifications: none
- Chrome installation and non-default profile switching: operator/managed-profile lifecycle
- Default managed Chrome cold start: deterministic plugin code on Windows
- Managed Chrome configuration: additive profile preferences before cold start and code-level configured unpacked-extension loading
- Plugin-owned daemon/config/runtime namespaces; no reuse of a global Browser Harness daemon

## Install

```bash
hermes plugins install tim-toothed/hermes-browser-harness
```

Enable the plugin and grant its required built-in tool override when Hermes prompts. On Hermes versions that separate installation from the privileged grant, run:

```bash
hermes plugins enable browser-harness --allow-tool-override
```

Restart the active Hermes process after installation so it reloads plugins.

## Configuration

```bash
hermes config set browser.backend browser-use
hermes config set browser.cdp_url http://127.0.0.1:9222
```

The configured endpoint must be loopback HTTP(S) CDP discovery. The plugin does not locate, download, install, update, or repair Google Chrome. It does not create or select Chrome profiles, and an explicit endpoint never falls back to `DevToolsActivePort` discovery. On Windows, when that endpoint is down and explicit `browser.harness.executable` and `browser.harness.user_data_dir` values are configured, plugin code cold-starts that default managed profile.

Before that cold start, the plugin additively prepares the configured profile. It preserves unrelated preferences and extensions while applying the managed translation, notification, session-restore, clean-exit, welcome-page, and download settings.

When `browser.harness.extensions` is configured, plugin code verifies each extension's ID, version, enabled state, and exact path after Chrome is ready and before executing the requested Browser Harness program. Missing configured extensions are loaded with browser-level `Extensions.loadUnpacked`; unexpected paths or versions fail closed. The LLM neither selects nor loads these extensions. Extension artifacts and credentials remain deployment inputs outside the public repository.

### CAPTCHA boundary

The plugin only loads and verifies a configured CAPTCHA extension. It does not call the provider API, poll provider telemetry, detach page targets, or infer completion from Chrome `/json/list`.

CAPTCHA orchestration belongs to the node's Hermes-visible policy skill. The accepted headed-Windows policy keeps the same `browser_exec` page and exact target visible in the interactive desktop, waits 80 seconds without page interaction, and inspects a screenshot. If the challenge is still visibly unsolved, it preserves the same page state for one additional 80-second interval and performs one final screenshot inspection. There is no automatic third interval or fallback to another browser, profile, target, or backend.

## Runtime

The complete Browser Harness 0.1.9 Python package is stored under `runtime/src/browser_harness`. Its MIT license is preserved in `runtime/BROWSER_HARNESS_LICENSE`. Exact Python dependencies are locked in `runtime/uv.lock` and run in the plugin-local environment with:

```text
uv run --frozen --project <plugin>/runtime browser-harness
```

No separate global `browser-harness` installation is required. The first execution may download only the Python packages pinned by `uv.lock`; it never installs a browser.

## Architecture

```text
Hermes browser toolset
  → browser_exec override
  → default Chrome cold start when required
  → managed preference preparation
  → configured extension initialization and read-back
  → bundled Browser Harness 0.1.9
  → BU_CDP_URL
  → managed Google Chrome
```

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile __init__.py tool.py tests/test_plugin.py runtime/src/browser_harness/*.py
cd runtime
uv lock --check
uv run --frozen browser-harness --version
```

## License

The plugin adapter is MIT licensed by Timur Sharifullin / PROCVETAEV. The vendored Browser Harness runtime remains MIT licensed by Browser Use; see `runtime/BROWSER_HARNESS_LICENSE`.
