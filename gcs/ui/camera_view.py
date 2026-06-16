import math
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QImage, QPolygon
from gcs.telemetry import telemetry_data

class CameraView(QWidget):
    def __init__(self, title="CAMERA HUD"):
        super().__init__()
        self.title = title
        self.setMinimumSize(400, 300)
        
        # Pre-generate dark aesthetic static noise frames
        self.static_images = []
        self._generate_static()
        self.static_idx = 0
        
        # Blinking indicators
        self.blink_state = True
        
        # Frame timer for static noise animation and blink states
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(50) # 20 Hz refresh for smoother static and overlays
        
        self.live_pixmap = None

    def _generate_static(self):
        # Generate 10 frames of dark cyberpunk noise
        w, h = 160, 120
        for _ in range(10):
            img = QImage(w, h, QImage.Format.Format_Grayscale8)
            for y in range(h):
                for x in range(w):
                    # Dark noise palette (between 5 and 25), with occasional bright scanline dots
                    val = random.randint(5, 25)
                    if random.random() < 0.005:
                        val = random.randint(100, 200)
                    img.setPixel(x, y, val)
            self.static_images.append(img)

    def on_tick(self):
        self.static_idx = (self.static_idx + 1) % len(self.static_images)
        # Slower blink state
        if self.static_idx % 10 == 0:
            self.blink_state = not self.blink_state
        self.update()

    def update_frame(self, pixmap):
        self.live_pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        # 1. Draw Background (Live Frame or Static)
        if self.live_pixmap:
            painter.drawPixmap(self.rect(), self.live_pixmap)
        else:
            if self.static_images:
                painter.drawImage(self.rect(), self.static_images[self.static_idx])
            else:
                painter.fillRect(self.rect(), QColor("#ffffff"))
        
        # 2. Extract Telemetry Variables
        roll = telemetry_data.get('roll', 0.0)      # radians
        pitch = telemetry_data.get('pitch', 0.0)    # radians
        yaw = telemetry_data.get('yaw', 0.0)        # radians
        alt = telemetry_data.get('alt', 0.0)        # meters
        speed = telemetry_data.get('groundspeed', 0.0) # m/s
        mode = telemetry_data.get('mode', 'DISCONNECTED')
        armed = telemetry_data.get('armed', False)
        sats = telemetry_data.get('satellites', 0)
        
        # 3. Setup HUD Colors & Styles
        hud_color = QColor("#0b57d0") # Primary
        hud_pen = QPen(hud_color, 1.5, Qt.PenStyle.SolidLine)
        painter.setPen(hud_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        
        cx, cy = w / 2, h / 2
        
        # 4. Draw Center Reticle (Crosshair)
        painter.drawEllipse(int(cx - 8), int(cy - 8), 16, 16)
        painter.drawLine(int(cx - 20), int(cy), int(cx - 8), int(cy))
        painter.drawLine(int(cx + 8), int(cy), int(cx + 20), int(cy))
        painter.drawLine(int(cx), int(cy - 20), int(cx), int(cy - 8))
        
        # 5. Draw Pitch Ladder & Roll Pointer
        painter.save()
        painter.translate(cx, cy)
        pitch_deg = math.degrees(pitch)
        roll_deg = math.degrees(roll)
        
        painter.rotate(-roll_deg)
        dy = pitch_deg * 3.0 # pixels per degree
        painter.translate(0, dy)
        
        # Horizon line
        painter.drawLine(-60, 0, -20, 0)
        painter.drawLine(20, 0, 60, 0)
        
        # Pitch ladder ticks
        for p in [-30, -20, -10, 10, 20, 30]:
            py = -p * 3.0
            painter.drawLine(-40, int(py), -20, int(py))
            painter.drawLine(20, int(py), 40, int(py))
            painter.drawLine(-40, int(py), -40, int(py + (5 if p > 0 else -5)))
            painter.drawLine(40, int(py), 40, int(py + (5 if p > 0 else -5)))
            painter.drawText(-65, int(py + 4), f"{abs(p)}")
            painter.drawText(45, int(py + 4), f"{abs(p)}")
            
        painter.restore()
        
        # 6. Draw Compass Heading Tape (Top Center)
        yaw_deg = math.degrees(yaw) % 360
        painter.setPen(hud_pen)
        
        bg_color = QColor("#f5f7fa")
        bg_color.setAlpha(180)
        painter.fillRect(QRect(int(cx - 100), 10, 200, 30), bg_color)
        painter.drawRect(int(cx - 100), 10, 200, 30)
        
        # Draw heading triangle
        painter.setBrush(hud_color)
        painter.drawPolygon(QPolygon([
            QPoint(int(cx), 40), QPoint(int(cx - 5), 45), QPoint(int(cx + 5), 45)
        ]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        # Ticks for compass
        for h_deg in range(int(yaw_deg) - 45, int(yaw_deg) + 45):
            if h_deg % 5 == 0:
                hx = cx + (h_deg - yaw_deg) * 2.2 # 2.2 pixels per degree
                if cx - 95 <= hx <= cx + 95:
                    is_major = (h_deg % 15 == 0)
                    painter.drawLine(int(hx), 40, int(hx), 40 - (10 if is_major else 5))
                    if is_major:
                        lbl = str(h_deg % 360)
                        if h_deg % 360 == 0: lbl = "N"
                        elif h_deg % 360 == 90: lbl = "E"
                        elif h_deg % 360 == 180: lbl = "S"
                        elif h_deg % 360 == 270: lbl = "W"
                        painter.drawText(int(hx - 10), 25, 20, 15, Qt.AlignmentFlag.AlignCenter, lbl)
                        
        # 7. Roll and Pitch Exact Readouts
        painter.setPen(hud_pen)
        painter.drawText(int(cx - 50), int(h - 40), f"R: {roll_deg:+.1f}°")
        painter.drawText(int(cx + 10), int(h - 40), f"P: {pitch_deg:+.1f}°")

        # 8. Draw Airspeed Tape (Left Side)
        tape_w = 45
        tape_h = h - 100
        painter.fillRect(QRect(10, 50, tape_w, int(tape_h)), bg_color)
        painter.drawRect(10, 50, tape_w, int(tape_h))
        # Speed ticks
        start_spd = max(0, int(speed - 10))
        for sp in range(start_spd, int(speed + 11)):
            sy = cy + (speed - sp) * 8
            if 50 <= sy <= h - 50:
                painter.drawLine(10, int(sy), 18, int(sy))
                if sp % 2 == 0:
                    painter.drawText(22, int(sy + 4), f"{sp}")
        # Active speed readout box
        painter.fillRect(QRect(5, int(cy - 12), 43, 24), hud_color)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(8, int(cy + 5), f"{speed:.1f}")
        
        # 9. Draw Altitude Tape (Right Side)
        painter.setPen(hud_pen)
        painter.fillRect(QRect(w - 55, 50, tape_w, int(tape_h)), bg_color)
        painter.drawRect(w - 55, 50, tape_w, int(tape_h))
        # Alt ticks
        start_alt = max(0, int(alt - 20))
        for al in range(start_alt, int(alt + 21), 2):
            ay = cy + (alt - al) * 4
            if 50 <= ay <= h - 50:
                painter.drawLine(w - 18, int(ay), w - 10, int(ay))
                if al % 10 == 0:
                    painter.drawText(w - 50, int(ay + 4), f"{al}")
        # Active alt readout box
        painter.fillRect(QRect(w - 48, int(cy - 12), 43, 24), hud_color)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(w - 45, int(cy + 5), f"{alt:.1f}")
        
        # 10. Top Info Overlay (Telemetry HUD Metadata)
        painter.setPen(hud_pen)
        painter.drawText(15, 25, self.title)
        
        status_info = f"MODE: {mode}  SAT: {sats}"
        painter.drawText(w - 180, 25, status_info)
        
        # 11. Draw Bottom Blinking Status / Arm Status
        state_color = QColor("#d93025") if not armed else QColor("#0f9d58") # Red if disarmed, Green if armed
        painter.setPen(QPen(state_color, 1.5))
        
        if armed:
            if self.blink_state:
                painter.drawText(int(cx - 25), h - 15, "ARMED")
        else:
            painter.drawText(int(cx - 32), h - 15, "DISARMED")
            
        # Draw "NO SIGNAL" blinking text if live stream is missing
        if not self.live_pixmap:
            painter.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
            # Black border for text
            painter.setPen(QPen(QColor(0, 0, 0), 2))
            if self.blink_state:
                painter.drawText(int(cx - 65), int(cy - 40), "NO SIGNAL")
            painter.setPen(QPen(QColor(217, 48, 37, 220), 1.5))
            if self.blink_state:
                painter.drawText(int(cx - 65), int(cy - 40), "NO SIGNAL")