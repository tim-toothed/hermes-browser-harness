"""External Browser Harness tool plugin for Hermes Agent."""

from .tool import BROWSER_EXEC_SCHEMA, handle_browser_exec, is_available


def _handle_browser_exec(args: dict, **kwargs):
    """Root-module wrapper keeps Hermes' override authorization auditable."""
    return handle_browser_exec(args, **kwargs)


def register(ctx) -> None:
    """Replace the built-in browser_exec without modifying Hermes core."""
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
