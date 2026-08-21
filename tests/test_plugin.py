import importlib.util
import json
import importlib.machinery
import sys
import tempfile
import unittest
import zipfile
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

    def test_extension_installer_normalizes_payload_for_service_user(self):
        loader = importlib.machinery.SourceFileLoader(
            "extension_installer", str(PLUGIN_DIR / "linux/scripts/install-browser-extensions")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir(mode=0o700)
            manifest = nested / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with patch.object(Path, "chmod") as chmod:
                module.normalize_payload_permissions(root)
            self.assertEqual([call.args[0] for call in chmod.call_args_list], [0o755, 0o755, 0o644])

    def test_extension_installer_excludes_webstore_metadata_from_unpacked_payload(self):
        loader = importlib.machinery.SourceFileLoader(
            "extension_installer_metadata", str(PLUGIN_DIR / "linux/scripts/install-browser-extensions")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "extension.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("manifest.json", "{}")
                archive.writestr("_metadata/verified_contents.json", "{}")
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual([item.filename for item in module.archive_files(archive)], ["manifest.json"])

    def test_registers_existing_browser_exec_in_exclusive_plugin_toolset(self):
        plugin = load_plugin_module()
        ctx = FakeContext()
        plugin.register(ctx)
        self.assertEqual(len(ctx.calls), 1)
        call = ctx.calls[0]
        self.assertEqual(call["name"], "browser_exec")
        self.assertEqual(call["toolset"], "browser_harness")
        self.assertIs(call["override"], True)
        self.assertEqual(call["handler"].__module__, plugin.__name__)
        self.assertEqual(set(call["schema"]["parameters"]["properties"]), {"code", "session", "timeout_s"})

    def test_runtime_is_bundled_and_locked_at_019(self):
        runtime = PLUGIN_DIR / "runtime"
        self.assertTrue((runtime / "src/browser_harness/run.py").is_file())
        self.assertTrue((runtime / "BROWSER_HARNESS_LICENSE").is_file())
        pyproject = (runtime / "pyproject.toml").read_text(encoding="utf-8")
        lock = (runtime / "uv.lock").read_text(encoding="utf-8")
        self.assertIn('version = "0.1.9"', pyproject)
        self.assertIn('name = "browser-harness"', lock)

    def test_unavailable_cdp_fails_before_runtime_start(self):
        load_plugin_module()
        tool = importlib.import_module("browser_harness_plugin.tool")
        with patch.object(tool, "_configured_cdp_url", return_value="http://127.0.0.1:9222"), patch.object(
            tool, "_ensure_browser", return_value="CDP unavailable"
        ), patch.object(tool, "_runtime_command", return_value=["browser-harness"]), patch.object(
            tool.subprocess, "run"
        ) as runtime_run:
            result = json.loads(tool.handle_browser_exec({"code": "print(page_info())"}))
        self.assertEqual(result["error"], "CDP unavailable")
        runtime_run.assert_not_called()

    def test_handler_uses_bundled_frozen_runtime_and_existing_cdp(self):
        load_plugin_module()
        tool = importlib.import_module("browser_harness_plugin.tool")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured.update({"cmd": cmd, **kwargs})
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")

        command = ["uv", "run", "--frozen", "--project", str(tool._RUNTIME_DIR), "browser-harness"]
        config = {"browser": {"cdp_url": "http://127.0.0.1:9222", "harness": {"name": "agent"}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(tool, "_read_config", return_value=config), patch.object(
            tool, "_cdp_ready", return_value=None
        ), patch.object(tool, "_runtime_command", return_value=command), patch.object(
            tool, "_workspace_dir", return_value=tmp
        ), patch.object(tool.subprocess, "run", side_effect=fake_run):
            result = json.loads(tool.handle_browser_exec({"code": 'print("ok")', "timeout_s": 30}, task_id="task-1"))

        self.assertTrue(result["success"])
        self.assertEqual(captured["cmd"], command)
        self.assertEqual(captured["input"], 'print("ok")')
        self.assertEqual(captured["env"]["BU_CDP_URL"], "http://127.0.0.1:9222")
        self.assertEqual(captured["env"]["BU_NAME"], tool._runtime_name("agent", "http://127.0.0.1:9222"))
        self.assertEqual(captured["env"]["BH_AGENT_WORKSPACE"], tmp)
        self.assertEqual(captured["cwd"], str(tool._RUNTIME_DIR))

    def test_non_loopback_cdp_is_rejected(self):
        load_plugin_module()
        tool = importlib.import_module("browser_harness_plugin.tool")
        self.assertIn("loopback", tool._validate_loopback_cdp("http://10.0.0.8:9222"))
        self.assertIsNone(tool._validate_loopback_cdp("http://localhost:9222"))


if __name__ == "__main__":
    unittest.main()
