import math
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QImage
from gcs.telemetry import telemetry_data

class CameraView(QWidget):
    def __init__(self, title="CAMERA HUD"):
        super().__init__()
        self.title = title
        self.setMinimumSize(250, 180)
        
        # Pre-generate dark aesthetic static noise frames
        self.static_images = []
        self._generate_static()
        self.static_idx = 0
        
        # Blinking indicators
        self.blink_state = True
        
        # Frame timer for static noise animation and blink states
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(100) # 10 Hz refresh for overlay animation
        
        self.live_pixmap = None

    def _generate_static(self):
        # Generate 6 frames of dark noise to cycle through
        w, h = 160, 120
        for _ in range(6):
            img = QImage(w, h, QImage.Format.Format_Grayscale8)
            for y in range(h):
                for x in range(w):
                    # Dark noise palette (between 12 and 36)
                    val = random.randint(12, 36)
                    img.setPixel(x, y, val)
            self.static_images.append(img)

    def on_tick(self):
        self.static_idx = (self.static_idx + 1) % len(self.static_images)
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
                # Scale static image to fit widget
                painter.drawImage(self.rect(), self.static_images[self.static_idx])
            else:
                painter.fillRect(self.rect(), QColor("#060d15"))
        
        # 2. Extract Telemetry Variables
        roll = telemetry_data.get('roll', 0.0)      # radians
        pitch = telemetry_data.get('pitch', 0.0)    # radians
        alt = telemetry_data.get('alt', 0.0)        # meters
        speed = telemetry_data.get('groundspeed', 0.0) # m/s
        battery = telemetry_data.get('battery', 0)
        mode = telemetry_data.get('mode', 'DISCONNECTED')
        armed = telemetry_data.get('armed', False)
        sats = telemetry_data.get('satellites', 0)
        
        # 3. Setup HUD Colors & Styles (Cyberpunk HUD Green #00ff66 or Cyan #00e5ff)
        hud_color = QColor(0, 229, 255) # Cyan default
        hud_pen = QPen(hud_color, 1.5, Qt.PenStyle.SolidLine)
        painter.setPen(hud_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        
        cx, cy = w / 2, h / 2
        
        # Draw HUD boundary frame
        border_pen = QPen(QColor(42, 74, 106, 150), 1, Qt.PenStyle.SolidLine)
        painter.setPen(border_pen)
        painter.drawRect(0, 0, w - 1, h - 1)
        
        painter.setPen(hud_pen)
        
        # 4. Draw Center Reticle (Crosshair)
        painter.drawEllipse(int(cx - 6), int(cy - 6), 12, 12)
        painter.drawLine(int(cx - 15), int(cy), int(cx - 6), int(cy))
        painter.drawLine(int(cx + 6), int(cy), int(cx + 15), int(cy))
        painter.drawLine(int(cx), int(cy - 15), int(cx), int(cy - 6))
        
        # 5. Draw Pitch Ladder & Roll Pointer (Rotated and Translated)
        painter.save()
        painter.translate(cx, cy)
        # Pitch scales: 1 degree pitch = 2.5 pixels offset
        pitch_deg = math.degrees(pitch)
        roll_deg = math.degrees(roll)
        
        painter.rotate(-roll_deg)
        dy = pitch_deg * 2.5
        painter.translate(0, dy)
        
        # Draw horizon line
        painter.drawLine(-45, 0, -15, 0)
        painter.drawLine(15, 0, 45, 0)
        
        # Draw +10 and -10 pitch ladder ticks
        for p in [-20, -10, 10, 20]:
            py = -p * 2.5
            # Draw ladder step
            painter.drawLine(-30, int(py), -10, int(py))
            painter.drawLine(10, int(py), 30, int(py))
            # Draw vertical tick indicators
            painter.drawLine(-30, int(py), -30, int(py + (5 if p > 0 else -5)))
            painter.drawLine(30, int(py), 30, int(py + (5 if p > 0 else -5)))
            # Label
            painter.drawText(-45, int(py + 4), f"{abs(p)}")
            painter.drawText(35, int(py + 4), f"{abs(p)}")
            
        painter.restore()
        
        # 6. Draw Pitch/Roll pointers on absolute overlay
        # Pitch/roll indicator arc at top center
        painter.drawArc(int(cx - 50), 20, 100, 40, 30 * 16, 120 * 16)
        # Draw current roll indicator tick
        rad_roll = math.radians(roll_deg)
        tx = cx + 50 * math.sin(rad_roll)
        ty = 40 - 20 * math.cos(rad_roll)
        painter.drawLine(int(cx), 40, int(tx), int(ty))
        
        # 7. Draw Airspeed Tape (Left Side)
        tape_w = 40
        tape_h = h - 60
        painter.fillRect(QRect(10, 30, tape_w, tape_h), QColor(13, 27, 42, 180))
        painter.drawRect(10, 30, tape_w, tape_h)
        # Speed ticks
        start_spd = max(0, int(speed - 5))
        for sp in range(start_spd, int(speed + 6)):
            sy = cy + (speed - sp) * 10
            if 30 <= sy <= h - 30:
                painter.drawLine(10, int(sy), 18, int(sy))
                if sp % 2 == 0:
                    painter.drawText(22, int(sy + 4), f"{sp}")
        # Active speed readout box
        painter.fillRect(QRect(5, int(cy - 10), 38, 20), QColor(0, 229, 255))
        painter.setPen(QColor("#0d1b2a"))
        painter.drawText(8, int(cy + 4), f"{speed:.1f}")
        
        # 8. Draw Altitude Tape (Right Side)
        painter.setPen(hud_pen)
        painter.fillRect(QRect(w - 50, 30, tape_w, tape_h), QColor(13, 27, 42, 180))
        painter.drawRect(w - 50, 30, tape_w, tape_h)
        # Alt ticks
        start_alt = max(0, int(alt - 10))
        for al in range(start_alt, int(alt + 11), 2):
            ay = cy + (alt - al) * 4
            if 30 <= ay <= h - 30:
                painter.drawLine(w - 18, int(ay), w - 10, int(ay))
                if al % 5 == 0:
                    painter.drawText(w - 48, int(ay + 4), f"{al}")
        # Active alt readout box
        painter.fillRect(QRect(w - 43, int(cy - 10), 38, 20), QColor(0, 229, 255))
        painter.setPen(QColor("#0d1b2a"))
        painter.drawText(w - 40, int(cy + 4), f"{alt:.1f}")
        
        # 9. Top Info Overlay (Telemetry HUD Metadata)
        painter.setPen(hud_pen)
        painter.drawText(12, 20, self.title)
        
        # Status right align info
        status_info = f"MODE: {mode}  SAT: {sats}"
        painter.drawText(w - 150, 20, status_info)
        
        # 10. Draw Bottom Blinking Status / Arm Status
        state_color = QColor(255, 68, 68) if not armed else QColor(68, 255, 136) # Red if disarmed, green if armed
        painter.setPen(QPen(state_color, 1.5))
        
        if armed:
            if self.blink_state:
                painter.drawText(int(cx - 25), h - 15, "ARMED")
        else:
            painter.drawText(int(cx - 32), h - 15, "DISARMED")
            
        # Draw "NO SIGNAL" blinking text if live stream is missing
        if not self.live_pixmap:
            painter.setPen(QPen(QColor(255, 68, 68, 150), 1.5))
            if self.blink_state:
                painter.drawText(int(cx - 40), int(cy - 30), "\u25cb NO SIGNAL")