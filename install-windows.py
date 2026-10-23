#!/usr/bin/env python3
"""Install the Windows host contract for PROCVETAEV Browser Harness 1.4.17.

Run this script from an already installed and enabled browser-harness plugin
checkout. It configures one managed Chrome profile on loopback CDP, installs
the policy skill, and creates an interactive
logon task. The Browser Harness Python runtime remains bundled with the plugin.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import html
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

PLUGIN_VERSION = "1.4.17"
BROWSER_HARNESS_VERSION = "0.1.9"
CDP_HOST = "127.0.0.1"
DEFAULT_CDP_PORT = 9222
HARNESS_NAME = "agent"
PROFILE_DIRECTORY = "Hermes Automation"
TASK_NAME = r"\PROCVETAEV\Browser Harness Chrome"
TASK_FOLDER = r"\PROCVETAEV"
LEGACY_TASK_NAMES = (r"\Hermes_Agent_Chrome",)
ROOT = Path(__file__).resolve().parent
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


def validate_package() -> None:
    manifest = ROOT / "plugin.yaml"
    runtime_project = ROOT / "runtime" / "pyproject.toml"
    runtime_lock = ROOT / "runtime" / "uv.lock"
    for required in (manifest, runtime_project, runtime_lock, WINDOWS_SKILL):
        if not required.is_file():
            raise RuntimeError(f"Package is incomplete: {required}")
    manifest_text = manifest.read_text(encoding="utf-8")
    if not re.search(rf"(?m)^version:\s*{re.escape(PLUGIN_VERSION)}\s*$", manifest_text):
        raise RuntimeError(f"plugin.yaml is not version {PLUGIN_VERSION}.")
    runtime_text = runtime_project.read_text(encoding="utf-8")
    if not re.search(rf'(?m)^version\s*=\s*"{re.escape(BROWSER_HARNESS_VERSION)}"\s*$', runtime_text):
        raise RuntimeError(f"Bundled Browser Harness runtime is not {BROWSER_HARNESS_VERSION}.")


def normalize_windows_acl(path: Path) -> bool:
    """Restore inherited user access after an elevated/SSH installation."""
    icacls = require_command("icacls.exe", "icacls")
    for item in (path, *path.rglob("*")):
        item.chmod(item.stat().st_mode | stat.S_IWRITE)
    run([icacls, path, "/inheritance:e", "/T", "/C", "/Q"])
    user = current_windows_user()
    run([icacls, path, "/grant:r", f"{user}:(OI)(CI)M", "/T", "/C", "/Q"])
    run([icacls, path, "/verify", "/T", "/C", "/Q"])
    powershell = require_command("powershell.exe", "powershell")
    escaped = str(path).replace("'", "''")
    protected = run([
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        f"[bool](Get-Acl -LiteralPath '{escaped}').AreAccessRulesProtected",
    ]).stdout.strip().casefold()
    if protected != "false":
        raise RuntimeError(f"ACL inheritance remains protected: {path}")
    acl_readback = run([
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            "$ErrorActionPreference='Stop';"
            "$identity=[Security.Principal.WindowsIdentity]::GetCurrent();"
            "$sids=@($identity.User.Value)+@($identity.Groups|ForEach-Object{$_.Value});"
            f"$items=@(Get-Item -LiteralPath '{escaped}')+"
            f"@(Get-ChildItem -LiteralPath '{escaped}' -Force -Recurse);"
            "$protected=@($items|Where-Object{(Get-Acl -LiteralPath $_.FullName).AreAccessRulesProtected}).Count;"
            "$denied=0;foreach($item in $items){foreach($rule in (Get-Acl -LiteralPath $item.FullName).Access){"
            "if($rule.AccessControlType -eq 'Deny'){try{$sid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}catch{continue};"
            "if($sids -contains $sid){$rights=[int64]$rule.FileSystemRights;"
            "$mask=[int64]([Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Read -bor [Security.AccessControl.FileSystemRights]::ReadData);"
            "if(($rights -band $mask)-ne 0){$denied++}}}}};"
            "[pscustomobject]@{protected=$protected;denied=$denied}|ConvertTo-Json -Compress"
        ),
    ]).stdout.strip()
    try:
        acl_status = json.loads(acl_readback)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ACL read-back returned invalid JSON: {path}") from exc
    if acl_status != {"protected": 0, "denied": 0}:
        raise RuntimeError(f"ACL effective read contract failed below: {path}: {acl_status}")
    return True


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
    if registry_path.exists():
        existing = validate_registry(json.loads(registry_path.read_text(encoding="utf-8")))
        if HARNESS_NAME in existing["profiles"]:
            existing["profiles"][HARNESS_NAME]["user_data_dir"] = str(user_data_dir)
        else:
            existing["profiles"][HARNESS_NAME] = {
                "label": "Основной профиль",
                "description": "Основной профиль Browser Harness",
                "user_data_dir": str(user_data_dir),
            }
        registry_payload = existing
    else:
        registry_payload = {
            "default": HARNESS_NAME,
            "profiles": {
                HARNESS_NAME: {
                    "label": "Основной профиль",
                    "description": "Основной профиль Browser Harness",
                    "user_data_dir": str(user_data_dir),
                }
            },
        }
    validate_registry(registry_payload)
    shutil.copy2(WINDOWS_SKILL, skill_path)
    write_json_atomic(registry_path, registry_payload)
    validate_registry(json.loads(registry_path.read_text(encoding="utf-8")))
    (target / OWNER_MARKER).write_text(f"browser-harness-windows {PLUGIN_VERSION}\n", encoding="utf-8")
    return skill_path, registry_path


_MISSING = object()


def config_get(hermes: Path, key: str, *, missing_ok: bool = False) -> object:
    completed = run([hermes, "config", "get", "--json", key], check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        if missing_ok and "not set" in detail.casefold():
            return _MISSING
        raise RuntimeError(f"Hermes config read-back failed: {key}\n{detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Hermes config returned invalid JSON: {key}") from exc


def write_browser_config(hermes_home: Path, values: dict[str, object]) -> None:
    import yaml

    config_path = hermes_home / "config.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RuntimeError("Hermes config root must be a mapping.")
    browser = payload.setdefault("browser", {})
    if not isinstance(browser, dict):
        raise RuntimeError("Hermes browser config must be a mapping.")
    browser.pop("backend", None)
    browser["cloud_provider"] = values["browser.cloud_provider"]
    browser["cdp_url"] = values["browser.cdp_url"]
    harness = browser.setdefault("harness", {})
    if not isinstance(harness, dict):
        raise RuntimeError("Hermes browser.harness config must be a mapping.")
    for key, value in values.items():
        if key.startswith("browser.harness."):
            harness[key.removeprefix("browser.harness.")] = value
    temporary = config_path.with_name(f".{config_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        checked = yaml.safe_load(temporary.read_text(encoding="utf-8"))
        if not isinstance(checked, dict):
            raise RuntimeError("Generated Hermes config is invalid.")
        os.replace(temporary, config_path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_legacy_user_environment() -> list[str]:
    import winreg

    removed = []
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        for name in ("BU_NAME", "BU_CDP_URL"):
            try:
                winreg.DeleteValue(key, name)
                removed.append(name)
            except FileNotFoundError:
                pass
            os.environ.pop(name, None)
    return removed


def remove_legacy_uv_runtime(uv: Path) -> bool:
    listing = run([uv, "tool", "list"]).stdout.splitlines()
    installed = any(re.fullmatch(r"browser-harness\s+v?0\.1\.9", line.strip()) for line in listing)
    if not installed:
        return False
    run([uv, "tool", "uninstall", "browser-harness"])
    remaining = run([uv, "tool", "list"]).stdout
    if re.search(r"(?m)^browser-harness\s+v?", remaining):
        raise RuntimeError("Legacy Browser Harness uv tool remains installed.")
    return True


def configure_hermes(
    hermes: Path,
    hermes_home: Path,
    chrome: Path,
    user_data_dir: Path,
    profile_directory: str,
    cdp_port: int,
) -> None:
    cdp_url = f"http://{CDP_HOST}:{cdp_port}"
    values = {
        "browser.cloud_provider": "local",
        "browser.cdp_url": cdp_url,
        "browser.harness.name": HARNESS_NAME,
        "browser.harness.executable": str(chrome),
        "browser.harness.user_data_dir": str(user_data_dir),
        "browser.harness.profile_directory": profile_directory,
    }
    write_browser_config(hermes_home, values)
    for key, value in values.items():
        if config_get(hermes, key) != value:
            raise RuntimeError(f"Hermes config read-back failed: {key}")
    backend = config_get(hermes, "browser.backend", missing_ok=True)
    if backend is not _MISSING and backend != "":
        raise RuntimeError("Hermes resolved browser.backend is not absent or empty.")
    for platform in ("cli", "telegram"):
        run([hermes, "tools", "enable", "browser", "--platform", platform])
        run([hermes, "tools", "disable", "computer_use", "--platform", platform])
        listing = " ".join(run([hermes, "tools", "list", "--platform", platform]).stdout.casefold().split())
        for expected in ("enabled browser", "disabled computer_use"):
            if expected not in listing:
                raise RuntimeError(f"Hermes toolset read-back failed on {platform}: missing {expected!r}")


def resolve_profile_directory(user_data_dir: Path) -> str:
    local_state = user_data_dir / "Local State"
    if local_state.is_file():
        try:
            payload = json.loads(local_state.read_text(encoding="utf-8"))
            last_used = payload.get("profile", {}).get("last_used")
            if (
                isinstance(last_used, str)
                and re.fullmatch(r"Default|Profile [0-9]+", last_used)
                and (user_data_dir / last_used).is_dir()
            ):
                return last_used
            raise RuntimeError("Chrome Local State names a missing or unsupported active subprofile.")
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Chrome Local State cannot be read safely; refusing to guess the active subprofile.") from exc
    existing = [
        path.name
        for path in user_data_dir.iterdir()
        if path.is_dir()
        and re.fullmatch(r"Default|Profile [0-9]+", path.name)
        and (path / "Preferences").is_file()
    ] if user_data_dir.is_dir() else []
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1:
        raise RuntimeError("Multiple Chrome subprofiles exist and Local State does not select one.")
    return "Default"


def chrome_arguments(user_data_dir: Path, profile_directory: str, cdp_port: int) -> str:
    args = [
        f'--remote-debugging-address={CDP_HOST}',
        f'--remote-debugging-port={cdp_port}',
        f'--user-data-dir="{user_data_dir}"',
        f'--profile-directory="{profile_directory}"',
        '--disable-background-mode',
        '--no-first-run',
        '--no-default-browser-check',
        '--start-minimized',
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


def ensure_task_folder() -> None:
    powershell = require_command("powershell.exe", "powershell")
    script = (
        "$s=New-Object -ComObject 'Schedule.Service';$s.Connect();"
        "$root=$s.GetFolder('\\');"
        "try{$null=$s.GetFolder('\\PROCVETAEV')}catch{$null=$root.CreateFolder('PROCVETAEV')}"
    )
    run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script])


def task_xml_or_missing(schtasks: Path, task_name: str) -> str | None:
    query = run([schtasks, "/Query", "/TN", task_name, "/XML"], check=False)
    if not query.returncode:
        return query.stdout
    listing = run([schtasks, "/Query", "/FO", "CSV", "/NH"]).stdout
    known = {row[0].casefold() for row in csv.reader(io.StringIO(listing)) if row}
    if task_name.casefold() not in known:
        return None
    raise RuntimeError(f"Scheduled Task exists but its XML cannot be read: {task_name}")


def task_contract(xml: str) -> dict[str, object]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise RuntimeError("Scheduled Task returned malformed XML.") from exc
    execs = root.findall(".//{*}Actions/{*}Exec")
    principals = root.findall(".//{*}Principals/{*}Principal")
    return {
        "description": root.findtext(".//{*}RegistrationInfo/{*}Description") or "",
        "exec_count": len(execs),
        "command": execs[0].findtext("./{*}Command") or "" if len(execs) == 1 else "",
        "arguments": execs[0].findtext("./{*}Arguments") or "" if len(execs) == 1 else "",
        "working_directory": execs[0].findtext("./{*}WorkingDirectory") or "" if len(execs) == 1 else "",
        "principal_count": len(principals),
        "logon_type": principals[0].findtext("./{*}LogonType") or "" if len(principals) == 1 else "",
        "run_level": principals[0].findtext("./{*}RunLevel") or "" if len(principals) == 1 else "",
    }


def argument_value(arguments: str, name: str) -> str | None:
    match = re.search(rf'(?:^|\s)--{re.escape(name)}=(?:"([^"]*)"|(\S+))', arguments)
    return (match.group(1) if match and match.group(1) is not None else match.group(2)) if match else None


def validate_legacy_logon_tasks(
    chrome: Path,
    user_data_dir: Path,
    profile_directory: str,
    cdp_port: int,
) -> list[str]:
    schtasks = require_command("schtasks.exe", "schtasks")
    owned = []
    for task_name in LEGACY_TASK_NAMES:
        xml = task_xml_or_missing(schtasks, task_name)
        if xml is None:
            continue
        contract = task_contract(xml)
        expected_arguments = (
            f'--remote-debugging-port={cdp_port} '
            f'--user-data-dir="{user_data_dir}" '
            f'--profile-directory="{profile_directory}" '
            '--no-first-run --no-default-browser-check --new-window "about:blank"'
        )
        if (
            contract["exec_count"] != 1
            or contract["principal_count"] != 1
            or Path(str(contract["command"])).resolve() != chrome.resolve()
            or contract["arguments"] != expected_arguments
            or contract["logon_type"] != "InteractiveToken"
        ):
            raise RuntimeError(f"Refusing to remove unrecognized legacy task: {task_name}")
        owned.append(task_name)
    return owned


def remove_legacy_logon_tasks(task_names: list[str]) -> list[str]:
    schtasks = require_command("schtasks.exe", "schtasks")
    removed = []
    for task_name in task_names:
        run([schtasks, "/Delete", "/TN", task_name, "/F"])
        if task_xml_or_missing(schtasks, task_name) is not None:
            raise RuntimeError(f"Legacy Scheduled Task remains installed: {task_name}")
        removed.append(task_name)
    return removed


def validate_existing_logon_task(
    chrome: Path,
    user_data_dir: Path,
    profile_directory: str,
    cdp_port: int,
    *,
    allow_previous: bool = False,
) -> None:
    schtasks = require_command("schtasks.exe", "schtasks")
    existing = task_xml_or_missing(schtasks, TASK_NAME)
    if existing is not None:
        contract = task_contract(existing)
        expected_arguments = chrome_arguments(user_data_dir, profile_directory, cdp_port)
        previous_arguments = expected_arguments.replace(" --start-minimized", "")
        allowed_arguments = (expected_arguments, previous_arguments) if allow_previous else (expected_arguments,)
        if (
            contract["description"] != "PROCVETAEV Browser Harness managed Chrome"
            or contract["exec_count"] != 1
            or contract["principal_count"] != 1
            or Path(str(contract["command"])).resolve() != chrome.resolve()
            or contract["arguments"] not in allowed_arguments
            or Path(str(contract["working_directory"])).resolve() != chrome.parent.resolve()
            or contract["logon_type"] != "InteractiveToken"
            or contract["run_level"] not in ("", "LeastPrivilege")
        ):
            raise RuntimeError(f"Refusing to overwrite unrecognized Scheduled Task: {TASK_NAME}")


def install_logon_task(chrome: Path, user_data_dir: Path, profile_directory: str, cdp_port: int) -> None:
    schtasks = require_command("schtasks.exe", "schtasks")
    ensure_task_folder()
    validate_existing_logon_task(
        chrome,
        user_data_dir,
        profile_directory,
        cdp_port,
        allow_previous=True,
    )
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
  <Actions Context="Author"><Exec><Command>{html.escape(str(chrome))}</Command><Arguments>{html.escape(chrome_arguments(user_data_dir, profile_directory, cdp_port))}</Arguments><WorkingDirectory>{html.escape(str(chrome.parent))}</WorkingDirectory></Exec></Actions>
</Task>
'''
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-16", delete=False) as handle:
        handle.write(xml)
        temporary = Path(handle.name)
    try:
        run([schtasks, "/Create", "/TN", TASK_NAME, "/XML", temporary, "/F"])
        validate_existing_logon_task(chrome, user_data_dir, profile_directory, cdp_port)
    finally:
        temporary.unlink(missing_ok=True)


def cdp_ready(cdp_port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{CDP_HOST}:{cdp_port}/json/version", timeout=2) as response:
            return bool(json.loads(response.read()).get("webSocketDebuggerUrl"))
    except Exception:
        return False


def validate_readable_tree(path: Path) -> None:
    if not path.exists():
        return
    for item in path.rglob("*"):
        if item.is_file():
            with item.open("rb") as handle:
                handle.read(1)


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
        local_app_data = Path(os.environ["LOCALAPPDATA"])
        hermes_home = Path(os.environ.get("HERMES_HOME", local_app_data / "hermes"))
        user_data_dir = hermes_home / PROFILE_DIRECTORY
        profile_directory = resolve_profile_directory(user_data_dir)
        legacy_tasks = validate_legacy_logon_tasks(chrome, user_data_dir, profile_directory, args.cdp_port) if not args.skip_logon_task else []
        if not args.skip_logon_task:
            validate_existing_logon_task(
                chrome,
                user_data_dir,
                profile_directory,
                args.cdp_port,
                allow_previous=True,
            )
        import yaml
        if (hermes_home / "config.yaml").is_file() and not isinstance(
            yaml.safe_load((hermes_home / "config.yaml").read_text(encoding="utf-8")) or {}, dict
        ):
            raise RuntimeError("Hermes config root must be a mapping.")
        registry_path = hermes_home / "skills" / "browser-harness" / "browser-profiles.json"
        if registry_path.is_file():
            validate_registry(json.loads(registry_path.read_text(encoding="utf-8")))
        validate_readable_tree(ROOT)
        validate_readable_tree(hermes_home / "skills" / "browser-harness")
        run([uv, "tool", "list"])
        for parent in (hermes_home, hermes_home / "skills"):
            existing_parent = next((candidate for candidate in (parent, *parent.parents) if candidate.exists()), None)
            if existing_parent is None or not os.access(existing_parent, os.W_OK):
                raise RuntimeError(f"Installer cannot write below: {parent}")
        if args.check_only:
            print(json.dumps({"status": "OK", "mode": "check-only", "plugin_version": PLUGIN_VERSION, "runtime_version": BROWSER_HARNESS_VERSION, "hermes": str(hermes), "uv": str(uv), "chrome": str(chrome), "user_data_dir": str(user_data_dir), "profile_directory": profile_directory, "legacy_tasks": legacy_tasks}, ensure_ascii=False, indent=2))
            return 0
        plugin_acl_normalized = normalize_windows_acl(ROOT)
        (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        skill_path, registry_path = install_skill(hermes_home, user_data_dir)
        skill_acl_normalized = normalize_windows_acl(skill_path.parent)
        configure_hermes(hermes, hermes_home, chrome, user_data_dir, profile_directory, args.cdp_port)
        if not args.skip_logon_task:
            install_logon_task(chrome, user_data_dir, profile_directory, args.cdp_port)
            removed_legacy_tasks = remove_legacy_logon_tasks(legacy_tasks)
        else:
            removed_legacy_tasks = []
        removed_environment = remove_legacy_user_environment()
        legacy_uv_runtime_removed = remove_legacy_uv_runtime(uv)
        result = {
            "status": "OK",
            "plugin_version": PLUGIN_VERSION,
            "runtime_version": BROWSER_HARNESS_VERSION,
            "plugin_acl_normalized": plugin_acl_normalized,
            "skill_acl_normalized": skill_acl_normalized,
            "cdp_url": f"http://{CDP_HOST}:{args.cdp_port}",
            "chrome": str(chrome),
            "user_data_dir": str(user_data_dir),
            "profile_directory": profile_directory,
            "skill": str(skill_path),
            "profile_registry": str(registry_path),
            "logon_task": None if args.skip_logon_task else TASK_NAME,
            "legacy_logon_tasks_removed": removed_legacy_tasks,
            "legacy_environment_removed": removed_environment,
            "legacy_uv_runtime_removed": legacy_uv_runtime_removed,
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
