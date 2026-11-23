"""Resource extraction preserves user edits and loads icons/translations from AppData."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def test_appdata_resources():
    with tempfile.TemporaryDirectory() as temporary:
        config = Path(temporary) / "RadioPlusPlusQt" / "settings.json"
        with patch.object(app, "CONFIG", config):
            app.extract_resources()
            resources = config.parent / "resources"
            icon = resources / "icons" / "default" / "play.png"
            language = resources / "languages" / "i18n" / "es.json"
            assert icon.is_file() and language.is_file()
            icon.write_bytes(b"custom icon")
            translations = json.loads(language.read_text(encoding="utf-8"))
            translations["mine"] = "Mis radios personalizadas"
            translations.pop("no_song")
            language.write_text(json.dumps(translations), encoding="utf-8")
            app.extract_resources()
            assert app.pack_path("default", "play.png") == icon
            assert icon.read_bytes() == b"custom icon"
            loaded = app.RadioApp.load_translations("es")
            assert loaded["mine"] == "Mis radios personalizadas"
            assert loaded["no_song"] == "Sin canción"


if __name__ == "__main__":
    test_appdata_resources()
    print("AppData resources and translation fallback OK")
