from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARE = ROOT / "linux" / "scripts" / "temporary-share"
sys.path.insert(0, str(SHARE))

from core import ShareKind, hash_token  # noqa: E402
from store import ShareStore  # noqa: E402


def load_install_state():
    path = ROOT / "linux" / "scripts" / "browser-install-state"
    loader = SourceFileLoader("browser_install_state", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("cannot load browser-install-state")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ShareStoreConcurrencyTests(unittest.TestCase):
    def test_otp_is_consumed_exactly_once_under_concurrency(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ShareStore(Path(directory) / "shares.sqlite", b"test-pepper")
            record, _token = store.create(ShareKind.REMOTE_ACCESS, 60)
            otp_hash = hash_token("ABC234", b"test-pepper")
            store.set_otp(record.share_id, otp_hash)
            with ThreadPoolExecutor(max_workers=12) as pool:
                outcomes = list(pool.map(lambda _index: store.verify_otp(record.share_id, otp_hash), range(12)))
            self.assertEqual(outcomes.count(True), 1)
            store.close()

    def test_expiry_returns_owned_target_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ShareStore(Path(directory) / "shares.sqlite", b"test-pepper")
            record, _token = store.create(
                ShareKind.REMOTE_ACCESS,
                1800,
                {"target": "local-browser", "browser_target_id": "owned-tab"},
            )
            expired = store.expire_due(datetime.now(timezone.utc) + timedelta(hours=1))
            self.assertEqual(expired, [(record.share_id, {
                "target": "local-browser",
                "browser_target_id": "owned-tab",
            })])
            store.close()


class InstallStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = load_install_state()

    def test_nested_restore_helpers_preserve_siblings(self):
        data = {"browser": {"harness": {"executable": "old", "other": 1}}}
        self.state.set_nested(data, "browser.harness.executable", "new")
        self.assertEqual(data["browser"]["harness"]["other"], 1)
        self.state.delete_nested(data, "browser.harness.executable")
        self.assertEqual(data, {"browser": {"harness": {"other": 1}}})

    def test_packaged_defaults_do_not_embed_private_auth_endpoint(self):
        env_example = (ROOT / "linux" / "config" / "share.env.example").read_text(encoding="utf-8")
        self.assertIn("SHARE_AUTH_BASE_URL=\n", env_example)
        self.assertIn("BROWSER_SHARE_BIND=127.0.0.1", env_example)
        self.assertIn("SHARE_MAX_TTL_SECONDS=1800", env_example)
        self.assertNotIn("auth.procvetaev.space", env_example)

    def test_host_installer_requires_enabled_plugin_before_mutation(self):
        installer = (ROOT / "install-linux.sh").read_text(encoding="utf-8")
        preflight = installer.index("hermes plugins list --plain --no-bundled")
        first_mutation = installer.index("apt-get update -qq")
        self.assertLess(preflight, first_mutation)
        self.assertIn('run: hermes plugins enable browser-harness --allow-tool-override', installer)

    def test_host_installer_refuses_multi_instance_chrome_before_mutation(self):
        installer = (ROOT / "install-linux.sh").read_text(encoding="utf-8")
        preflight = installer.index("refusing multi-instance Chrome migration")
        first_mutation = installer.index("apt-get update -qq")
        self.assertLess(preflight, first_mutation)
        self.assertIn("procvetaev-browser.target.wants", installer)
        self.assertIn("--user-data-dir=", installer)
        self.assertIn("--remote-debugging-port=", installer)

    def test_remote_access_requires_target_and_owns_one_tab(self):
        broker = (SHARE / "broker.py").read_text(encoding="utf-8")
        skill = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('validate_target_url(payload.get("target_url"))', broker)
        self.assertIn('"browser_target_id": browser_target_id', broker)
        self.assertIn("close_owned_target(metadata)", broker)
        self.assertIn('"target_url":"https://target.example/","ttl_seconds":1800', skill)

    def test_caddy_defaults_to_loopback(self):
        caddy = (ROOT / "linux" / "caddy" / "procvetaev-browser-share.Caddyfile").read_text(encoding="utf-8")
        self.assertIn("https://vps-broker.local:{$BROWSER_SHARE_PORT:8791}", caddy)
        self.assertIn("bind {$BROWSER_SHARE_BIND:127.0.0.1}", caddy)

    def test_broker_waits_for_listener_socket_before_auth_registration(self):
        broker = (SHARE / "broker.py").read_text(encoding="utf-8")
        self.assertIn('socket.create_connection(("127.0.0.1"', broker)
        self.assertIn("browser share listener did not become ready", broker)

    def test_capture_restore_roundtrip_preserves_preinstall_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config_path = home / "config.yaml"
            before = {
                "browser": {
                    "backend": "legacy",
                    "cloud_provider": "remote",
                    "cdp_url": "http://127.0.0.1:9333",
                    "harness": {"executable": "/old/chrome", "unrelated": "keep"},
                }
            }
            config_path.write_text(yaml.safe_dump(before, sort_keys=False), encoding="utf-8")
            state_file = home / "install-state.json"
            with patch.dict(os.environ, {"HERMES_HOME": str(home)}), patch.object(
                self.state, "tool_status", return_value=dict(self.state.TOOLSETS)
            ):
                self.state.capture(state_file, "/new/profile")
                installed = self.state.installed_config("/new/profile")
                changed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                for key, expected in installed.items():
                    if expected["present"]:
                        self.state.set_nested(changed, key, expected["value"])
                    else:
                        self.state.delete_nested(changed, key)
                config_path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
                self.state.restore(state_file)
            restored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(restored, before)

    def test_restore_reverts_only_package_owned_toolset_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.yaml").write_text("{}\n", encoding="utf-8")
            state_file = home / "install-state.json"
            state_file.write_text(json.dumps({
                "version": 1,
                "previous_config": {},
                "installed_config": {},
                "previous_toolsets": {"cli": {
                    "browser_harness": False,
                    "browser": True,
                    "computer_use": True,
                }},
                "installed_toolsets": {"cli": dict(self.state.TOOLSETS)},
            }), encoding="utf-8")
            with patch.dict(os.environ, {"HERMES_HOME": str(home)}), patch.object(
                self.state, "tool_status", return_value=dict(self.state.TOOLSETS)
            ), patch.object(self.state.subprocess, "run") as run:
                self.state.restore(state_file)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands, [
                ["hermes", "tools", "disable", "browser_harness", "--platform", "cli"],
                ["hermes", "tools", "enable", "browser", "--platform", "cli"],
                ["hermes", "tools", "enable", "computer_use", "--platform", "cli"],
            ])


if __name__ == "__main__":
    unittest.main()
