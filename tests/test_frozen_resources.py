"""Smoke test the packaged executable with an isolated APPDATA directory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

EXE = (Path(sys.argv[1]) if len(sys.argv) > 1 else
       Path(__file__).resolve().parents[1] / "dist" / "RadioPlusPlus-Qt.exe")


def run_until_extracted(profile, icon, translation):
    environment = os.environ.copy()
    environment["APPDATA"] = str(profile)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.Popen([str(EXE)], env=environment, cwd=str(EXE.parent))
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if icon.exists() and translation.exists():
                if process.poll() is not None:
                    raise AssertionError(f"App exited unexpectedly: {process.returncode}")
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                else:
                    raise AssertionError(f"App exited after extraction: {process.returncode}")
                return
            if process.poll() is not None:
                raise AssertionError(f"App exited unexpectedly: {process.returncode}")
            time.sleep(0.2)
        raise AssertionError("Bundled resources were not extracted")
    finally:
        # PyInstaller onefile runs a parent and child; stop only this launched tree.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError("Test executable could not be closed") from None


def main():
    if not EXE.is_file():
        raise FileNotFoundError(EXE)
    with tempfile.TemporaryDirectory(prefix="radioplus-resources-") as directory:
        profile = Path(directory)
        resources = profile / "RadioPlusPlusQt" / "resources"
        icon = resources / "icons" / "default" / "question.png"
        translation = resources / "languages" / "i18n" / "es.json"
        run_until_extracted(profile, icon, translation)
        assert icon.stat().st_size > 0
        assert json.loads(translation.read_text(encoding="utf-8"))["no_song"] == "Sin canción"
        original = icon.read_bytes()
        icon.write_bytes(b"my custom PNG placeholder")
        missing = resources / "languages" / "i18n" / "fr.json"
        missing.unlink()
        run_until_extracted(profile, icon, missing)
        assert missing.is_file()
        assert icon.read_bytes() == b"my custom PNG placeholder"
        assert original != icon.read_bytes()
        print("Packaged executable extracts resources and preserves user edits.")


if __name__ == "__main__":
    main()
