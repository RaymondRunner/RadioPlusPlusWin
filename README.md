# Radio++ for Windows

A Windows radio player built with Qt/PySide6 and libmpv. Discover stations through [Radio Browser](https://www.radio-browser.info/), or add your own URLs. Inspired by the [Radio++ Cinnamon applet](https://github.com/linuxmint/cinnamon-spices-applets/tree/092e3f889e27dc98ee3734651bd777efb286c95d/radio%40driglu4it).

## Features

- Starts in the system tray. Hover over or click its icon to open the player.
- Browse stations, listen before saving, add your own URLs, and remove saved stations.
- The player shows the current station, a permanent song-title line (“No song” when no metadata is available), and a compact station list. The list shows up to seven rows; its vertical scrollbar appears when needed and the popup stays above the Windows taskbar.
- Previous, play/pause, stop, and next controls use tintable PNG icons from `resources/icons/default/`.
- Global, configurable keyboard shortcuts work while the main window is hidden: `Ctrl+Alt+Left` (previous), `Ctrl+Alt+Right` (next), `Ctrl+Alt+P` (play/pause), and `Ctrl+Alt+S` (stop). Windows will report shortcuts already claimed by other applications.
- **Preferences → Appearance** controls fonts, colors, and icon packs, and can follow the Windows accent color without losing your manually selected accent. **Preferences → Shortcuts** customizes keys. **Preferences → Languages** offers English, Spanish, and French; changing language restarts the app in the tray.
- yt-dlp resolves supported page links (including YouTube) in the background. Direct radio streams go straight to mpv. When adding your own station, you can explicitly enable yt-dlp for its URL.

## Build on Windows

Requires 64-bit Windows, Python 3.13, and internet access for initial dependencies:

```powershell
python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The script downloads a pinned libmpv NuGet package, verifies its SHA-256, and builds `dist\RadioPlusPlus-Qt-v14.exe`, which includes Python, yt-dlp, the default icon pack, and the translations. The single-file executable extracts its contents to a temporary directory when launched.

To run from source, place `libmpv-2.dll` alongside `app.py` and run `python app.py`.

Settings and saved stations are stored at `%APPDATA%\RadioPlusPlusQt\settings.json`. On first launch, settings from the earlier Radio++ Windows version are imported if present.

## Icon packs and translations

Create `resources/icons/YOUR_PACK/` next to the executable, or `%APPDATA%\RadioPlusPlusQt\iconpacks\YOUR_PACK\`, with PNG files named `Previous.png`, `Next.png`, `pause.png`, `play.png`, and `stop.png`. Select your pack under Appearance. PNG transparency is retained when recoloring; missing files fall back to the built-in default pack. The executable icon comes from `resources/icons/default/radio-original.ico`.

Translations are JSON files in `resources/languages/i18n/`. Add a new language by copying an existing file and registering its language code in `PreferencesPage` and `RadioApp.load()`. Missing keys fall back to English.

`dist/` is ignored by Git. To distribute the executable, attach it to a GitHub Release instead of committing it to the repository.

## License

See [LICENSE](LICENSE). Check the redistribution terms for any icons or other assets you add.

> Note: This project was "vibecoded", inspired by the Radio++ applet for Cinnamon.
