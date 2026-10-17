"""
PythonGCS Camera & Video Streaming Pipeline
Provides off-thread video capture via OpenCV (RTSP/UDP/HTTP/USB/Test Stream),
frame freshness tracking, honest stream states, and configurable OSD HUD overlays.
"""

import time
import math
import threading
from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QThread
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QImage, QPixmap
from gcs.ui.theme import get_theme, FONT_FAMILY_PRIMARY, FONT_FAMILY_MONO
from gcs.telemetry import telemetry_data

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


class VideoCaptureWorker(QThread):
    """
    Background worker thread for capturing and decoding video frames.
    Keeps all network I/O, RTSP handshake, and OpenCV decoding completely off the Qt main thread.
    """
    frame_ready = pyqtSignal(QImage)
    state_changed = pyqtSignal(str) # CONNECTING, LIVE, FAILED, DISCONNECTED

    def __init__(self, source_url: str = ""):
        super().__init__()
        self.source_url = source_url
        self.running = True
        self._stop_signal = threading.Event()
        self._is_test_stream = (source_url.lower() == "test" or source_url == "")

    def set_source(self, url: str):
        self.source_url = url
        self._is_test_stream = (url.lower() == "test" or url == "")

    def run(self):
        if self._is_test_stream:
            self.state_changed.emit("TEST_PATTERN")
            self._run_test_pattern()
            return

        if not CV2_AVAILABLE:
            self.state_changed.emit("FAILED: OpenCV not installed")
            return

        while self.running:
            self.state_changed.emit("CONNECTING")
            cap = None
            try:
                # Open source (integer index for webcam or string for RTSP/UDP/HTTP)
                if self.source_url.isdigit():
                    cap = cv2.VideoCapture(int(self.source_url))
                else:
                    cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG, [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1000])

                if not cap.isOpened():
                    self.state_changed.emit("FAILED")
                    self._stop_signal.wait(2.0)
                    continue

                self.state_changed.emit("LIVE")
                consecutive_failures = 0

                while self.running and cap.isOpened():
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        consecutive_failures += 1
                        if consecutive_failures > 15:
                            self.state_changed.emit("FAILED")
                            break
                        self._stop_signal.wait(0.05)
                        continue

                    consecutive_failures = 0
                    # Convert BGR to RGB
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w
                    qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                    self.frame_ready.emit(qimg)
                    self._stop_signal.wait(0.033) # ~30 FPS

            except Exception as e:
                self.state_changed.emit(f"FAILED: {e}")
                self._stop_signal.wait(2.0)
            finally:
                if cap is not None:
                    cap.release()

    def _run_test_pattern(self):
        """Generates clean synthetic SMPTE test pattern / telemetry simulation."""
        w, h = 640, 360
        img = QImage(w, h, QImage.Format.Format_RGB888)
        colors = [
            QColor(192, 192, 192), # Gray
            QColor(192, 192, 0),   # Yellow
            QColor(0, 192, 192),   # Cyan
            QColor(0, 192, 0),     # Green
            QColor(192, 0, 192),   # Magenta
            QColor(192, 0, 0),     # Red
            QColor(0, 0, 192),     # Blue
        ]
        bar_w = w // len(colors)
        p = QPainter(img)
        for i, c in enumerate(colors):
            p.fillRect(i * bar_w, 0, bar_w, int(h * 0.75), c)
        p.fillRect(0, int(h * 0.75), w, int(h * 0.25), QColor(20, 25, 35))
        p.end()

        while self.running and self._is_test_stream:
            self.frame_ready.emit(img)
            self._stop_signal.wait(0.1) # 10 Hz test pattern

    def stop(self):
        self.running = False
        self._stop_signal.set()


class CameraView(QWidget):
    """
    High-fidelity Video Display with honest state reporting and OSD HUD overlay.
    States:
    - DISCONNECTED: No camera source selected
    - CONNECTING: Awaiting stream handshake
    - LIVE: Real-time frames streaming
    - STALE: No frame received for > 2.0s
    - FAILED: Connection error / broken pipe
    - TEST_PATTERN: Synthetic test pattern (honestly labeled)
    """
    def __init__(self, title="CAMERA HUD", parent=None):
        super().__init__(parent)
        self.title = title
        self.setMinimumSize(320, 220)
        
        self.current_frame: Optional[QImage] = None
        self.last_frame_time = 0.0
        self.stream_state = "DISCONNECTED"
        self.show_osd = True

        self.worker: Optional[VideoCaptureWorker] = None
        self._workers = []
        self._source_generation = 0

        # Watchdog timer to detect frozen/stale stream (5 Hz)
        self.watchdog = QTimer(self)
        self.watchdog.timeout.connect(self._check_freshness)
        self.watchdog.start(200)

    def set_stream_source(self, source_url: str):
        """Starts or changes the video stream source."""
        self._source_generation += 1
        generation = self._source_generation
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.current_frame = None
        self.last_frame_time = 0.0

        if not source_url:
            self.stream_state = "DISCONNECTED"
            self.current_frame = None
            self.update()
            return

        self.worker = VideoCaptureWorker(source_url)
        self._workers.append(self.worker)
        self.stream_state = 'CONNECTING'
        self.worker.frame_ready.connect(lambda frame, gen=generation: self._accept_frame(gen, frame))
        self.worker.state_changed.connect(lambda state, gen=generation: self._accept_state(gen, state))
        worker = self.worker
        worker.finished.connect(lambda worker=worker: self._worker_finished(worker))
        self.worker.start()

    def _worker_finished(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()

    def _accept_frame(self, generation, frame):
        if generation == self._source_generation:
            self.on_frame_received(frame)

    def _accept_state(self, generation, state):
        if generation == self._source_generation:
            self.on_state_changed(state)

    def on_frame_received(self, image: QImage):
        self.current_frame = image
        self.last_frame_time = time.monotonic()
        if self.stream_state not in ("TEST_PATTERN",):
            self.stream_state = "LIVE"
        self.update()

    def update_frame(self, pixmap_or_img):
        """External frame injection compatibility method."""
        if isinstance(pixmap_or_img, QPixmap):
            self.current_frame = pixmap_or_img.toImage()
        elif isinstance(pixmap_or_img, QImage):
            self.current_frame = pixmap_or_img
        self.last_frame_time = time.monotonic()
        self.stream_state = "LIVE"
        self.update()

    def on_state_changed(self, state: str):
        self.stream_state = state
        self.update()

    def _check_freshness(self):
        if self.stream_state == "LIVE" and (time.monotonic() - self.last_frame_time > 2.0):
            self.stream_state = "STALE"
            self.update()

    def toggle_osd(self):
        self.show_osd = not self.show_osd
        self.update()

    def paintEvent(self, event):
        t = get_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()

        # 1. Draw Frame or State Placeholder
        if self.current_frame and not self.current_frame.isNull() and self.stream_state in ("LIVE", "STALE", "TEST_PATTERN"):
            # Scaled aspect ratio
            scaled = self.current_frame.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            x_off = (w - scaled.width()) // 2
            y_off = (h - scaled.height()) // 2
            # Dark letterbox background
            p.fillRect(self.rect(), QColor(10, 15, 25))
            p.drawImage(x_off, y_off, scaled)
        else:
            # Standby / Disconnected Background
            p.fillRect(self.rect(), QColor(15, 23, 42))
            p.setPen(QPen(QColor(t['border']), 1.0))
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))

            # Centered Status Text
            p.setFont(QFont(FONT_FAMILY_PRIMARY, 11, QFont.Weight.Bold))
            p.setPen(QPen(QColor('#94a3b8'), 1.0))
            msg = {
                "DISCONNECTED": "NO VIDEO STREAM CONFIGURED\n(Select Source in Settings)",
                "CONNECTING": "CONNECTING TO VIDEO STREAM...",
                "FAILED": "VIDEO STREAM CONNECTION FAILED",
                "STALE": "VIDEO SIGNAL LOST / FROZEN"
            }.get(self.stream_state, f"VIDEO: {self.stream_state}")
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, msg)

        # 2. Status Badge (Top-Left)
        badge_color = {
            "LIVE": QColor(16, 185, 129, 220),       # Green
            "TEST_PATTERN": QColor(2, 132, 199, 220), # Blue
            "CONNECTING": QColor(245, 158, 11, 220), # Amber
            "STALE": QColor(239, 68, 68, 220),       # Red
            "FAILED": QColor(239, 68, 68, 220),      # Red
            "DISCONNECTED": QColor(100, 116, 139, 220)# Gray
        }.get(self.stream_state, QColor(100, 116, 139, 220))

        p.fillRect(QRectF(10, 10, 120, 22), badge_color)
        p.setPen(QPen(QColor('#ffffff'), 1.0))
        p.setFont(QFont(FONT_FAMILY_PRIMARY, 9, QFont.Weight.Bold))
        label_text = f"CAM: {self.stream_state}"
        p.drawText(QRectF(10, 10, 120, 22), Qt.AlignmentFlag.AlignCenter, label_text)

        # 3. OSD Telemetry Overlay
        if self.show_osd and self.stream_state in ("LIVE", "TEST_PATTERN", "STALE"):
            cx, cy = w / 2.0, h / 2.0
            p.setPen(QPen(QColor('#38bdf8'), 1.5))
            
            # Crosshair
            p.drawLine(QPointF(cx - 15, cy), QPointF(cx - 5, cy))
            p.drawLine(QPointF(cx + 5, cy), QPointF(cx + 15, cy))
            p.drawLine(QPointF(cx, cy - 15), QPointF(cx, cy - 5))
            p.drawLine(QPointF(cx, cy + 5), QPointF(cx, cy + 15))
            p.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))

            # Bottom OSD Ribbon (Alt, Speed, Batt, Mode)
            ribbon_h = 24.0
            p.fillRect(QRectF(0, h - ribbon_h, w, ribbon_h), QColor(0, 0, 0, 180))
            p.setFont(QFont(FONT_FAMILY_MONO, 9, QFont.Weight.Bold))
            p.setPen(QPen(QColor('#f8fafc'), 1.0))

            alt = telemetry_data.get('alt', 0.0)
            spd = telemetry_data.get('groundspeed', 0.0)
            batt = telemetry_data.get('battery', -1)
            mode = telemetry_data.get('mode', 'UNKNOWN')
            batt_str = f"{batt}%" if batt >= 0 else "---%"

    def stop_stream(self):
        self._source_generation += 1
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.current_frame = None
        self.stream_state = "DISCONNECTED"
        self.update()

    def shutdown(self):
        self.stop_stream()
        deadline = time.monotonic() + 4.0
        for worker in list(self._workers):
            worker.stop()
            worker.wait(max(0, int((deadline - time.monotonic()) * 1000)))

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
