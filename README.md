# Hermes Browser Harness

Standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that replaces the built-in `browser_exec` handler with [Browser Harness](https://github.com/browser-use/browser-harness), without modifying Hermes core.

## Install

```bash
hermes plugins install tim-toothed/hermes-browser-harness
```

When Hermes asks whether to enable the plugin and grant permission to replace built-in tools, confirm both prompts. The override is required because this plugin intentionally replaces `browser_exec` while preserving its native tool name and `browser` toolset.

Restart the active Hermes process after installation so it reloads plugins.

## Requirements

- Hermes Agent with standalone plugin support
- Windows and Google Chrome
- Browser Harness CLI available as `browser-harness`, or `uvx` available for fallback execution
- Managed Chrome configuration under `browser.harness` when automatic Chrome launch is required

Minimal runtime configuration:

```yaml
browser:
  backend: browser-use
  cdp_url: http://127.0.0.1:9222
  harness:
    name: agent
    executable: C:\Program Files\Google\Chrome\Application\chrome.exe
    user_data_dir: C:\Users\YOUR_USER\AppData\Local\hermes\Hermes Automation
    profile_directory: Default
```

Use `hermes config set` rather than editing `config.yaml` manually.

## What it does

- registers an explicit override for the existing `browser_exec` tool;
- keeps the upstream `browser` toolset and schema-facing workflow;
- launches or reuses one managed Chrome on loopback CDP;
- preserves the persistent Chrome profile;
- executes Browser Harness Python through its CLI;
- leaves Hermes source files unchanged.

## Security

Tool override is a privileged Hermes capability. Review this repository before granting it. The plugin refuses non-loopback managed Chrome startup and reuses Hermes URL safety checks when available. It does not collect credentials or telemetry.

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile __init__.py tool.py tests/test_plugin.py
```

## Русский

Плагин штатно устанавливается через `hermes plugins install`, переопределяет только `browser_exec` и не изменяет внутренние файлы Hermes. При установке необходимо явно разрешить override встроенного инструмента.
