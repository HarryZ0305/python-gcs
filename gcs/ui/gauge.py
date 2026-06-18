from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from PyQt6.QtCore import Qt, QRectF, QSize

class ArcGauge(QWidget):
    """
    A custom radial gauge widget shaped like a 270-degree arc (open at the bottom).
    Fills clockwise from bottom-left (225 degrees) to bottom-right (-45 degrees).
    """
    def __init__(self, label, unit, min_val, max_val, accent_color, parent=None):
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self.min_val = min_val
        self.max_val = max_val
        self.accent_color = QColor(accent_color)
        self.value = 0.0
        
        # Color palette matching the dark theme
        self.track_color = QColor('#1e293b')  # THEME['panel_border'] fallback
        self.text_color = QColor('#f8fafc')   # THEME['dark_text'] fallback
        self.muted_color = QColor('#64748b')  # THEME['muted'] fallback
        
        self.setMinimumSize(100, 110)

    def sizeHint(self):
        return QSize(120, 130)

    def set_value(self, v):
        self.value = v
        self.update()

    def set_accent(self, color):
        self.accent_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # 1. Calculate bounding box for the arc
        label_height = 18
        side = min(width, height - label_height - 6)
        side = max(side, 30)

        # Gauge thickness is proportional to gauge size
        pen_width = max(5, int(side / 11))
        padding = pen_width / 2 + 3
        arc_size = side - 2 * padding

        arc_rect = QRectF((width - arc_size) / 2, padding + 2, arc_size, arc_size)

        # 2. Draw background track (270 degrees, clockwise, open at the bottom)
        # 0 deg is 3 o'clock. 225 deg is bottom-left (South-West).
        # Span angle is -270 degrees (clockwise to South-East / -45 deg).
        track_pen = QPen(self.track_color, pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(arc_rect, 225 * 16, -270 * 16)

        # 3. Draw dynamic value arc (clamped to range [min_val, max_val])
        clamped_val = max(self.min_val, min(self.max_val, self.value))
        val_range = self.max_val - self.min_val
        proportion = (clamped_val - self.min_val) / val_range if val_range > 0 else 0.0

        if proportion > 0.0:
            value_pen = QPen(self.accent_color, pen_width)
            value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(value_pen)
            painter.drawArc(arc_rect, 225 * 16, int(-proportion * 270 * 16))

        # 4. Draw center value text (Courier New, bold)
        if isinstance(self.value, int):
            val_str = str(self.value)
        elif isinstance(self.value, float):
            # If the float is effectively an integer or represents percentages/satellites, show as int
            if self.value.is_integer() or self.unit in ["%", "sats"]:
                val_str = str(int(self.value))
            else:
                val_str = f"{self.value:.1f}"
        else:
            val_str = str(self.value)

        center_x = width / 2
        center_y = padding + 2 + arc_size / 2

        # Value text placement inside the arc
        value_font_size = max(9, int(arc_size / 5))
        value_font = QFont("Google Sans Code", value_font_size, QFont.Weight.Bold)
        painter.setFont(value_font)
        painter.setPen(self.text_color)
        value_rect = QRectF(center_x - arc_size / 2, center_y - arc_size / 3.5, arc_size, arc_size / 2.2)
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, val_str)

        # 5. Draw unit text below the value text
        unit_font_size = max(7, int(arc_size / 8.5))
        unit_font = QFont("Google Sans Code", unit_font_size, QFont.Weight.Bold)
        painter.setFont(unit_font)
        painter.setPen(self.muted_color)
        unit_rect = QRectF(center_x - arc_size / 2, center_y + arc_size / 10, arc_size, arc_size / 3.5)
        painter.drawText(unit_rect, Qt.AlignmentFlag.AlignCenter, self.unit)

        # 6. Draw label below the entire gauge
        label_font = QFont("Google Sans Code", 9, QFont.Weight.Bold)
        painter.setFont(label_font)
        painter.setPen(self.text_color)
        label_rect = QRectF(0, height - label_height, width, label_height)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.label)
