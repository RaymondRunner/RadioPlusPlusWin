"""Check individual sharing and full-list backups without touching user settings."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import (BACKUP_FILE_FORMAT, STATION_FILE_FORMAT, read_station_file,
                 station_filename, valid_station, write_station_file)


def test_station_files():
    assert station_filename("Mi Radio") == "Mi Radio.json"
    assert station_filename("Rock / Pop: Live?") == "Rock _ Pop_ Live_.json"
    assert station_filename("CON") == "_CON.json"
    with tempfile.TemporaryDirectory() as folder:
        individual = Path(folder) / "one.json"
        backup = Path(folder) / "backup.json"
        station = valid_station({"Name": " Example ", "Url": "https://example.org/live",
                                 "UseYtDlp": True})
        write_station_file(individual, STATION_FILE_FORMAT, station)
        assert read_station_file(individual, STATION_FILE_FORMAT) == station
        assert "stations" not in json.loads(individual.read_text(encoding="utf-8"))
        write_station_file(backup, BACKUP_FILE_FORMAT, [station])
        assert read_station_file(backup, BACKUP_FILE_FORMAT) == [station]
        for path, format_name in ((individual, BACKUP_FILE_FORMAT),
                                  (backup, STATION_FILE_FORMAT)):
            try:
                read_station_file(path, format_name)
            except ValueError:
                pass
            else:
                raise AssertionError("Accepted a file of the wrong format")
        backup.write_text(json.dumps({"format": BACKUP_FILE_FORMAT,
                                      "stations": [station, station]}), encoding="utf-8")
        try:
            read_station_file(backup, BACKUP_FILE_FORMAT)
        except ValueError:
            pass
        else:
            raise AssertionError("Accepted duplicate URLs in backup")


if __name__ == "__main__":
    test_station_files()
    print("Station sharing and backups OK")
