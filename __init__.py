"""External Browser Harness tool plugin for Hermes Agent."""

import logging

from .tool import BROWSER_EXEC_SCHEMA, handle_browser_exec, is_available, stop_task_daemon


logger = logging.getLogger(__name__)


_SUPPRESSED_BUILTIN_BROWSER_TOOLS = (
    "browser_back",
    "browser_cdp",
    "browser_click",
    "browser_console",
    "browser_dialog",
    "browser_get_images",
    "browser_navigate",
    "browser_press",
    "browser_scroll",
    "browser_snapshot",
    "browser_type",
    "browser_vision",
)


def _never_available() -> bool:
    """Keep legacy browser actions out of the model-facing tool surface."""
    return False


def _suppressed_builtin_handler(args: dict, **kwargs):
    """Fail closed if a host bypasses availability filtering."""
    raise RuntimeError("Built-in browser action is disabled; use browser_exec")


def _suppressed_schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Disabled by the Browser Harness plugin.",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _handle_browser_exec(args: dict, **kwargs):
    """Root-module wrapper keeps Hermes' override authorization auditable."""
    return handle_browser_exec(args, **kwargs)


def _on_session_end(**kwargs) -> None:
    """Release only the daemon belonging to the completed parent/child task."""
    try:
        stop_task_daemon(str(kwargs.get("task_id") or ""))
    except Exception:
        logger.warning("Browser Harness task cleanup hook failed", exc_info=True)


def register(ctx) -> None:
    """Make Browser Harness the exclusive implementation of Hermes browser."""
    for name in _SUPPRESSED_BUILTIN_BROWSER_TOOLS:
        ctx.register_tool(
            name=name,
            toolset="browser",
            schema=_suppressed_schema(name),
            handler=_suppressed_builtin_handler,
            check_fn=_never_available,
            description="Disabled in favor of Browser Harness browser_exec",
            override=True,
        )
    ctx.register_tool(
        name="browser_exec",
        toolset="browser",
        schema=BROWSER_EXEC_SCHEMA,
        handler=_handle_browser_exec,
        check_fn=is_available,
        description="Browser Harness execution through persistent managed Chrome",
        emoji="🌐",
        override=True,
    )
    ctx.register_hook("on_session_end", _on_session_end)
