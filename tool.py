"""Cross-platform browser_exec adapter for the bundled Browser Harness runtime."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 300
_MIN_TIMEOUT_S = 5
_MAX_TIMEOUT_S = 1800
_STDERR_CAP_CHARS = 4000
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_TASK_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_URL_RE = re.compile(r"https?://[^\s'\"\\)]+", re.IGNORECASE)
_IMAGE_PATH_RE = re.compile(
    r"((?:[A-Za-z]:[\\/]|/)[^\s\"']+?\.(?:png|jpe?g|webp))", re.IGNORECASE
)
_RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
_STATE_VERSION = "plugin-1.1.1-runtime-0.1.9"

_DESCRIPTION = (
    "Drive an already-running Google Chrome through the bundled Browser Harness "
    "0.1.9 runtime and its loopback CDP endpoint. The code argument is Python "
    "executed with Browser Harness pre-imported helpers; print every value needed "
    "in the result. Browser state and workspace persist across calls, but Python "
    "variables do not. Use new_tab(url) for first navigation, goto_url(url) for "
    "current-tab navigation, wait_for_load(), page_info(), js(expr), fill_input(), "
    "capture_screenshot(), and cdp('Domain.method', **kwargs). Chrome installation, "
    "startup, profiles, and OS lifecycle are operator-managed outside this plugin."
)

BROWSER_EXEC_SCHEMA = {
    "name": "browser_exec",
    "description": _DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python using Browser Harness pre-imported helpers. Use print(...) for returned data.",
            },
            "session": {
                "type": "string",
                "description": "Optional Browser Harness daemon namespace. Reuse it for related calls.",
            },
            "timeout_s": {
                "type": "integer",
                "description": "Execution timeout in seconds (default 300, maximum 1800).",
                "default": _DEFAULT_TIMEOUT_S,
            },
        },
        "required": ["code"],
    },
}


def is_available() -> bool:
    """An enabled plugin owns browser_exec; setup failures are returned at call time."""
    return True


def _json_error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _read_config() -> dict:
    try:
        from hermes_cli.config import read_raw_config

        value = read_raw_config() or {}
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        logger.debug("Could not read Hermes config: %s", exc)
        return {}


def _browser_config() -> dict:
    value = _read_config().get("browser", {})
    return value if isinstance(value, dict) else {}


def _configured_cdp_url() -> str:
    return str(
        os.environ.get("BROWSER_CDP_URL")
        or _browser_config().get("cdp_url")
        or "http://127.0.0.1:9222"
    ).strip()


def _configured_name() -> str:
    harness = _browser_config().get("harness", {})
    if not isinstance(harness, dict):
        harness = {}
    name = str(harness.get("name") or "agent").strip()
    return name if _SESSION_RE.fullmatch(name) else "agent"


def _validate_loopback_cdp(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Browser Harness requires an HTTP(S) CDP discovery URL."
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return "Browser Harness CDP must use a loopback address."
    if not parsed.port:
        return "Browser Harness CDP URL must include a port."
    return None


def _cdp_ready(url: str) -> Optional[str]:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/json/version", timeout=3) as response:
            payload = json.loads(response.read())
        if payload.get("webSocketDebuggerUrl"):
            return None
        return "Google Chrome CDP discovery returned no WebSocket endpoint."
    except Exception as exc:
        return (
            f"Google Chrome CDP is unavailable at {url}. "
            "Chrome startup and profile lifecycle are operator-managed outside this plugin. "
            f"Details: {exc}"
        )


def _find_uv() -> Optional[str]:
    uv = shutil.which("uv")
    if uv:
        return uv
    candidates = []
    try:
        from hermes_constants import get_hermes_home

        candidates.append(Path(get_hermes_home()) / "bin" / ("uv.exe" if os.name == "nt" else "uv"))
    except Exception:
        pass
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "uv" / "bin" / "uv.exe")
    candidates.append(Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _runtime_command() -> Optional[list[str]]:
    uv = _find_uv()
    if not uv:
        return None
    if not (_RUNTIME_DIR / "pyproject.toml").is_file() or not (_RUNTIME_DIR / "uv.lock").is_file():
        return None
    return [uv, "run", "--frozen", "--project", str(_RUNTIME_DIR), "browser-harness"]


def _blocked_url(code: str) -> Optional[str]:
    try:
        from tools.browser_tool import evaluate_url_safety
    except Exception:
        return None
    for url in _URL_RE.findall(code or ""):
        error = evaluate_url_safety(url)
        if error:
            return error.get("error", "Blocked: unsafe URL")
    return None


def _base_env() -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("BU_CDP_WS", None)
    home = _hermes_home() / "cache" / "browser-harness" / _STATE_VERSION
    config = home / "config"
    tmp = home / "tmp"
    runtime_key = hashlib.sha256(str(home.resolve()).encode("utf-8")).hexdigest()[:12]
    runtime = Path(tempfile.gettempdir()) / f"hbh-{runtime_key}"
    for path in (home, config, tmp, runtime):
        path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        runtime.chmod(0o700)
    env["BH_HOME"] = str(home)
    env["BH_CONFIG_DIR"] = str(config)
    env["BH_TMP_DIR"] = str(tmp)
    env["BH_RUNTIME_DIR"] = str(runtime)
    env["BH_RUNTIME_DIR_SHARED"] = "1"
    env["BH_TMP_DIR_SHARED"] = "1"
    env.setdefault("ANONYMIZED_TELEMETRY", "false")
    return env


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        configured = os.environ.get("HERMES_HOME")
        return Path(configured) if configured else Path.home() / ".hermes"


def _runtime_name(name: str, cdp_url: str) -> str:
    endpoint = cdp_url.rstrip("/").lower().encode("utf-8")
    suffix = hashlib.sha256(endpoint).hexdigest()[:10]
    return f"{name[:53]}-{suffix}"


def _workspace_dir(task_id: Optional[str]) -> Optional[str]:
    existing = os.environ.get("BH_AGENT_WORKSPACE")
    if existing:
        return existing
    try:
        from hermes_constants import get_hermes_home

        safe = _TASK_ID_SAFE_RE.sub("_", str(task_id or "default"))[:80] or "default"
        path = Path(get_hermes_home()) / "cache" / "browser-harness" / "workspace" / safe
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    except Exception as exc:
        logger.debug("Browser Harness workspace unavailable: %s", exc)
        return None


def _find_screenshot(stdout: str, since: float) -> Optional[str]:
    for path in reversed(_IMAGE_PATH_RE.findall(stdout or "")):
        try:
            if os.path.isfile(path) and os.path.getmtime(path) >= since - 1:
                return path
        except OSError:
            continue
    return None


def _native_screenshot(result: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    try:
        from tools.vision_tools import _resize_image_for_vision, _should_use_native_vision_fast_path

        if not _should_use_native_vision_fast_path():
            return None
        data_url = _resize_image_for_vision(Path(path))
        text = json.dumps(result, ensure_ascii=False)
        return {
            "_multimodal": True,
            "content": [
                {"type": "text", "text": text + "\n\nThe screenshot from this call is attached."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            "text_summary": text,
            "meta": {"screenshot_path": path, "native_vision": True},
        }
    except Exception as exc:
        logger.debug("Native screenshot attach failed: %s", exc)
        return None


def handle_browser_exec(args: dict, **kwargs):
    """Execute one Browser Harness program against an existing loopback CDP."""
    code = str(args.get("code") or "")
    if not code.strip():
        return _json_error("No code provided. Use Browser Harness helpers and print returned data.")
    blocked = _blocked_url(code)
    if blocked:
        return _json_error(blocked)

    cdp_url = _configured_cdp_url()
    error = _validate_loopback_cdp(cdp_url) or _cdp_ready(cdp_url)
    if error:
        return _json_error(error)
    command = _runtime_command()
    if not command:
        return _json_error("Bundled Browser Harness runtime is incomplete or uv is unavailable.")

    session = str(args.get("session") or "").strip()
    if session and not _SESSION_RE.fullmatch(session):
        return _json_error(
            f"Invalid session name {session!r}: use 1-64 letters, digits, dashes, or underscores."
        )
    try:
        timeout = max(_MIN_TIMEOUT_S, min(int(args.get("timeout_s", _DEFAULT_TIMEOUT_S)), _MAX_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_S

    env = _base_env()
    env["BU_NAME"] = _runtime_name(session or _configured_name(), cdp_url)
    env["BU_CDP_URL"] = cdp_url
    workspace = _workspace_dir(kwargs.get("task_id"))
    if workspace:
        env["BH_AGENT_WORKSPACE"] = workspace

    popen_extra: dict[str, Any] = {}
    if os.name == "nt":
        try:
            from hermes_cli._subprocess_compat import windows_hide_flags

            popen_extra["creationflags"] = windows_hide_flags()
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            popen_extra["startupinfo"] = startup
        except Exception as exc:
            logger.debug("Windows hide flags unavailable: %s", exc)

    started = time.time()
    try:
        process = subprocess.run(
            command,
            input=code,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=str(_RUNTIME_DIR),
            **popen_extra,
        )
    except subprocess.TimeoutExpired:
        return _json_error(f"browser-harness exec timed out after {timeout}s.")
    except OSError as exc:
        return _json_error(f"Failed to launch bundled Browser Harness runtime: {exc}")

    result: dict[str, Any] = {
        "success": process.returncode == 0,
        "exit_code": process.returncode,
        "output": process.stdout,
    }
    if workspace:
        result["workspace"] = workspace
    if session:
        result["session"] = session
    stderr = (process.stderr or "").strip()
    if stderr:
        result["stderr"] = stderr[:_STDERR_CAP_CHARS] + (
            "\n… (stderr truncated)" if len(stderr) > _STDERR_CAP_CHARS else ""
        )
    screenshot = _find_screenshot(process.stdout, started)
    if screenshot:
        result["screenshot_path"] = screenshot
        native = _native_screenshot(result, screenshot)
        if native is not None:
            return native
    return json.dumps(result, ensure_ascii=False)
