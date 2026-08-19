# Hermes Browser Harness

Cross-platform Hermes Agent plugin that replaces the built-in `browser_exec` handler with a bundled, version-locked Browser Harness runtime.

- Browser Harness runtime: **0.1.9**, vendored in this repository
- Supported hosts: Windows and Linux
- Browser transport: existing loopback Chrome DevTools Protocol endpoint
- Hermes core modifications: none
- Chrome installation, startup, profile selection, and OS lifecycle: outside this plugin
- Managed Chrome configuration: additive profile preferences before cold start and configured unpacked-extension loading on `browser_exec`
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

The configured endpoint must be loopback HTTP(S) CDP discovery. The plugin does not locate, download, install, launch, stop, update, or repair Google Chrome. It does not create or select Chrome profiles, and an explicit endpoint never falls back to `DevToolsActivePort` discovery.

When `browser.harness.user_data_dir` is configured and the CDP endpoint is down, the plugin additively prepares the configured profile before the external lifecycle starts Chrome. It preserves unrelated preferences and extensions while applying the managed translation, notification, session-restore, clean-exit, welcome-page, and download settings.

When `browser.harness.extensions` is configured, every `browser_exec` verifies each extension's ID, version, enabled state, and exact path. Missing configured extensions are loaded into the already-running Chrome with `Extensions.loadUnpacked`; unexpected paths or versions fail closed. Extension artifacts and credentials remain deployment inputs outside the public repository.

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
  → managed preference preparation / configured extension read-back
  → bundled Browser Harness 0.1.9
  → BU_CDP_URL
  → operator-managed Google Chrome
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
