"""Radio++ para Windows: Qt + libmpv + Radio Browser."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QLocale, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QFontComboBox, QSpinBox, QKeySequenceEdit,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSlider, QSystemTrayIcon, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

APPDATA = Path(os.getenv("APPDATA", str(Path.home())))
CONFIG = APPDATA / "RadioPlusPlusQt" / "settings.json"
LEGACY_CONFIG = APPDATA / "RadioPlusPlus" / "settings.json"
COLORS = {
    "TextColor": ("Texto", "#f0f3ef"),
    "PanelBackground": ("Fondo del reproductor", "#1c2420"),
    "WindowBackground": ("Fondo de la ventana", "#1c2420"),
    "SurfaceColor": ("Tablas y campos", "#252c27"),
    "AccentColor": ("Acento y botones", "#6c9864"),
    "MutedColor": ("Texto secundario", "#a7b4a7"),
    "BorderColor": ("Bordes", "#536454"),
    "SelectedColor": ("Fila seleccionada", "#51734a"),
    "PlayingColor": ("Emisora activa", "#a9d68e"),
    "IconColor": ("Iconos del reproductor", "#f0f3ef"),
}
DEFAULT_SHORTCUTS = {
    "Previous": "Ctrl+Alt+Left",
    "Next": "Ctrl+Alt+Right",
    "Pause": "Ctrl+Alt+P",
    "Stop": "Ctrl+Alt+S",
}
HOTKEY_ACTIONS = tuple(DEFAULT_SHORTCUTS)
IMAGE_NAMES = {"Previous": "Previous.png", "Next": "Next.png",
               "Pause": "pause.png", "Stop": "stop.png"}
DEFAULTS = [
    {"Name": "Akustika", "Url": "http://ic3.101.ru:8000/c16_34", "Included": True},
    {"Name": "Rock Hits", "Url": "http://icecast.radiomaximum.cdnvideo.ru/st25.mp3", "Included": True},
    {"Name": "Hit FM", "Url": "http://icecast.radiohitfm.cdnvideo.ru/hit.mp3", "Included": True},
    {"Name": "Chillout", "Url": "http://ic7.101.ru:8000/c15_3", "Included": False},
]
EXTRACTOR_HOSTS = ("youtube.com", "youtu.be", "soundcloud.com", "mixcloud.com",
                   "bandcamp.com", "twitch.tv", "vimeo.com")


def needs_extractor(station):
    host = (urlparse(station["Url"]).hostname or "").lower()
    return station.get("UseYtDlp", False) or any(host == domain or host.endswith("." + domain)
                                                   for domain in EXTRACTOR_HOSTS)


def resolve_media(url):
    try:
        import yt_dlp
    except Exception as exc:
        raise RuntimeError(f"yt-dlp no está disponible: {exc}") from exc
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                           "noplaylist": True, "format": "bestaudio/best",
                           "socket_timeout": 15}) as downloader:
        info = downloader.extract_info(url, download=False)
        if not info:
            raise ValueError("yt-dlp no encontró audio para esta URL.")
        if info.get("entries"):
            info = next((item for item in info["entries"] if item), None)
        if not info:
            raise ValueError("La lista de reproducción está vacía.")
        stream = info.get("url")
        if not stream and info.get("formats"):
            stream = info["formats"][-1].get("url")
        if not stream:
            raise ValueError("yt-dlp no devolvió un stream reproducible.")
        return stream


def asset_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / name


def pack_path(pack, name):
    folder = Path("resources") / "icons" / pack
    candidates = [
        Path(sys.executable).parent / folder / name if getattr(sys, "frozen", False) else
        Path(__file__).parent / folder / name,
        CONFIG.parent / "iconpacks" / pack / name,
        asset_path(f"resources/icons/default/{name}"),
    ]
    return next((path for path in candidates if path.is_file()), candidates[-1])


def tinted_icon(name, color, pack="default", size=25):
    source = QPixmap(str(pack_path(pack, name)))
    if source.isNull():
        return QIcon()
    pixmap = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawPixmap((size - pixmap.width()) // 2, (size - pixmap.height()) // 2, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor(color))
    painter.end()
    return QIcon(result)


def shortcut_parts(text):
    sequence = QKeySequence(text)
    if sequence.count() != 1:
        raise ValueError("shortcut_one")
    combined = sequence[0].toCombined()
    key = combined & 0x01ffffff
    modifiers = ((1 if combined & Qt.KeyboardModifier.AltModifier.value else 0) |
                 (2 if combined & Qt.KeyboardModifier.ControlModifier.value else 0) |
                 (4 if combined & Qt.KeyboardModifier.ShiftModifier.value else 0) |
                 (8 if combined & Qt.KeyboardModifier.MetaModifier.value else 0))
    special = {Qt.Key.Key_Left.value: 0x25, Qt.Key.Key_Up.value: 0x26,
               Qt.Key.Key_Right.value: 0x27, Qt.Key.Key_Down.value: 0x28,
               Qt.Key.Key_Space.value: 0x20}
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F12.value:
        vk = 0x70 + key - Qt.Key.Key_F1.value
    else:
        vk = special.get(key, key if 0x30 <= key <= 0x5a else 0)
    if not vk or not modifiers:
        raise ValueError("shortcut_keys")
    return modifiers | 0x4000, vk


class NativeMessage(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


class WindowsHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, radio):
        super().__init__()
        self.radio = radio

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = ctypes.cast(int(message), ctypes.POINTER(NativeMessage)).contents
            if msg.message == 0x0312 and 1 <= msg.wParam <= len(HOTKEY_ACTIONS):
                action = HOTKEY_ACTIONS[msg.wParam - 1]
                QTimer.singleShot(0, lambda name=action: self.radio.run_action(name))
                return True, 0
        return False, 0


def readable_color(foreground, background, fallback="#f0f3ef"):
    def luminance(color):
        rgb = QColor(color)
        channels = [value / 255 for value in (rgb.red(), rgb.green(), rgb.blue())]
        values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                  for v in channels]
        return sum(a * b for a, b in zip(values, (0.2126, 0.7152, 0.0722)))
    a, b = luminance(foreground), luminance(background)
    if (max(a, b) + 0.05) / (min(a, b) + 0.05) >= 4.5:
        return foreground
    return "#f0f3ef" if luminance(background) < 0.45 else "#202820"


def icon(active=False, color="#99bb77"):
    pix = QPixmap(36, 36)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color if active else "#bababa"))
    painter.drawRoundedRect(3, 11, 30, 22, 4, 4)
    painter.drawRect(8, 6, 20, 4)
    painter.setBrush(QColor("#303030"))
    painter.drawEllipse(9, 17, 9, 9)
    painter.end()
    return QIcon(pix)


class Audio:
    def __init__(self, volume):
        self.lib = ctypes.CDLL(str(asset_path("libmpv-2.dll")))
        self.lib.mpv_create.restype = ctypes.c_void_p
        self.lib.mpv_set_option_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.lib.mpv_initialize.argtypes = [ctypes.c_void_p]
        self.lib.mpv_command.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
        self.lib.mpv_set_property.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        self.lib.mpv_terminate_destroy.argtypes = [ctypes.c_void_p]
        self.ctx = self.lib.mpv_create()
        if not self.ctx:
            raise RuntimeError("No se pudo iniciar mpv")
        self.check(self.lib.mpv_set_option_string(self.ctx, b"vid", b"no"))
        self.check(self.lib.mpv_set_option_string(self.ctx, b"terminal", b"no"))
        self.check(self.lib.mpv_set_option_string(self.ctx, b"ytdl", b"no"))
        self.check(self.lib.mpv_initialize(self.ctx))
        self.playing = False
        self.paused = False
        self.volume(volume)

    @staticmethod
    def check(code):
        if code < 0:
            raise RuntimeError(f"Error de mpv: {code}")

    def command(self, *args):
        array = (ctypes.c_char_p * (len(args) + 1))(
            *(arg.encode("utf-8") for arg in args), None
        )
        self.check(self.lib.mpv_command(self.ctx, array))

    def play(self, url):
        self.command("loadfile", url, "replace")
        self.playing, self.paused = True, False

    def toggle(self):
        flag = ctypes.c_int(0 if self.paused else 1)
        self.check(self.lib.mpv_set_property(self.ctx, b"pause", 3, ctypes.byref(flag)))
        self.paused = not self.paused

    def stop(self):
        self.command("stop")
        self.playing = self.paused = False

    def volume(self, value):
        number = ctypes.c_double(value)
        self.check(self.lib.mpv_set_property(self.ctx, b"volume", 5, ctypes.byref(number)))

    def close(self):
        self.lib.mpv_terminate_destroy(self.ctx)


class SearchSignals(QObject):
    finished = Signal(str, object, str)


class PlaybackSignals(QObject):
    resolved = Signal(int, object, str)


def paint_rounded_background(widget, background, border):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = widget.rect().adjusted(1, 1, -1, -1)
    path = QPainterPath()
    path.addRoundedRect(rect, 16, 16)
    painter.fillPath(path, QColor(background))
    painter.setPen(QPen(QColor(border), 1))
    painter.drawPath(path)


def mask_rounded(widget):
    path = QPainterPath()
    path.addRoundedRect(QRectF(widget.rect()), 16, 16)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


class RoundedShell(QWidget):
    def __init__(self, radio):
        super().__init__()
        self.radio = radio

    def paintEvent(self, event):
        paint_rounded_background(
            self, self.radio.config["WindowBackground"], self.radio.config["BorderColor"])


class Tray(QSystemTrayIcon):
    def __init__(self, app):
        super().__init__(QIcon(str(pack_path(app.config["IconPack"], "radio-original.png"))), app.window)
        self.radio = app

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            self.radio.show_popup()
            return True
        return super().event(event)


class StationDialog(QDialog):
    def __init__(self, radio, parent=None):
        super().__init__(parent)
        self.radio = radio
        self.setWindowTitle(radio.tr("custom_title"))
        self.setMinimumWidth(420)
        layout = QFormLayout(self)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText(radio.tr("custom_url_hint"))
        layout.addRow(radio.tr("name"), self.name)
        layout.addRow(radio.tr("url"), self.url)
        self.extract = QCheckBox(radio.tr("yt_resolve"))
        layout.addRow(self.extract)
        button = QPushButton(radio.tr("add"))
        button.clicked.connect(self.submit)
        layout.addRow(button)

    def submit(self):
        if not self.name.text().strip() or not self.url.text().startswith(("http://", "https://")):
            QMessageBox.warning(self, "Radio++", self.radio.tr("custom_invalid"))
            return
        self.accept()


class Manager(QMainWindow):
    def __init__(self, radio):
        super().__init__()
        self.radio = radio
        self.setWindowTitle(radio.tr("explore_title"))
        self.resize(860, 650)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_origin = None
        shell = RoundedShell(radio)
        shell.setObjectName("mainShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 10, 14, 14)
        shell_layout.setSpacing(8)
        titlebar = QWidget()
        titlebar.setObjectName("titleBar")
        titlebar.installEventFilter(self)
        title_layout = QHBoxLayout(titlebar)
        title_layout.setContentsMargins(12, 0, 4, 0)
        title = QLabel("◉  RADIO++  /  EXPLORAR")
        title.installEventFilter(self)
        title_layout.addWidget(title, 1)
        minimize = QPushButton("—")
        minimize.setFixedSize(34, 30)
        minimize.clicked.connect(self.showMinimized)
        close = QPushButton("×")
        close.setFixedSize(34, 30)
        close.clicked.connect(self.close)
        title_layout.addWidget(minimize)
        title_layout.addWidget(close)
        shell_layout.addWidget(titlebar)
        tabs = QTabWidget()
        tabs.setObjectName("managerTabs")
        self.tabs = tabs
        shell_layout.addWidget(tabs)
        self.setCentralWidget(shell)
        find = QWidget()
        own = QWidget()
        tabs.addTab(find, radio.tr("explore"))
        tabs.addTab(own, radio.tr("mine"))
        self.preferences_page = PreferencesPage(radio)
        tabs.addTab(self.preferences_page, radio.tr("preferences"))
        find_layout = QVBoxLayout(find)
        find_layout.setContentsMargins(20, 20, 20, 20)
        find_layout.setSpacing(12)
        find_layout.addWidget(QLabel(radio.tr("explore_header")))
        description = QLabel(radio.tr("explore_hint"))
        description.setObjectName("hint")
        find_layout.addWidget(description)
        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕  " + radio.tr("search_hint"))
        self.search.setMinimumHeight(42)
        find_layout.addWidget(self.search)
        self.status = QLabel(radio.tr("loading"))
        self.status.setObjectName("hint")
        find_layout.addWidget(self.status)
        self.results = self.table()
        find_layout.addWidget(self.results)
        row = QHBoxLayout()
        for text, action in (
            (radio.tr("listen"), lambda: self.listen(self.results)),
            (radio.tr("add_saved"), self.add_selected),
        ):
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        find_layout.addLayout(row)
        self.results.cellDoubleClicked.connect(lambda *_: self.listen(self.results))
        own_layout = QVBoxLayout(own)
        own_layout.setContentsMargins(20, 20, 20, 20)
        own_layout.setSpacing(12)
        own_layout.addWidget(QLabel(radio.tr("mine_header")))
        own_description = QLabel(radio.tr("mine_hint"))
        own_description.setObjectName("hint")
        own_layout.addWidget(own_description)
        self.saved = self.table()
        own_layout.addWidget(self.saved)
        row = QHBoxLayout()
        for text, action in (
            (radio.tr("listen"), lambda: self.listen(self.saved)),
            (radio.tr("add_custom"), self.add_custom),
            (radio.tr("remove"), self.remove_selected),
        ):
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        own_layout.addLayout(row)
        self.saved.cellDoubleClicked.connect(lambda *_: self.listen(self.saved))
        self.signals = SearchSignals(self)
        self.signals.finished.connect(self.receive)
        self.delay = QTimer(self, singleShot=True, interval=450)
        self.delay.timeout.connect(self.search_online)
        self.search.textChanged.connect(lambda _: self.delay.start())
        self.show_saved()
        self.search_online()
        mask_rounded(self)

    def resizeEvent(self, event):
        mask_rounded(self)
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj.objectName() == "titleBar" or isinstance(obj, QLabel):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_origin is not None:
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def table():
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Name", "URL"])
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setDefaultSectionSize(42)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 310)
        return table

    @staticmethod
    def selected(table):
        row = table.currentRow()
        if row < 0 or not table.item(row, 0):
            return None
        return table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    @staticmethod
    def fill(table, stations):
        table.setRowCount(len(stations))
        for row, station in enumerate(stations):
            name = QTableWidgetItem("  ◉   " + station["Name"])
            name.setData(Qt.ItemDataRole.UserRole, station)
            name.setToolTip(station["Name"])
            url = QTableWidgetItem(station["Url"])
            url.setToolTip(station["Url"])
            table.setItem(row, 0, name)
            table.setItem(row, 1, url)

    def search_online(self):
        text = self.search.text().strip()
        endpoint = (
            "stations/search?" + urlencode({"name": text, "limit": 100, "hidebroken": "true"})
            if len(text) >= 2 else "stations/topclick/50?hidebroken=true"
        )
        self.status.setText(self.radio.tr("searching" if text else "loading"))
        url = "https://de1.api.radio-browser.info/json/" + endpoint
        signals = self.signals

        def download():
            try:
                request = Request(url, headers={"User-Agent": "RadioPlusPlus-Qt/1.0"})
                with urlopen(request, timeout=15) as response:
                    data = json.load(response)
                signals.finished.emit(text, data, "")
            except Exception as exc:
                signals.finished.emit(text, None, str(exc))

        threading.Thread(target=download, daemon=True).start()

    def receive(self, query, data, error):
        if query != self.search.text().strip():
            return
        try:
            if error:
                raise RuntimeError(error)
            found = []
            for entry in data:
                name = (entry.get("name") or "").strip()
                url = entry.get("url_resolved") or ""
                if name and url.startswith(("http://", "https://")):
                    found.append({"Name": name, "Url": url})
            self.fill(self.results, found)
            self.status.setText(self.radio.tr("results" if query else "popular", count=len(found)))
        except Exception as exc:
            self.status.setText(self.radio.tr("search_error", error=exc))

    def show_saved(self):
        self.fill(self.saved, self.radio.config["Stations"])

    def listen(self, table):
        if station := self.selected(table):
            self.radio.play(station)

    def add_selected(self):
        if station := self.selected(self.results):
            self.radio.add(station)
            self.show_saved()

    def add_custom(self):
        dialog = StationDialog(self.radio, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.radio.add({"Name": dialog.name.text().strip(), "Url": dialog.url.text().strip(),
                            "Included": True, "UseYtDlp": dialog.extract.isChecked()})
            self.show_saved()

    def remove_selected(self):
        if station := self.selected(self.saved):
            self.radio.remove(station)
            self.show_saved()

class PreferencesPage(QWidget):
    def __init__(self, radio):
        super().__init__()
        self.radio = radio
        sections = QTabWidget(self)
        outer = QVBoxLayout(self)
        outer.addWidget(sections)
        appearance = QWidget()
        shortcuts = QWidget()
        language_page = QWidget()
        sections.addTab(appearance, radio.tr("appearance"))
        sections.addTab(shortcuts, radio.tr("shortcuts"))
        sections.addTab(language_page, radio.tr("languages"))
        form = QFormLayout(appearance)
        form.setSpacing(14)
        form.setContentsMargins(22, 22, 22, 22)
        form.addRow(QLabel(radio.tr("font_header")))
        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont(radio.config["FontFamily"]))
        self.font_family.currentFontChanged.connect(
            lambda font: self.update_value("FontFamily", font.family()))
        form.addRow(radio.tr("font_family"), self.font_family)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 30)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(int(radio.config["FontSize"]))
        self.font_size.valueChanged.connect(lambda value: self.update_value("FontSize", value))
        form.addRow(radio.tr("font_size"), self.font_size)
        form.addRow(QLabel(radio.tr("colors_header")))
        for key, (label, _) in COLORS.items():
            button = QPushButton()
            button.clicked.connect(lambda _, name=key: self.pick_color(name))
            form.addRow(radio.tr({"TextColor": "text_color", "PanelBackground": "panel_background",
                                "WindowBackground": "window_background", "SurfaceColor": "surface_color",
                                "AccentColor": "accent_color", "MutedColor": "muted_color",
                                "BorderColor": "border_color", "SelectedColor": "selected_color",
                                "PlayingColor": "station_color", "IconColor": "icon_color"}[key]), button)
            self.update_swatch(button, radio.config[key])
            setattr(self, "color_" + key, button)
        self.packs = QComboBox()
        pack_names = {"default"}
        for base in (asset_path("resources/icons"), CONFIG.parent / "iconpacks",
                     Path(sys.executable).parent / "resources" / "icons"):
            if base.is_dir():
                pack_names.update(path.name for path in base.iterdir() if path.is_dir())
        self.packs.addItems(sorted(pack_names))
        self.packs.setCurrentText(radio.config["IconPack"])
        self.packs.currentTextChanged.connect(lambda value: self.update_value("IconPack", value))
        form.addRow(radio.tr("icon_pack"), self.packs)
        shortcut_form = QFormLayout(shortcuts)
        shortcut_form.setSpacing(16)
        shortcut_form.setContentsMargins(22, 22, 22, 22)
        shortcut_form.addRow(QLabel(radio.tr("shortcut_header")))
        self.shortcut_status = QLabel("")
        for action, key in (("Previous", "previous"), ("Next", "next"),
                            ("Pause", "pause"), ("Stop", "stop")):
            editor = QKeySequenceEdit(QKeySequence(radio.config["Shortcuts"][action]))
            editor.editingFinished.connect(lambda name=action, field=editor:
                                           self.set_shortcut(name, field))
            shortcut_form.addRow(radio.tr(key), editor)
        shortcut_form.addRow(self.shortcut_status)
        language_form = QFormLayout(language_page)
        language_form.setSpacing(16)
        language_form.setContentsMargins(22, 22, 22, 22)
        language_form.addRow(QLabel(radio.tr("language_header")))
        selector = QComboBox()
        for code, label in (("en", "English"), ("es", "Español"), ("fr", "Français")):
            selector.addItem(label, code)
        selector.setCurrentIndex(max(0, selector.findData(radio.config["Language"])))
        selector.currentIndexChanged.connect(lambda: radio.set_language(selector.currentData()))
        language_form.addRow(radio.tr("language"), selector)
        language_form.addRow(QLabel(radio.tr("language_hint")))

    def update_swatch(self, button, value):
        button.setText(value.upper() + "   ●")
        button.setToolTip(self.radio.tr("choose_color_hint"))

    def update_value(self, key, value):
        self.radio.config[key] = value
        self.radio.save()
        self.radio.apply_style()

    def pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.radio.config[key]), self, self.radio.tr("choose_color"))
        if color.isValid():
            self.update_value(key, color.name())
            self.update_swatch(getattr(self, "color_" + key), color.name())

    def set_shortcut(self, action, editor):
        value = editor.keySequence().toString()
        old = self.radio.config["Shortcuts"][action]
        try:
            shortcut_parts(value)
            if any(shortcut == value for name, shortcut in self.radio.config["Shortcuts"].items()
                   if name != action):
                raise ValueError("shortcut_duplicate")
            self.radio.config["Shortcuts"][action] = value
            self.radio.register_shortcuts()
            if action in self.radio.shortcut_errors:
                raise ValueError(self.radio.shortcut_errors[action])
            self.radio.save()
            self.shortcut_status.setText(self.radio.tr("shortcut_saved", action=action, value=value))
        except ValueError as exc:
            self.radio.config["Shortcuts"][action] = old
            self.radio.register_shortcuts()
            editor.setKeySequence(QKeySequence(old))
            self.shortcut_status.setText(self.radio.tr(str(exc)))


class Popup(QWidget):
    def __init__(self, radio):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("radioPopup")
        self.radio = radio
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        self.stations = QListWidget()
        self.stations.setObjectName("stationList")
        self.stations.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.stations.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.stations.itemClicked.connect(self.select)
        layout.addWidget(self.stations)
        self.now = QLabel(radio.tr("not_playing"))
        self.now.setObjectName("nowPlaying")
        self.now.setMinimumHeight(48)
        layout.addWidget(self.now)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.controls = {}
        for action, title, callback in (
            ("Previous", radio.tr("previous"), radio.previous),
            ("Pause", radio.tr("pause"), radio.toggle),
            ("Stop", radio.tr("stop"), radio.stop),
            ("Next", radio.tr("next"), radio.next),
        ):
            button = QPushButton()
            button.setFixedHeight(42)
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.clicked.connect(callback)
            self.controls[action] = button
            row.addWidget(button, 1)
        layout.addLayout(row)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(radio.config["Volume"])
        self.volume.valueChanged.connect(radio.volume)
        volume_label = QLabel(radio.tr("volume"))
        volume_label.setObjectName("fieldLabel")
        layout.addWidget(volume_label)
        layout.addWidget(self.volume)
        actions = QHBoxLayout()
        manager = QPushButton(radio.tr("find_stations"))
        manager.clicked.connect(radio.open_manager)
        actions.addWidget(manager, 1)
        gear = QPushButton("⚙")
        gear.setToolTip(radio.tr("preferences"))
        gear.setAccessibleName(radio.tr("preferences"))
        gear.setFixedWidth(48)
        gear.clicked.connect(radio.open_preferences)
        actions.addWidget(gear)
        layout.addLayout(actions)
        self.refresh()
        mask_rounded(self)

    def resizeEvent(self, event):
        mask_rounded(self)
        super().resizeEvent(event)

    def paintEvent(self, event):
        paint_rounded_background(
            self, self.radio.config["PanelBackground"], self.radio.config["BorderColor"])

    def refresh(self):
        old_scroll = self.stations.verticalScrollBar().value()
        self.stations.blockSignals(True)
        self.stations.clear()
        active_row = None
        for station in self.radio.config["Stations"]:
            if station.get("Included", True):
                item = QListWidgetItem(station["Name"])
                item.setData(Qt.ItemDataRole.UserRole, station)
                item.setSizeHint(QSize(0, 35))
                self.stations.addItem(item)
                if self.radio.current and station["Url"] == self.radio.current["Url"]:
                    active_row = self.stations.count() - 1
        count = self.stations.count()
        self.stations.setFixedHeight(min(max(count, 1), 7) * 35 + 4)
        self.setFixedHeight(270 + self.stations.height())
        if active_row is not None:
            self.stations.setCurrentRow(active_row)
        self.stations.verticalScrollBar().setValue(old_scroll)
        self.stations.blockSignals(False)
        self.now.setText(self.radio.current["Name"] if self.radio.current else self.radio.tr("not_playing"))
        playing = self.radio.audio.playing and not self.radio.audio.paused
        self.controls["Pause"].setToolTip(self.radio.tr("pause"))
        self.update_icons()

    def update_icons(self):
        color = self.radio.config["IconColor"]
        pack = self.radio.config["IconPack"]
        for action, button in self.controls.items():
            name = "pause.png" if action == "Pause" and self.radio.audio.playing and not self.radio.audio.paused \
                else "play.png" if action == "Pause" else IMAGE_NAMES[action]
            button.setIcon(tinted_icon(name, color, pack))
            button.setIconSize(QPixmap(25, 25).size())

    def select(self, item):
        self.radio.play(item.data(Qt.ItemDataRole.UserRole))

class RadioApp:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.hotkey_filter = WindowsHotkeyFilter(self)
        self.qt.installNativeEventFilter(self.hotkey_filter)
        self.qt.setWindowIcon(QIcon(str(pack_path("default", "radio-original.png"))))
        self.qt.setQuitOnLastWindowClosed(False)
        self.config = self.load()
        self.translations = self.load_translations(self.config["Language"])
        self.audio = Audio(self.config["Volume"])
        self.current = None
        self.playback_version = 0
        self.playback_signals = PlaybackSignals()
        self.playback_signals.resolved.connect(self._play_resolved)
        self.window = Manager(self)
        self.popup = Popup(self)
        self.tray = Tray(self)
        menu = QMenu()
        menu.addAction(self.tr("tray_manager"), self.open_manager)
        menu.addAction(self.tr("stop"), self.stop)
        menu.addSeparator()
        menu.addAction(self.tr("tray_exit"), self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_popup()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self.apply_style()
        self.shortcut_errors = {}
        self.register_shortcuts()

    @staticmethod
    def load():
        base = {
            "Stations": DEFAULTS, "PlayingColor": "#99bb77", "PanelBackground": "#303030",
            "FontFamily": "Segoe UI", "FontSize": 10, "Volume": 70,
        }
        try:
            source = CONFIG if CONFIG.exists() else LEGACY_CONFIG
            if source.exists():
                raw = json.loads(source.read_text(encoding="utf-8"))
                base.update(raw)
        except (ValueError, OSError):
            pass
        for key, (_, default) in COLORS.items():
            base.setdefault(key, default)
        base.setdefault("Language", QLocale.system().name().split("_")[0])
        if base["Language"] not in ("en", "es", "fr"):
            base["Language"] = "en"
        base.setdefault("IconPack", "default")
        base["Shortcuts"] = {**DEFAULT_SHORTCUTS, **base.get("Shortcuts", {})}
        return base

    @staticmethod
    def load_translations(language):
        path = asset_path(f"resources/languages/i18n/{language}.json")
        fallback = asset_path("resources/languages/i18n/en.json")
        try:
            english = json.loads(fallback.read_text(encoding="utf-8"))
            return {**english, **json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return {}

    def tr(self, key, **values):
        text = self.translations.get(key, key)
        return text.format(**values) if values else text

    def set_language(self, language):
        if language == self.config["Language"]:
            return
        self.config["Language"] = language
        self.save()
        QTimer.singleShot(100, self.restart)

    def restart(self):
        command = [sys.executable] if getattr(sys, "frozen", False) else \
            [sys.executable, str(Path(__file__).resolve())]
        environment = os.environ.copy()
        if getattr(sys, "frozen", False):
            # PyInstaller onefile otherwise reuses the parent's temporary extraction.
            # The parent then removes Qt DLLs while the restarted process imports them.
            environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        self.quit()
        subprocess.Popen(command, cwd=str(Path(sys.executable).parent),
                         env=environment, creationflags=subprocess.DETACHED_PROCESS)

    def save(self):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    def apply_style(self):
        bg = self.config["PanelBackground"]
        font = self.config["FontFamily"]
        size = max(7, int(self.config["FontSize"]))
        colors = self.config
        surface = colors["SurfaceColor"]
        accent = colors["AccentColor"]
        muted = colors["MutedColor"]
        border = colors["BorderColor"]
        selected = colors["SelectedColor"]
        text = colors["TextColor"]
        window = colors["WindowBackground"]
        panel_text = readable_color(text, bg)
        title_color = readable_color(accent, bg)
        muted_color = readable_color(muted, bg)
        selected_text = readable_color(text, selected)
        button_text = readable_color(text, accent)
        playing_text = readable_color(colors["PlayingColor"], surface)
        self.qt.setFont(QFont(font, size))
        self.qt.setStyleSheet(f"""
            QMainWindow {{ background: transparent; }}
            QWidget#mainShell {{
                background: {window}; border: 1px solid {border}; border-radius: 18px;
            }}
            QWidget#titleBar {{ background: transparent; border: 0; }}
            QWidget {{
                background: {window}; color: {text};
                font-family: "{font}"; font-size: {size}pt;
            }}
            QWidget#radioPopup {{
                background: {bg}; color: {panel_text}; border: 1px solid {border};
                border-radius: 16px;
            }}
            QLabel {{ background: transparent; border: none; }}
            QWidget#radioPopup QLabel {{ color: {panel_text}; }}
            QLabel#hint {{ color: {muted_color}; padding: 2px 0 6px 0; }}
            QLabel#popupTitle {{
                background: transparent; font-size: 18pt; font-weight: 800;
                letter-spacing: 1px; color: {title_color};
            }}
            QLabel#popupCaption {{ color: {muted_color}; font-size: 9pt; }}
            QLabel#fieldLabel {{
                color: {muted_color}; font-size: 9pt; font-weight: 700;
                padding-top: 5px;
            }}
            QLabel#nowPlaying {{
                background: {surface}; border: 1px solid {border};
                border-radius: 8px; padding: 12px; color: {playing_text};
                font-weight: 600;
            }}
            QPushButton {{
                background: {accent}; color: {button_text}; border: 1px solid {border};
                border-radius: 8px; padding: 8px 12px; font-weight: 600;
            }}
            QPushButton:hover {{ border-color: {text}; }}
            QLineEdit, QComboBox {{
                background: {surface}; border: 1px solid {border};
                border-radius: 8px; padding: 8px; selection-background-color: {selected};
                selection-color: {selected_text}; color: {text};
            }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
            QTableWidget {{
                background: {surface}; alternate-background-color: {window};
                gridline-color: {border}; border: 1px solid {border};
                border-radius: 8px; selection-background-color: {selected};
                selection-color: {selected_text};
            }}
            QHeaderView::section {{
                background: {surface}; color: {text}; padding: 10px;
                border: 0; border-bottom: 1px solid {border}; font-weight: 700;
            }}
            QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; }}
            QTabBar::tab {{
                background: {surface}; color: {muted}; padding: 12px 22px;
                border: 1px solid {border}; border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            QTabBar::tab:selected {{ background: {accent}; color: {button_text}; }}
            QSlider::groove:horizontal {{ background: {border}; height: 6px; border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
            QWidget#radioPopup QSlider {{ background: transparent; }}
            QWidget#radioPopup QSlider::groove:horizontal {{
                background: {bg}; border: 1px solid {border};
                height: 6px; border-radius: 4px;
            }}
            QWidget#radioPopup QSlider::sub-page:horizontal {{
                background: {accent}; border-radius: 3px;
            }}
            QListWidget#stationList {{
                background: {surface}; color: {text}; border: 1px solid {border};
                border-radius: 8px; padding: 3px; outline: none;
            }}
            QListWidget#stationList::item {{ border-radius: 5px; padding-left: 10px; }}
            QListWidget#stationList::item:hover {{ background: {selected}; }}
            QListWidget#stationList::item:selected {{
                background: {selected}; color: {selected_text};
            }}
            QListWidget#stationList QScrollBar:vertical {{
                background: {bg}; width: 12px; margin: 4px 1px;
            }}
            QListWidget#stationList QScrollBar::handle:vertical {{
                background: {accent}; min-height: 24px; border-radius: 5px;
            }}
            QListWidget#stationList QScrollBar::add-line:vertical,
            QListWidget#stationList QScrollBar::sub-line:vertical {{ height: 0; }}
            QSlider::handle:horizontal {{
                background: {text}; width: 16px; border-radius: 8px; margin: -5px 0;
            }}
        """)
        self.popup.update_icons()
        self.tray.setIcon(QIcon(str(pack_path(self.config["IconPack"], "radio-original.png"))))

    def show_popup(self):
        self.popup.refresh()
        pos = self.qt.primaryScreen().availableGeometry()
        cursor = __import__("PySide6.QtGui", fromlist=["QCursor"]).QCursor.pos()
        screen = self.qt.screenAt(cursor) or self.qt.primaryScreen()
        pos = screen.availableGeometry()
        x = max(pos.left(), min(cursor.x() - self.popup.width() // 2, pos.right() - self.popup.width()))
        self.popup.move(QPoint(x, pos.bottom() - self.popup.height()))
        self.popup.show()

    def open_manager(self):
        self.popup.hide()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_preferences(self):
        self.popup.hide()
        self.open_manager()
        self.window.tabs.setCurrentWidget(self.window.preferences_page)

    def play(self, station):
        self.playback_version += 1
        version = self.playback_version
        self.current = station
        if needs_extractor(station):
            self.audio.stop()
            self.popup.refresh()
            self.popup.now.setText(self.tr("starting", station=station["Name"]))
            signals = self.playback_signals
            url = station["Url"]

            def extract():
                try:
                    signals.resolved.emit(version, station, resolve_media(url))
                except Exception as exc:
                    signals.resolved.emit(version, station, f"ERROR: {exc}")

            threading.Thread(target=extract, daemon=True).start()
            return
        self._play_resolved(version, station, station["Url"])

    def _play_resolved(self, version, station, stream):
        if version != self.playback_version:
            return
        if stream.startswith("ERROR: "):
            self.current = None
            self.popup.refresh()
            self.tray.showMessage("Radio++ · yt-dlp", stream[7:],
                                  QSystemTrayIcon.MessageIcon.Warning, 6000)
            return
        try:
            self.audio.play(stream)
            self.current = station
            self.popup.refresh()
            self.apply_style()
        except Exception as exc:
            self.tray.showMessage("Radio++ · " + self.tr("playback_error"), str(exc),
                                  QSystemTrayIcon.MessageIcon.Warning, 6000)

    def toggle(self):
        try:
            if self.audio.playing:
                self.audio.toggle()
                self.popup.refresh()
            elif self.current:
                self.play(self.current)
            elif station := next((s for s in self.config["Stations"] if s.get("Included", True)), None):
                self.play(station)
        except Exception as exc:
            QMessageBox.warning(self.window, "Radio++", str(exc))

    def navigate(self, direction):
        stations = [s for s in self.config["Stations"] if s.get("Included", True)]
        if not stations:
            return
        current_url = self.current["Url"] if self.current else None
        index = next((i for i, station in enumerate(stations) if station["Url"] == current_url), None)
        next_index = ((index + direction) % len(stations)) if index is not None else (0 if direction > 0 else -1)
        self.play(stations[next_index])

    def previous(self):
        self.navigate(-1)

    def next(self):
        self.navigate(1)

    def run_action(self, action):
        {"Previous": self.previous, "Next": self.next,
         "Pause": self.toggle, "Stop": self.stop}[action]()

    def register_shortcuts(self):
        user32 = ctypes.windll.user32
        for identifier in range(1, len(HOTKEY_ACTIONS) + 1):
            user32.UnregisterHotKey(None, identifier)
        self.shortcut_errors = {}
        for identifier, action in enumerate(HOTKEY_ACTIONS, 1):
            try:
                modifiers, key = shortcut_parts(self.config["Shortcuts"][action])
                if not user32.RegisterHotKey(None, identifier, modifiers, key):
                    raise ValueError("shortcut_occupied")
            except ValueError as exc:
                self.shortcut_errors[action] = str(exc)
        if self.shortcut_errors:
            self.tray.showMessage(
                "Radio++ · " + self.tr("shortcuts"),
                self.tr("tray_shortcuts_error", actions=", ".join(
                    self.tr(message) for message in self.shortcut_errors.values())),
                QSystemTrayIcon.MessageIcon.Warning, 7000)

    def stop(self):
        self.playback_version += 1
        self.audio.stop()
        self.current = None
        self.popup.refresh()
        self.apply_style()

    def volume(self, value):
        self.audio.volume(value)
        self.config["Volume"] = value
        self.save()

    def add(self, station):
        if any(s["Url"] == station["Url"] for s in self.config["Stations"]):
            QMessageBox.information(self.window, "Radio++", self.tr("already_saved"))
            return
        self.config["Stations"].append(station)
        self.save()
        self.popup.refresh()

    def remove(self, station):
        self.config["Stations"] = [s for s in self.config["Stations"] if s["Url"] != station["Url"]]
        self.save()
        self.popup.refresh()

    def quit(self):
        for identifier in range(1, len(HOTKEY_ACTIONS) + 1):
            ctypes.windll.user32.UnregisterHotKey(None, identifier)
        self.qt.removeNativeEventFilter(self.hotkey_filter)
        self.tray.hide()
        self.audio.close()
        self.qt.quit()


if __name__ == "__main__":
    try:
        app = RadioApp()
        sys.exit(app.qt.exec())
    except Exception as error:
        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Radio++", f"No se pudo iniciar:\n{error}")
