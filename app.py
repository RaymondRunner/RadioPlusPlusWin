"""Radio++ para Windows: Qt + libmpv + Radio Browser."""
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QDialog, QFontComboBox, QSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
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
}
DEFAULTS = [
    {"Name": "Akustika", "Url": "http://ic3.101.ru:8000/c16_34", "Included": True},
    {"Name": "Rock Hits", "Url": "http://icecast.radiomaximum.cdnvideo.ru/st25.mp3", "Included": True},
    {"Name": "Hit FM", "Url": "http://icecast.radiohitfm.cdnvideo.ru/hit.mp3", "Included": True},
    {"Name": "Chillout", "Url": "http://ic7.101.ru:8000/c15_3", "Included": False},
]


def asset_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / name


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
        super().__init__(QIcon(str(asset_path("radio-original.png"))), app.window)
        self.radio = app

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            self.radio.show_popup()
            return True
        return super().event(event)


class StationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Añadir mi emisora")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://ejemplo.com/stream.mp3")
        layout.addRow("Nombre", self.name)
        layout.addRow("URL", self.url)
        button = QPushButton("＋ Añadir")
        button.clicked.connect(self.submit)
        layout.addRow(button)

    def submit(self):
        if not self.name.text().strip() or not self.url.text().startswith(("http://", "https://")):
            QMessageBox.warning(self, "Radio++", "Introduce un nombre y URL HTTP/HTTPS.")
            return
        self.accept()


class Manager(QMainWindow):
    def __init__(self, radio):
        super().__init__()
        self.radio = radio
        self.setWindowTitle("Radio++ · Explorar emisoras")
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
        shell_layout.addWidget(tabs)
        self.setCentralWidget(shell)
        find = QWidget()
        own = QWidget()
        tabs.addTab(find, "Find Station")
        tabs.addTab(own, "My Stations")
        find_layout = QVBoxLayout(find)
        find_layout.setContentsMargins(20, 20, 20, 20)
        find_layout.setSpacing(12)
        find_layout.addWidget(QLabel("EXPLORAR RADIO"))
        description = QLabel("Encuentra una emisora, escúchala y guárdala en tu colección.")
        description.setObjectName("hint")
        find_layout.addWidget(description)
        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕  Buscar por nombre, por ejemplo Rock o Deep House…")
        self.search.setMinimumHeight(42)
        find_layout.addWidget(self.search)
        self.status = QLabel("Cargando emisoras populares…")
        self.status.setObjectName("hint")
        find_layout.addWidget(self.status)
        self.results = self.table()
        find_layout.addWidget(self.results)
        row = QHBoxLayout()
        for text, action in (
            ("▶ Escuchar", lambda: self.listen(self.results)),
            ("＋ Add to My Stations", self.add_selected),
        ):
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        find_layout.addLayout(row)
        self.results.cellDoubleClicked.connect(lambda *_: self.listen(self.results))
        own_layout = QVBoxLayout(own)
        own_layout.setContentsMargins(20, 20, 20, 20)
        own_layout.setSpacing(12)
        own_layout.addWidget(QLabel("MIS EMISORAS"))
        own_description = QLabel("Tu colección personal. Doble clic para escuchar.")
        own_description.setObjectName("hint")
        own_layout.addWidget(own_description)
        self.saved = self.table()
        own_layout.addWidget(self.saved)
        row = QHBoxLayout()
        for text, action in (
            ("▶ Escuchar", lambda: self.listen(self.saved)),
            ("＋ Añadir mi emisora", self.add_custom),
            ("− Quitar seleccionada", self.remove_selected),
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
        return {"Name": table.item(row, 0).data(Qt.ItemDataRole.UserRole),
                "Url": table.item(row, 1).text(), "Included": True}

    @staticmethod
    def fill(table, stations):
        table.setRowCount(len(stations))
        for row, station in enumerate(stations):
            name = QTableWidgetItem("  ◉   " + station["Name"])
            name.setData(Qt.ItemDataRole.UserRole, station["Name"])
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
        self.status.setText("Buscando emisoras…" if text else "Cargando emisoras populares…")
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
            self.status.setText(f"{len(found)} emisoras encontradas" if query else
                                f"{len(found)} emisoras populares")
        except Exception as exc:
            self.status.setText(f"No se pudo buscar: {exc}")

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
        dialog = StationDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.radio.add({"Name": dialog.name.text().strip(), "Url": dialog.url.text().strip(), "Included": True})
            self.show_saved()

    def remove_selected(self):
        if station := self.selected(self.saved):
            self.radio.remove(station)
            self.show_saved()

class PreferencesDialog(QDialog):
    def __init__(self, radio):
        super().__init__(radio.window)
        self.radio = radio
        self.setWindowTitle("Radio++ · Preferencias")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        form.setSpacing(14)
        form.setContentsMargins(22, 22, 22, 22)
        form.addRow(QLabel("TIPOGRAFÍA"))
        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont(radio.config["FontFamily"]))
        self.font_family.currentFontChanged.connect(
            lambda font: self.update_value("FontFamily", font.family()))
        form.addRow("Fuente del reproductor", self.font_family)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 30)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(int(radio.config["FontSize"]))
        self.font_size.valueChanged.connect(lambda value: self.update_value("FontSize", value))
        form.addRow("Tamaño", self.font_size)
        form.addRow(QLabel("COLORES"))
        for key, (label, _) in COLORS.items():
            button = QPushButton()
            button.clicked.connect(lambda _, name=key: self.pick_color(name))
            form.addRow(label, button)
            self.update_swatch(button, radio.config[key])
            setattr(self, "color_" + key, button)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        form.addRow(close)

    @staticmethod
    def update_swatch(button, value):
        button.setText(value.upper() + "   ●")
        button.setToolTip("Haz clic para cambiar este color")

    def update_value(self, key, value):
        self.radio.config[key] = value
        self.radio.save()
        self.radio.apply_style()

    def pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.radio.config[key]), self, "Elegir color")
        if color.isValid():
            self.update_value(key, color.name())
            self.update_swatch(getattr(self, "color_" + key), color.name())


class Popup(QWidget):
    def __init__(self, radio):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("radioPopup")
        self.radio = radio
        self.setFixedSize(380, 365)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)
        heading = QLabel("RADIO++")
        heading.setObjectName("popupTitle")
        layout.addWidget(heading)
        caption = QLabel("TU RADIO, A UN CLIC")
        caption.setObjectName("popupCaption")
        layout.addWidget(caption)
        station_label = QLabel("EMISORA")
        station_label.setObjectName("fieldLabel")
        layout.addWidget(station_label)
        self.stations = QComboBox()
        self.stations.setMinimumHeight(42)
        layout.addWidget(self.stations)
        self.now = QLabel("Sin reproducción")
        self.now.setObjectName("nowPlaying")
        self.now.setMinimumHeight(48)
        layout.addWidget(self.now)
        row = QHBoxLayout()
        self.play_button = QPushButton("▶  Reproducir")
        self.play_button.clicked.connect(self.toggle)
        row.addWidget(self.play_button)
        stop = QPushButton("■  Detener")
        stop.clicked.connect(radio.stop)
        row.addWidget(stop)
        layout.addLayout(row)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(radio.config["Volume"])
        self.volume.valueChanged.connect(radio.volume)
        volume_label = QLabel("VOLUMEN")
        volume_label.setObjectName("fieldLabel")
        layout.addWidget(volume_label)
        layout.addWidget(self.volume)
        actions = QHBoxLayout()
        manager = QPushButton("＋  Buscar emisoras")
        manager.clicked.connect(radio.open_manager)
        actions.addWidget(manager, 1)
        gear = QPushButton("⚙")
        gear.setToolTip("Preferencias")
        gear.setAccessibleName("Preferencias")
        gear.setFixedWidth(48)
        gear.clicked.connect(radio.open_preferences)
        actions.addWidget(gear)
        layout.addLayout(actions)
        self.stations.activated.connect(self.select)
        self.refresh()
        mask_rounded(self)

    def paintEvent(self, event):
        paint_rounded_background(
            self, self.radio.config["PanelBackground"], self.radio.config["BorderColor"])

    def refresh(self):
        self.stations.blockSignals(True)
        self.stations.clear()
        for station in self.radio.config["Stations"]:
            if station.get("Included", True):
                self.stations.addItem(station["Name"], station)
        self.stations.blockSignals(False)
        self.now.setText(self.radio.current["Name"] if self.radio.current else "Sin reproducción")
        self.play_button.setText("⏸  Pausar" if self.radio.audio.playing and not self.radio.audio.paused
                                 else "▶  Reproducir")

    def select(self, index):
        self.radio.play(self.stations.itemData(index))

    def toggle(self):
        if self.radio.audio.playing:
            self.radio.audio.toggle()
            self.refresh()
        elif self.stations.currentData():
            self.radio.play(self.stations.currentData())


class RadioApp:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setWindowIcon(QIcon(str(asset_path("radio-original.png"))))
        self.qt.setQuitOnLastWindowClosed(False)
        self.config = self.load()
        self.audio = Audio(self.config["Volume"])
        self.current = None
        self.window = Manager(self)
        self.popup = Popup(self)
        self.tray = Tray(self)
        menu = QMenu()
        menu.addAction("Buscar / configurar emisoras…", self.open_manager)
        menu.addAction("Detener", self.stop)
        menu.addSeparator()
        menu.addAction("Salir", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_popup()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self.apply_style()
        self.window.show()

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
        return base

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
            QSlider::handle:horizontal {{
                background: {text}; width: 16px; border-radius: 8px; margin: -5px 0;
            }}
        """)
        self.tray.setIcon(QIcon(str(asset_path("radio-original.png"))))

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
        self.preferences = PreferencesDialog(self)
        self.preferences.show()

    def play(self, station):
        try:
            self.audio.play(station["Url"])
            self.current = station
            self.popup.refresh()
            self.apply_style()
        except Exception as exc:
            QMessageBox.warning(self.window, "Radio++", str(exc))

    def stop(self):
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
            QMessageBox.information(self.window, "Radio++", "La emisora ya está en My Stations.")
            return
        self.config["Stations"].append(station)
        self.save()
        self.popup.refresh()

    def remove(self, station):
        self.config["Stations"] = [s for s in self.config["Stations"] if s["Url"] != station["Url"]]
        self.save()
        self.popup.refresh()

    def quit(self):
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
