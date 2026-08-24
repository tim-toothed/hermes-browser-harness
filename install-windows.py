#!/usr/bin/env python3
"""Install the Windows host contract for PROCVETAEV Browser Harness 1.4.10.

Run this script from an already installed and enabled browser-harness plugin
checkout. It configures one managed Chrome profile on loopback CDP, installs
the pinned unpacked extension and policy skill, and creates an interactive
logon task. The Browser Harness Python runtime remains bundled with the plugin.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PureWindowsPath

PLUGIN_VERSION = "1.4.10"
BROWSER_HARNESS_VERSION = "0.1.9"
CDP_HOST = "127.0.0.1"
DEFAULT_CDP_PORT = 9222
HARNESS_NAME = "agent"
PROFILE_DIRECTORY = "Hermes Automation"
TASK_NAME = r"\PROCVETAEV\Browser Harness Chrome"
UBOL_ID = "ddkjiahejlhfcafbddmgiahcphecmpfh"
UBOL_VERSION = "2026.812.1211"
UBOL_SHA256 = "fd910beea9e130ec63b8dc6a8a13e529fc2ab114f9e6e120c9ba36ccf01d1ce3"
ROOT = Path(__file__).resolve().parent
UBOL_ARCHIVE = ROOT / "extensions" / "ublock-origin-lite" / UBOL_VERSION / "ublock-origin-lite-unpacked.zip"
WINDOWS_SKILL = ROOT / "windows" / "skill" / "SKILL.md"
OWNER_MARKER = ".windows-browser-harness-owned"


def run(argv: list[str | Path], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [str(value) for value in argv]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed


def require_command(*names: str) -> Path:
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved).resolve()
    raise RuntimeError(f"Required command is unavailable: {' or '.join(names)}")


def resolve_chrome() -> Path:
    candidates = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Google Chrome is required but chrome.exe was not found.")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package() -> None:
    manifest = ROOT / "plugin.yaml"
    runtime_project = ROOT / "runtime" / "pyproject.toml"
    runtime_lock = ROOT / "runtime" / "uv.lock"
    for required in (manifest, runtime_project, runtime_lock, UBOL_ARCHIVE, WINDOWS_SKILL):
        if not required.is_file():
            raise RuntimeError(f"Package is incomplete: {required}")
    manifest_text = manifest.read_text(encoding="utf-8")
    if not re.search(rf"(?m)^version:\s*{re.escape(PLUGIN_VERSION)}\s*$", manifest_text):
        raise RuntimeError(f"plugin.yaml is not version {PLUGIN_VERSION}.")
    runtime_text = runtime_project.read_text(encoding="utf-8")
    if not re.search(rf'(?m)^version\s*=\s*"{re.escape(BROWSER_HARNESS_VERSION)}"\s*$', runtime_text):
        raise RuntimeError(f"Bundled Browser Harness runtime is not {BROWSER_HARNESS_VERSION}.")
    if sha256(UBOL_ARCHIVE) != UBOL_SHA256:
        raise RuntimeError("Pinned uBlock Origin Lite archive checksum does not match.")


def verify_plugin_enabled(hermes: Path) -> None:
    payload = json.loads(run([hermes, "plugins", "list", "--json"]).stdout)
    matches = [item for item in payload if item.get("name") == "browser-harness"]
    if len(matches) != 1:
        raise RuntimeError("browser-harness plugin must be installed before host setup.")
    plugin = matches[0]
    if plugin.get("version") != PLUGIN_VERSION or plugin.get("status") != "enabled":
        raise RuntimeError(
            f"browser-harness plugin must be enabled at {PLUGIN_VERSION}; "
            f"found version={plugin.get('version')!r}, status={plugin.get('status')!r}."
        )


def archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for item in archive.infolist():
        relative = PureWindowsPath(item.filename.replace("/", "\\"))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe extension archive member: {item.filename}")
        if item.filename.startswith("_metadata/"):
            continue
        members.append(item)
    return members


def install_ubol(hermes_home: Path) -> Path:
    target = hermes_home / "extensions" / "ublock-origin-lite" / UBOL_VERSION
    manifest_path = target / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("version") == UBOL_VERSION:
                return target
        except (OSError, json.JSONDecodeError):
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{UBOL_VERSION}.", dir=target.parent))
    try:
        with zipfile.ZipFile(UBOL_ARCHIVE) as archive:
            for item in archive_members(archive):
                archive.extract(item, temporary)
        manifest = json.loads((temporary / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("version") != UBOL_VERSION:
            raise RuntimeError("Extracted uBlock Origin Lite version does not match.")
        if target.exists():
            shutil.rmtree(target)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_registry(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {"default", "profiles"}:
        raise RuntimeError("Browser profile registry must contain default and profiles.")
    default = payload.get("default")
    profiles = payload.get("profiles")
    if not isinstance(default, str) or not isinstance(profiles, dict) or default not in profiles:
        raise RuntimeError("Browser profile registry has an invalid default.")
    for profile_id, profile in profiles.items():
        if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", profile_id):
            raise RuntimeError(f"Invalid profile id: {profile_id!r}")
        if not isinstance(profile, dict) or set(profile) != {"label", "description", "user_data_dir"}:
            raise RuntimeError(f"Invalid profile entry: {profile_id}")
        if not all(isinstance(value, str) and value for value in profile.values()):
            raise RuntimeError(f"Empty profile field: {profile_id}")
        if not PureWindowsPath(profile["user_data_dir"]).is_absolute():
            raise RuntimeError(f"Profile path is not absolute: {profile_id}")
    return payload


def install_skill(hermes_home: Path, user_data_dir: Path) -> tuple[Path, Path]:
    target = hermes_home / "skills" / "browser-harness"
    target.mkdir(parents=True, exist_ok=True)
    skill_path = target / "SKILL.md"
    registry_path = target / "browser-profiles.json"
    shutil.copy2(WINDOWS_SKILL, skill_path)
    if registry_path.exists():
        existing = validate_registry(json.loads(registry_path.read_text(encoding="utf-8")))
        if HARNESS_NAME in existing["profiles"]:
            existing["profiles"][HARNESS_NAME]["user_data_dir"] = str(user_data_dir)
            write_json_atomic(registry_path, existing)
    else:
        write_json_atomic(
            registry_path,
            {
                "default": HARNESS_NAME,
                "profiles": {
                    HARNESS_NAME: {
                        "label": "Основной профиль",
                        "description": "Основной профиль Browser Harness",
                        "user_data_dir": str(user_data_dir),
                    }
                },
            },
        )
    validate_registry(json.loads(registry_path.read_text(encoding="utf-8")))
    (target / OWNER_MARKER).write_text(f"browser-harness-windows {PLUGIN_VERSION}\n", encoding="utf-8")
    return skill_path, registry_path


def config_set(hermes: Path, key: str, value: str) -> None:
    run([hermes, "config", "set", "--force", key, value])
    actual = run([hermes, "config", "get", key]).stdout.strip()
    if value not in actual:
        raise RuntimeError(f"Hermes config read-back failed: {key}")


def configure_hermes(hermes: Path, chrome: Path, user_data_dir: Path, extension_path: Path, cdp_port: int) -> None:
    cdp_url = f"http://{CDP_HOST}:{cdp_port}"
    values = {
        "browser.cloud_provider": "local",
        "browser.cdp_url": cdp_url,
        "browser.harness.name": HARNESS_NAME,
        "browser.harness.executable": str(chrome),
        "browser.harness.user_data_dir": str(user_data_dir),
        "browser.harness.profile_directory": "Default",
        "browser.harness.extensions": json.dumps(
            [{"id": UBOL_ID, "version": UBOL_VERSION, "path": str(extension_path)}],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    run([hermes, "config", "unset", "browser.backend"], check=False)
    for key, value in values.items():
        config_set(hermes, key, value)
    for platform in ("cli", "telegram"):
        run([hermes, "tools", "enable", "browser_harness", "--platform", platform])
        run([hermes, "tools", "disable", "browser", "--platform", platform])
        run([hermes, "tools", "disable", "computer_use", "--platform", platform])
        listing = " ".join(run([hermes, "tools", "list", "--platform", platform]).stdout.casefold().split())
        for expected in ("enabled browser_harness", "disabled browser", "disabled computer_use"):
            if expected not in listing:
                raise RuntimeError(f"Hermes toolset read-back failed on {platform}: missing {expected!r}")


def chrome_arguments(user_data_dir: Path, cdp_port: int) -> str:
    args = [
        f'--remote-debugging-address={CDP_HOST}',
        f'--remote-debugging-port={cdp_port}',
        f'--user-data-dir="{user_data_dir}"',
        '--profile-directory=Default',
        '--disable-background-mode',
        '--no-first-run',
        '--no-default-browser-check',
        '--new-window',
        'about:blank',
    ]
    return " ".join(args)


def current_windows_user() -> str:
    whoami = shutil.which("whoami.exe") or shutil.which("whoami")
    if whoami:
        value = run([whoami]).stdout.strip()
        if value:
            return value
    domain = os.environ.get("USERDOMAIN")
    username = os.environ.get("USERNAME") or getpass.getuser()
    return f"{domain}\\{username}" if domain else username


def install_logon_task(chrome: Path, user_data_dir: Path, cdp_port: int) -> None:
    schtasks = require_command("schtasks.exe", "schtasks")
    user = current_windows_user()
    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>PROCVETAEV Browser Harness managed Chrome</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{html.escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{html.escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{html.escape(str(chrome))}</Command><Arguments>{html.escape(chrome_arguments(user_data_dir, cdp_port))}</Arguments><WorkingDirectory>{html.escape(str(chrome.parent))}</WorkingDirectory></Exec></Actions>
</Task>
'''
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-16", delete=False) as handle:
        handle.write(xml)
        temporary = Path(handle.name)
    try:
        run([schtasks, "/Create", "/TN", TASK_NAME, "/XML", temporary, "/F"])
        query = run([schtasks, "/Query", "/TN", TASK_NAME, "/XML"]).stdout
        required = [str(chrome), str(user_data_dir), f"--remote-debugging-port={cdp_port}", "IgnoreNew", "InteractiveToken"]
        if any(value.casefold() not in query.casefold() for value in required):
            raise RuntimeError("Scheduled Task read-back does not match the managed Chrome contract.")
    finally:
        temporary.unlink(missing_ok=True)


def cdp_ready(cdp_port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{CDP_HOST}:{cdp_port}/json/version", timeout=2) as response:
            return bool(json.loads(response.read()).get("webSocketDebuggerUrl"))
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-port", type=int, default=DEFAULT_CDP_PORT)
    parser.add_argument("--check-only", action="store_true", help="Validate package and prerequisites without changing the host.")
    parser.add_argument("--skip-logon-task", action="store_true", help="Test-only: do not create the Windows logon task.")
    args = parser.parse_args()
    try:
        if os.name != "nt":
            raise RuntimeError("This installer supports Windows only.")
        if not 1 <= args.cdp_port <= 65535:
            raise RuntimeError("CDP port must be between 1 and 65535.")
        hermes = require_command("hermes.exe", "hermes")
        uv = require_command("uv.exe", "uv")
        chrome = resolve_chrome()
        validate_package()
        verify_plugin_enabled(hermes)
        if args.check_only:
            print(json.dumps({"status": "OK", "mode": "check-only", "plugin_version": PLUGIN_VERSION, "runtime_version": BROWSER_HARNESS_VERSION, "hermes": str(hermes), "uv": str(uv), "chrome": str(chrome)}, ensure_ascii=False, indent=2))
            return 0
        local_app_data = Path(os.environ["LOCALAPPDATA"])
        hermes_home = Path(os.environ.get("HERMES_HOME", local_app_data / "hermes"))
        user_data_dir = hermes_home / PROFILE_DIRECTORY
        user_data_dir.mkdir(parents=True, exist_ok=True)
        extension_path = install_ubol(hermes_home)
        skill_path, registry_path = install_skill(hermes_home, user_data_dir)
        configure_hermes(hermes, chrome, user_data_dir, extension_path, args.cdp_port)
        if not args.skip_logon_task:
            install_logon_task(chrome, user_data_dir, args.cdp_port)
        result = {
            "status": "OK",
            "plugin_version": PLUGIN_VERSION,
            "runtime_version": BROWSER_HARNESS_VERSION,
            "cdp_url": f"http://{CDP_HOST}:{args.cdp_port}",
            "chrome": str(chrome),
            "user_data_dir": str(user_data_dir),
            "extension_path": str(extension_path),
            "skill": str(skill_path),
            "profile_registry": str(registry_path),
            "logon_task": None if args.skip_logon_task else TASK_NAME,
            "cdp_already_ready": cdp_ready(args.cdp_port),
            "next_step": "Restart Hermes Gateway, then perform a real browser_exec page operation.",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
