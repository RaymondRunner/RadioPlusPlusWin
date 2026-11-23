"""Manual integration check: yt-dlp must work without optional requests/urllib3."""
import builtins
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

original_import = builtins.__import__


def import_without_requests(name, *args, **kwargs):
    if name.split(".", 1)[0] in {"requests", "urllib3", "curl_cffi"}:
        raise ModuleNotFoundError(f"Excluded optional dependency: {name}")
    return original_import(name, *args, **kwargs)


if __name__ == "__main__":
    builtins.__import__ = import_without_requests
    stream = app.resolve_media("https://www.youtube.com/watch?v=5yx6BWlEVcY")
    assert stream.startswith(("http://", "https://"))
    print("yt-dlp resolved a stream without requests or urllib3.")
