import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin_module(name="browser_harness_plugin"):
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeContext:
    def __init__(self):
        self.calls = []

    def register_tool(self, **kwargs):
        self.calls.append(kwargs)


class BrowserHarnessPluginTests(unittest.TestCase):
    def tearDown(self):
        for name in list(sys.modules):
            if name == "browser_harness_plugin" or name.startswith("browser_harness_plugin."):
                sys.modules.pop(name, None)

    def test_registers_browser_exec_as_explicit_override_in_existing_toolset(self):
        plugin = load_plugin_module()
        ctx = FakeContext()

        plugin.register(ctx)

        self.assertEqual(len(ctx.calls), 1)
        call = ctx.calls[0]
        self.assertEqual(call["name"], "browser_exec")
        self.assertEqual(call["toolset"], "browser")
        self.assertIs(call["override"], True)
        self.assertEqual(call["handler"].__module__, plugin.__name__)
        self.assertTrue(call["check_fn"]())
        self.assertIn("Browser Harness", call["schema"]["description"])

    def test_handler_passes_code_name_cdp_and_workspace_to_harness(self):
        plugin = load_plugin_module()
        tool = importlib.import_module("browser_harness_plugin.tool")
        config = {
            "browser": {
                "cdp_url": "http://127.0.0.1:9222",
                "harness": {"name": "agent"},
            }
        }
        captured = {}

        def fake_run(cmd, **kwargs):
            captured.update({"cmd": cmd, **kwargs})
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp, patch.object(tool, "_read_config", return_value=config), patch.object(
            tool, "_find_cli", return_value=["browser-harness"]
        ), patch.object(tool, "_ensure_browser", return_value=None), patch.object(
            tool, "_ensure_extensions", return_value=None
        ), patch.object(tool, "_workspace_dir", return_value=tmp), patch.object(
            tool.subprocess, "run", side_effect=fake_run
        ):
            result = json.loads(
                tool.handle_browser_exec(
                    {"code": 'print("ok")', "timeout_s": 30}, task_id="task-1"
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(captured["cmd"], ["browser-harness"])
        self.assertEqual(captured["input"], 'print("ok")')
        self.assertEqual(captured["env"]["BU_NAME"], "agent")
        self.assertEqual(captured["env"]["BU_CDP_URL"], "http://127.0.0.1:9222")
        self.assertEqual(captured["env"]["BH_AGENT_WORKSPACE"], tmp)

    def test_profile_preferences_are_additive_and_idempotent(self):
        load_plugin_module()
        tool = importlib.import_module("browser_harness_plugin.tool")
        with tempfile.TemporaryDirectory() as tmp:
            user_data_dir = Path(tmp) / "profile"
            default = user_data_dir / "Default"
            default.mkdir(parents=True)
            preferences = default / "Preferences"
            original = {
                "extensions": {"settings": {"keep-me": {"state": 1}}},
                "profile": {"default_content_setting_values": {"popups": 1}},
            }
            preferences.write_text(json.dumps(original), encoding="utf-8")

            self.assertTrue(tool.apply_profile_preferences(user_data_dir, "Default"))
            configured = json.loads(preferences.read_text(encoding="utf-8"))
            self.assertEqual(configured["extensions"], original["extensions"])
            self.assertEqual(
                configured["profile"]["default_content_setting_values"]["popups"], 1
            )
            self.assertEqual(
                configured["profile"]["default_content_setting_values"]["notifications"],
                2,
            )
            self.assertFalse(configured["translate"]["enabled"])
            self.assertFalse(configured["download"]["prompt_for_download"])
            self.assertFalse(tool.apply_profile_preferences(user_data_dir, "Default"))

    def test_missing_cli_returns_install_hint(self):
        load_plugin_module()
        tool = importlib.import_module("browser_harness_plugin.tool")
        with patch.object(tool, "_find_cli", return_value=None):
            result = json.loads(tool.handle_browser_exec({"code": "print(page_info())"}))
        self.assertIn("browser-harness", result["error"])
        self.assertIn("uv tool install browser-harness", result["error"])


if __name__ == "__main__":
    unittest.main()
