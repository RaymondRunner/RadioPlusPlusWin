"""Regression check for restarting a PyInstaller onefile executable."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def test_restart_resets_pyinstaller_extraction():
    runner = object.__new__(app.RadioApp)
    runner.quit = lambda: None
    with patch.object(sys, "frozen", True, create=True), patch.object(app.subprocess, "Popen") as launch:
        runner.restart()
    assert launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert launch.call_args.args[0] == [sys.executable]


if __name__ == "__main__":
    test_restart_resets_pyinstaller_extraction()
    print("Frozen restart resets PyInstaller environment.")
