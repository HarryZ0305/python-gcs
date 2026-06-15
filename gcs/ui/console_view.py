from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtGui import QFont
from gcs.logs import log_messages

class ConsoleView(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet("""
            background-color: #f8fafc; color: #0f172a;
            border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px;
        """)
        self._shown = 0  # how many messages already displayed

    def refresh_logs(self):
        # append only new messages since last refresh
        while self._shown < len(log_messages):
            self.append(log_messages[self._shown])
            self._shown += 1