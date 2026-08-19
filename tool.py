"""Standalone browser_exec implementation backed by Browser Harness."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
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

_DESCRIPTION = (
    "Drive persistent managed Google Chrome through Browser Harness. The code "
    "argument is Python executed with Browser Harness pre-imported helpers; print "
    "every value needed in the result. The browser profile and workspace persist "
    "across calls, but Python variables do not. Batch related actions in one call. "
    "Use goto_url(url) then wait_for_load() for normal navigation; use new_tab(url) "
    "only when one operation genuinely needs multiple pages at once. page_info() "
    "summarizes the current page, js(expr) reads or evaluates DOM state, "
    "fill_input(selector, text) types, capture_screenshot() saves a screenshot, and "
    "cdp('Domain.method', **kwargs) exposes raw CDP. Use web_search for ordinary "
    "public source discovery; use Browser Harness for known URLs, interactive "
    "controls, downloads/uploads, JavaScript, and existing authenticated sessions. "
    "Stop for passwords, OTP/MFA, CAPTCHA, payment, or user consent."
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
                "description": "Optional Browser Harness daemon namespace. Reuse the same name for related calls.",
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
    """The enabled plugin owns browser_exec; runtime errors carry setup hints."""
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


def _harness_config() -> dict:
    value = _browser_config().get("harness", {})
    return value if isinstance(value, dict) else {}


def _configured_name() -> str:
    name = str(_harness_config().get("name") or "agent").strip()
    return name if _SESSION_RE.fullmatch(name) else "agent"


def _configured_cdp_url() -> str:
    return str(
        os.environ.get("BROWSER_CDP_URL")
        or _browser_config().get("cdp_url")
        or "http://127.0.0.1:9222"
    ).strip()


def _candidate_bin_dirs() -> list[str | None]:
    dirs: list[str | None] = [None]
    try:
        from hermes_constants import get_hermes_home

        dirs.insert(0, str(Path(get_hermes_home()) / "bin"))
    except Exception:
        pass
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(str(Path(appdata) / "uv" / "bin"))
    dirs.append(str(Path.home() / ".local" / "bin"))
    return dirs


def _find_cli() -> Optional[list[str]]:
    for directory in _candidate_bin_dirs():
        executable = shutil.which("browser-harness", path=directory)
        if executable:
            return [executable]
    for directory in _candidate_bin_dirs():
        uvx = shutil.which("uvx", path=directory)
        if uvx:
            return [uvx, "browser-harness"]
    return None


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
    env.setdefault("ANONYMIZED_TELEMETRY", "false")
    return env


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


def _cdp_ready(url: str, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read())
        return bool(payload.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def apply_profile_preferences(user_data_dir: Path, profile_directory: str) -> bool:
    """Apply only managed automation preferences; preserve unrelated profile data."""
    profile_dir = user_data_dir / profile_directory
    profile_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir = (user_data_dir / "Downloads").resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / "Preferences"
    if path.is_file():
        try:
            preferences = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Managed Chrome Preferences cannot be read: {exc}") from exc
        if not isinstance(preferences, dict):
            raise RuntimeError("Managed Chrome Preferences root must be an object.")
    else:
        preferences = {}

    desired = {
        ("translate", "enabled"): False,
        ("profile", "default_content_setting_values", "notifications"): 2,
        ("session", "restore_on_startup"): 5,
        ("browser", "has_seen_welcome_page"): True,
        ("profile", "exit_type"): "Normal",
        ("profile", "exited_cleanly"): True,
        ("download", "default_directory"): str(downloads_dir),
        ("download", "prompt_for_download"): False,
        ("download", "directory_upgrade"): True,
    }
    changed = False
    for keys, value in desired.items():
        node = preferences
        for key in keys[:-1]:
            child = node.get(key)
            if child is None:
                child = {}
                node[key] = child
            elif not isinstance(child, dict):
                raise RuntimeError(f"Managed Chrome Preferences conflicts at {'.'.join(keys[:-1])}.")
            node = child
        if node.get(keys[-1]) != value:
            node[keys[-1]] = value
            changed = True
    if not changed:
        return False

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _launch_config() -> Optional[dict[str, str]]:
    cfg = _harness_config()
    executable = os.path.expandvars(str(cfg.get("executable") or "").strip())
    user_data_dir = os.path.expandvars(str(cfg.get("user_data_dir") or "").strip())
    if not executable or not user_data_dir:
        return None
    return {
        "executable": executable,
        "user_data_dir": user_data_dir,
        "profile_directory": str(cfg.get("profile_directory") or "Default").strip() or "Default",
    }


def _ensure_browser(env: dict, timeout_s: float = 15.0) -> Optional[str]:
    if os.name != "nt":
        return None
    launch = _launch_config()
    if launch is None:
        return None
    cdp_url = str(env.get("BU_CDP_URL") or "").strip()
    parsed = urllib.parse.urlparse(cdp_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    if not parsed.port:
        return f"Browser Harness CDP URL has no port: {cdp_url}"
    if _cdp_ready(cdp_url):
        return None
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=0.3):
            return f"Browser Harness cannot start managed Chrome because {parsed.hostname}:{parsed.port} is occupied by a non-CDP listener."
    except OSError:
        pass

    executable = Path(launch["executable"])
    user_data_dir = Path(launch["user_data_dir"])
    if not executable.is_file():
        return f"Configured Chrome executable does not exist: {executable}"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    try:
        apply_profile_preferences(user_data_dir, launch["profile_directory"])
    except (OSError, RuntimeError) as exc:
        return f"Failed to configure managed Chrome profile: {exc}"

    command = [
        str(executable),
        f"--remote-debugging-port={parsed.port}",
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={launch['profile_directory']}",
        "--disable-background-mode",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "about:blank",
    ]
    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        return f"Failed to launch configured Chrome: {exc}"
    deadline = time.monotonic() + max(1.0, timeout_s)
    while time.monotonic() < deadline:
        if _cdp_ready(cdp_url):
            return None
        if process.poll() is not None:
            break
        time.sleep(0.2)
    return f"Configured Chrome did not expose Browser Harness CDP at {cdp_url} within {timeout_s:g}s."


def _browser_cdp_call(cdp_url: str, method: str, params: Optional[dict] = None) -> dict:
    from websockets.sync.client import connect

    with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=5) as response:
        version = json.loads(response.read())
    with connect(version["webSocketDebuggerUrl"], origin=None, open_timeout=5, close_timeout=2) as ws:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            response = json.loads(ws.recv(timeout=10))
            if response.get("id") != 1:
                continue
            if "error" in response:
                raise RuntimeError(response["error"])
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"Invalid CDP result for {method}")
            return result


def _ensure_extensions(env: dict) -> Optional[str]:
    configured = _harness_config().get("extensions") or []
    if not isinstance(configured, list):
        return "Browser Harness extensions config must be a list."
    if not configured:
        return None
    cdp_url = str(env.get("BU_CDP_URL") or "").strip()

    def normalized(value: object) -> str:
        return os.path.normcase(os.path.normpath(os.path.expandvars(str(value))))

    expected = []
    for item in configured:
        if not isinstance(item, dict):
            return "Each Browser Harness extension must be an object."
        extension_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "").strip()
        path = os.path.expandvars(str(item.get("path") or "").strip())
        if not re.fullmatch(r"[a-p]{32}", extension_id):
            return f"Invalid Browser Harness extension id: {extension_id!r}"
        if not version or not path or not Path(path).is_dir():
            return f"Browser Harness extension is unavailable: {extension_id}"
        expected.append({"id": extension_id, "version": version, "path": path})

    def missing_id(extensions: list) -> Optional[str]:
        by_id = {str(item.get("id")): item for item in extensions if isinstance(item, dict)}
        for item in expected:
            actual = by_id.get(item["id"])
            if actual is None:
                return item["id"]
            if normalized(actual.get("path", "")) != normalized(item["path"]):
                raise RuntimeError(f"Extension {item['id']} is loaded from an unexpected path.")
            if actual.get("version") != item["version"] or actual.get("enabled") is not True:
                raise RuntimeError(f"Extension {item['id']} failed version/enabled read-back.")
        return None

    try:
        current = _browser_cdp_call(cdp_url, "Extensions.getExtensions").get("extensions", [])
        missing = missing_id(current)
        while missing:
            item = next(value for value in expected if value["id"] == missing)
            loaded = _browser_cdp_call(
                cdp_url,
                "Extensions.loadUnpacked",
                {"path": str(Path(item["path"]).resolve())},
            )
            if loaded.get("id") != missing:
                raise RuntimeError(f"Chrome loaded an unexpected extension id for {missing}.")
            current = _browser_cdp_call(cdp_url, "Extensions.getExtensions").get("extensions", [])
            missing = missing_id(current)
        return None
    except Exception as exc:
        return f"Browser Harness extension initialization failed: {exc}"


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
    """Execute one Browser Harness Python program and return a Hermes tool result."""
    code = str(args.get("code") or "")
    if not code.strip():
        return _json_error("No code provided. Use Browser Harness pre-imported helpers and print returned data.")
    blocked = _blocked_url(code)
    if blocked:
        return _json_error(blocked)
    command = _find_cli()
    if not command:
        return _json_error(
            "browser-harness CLI not found. Install it with `uv tool install browser-harness`."
        )

    session = str(args.get("session") or "").strip()
    if session and not _SESSION_RE.fullmatch(session):
        return _json_error(
            f"Invalid session name {session!r}: use 1-64 letters, digits, dashes, or underscores."
        )
    env = _base_env()
    env["BU_NAME"] = session or _configured_name()
    env["BU_CDP_URL"] = _configured_cdp_url()
    workspace = _workspace_dir(kwargs.get("task_id"))
    if workspace:
        env["BH_AGENT_WORKSPACE"] = workspace

    error = _ensure_browser(env)
    if error:
        return _json_error(error)
    error = _ensure_extensions(env)
    if error:
        return _json_error(error)
    try:
        timeout = max(_MIN_TIMEOUT_S, min(int(args.get("timeout_s", _DEFAULT_TIMEOUT_S)), _MAX_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_S

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
            **popen_extra,
        )
    except subprocess.TimeoutExpired:
        return _json_error(
            f"browser-harness exec timed out after {timeout}s; retry with a larger timeout_s or split the task."
        )
    except OSError as exc:
        return _json_error(f"Failed to launch browser-harness CLI: {exc}")

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
