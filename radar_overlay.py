"""
CS2 Sound Radar — standalone always-on-top overlay.

WASAPI loopback capture (you still hear the game). Floating radar only.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

# ── Paths / logging (before Qt) ─────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = APP_DIR / "radar_log.txt"


def log(msg: str) -> None:
    line = msg.rstrip()
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def show_error_box(title: str, text: str) -> None:
    """Fallback message box even if our UI failed mid-init."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, title, text)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
        except Exception:
            pass


# ── Dependencies ────────────────────────────────────────────────────────

try:
    import numpy as np
    import soundcard as sc
    from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal, QObject
    from PySide6.QtGui import (
        QColor,
        QFont,
        QGuiApplication,
        QPainter,
        QPen,
        QRadialGradient,
        QIcon,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QWidget,
        QSystemTrayIcon,
        QMenu,
        QStyle,
        QComboBox,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QFrame,
    )
except Exception as exc:
    log(f"IMPORT ERROR: {exc}\n{traceback.format_exc()}")
    show_error_box(
        "CS2 Sound Radar — missing packages",
        f"Could not import dependencies:\n\n{exc}\n\n"
        "Open a terminal in this folder and run:\n"
        "  python -m pip install -r requirements.txt\n\n"
        f"Details saved to:\n{LOG_PATH}",
    )
    raise SystemExit(1)


@dataclass
class StereoState:
    angle: float = 0.0
    intensity: float = 0.0
    balance: float = 0.0
    level_l: float = 0.0
    level_r: float = 0.0
    device_name: str = ""
    error: str = ""
    active: bool = False


class AudioBridge(QObject):
    updated = Signal()


class LoopbackCapture:
    def __init__(self, bridge: AudioBridge, state: StereoState):
        self.bridge = bridge
        self.state = state
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._angle = 0.0
        self._intensity = 0.0
        self._balance = 0.0
        self._l = 0.0
        self._r = 0.0
        self._mic_id: str | None = None  # force a specific loopback id

    def list_loopbacks(self) -> list[tuple[str, object]]:
        """Return (label, mic) for every loopback device."""
        out: list[tuple[str, object]] = []
        try:
            for m in sc.all_microphones(include_loopback=True):
                if getattr(m, "isloopback", False):
                    out.append((m.name, m))
        except Exception as exc:
            log(f"list_loopbacks error: {exc}")
        return out

    def set_device_id(self, mic_id: str | None) -> None:
        self._mic_id = mic_id

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="loopback", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.5)
        self._thread = None
        self.state.active = False

    def _pick_loopback(self):
        if self._mic_id:
            try:
                mic = sc.get_microphone(id=self._mic_id, include_loopback=True)
                return mic, f"{mic.name}"
            except Exception as exc:
                log(f"forced device failed: {exc}")

        speaker = sc.default_speaker()
        log(f"default speaker: {speaker.name} id={speaker.id}")

        try:
            mic = sc.get_microphone(id=speaker.id, include_loopback=True)
            return mic, f"{speaker.name} (loopback)"
        except Exception as exc:
            log(f"default loopback failed: {exc}")

        loops = self.list_loopbacks()
        if not loops:
            raise RuntimeError(
                "No loopback devices found. Windows must allow desktop audio capture."
            )

        spk = speaker.name.lower()
        for name, mic in loops:
            if spk in name.lower() or name.lower() in spk:
                return mic, name

        tokens = [t for t in spk.replace("(", " ").replace(")", " ").split() if len(t) > 3]
        best, score = loops[0], 0
        for name, mic in loops:
            s = sum(1 for t in tokens if t in name.lower())
            if s > score:
                best, score = (name, mic), s
        name, mic = best if isinstance(best, tuple) else loops[0]
        return mic, name

    def _run(self) -> None:
        try:
            mic, name = self._pick_loopback()
            log(f"capturing: {name} id={getattr(mic, 'id', '?')}")
            self.state.device_name = name
            self.state.error = ""
            self.state.active = True
            self.bridge.updated.emit()

            samplerate = 48000
            block = 1024
            with mic.recorder(samplerate=samplerate, channels=2, blocksize=block) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=block)
                    if data is None or len(data) == 0:
                        continue
                    self._process(np.asarray(data, dtype=np.float32))
        except Exception as exc:
            log(f"capture error: {exc}\n{traceback.format_exc()}")
            self.state.active = False
            self.state.error = str(exc)
            self.bridge.updated.emit()
            return

        self.state.active = False
        self.bridge.updated.emit()

    def _process(self, data: np.ndarray) -> None:
        if data.ndim == 1:
            left = right = data
        elif data.shape[1] == 1:
            left = right = data[:, 0]
        else:
            left = data[:, 0]
            right = data[:, 1]

        l_rms = float(np.sqrt(np.mean(left * left)) + 1e-12)
        r_rms = float(np.sqrt(np.mean(right * right)) + 1e-12)
        total = l_rms + r_rms
        balance = (r_rms - l_rms) / total if total > 1e-9 else 0.0
        intensity = min(1.0, math.sqrt(l_rms * l_rms + r_rms * r_rms) * 12.0)
        target_angle = balance * (math.pi / 2.0)

        a = 0.35
        self._balance += (balance - self._balance) * a
        self._intensity += (intensity - self._intensity) * a
        self._l += (l_rms - self._l) * a
        self._r += (r_rms - self._r) * a
        self._angle += (target_angle - self._angle) * 0.4

        with self._lock:
            self.state.angle = self._angle
            self.state.intensity = self._intensity
            self.state.balance = self._balance
            self.state.level_l = self._l
            self.state.level_r = self._r

        self.bridge.updated.emit()

    def snapshot(self) -> StereoState:
        with self._lock:
            return StereoState(
                angle=self.state.angle,
                intensity=self.state.intensity,
                balance=self.state.balance,
                level_l=self.state.level_l,
                level_r=self.state.level_r,
                device_name=self.state.device_name,
                error=self.state.error,
                active=self.state.active,
            )


class RadarCanvas(QWidget):
    def __init__(self, capture: LoopbackCapture):
        super().__init__()
        self.capture = capture
        self._trail: list[tuple[float, float, float]] = []
        self.setMinimumSize(200, 200)

    def paintEvent(self, _event):
        snap = self.capture.snapshot()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        size = min(w, h)
        cx, cy = w / 2, h / 2
        radius = size * 0.38

        disc = QRadialGradient(cx, cy, radius)
        disc.setColorAt(0.0, QColor(12, 28, 36, 255))
        disc.setColorAt(0.55, QColor(6, 14, 22, 255))
        disc.setColorAt(1.0, QColor(3, 8, 14, 255))
        p.setBrush(disc)
        p.setPen(QPen(QColor(61, 224, 197, 120), 2))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(radius), int(radius))

        p.setPen(QPen(QColor(90, 180, 220, 40), 1))
        for i in range(1, 5):
            r = radius * i / 4
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))
        p.drawLine(int(cx - radius), int(cy), int(cx + radius), int(cy))
        p.drawLine(int(cx), int(cy - radius), int(cx), int(cy + radius))

        p.setPen(QColor(180, 200, 220))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lr = radius * 1.12
        p.drawText(QRectF(cx - 12, cy - lr - 8, 24, 16), Qt.AlignmentFlag.AlignCenter, "F")
        p.drawText(QRectF(cx + lr - 8, cy - 8, 24, 16), Qt.AlignmentFlag.AlignCenter, "R")
        p.drawText(QRectF(cx - 12, cy + lr - 6, 24, 16), Qt.AlignmentFlag.AlignCenter, "B")
        p.drawText(QRectF(cx - lr - 12, cy - 8, 24, 16), Qt.AlignmentFlag.AlignCenter, "L")

        if snap.intensity > 0.05:
            self._trail.append((snap.angle, snap.intensity, 1.0))
            if len(self._trail) > 40:
                self._trail.pop(0)

        aged: list[tuple[float, float, float]] = []
        for ang, inten, life in self._trail:
            life *= 0.94
            if life > 0.05:
                aged.append((ang, inten, life))
                self._blip(p, cx, cy, radius, ang, inten * life * 0.5, life * 0.45, True)
        self._trail = aged

        if snap.intensity > 0.02:
            x, y = self._polar(cx, cy, radius * 0.92, snap.angle)
            p.setPen(QPen(QColor(61, 224, 197, int(50 + snap.intensity * 100)), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(int(cx), int(cy), int(x), int(y))
            self._blip(p, cx, cy, radius, snap.angle, snap.intensity, 1.0, False)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(61, 224, 197))
        p.drawEllipse(QPoint(int(cx), int(cy)), 4, 4)

        p.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        p.setPen(QColor(61, 224, 197))
        if snap.intensity < 0.03:
            text = "Silent" if snap.active else "No signal"
        else:
            deg = snap.angle * 180.0 / math.pi
            sign = "+" if deg > 0.5 else ""
            pct = int(abs(snap.balance) * 100)
            side = "Center" if pct < 8 else (f"{pct}% L" if snap.balance < 0 else f"{pct}% R")
            text = f"{sign}{deg:.0f}°  {side}"
        p.drawText(QRectF(0, cy + radius * 0.55, w, 22), Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def _polar(self, cx, cy, r, angle):
        a = angle - math.pi / 2
        return cx + math.cos(a) * r, cy + math.sin(a) * r

    def _color(self, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(int(90 + 165 * t), int(208 - 54 * t), int(255 - 181 * t))

    def _blip(self, p, cx, cy, radius, angle, intensity, alpha, trail):
        dist = radius * (0.35 + 0.55 * min(1.0, intensity * 1.1))
        x, y = self._polar(cx, cy, dist, angle)
        t = (angle / (math.pi / 2) + 1) / 2
        col = self._color(t)
        size = (5 if trail else 9) * (0.55 + intensity)
        g = QColor(col)
        g.setAlpha(int(90 * alpha * max(intensity, 0.25)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPoint(int(x), int(y)), int(size * 2.3), int(size * 2.3))
        c = QColor(col)
        c.setAlpha(int(240 * alpha))
        p.setBrush(c)
        p.drawEllipse(QPoint(int(x), int(y)), int(size), int(size))


class MeterBar(QWidget):
    def __init__(self, label: str, color: QColor):
        super().__init__()
        self.label = label
        self.color = color
        self.value = 0.0
        self.setFixedHeight(18)

    def set_value(self, v: float) -> None:
        self.value = max(0.0, min(100.0, v))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QColor(160, 175, 195))
        p.setFont(QFont("Consolas", 8))
        p.drawText(0, 0, 14, self.height(), Qt.AlignmentFlag.AlignVCenter, self.label)
        x, y, w, h = 18, 4, self.width() - 18, self.height() - 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(x, y, w, h, 4, 4)
        fill = QColor(self.color)
        fill.setAlpha(230)
        p.setBrush(fill)
        p.drawRoundedRect(x, y, int(w * self.value / 100.0), h, 4, 4)
        p.end()


class RadarOverlay(QWidget):
    def __init__(self, capture: LoopbackCapture):
        super().__init__()
        self.capture = capture
        self._drag_offset: QPoint | None = None
        self._devices: list[tuple[str, object]] = []

        # Visible on taskbar (not Tool), always on top, frameless
        self.setWindowTitle("CS2 Sound Radar")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(
            """
            QWidget#root {
                background: #0a1018;
                border: 1px solid rgba(61,224,197,0.35);
                border-radius: 14px;
            }
            QLabel { color: #9eb0c8; font-size: 11px; }
            QLabel#title { color: #e8f0ff; font-size: 13px; font-weight: 700; }
            QLabel#statusLive { color: #3de0c5; font-weight: 700; }
            QLabel#statusErr { color: #ff6b7a; font-weight: 700; }
            QComboBox {
                background: #121a26;
                color: #e8f0ff;
                border: 1px solid rgba(120,180,255,0.2);
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 24px;
            }
            QPushButton {
                background: #152032;
                color: #e8f0ff;
                border: 1px solid rgba(120,180,255,0.25);
                border-radius: 6px;
                padding: 5px 10px;
            }
            QPushButton:hover { border-color: #3de0c5; color: #3de0c5; }
            """
        )

        root = QFrame(self)
        root.setObjectName("root")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(root)

        inner = QVBoxLayout(root)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("CS2 Sound Radar")
        self.title.setObjectName("title")
        self.status = QLabel("STARTING…")
        self.status.setObjectName("statusLive")
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedWidth(32)
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.status)
        header.addWidget(self.btn_close)
        inner.addLayout(header)

        hint = QLabel("Drag header to move · always on top · pick the device CS2 plays on")
        hint.setStyleSheet("color:#6f829c; font-size:10px;")
        inner.addWidget(hint)

        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Audio:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_restart = QPushButton("Restart")
        dev_row.addWidget(self.device_combo, 1)
        dev_row.addWidget(self.btn_refresh)
        dev_row.addWidget(self.btn_restart)
        inner.addLayout(dev_row)

        self.canvas = RadarCanvas(capture)
        self.canvas.setMinimumSize(260, 260)
        inner.addWidget(self.canvas, 1)

        self.meter_l = MeterBar("L", QColor(90, 208, 255))
        self.meter_r = MeterBar("R", QColor(255, 154, 74))
        inner.addWidget(self.meter_l)
        inner.addWidget(self.meter_r)

        self.footer = QLabel("")
        self.footer.setStyleSheet("color:#7a8ea8; font-size:10px;")
        self.footer.setWordWrap(True)
        inner.addWidget(self.footer)

        self.resize(320, 420)
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

        self.btn_refresh.clicked.connect(self.populate_devices)
        self.btn_restart.clicked.connect(self.restart_capture)
        self.device_combo.activated.connect(self.on_device_chosen)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        capture.bridge.updated.connect(self.tick)

        self.populate_devices()
        QTimer.singleShot(100, self.raise_and_focus)

    def raise_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        # Windows flash to grab attention
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.alert(self, 3000)
        except Exception:
            pass

    def populate_devices(self) -> None:
        self._devices = self.capture.list_loopbacks()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if not self._devices:
            self.device_combo.addItem("(no loopback devices found)")
        else:
            for name, mic in self._devices:
                self.device_combo.addItem(name, getattr(mic, "id", None))
            # Select default speaker match
            try:
                spk = sc.default_speaker().name.lower()
                for i, (name, _) in enumerate(self._devices):
                    if spk in name.lower() or name.lower() in spk:
                        self.device_combo.setCurrentIndex(i)
                        break
            except Exception:
                pass
        self.device_combo.blockSignals(False)
        log(f"devices: {[n for n, _ in self._devices]}")

    def on_device_chosen(self, index: int) -> None:
        mic_id = self.device_combo.itemData(index)
        self.capture.set_device_id(str(mic_id) if mic_id else None)
        self.restart_capture()

    def restart_capture(self) -> None:
        idx = self.device_combo.currentIndex()
        mic_id = self.device_combo.itemData(idx)
        self.capture.set_device_id(str(mic_id) if mic_id else None)
        self.capture.start()

    def tick(self) -> None:
        snap = self.capture.snapshot()
        self.canvas.update()
        self.meter_l.set_value(snap.level_l * 800)
        self.meter_r.set_value(snap.level_r * 800)

        if snap.active:
            self.status.setText("LIVE")
            self.status.setObjectName("statusLive")
        elif snap.error:
            self.status.setText("ERROR")
            self.status.setObjectName("statusErr")
        else:
            self.status.setText("IDLE")
            self.status.setObjectName("statusErr")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        if snap.error and not snap.active:
            self.footer.setText(f"Error: {snap.error}")
        else:
            self.footer.setText(snap.device_name or "Starting capture…")

    # Drag window from header area
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 48:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_R:
            self.restart_capture()
        else:
            super().keyPressEvent(event)


def main() -> int:
    # Fresh log each launch
    try:
        LOG_PATH.write_text("=== CS2 Sound Radar start ===\n", encoding="utf-8")
    except Exception:
        pass

    log(f"python: {sys.version}")
    log(f"cwd: {os.getcwd()}")
    log(f"app dir: {APP_DIR}")

    os.chdir(APP_DIR)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("CS2 Sound Radar")
    app.setApplicationDisplayName("CS2 Sound Radar")

    bridge = AudioBridge()
    state = StereoState()
    capture = LoopbackCapture(bridge, state)

    win = RadarOverlay(capture)
    win.show()
    win.raise_()
    win.activateWindow()

    # Start capture after UI is up
    QTimer.singleShot(50, capture.start)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(app.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume), app)
        menu = QMenu()
        menu.addAction("Show", win.show)
        menu.addAction("Restart capture", win.restart_capture)
        menu.addAction("Quit", app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("CS2 Sound Radar")
        tray.show()
        tray.showMessage(
            "CS2 Sound Radar",
            "Overlay is running (always on top).",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )
        app._tray = tray  # type: ignore[attr-defined]

    log("UI shown, entering event loop")
    code = app.exec()
    capture.stop()
    log(f"exit code {code}")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        log(f"FATAL: {exc}\n{traceback.format_exc()}")
        show_error_box(
            "CS2 Sound Radar crashed",
            f"{exc}\n\nSee log:\n{LOG_PATH}",
        )
        raise SystemExit(1)
