from PyQt6.QtWidgets import QTextEdit, QGraphicsDropShadowEffect
from PyQt6.QtGui import QFont, QColor
from gcs.logs import log_messages

class ConsoleView(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(QFont("Google Sans Code", 9))
        self.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff; color: #0f172a;
                border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px;
            }
        """)
        
        # Soft shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        self._shown = 0  # how many messages already displayed

    def refresh_logs(self):
        # append only new messages since last refresh
        while self._shown < len(log_messages):
            self.append(log_messages[self._shown])
            self._shown += 1