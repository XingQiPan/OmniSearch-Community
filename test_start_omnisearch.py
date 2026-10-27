"""Bounded launcher tests: no real services are started or stopped."""

import importlib.util
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("launcher", ROOT / "start_omnisearch.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_bat_is_ascii_crlf(self):
        content = (ROOT / "start-omnisearch.bat").read_bytes()
        content.decode("ascii")
        self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
        self.assertIn(b'"%~dp0start_omnisearch.py"', content)
        self.assertIn(b"exit /b %errorlevel%", content)

    def test_foreign_backend_rejected(self):
        with patch.object(launcher, "read_json", return_value={"info": {"title": "Other API"}, "paths": {}}):
            with self.assertRaisesRegex(launcher.LaunchError, "different application"):
                launcher.verify_backend()

    def test_correct_schema_but_dashboard_not_ready(self):
        schema = {"info": {"title": launcher.API_TITLE, "version": launcher.API_VERSION}, "paths": dict.fromkeys(launcher.API_PATHS)}
        with patch.object(launcher, "read_json", side_effect=[schema, {}]):
            with self.assertRaisesRegex(launcher.LaunchError, "not ready"):
                launcher.verify_backend()

    def test_foreign_frontend_rejected(self):
        with patch.object(launcher, "request", return_value="<title>Other app</title>"):
            with self.assertRaisesRegex(launcher.LaunchError, "different application"):
                launcher.verify_frontend(ROOT)

    def test_vite_hmr_timestamp_is_accepted(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8").replace('/src/main.tsx"', '/src/main.tsx?t=123"') + '<script src="/@vite/client"></script>'
        with patch.object(launcher, "request", side_effect=[html, 'import "/src/App.tsx"', 'SearchWorkspace RoutingStudio AuditAndGatewayPage']):
            launcher.verify_frontend(ROOT)

    def test_any_port_conflict_prevents_all_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher, "check_dependencies", return_value=("node", Path("vite.js"))), \
                    patch.object(launcher, "runtime_dir", return_value=Path(directory)), \
                    patch.object(launcher, "port_available", side_effect=[True, False]), \
                    patch.object(launcher, "verify_frontend", side_effect=launcher.LaunchError("foreign server")), \
                    patch.object(launcher, "start_service") as start:
                with self.assertRaisesRegex(launcher.LaunchError, "No process was stopped"):
                    launcher.launch(ROOT, no_browser=True)
                start.assert_not_called()

    def test_check_missing_service_does_not_start_or_open_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher, "check_dependencies", return_value=("node", Path("vite.js"))), \
                    patch.object(launcher, "runtime_dir", return_value=Path(directory)), \
                    patch.object(launcher, "service_states", return_value={"backend": "stopped", "frontend": "ready"}), \
                    patch.object(launcher, "start_service") as start, \
                    patch.object(launcher.webbrowser, "open") as browser:
                with self.assertRaisesRegex(launcher.LaunchError, "Nothing was started"):
                    launcher.launch(ROOT, check=True)
                start.assert_not_called()
                browser.assert_not_called()

    def test_ready_services_reused_without_new_process(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher, "check_dependencies", return_value=("node", Path("vite.js"))), \
                    patch.object(launcher, "runtime_dir", return_value=Path(directory)), \
                    patch.object(launcher, "service_states", return_value={"backend": "ready", "frontend": "ready"}), \
                    patch.object(launcher, "verify_backend"), patch.object(launcher, "verify_frontend"), \
                    patch.object(launcher, "dashboard_ready"), patch.object(launcher, "start_service") as start, \
                    patch.object(launcher.webbrowser, "open") as browser:
                self.assertEqual(launcher.launch(ROOT, no_browser=True), 0)
                start.assert_not_called()
                browser.assert_not_called()

    def test_missing_python_dependency_is_explicit(self):
        with patch.object(launcher.importlib.metadata, "version", side_effect=launcher.importlib.metadata.PackageNotFoundError("fastapi")):
            with self.assertRaisesRegex(launcher.LaunchError, "Missing Python dependency"):
                launcher.check_dependencies(ROOT)

    def test_child_exit_is_failure_not_success(self):
        child = Mock()
        child.poll.return_value = 1
        verify = Mock()
        with self.assertRaisesRegex(launcher.LaunchError, "exit 1"):
            launcher.wait_ready("backend", verify, child, Path("test.log"), 1)
        verify.assert_not_called()
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_readiness_timeout_is_failure(self):
        child = Mock()
        child.poll.return_value = None
        with patch.object(launcher.time, "monotonic", side_effect=[0, 0, 2]), \
                patch.object(launcher.time, "sleep"):
            with self.assertRaisesRegex(launcher.LaunchError, "not ready"):
                launcher.wait_ready("frontend", Mock(side_effect=launcher.LaunchError("not ready")), child, Path("test.log"), 1)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_frontend_launch_uses_node_and_strict_port(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Mock()
            with patch.object(launcher, "check_dependencies", return_value=("node", Path(directory) / "vite.js")), \
                    patch.object(launcher, "runtime_dir", return_value=Path(directory)), \
                    patch.object(launcher, "service_states", return_value={"backend": "ready", "frontend": "stopped"}), \
                    patch.object(launcher, "verify_backend"), patch.object(launcher, "verify_frontend"), \
                    patch.object(launcher, "dashboard_ready"), patch.object(launcher, "wait_ready"), \
                    patch.object(launcher, "start_service", return_value=(child, Path("test.log"))) as start:
                launcher.launch(ROOT, no_browser=True)
                command = start.call_args.args[1]
                self.assertEqual(command[0], "node")
                self.assertIn("--strictPort", command)
                self.assertIn("5173", command)

    def test_concurrent_launcher_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with launcher.launch_lock(Path(directory)):
                with self.assertRaisesRegex(launcher.LaunchError, "Another launcher"):
                    with launcher.launch_lock(Path(directory)):
                        self.fail("Concurrent lock acquired")

    @unittest.skipUnless(os.name == "nt", "Windows batch wrapper")
    def test_bat_from_chinese_space_directory_and_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="OmniSearch 中文 space ") as directory:
            wrapper = Path(directory) / "start-omnisearch.bat"
            shutil.copyfile(ROOT / "start-omnisearch.bat", wrapper)
            shutil.copyfile(ROOT / "start_omnisearch.py", Path(directory) / "start_omnisearch.py")
            # Explicit trusted subprocess cmd invocation: never through shell_exec.
            for argument, expected in (("--help", 0), ("--unknown-launcher-option", 2)):
                command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{wrapper}" {argument}"'
                result = subprocess.run(command,
                                        cwd=directory, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
