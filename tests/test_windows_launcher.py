import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@unittest.skipUnless(sys.platform == "win32", "Windows launcher is Windows-only")
class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_uses_project_venv_and_localhost_only(self):
        content = (SCRIPTS_DIR / "start_autosupply.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('.venv\\Scripts\\python.exe', content)
        self.assertIn('"127.0.0.1"', content)
        self.assertIn('http://127.0.0.1:$Port', content)
        self.assertNotIn('"0.0.0.0"', content)
        self.assertIn("Test-OwnedStreamlitProcess", content)
        self.assertIn("Get-NetTCPConnection", content)
        self.assertIn("Get-OwnedListenerProcessId", content)
        self.assertIn(
            "Set-Content -LiteralPath $pidFile -Value $listenerPid", content
        )
        self.assertIn("RedirectStandardError", content)

    def test_stop_script_validates_process_before_stopping(self):
        content = (SCRIPTS_DIR / "stop_autosupply.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('Contains("streamlit")', content)
        self.assertIn('Contains("app.py")', content)
        self.assertIn("Stop-Process -Id $streamlitPid", content)

    def test_shortcut_creator_builds_start_and_stop_shortcuts(self):
        content = (SCRIPTS_DIR / "create_desktop_shortcuts.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("AutoSupply Copilot.lnk", content)
        self.assertIn("Stop AutoSupply Copilot.lnk", content)
        self.assertIn("-WindowStyle Hidden", content)
        self.assertNotIn("schtasks", content.lower())
        self.assertNotIn("startup", content.lower())


if __name__ == "__main__":
    unittest.main()
