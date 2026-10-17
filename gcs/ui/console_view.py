import html
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QCheckBox,
    QGraphicsDropShadowEffect
)
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import Qt
from gcs.logs import log_messages
from gcs.ui.theme import get_theme, FONT_FAMILY_MONO

class ConsoleView(QFrame):
    def __init__(self):
        super().__init__()
        t = get_theme()
        self.setObjectName("ConsoleViewContainer")
        self.setStyleSheet(f"""
            #ConsoleViewContainer {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 10px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Top Control Strip
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        title = QLabel("MAVLINK CONSOLE & ACK LOG")
        title.setStyleSheet(f"color: {t['primary']}; font-family: Segoe UI; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        top_bar.addWidget(title)

        # Filter Input
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter logs...")
        self.filter_input.setFixedWidth(140)
        self.filter_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['surface_elevated']}; color: {t['text']};
                border: 1px solid {t['border']}; border-radius: 4px;
                padding: 2px 6px; font-family: Segoe UI; font-size: 10px;
            }}
        """)
        self.filter_input.textChanged.connect(self._reapply_filter)
        top_bar.addWidget(self.filter_input)

        # Category buttons
        self.active_category = "ALL"
        self.cat_all = QPushButton("ALL")
        self.cat_err = QPushButton("ERRORS")
        self.cat_ack = QPushButton("ACKS")

        for btn, cat in [(self.cat_all, "ALL"), (self.cat_err, "ERRORS"), (self.cat_ack, "ACKS")]:
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._btn_style(cat == "ALL"))
            btn.clicked.connect(lambda checked, c=cat: self._set_category(c))
            top_bar.addWidget(btn)

        top_bar.addStretch(1)

        # Auto-scroll Checkbox
        self.autoscroll_cb = QCheckBox("Auto-scroll")
        self.autoscroll_cb.setChecked(True)
        self.autoscroll_cb.setStyleSheet(f"""
            QCheckBox {{
                color: {t['text_muted']}; font-family: Segoe UI; font-size: 10px; border: none; background: transparent;
            }}
        """)
        top_bar.addWidget(self.autoscroll_cb)

        # Clear Button
        clear_btn = QPushButton("CLEAR")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {t['text_muted']};
                border: 1px solid {t['border']}; border-radius: 4px;
                padding: 2px 8px; font-family: Segoe UI; font-size: 10px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {t['danger_subtle']}; color: {t['danger']}; border-color: {t['danger']}; }}
        """)
        clear_btn.clicked.connect(self.clear_logs)
        top_bar.addWidget(clear_btn)

        layout.addLayout(top_bar)

        # Log Text Box
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont(FONT_FAMILY_MONO, 9))
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {t['surface_elevated']}; color: {t['text']};
                border: 1px solid {t['border']}; border-radius: 6px; padding: 4px 6px;
                font-family: Segoe UI;
            }}
        """)
        layout.addWidget(self.text_edit)

        self._shown_count = 0
        self._all_entries = [] # List of tuples: (raw_str, formatted_html, category)

    def _btn_style(self, active):
        t = get_theme()
        if active:
            return f"""
                QPushButton {{
                    background-color: {t['primary']}; color: {t['text_inverse']};
                    border: 1px solid {t['primary']}; border-radius: 4px;
                    padding: 2px 8px; font-family: Segoe UI; font-size: 10px; font-weight: bold;
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background-color: transparent; color: {t['text_muted']};
                    border: 1px solid {t['border']}; border-radius: 4px;
                    padding: 2px 8px; font-family: Segoe UI; font-size: 10px;
                }}
                QPushButton:hover {{ background-color: {t['primary_subtle']}; color: {t['text']}; }}
            """

    def _set_category(self, cat):
        self.active_category = cat
        self.cat_all.setStyleSheet(self._btn_style(cat == "ALL"))
        self.cat_err.setStyleSheet(self._btn_style(cat == "ERRORS"))
        self.cat_ack.setStyleSheet(self._btn_style(cat == "ACKS"))
        self._reapply_filter()

    def _format_entry(self, raw_msg):
        t = get_theme()
        escaped = html.escape(raw_msg)
        up = raw_msg.upper()
        
        category = "GENERAL"
        color = t['text_secondary']

        if "FAIL" in up or "DENIED" in up or "ERROR" in up or "REJECTED" in up:
            color = t['danger']
            category = "ERRORS"
        elif "ACCEPTED" in up or "SUCCESS" in up:
            color = t['success']
            category = "ACKS"
        elif "ACK:" in up:
            color = t['primary']
            category = "ACKS"
        elif "FCU:" in up:
            color = t['info']
            category = "FCU"
        elif "ARM" in up or "DISARM" in up or "TAKEOFF" in up or "HOLD" in up:
            color = t['warning']
            category = "COMMANDS"

        styled_html = f"<div style='color: {color}; margin-bottom: 2px;'>{escaped}</div>"
        return styled_html, category

    def refresh_logs(self):
        # Process any new messages from global buffer
        while self._shown_count < len(log_messages):
            raw = log_messages[self._shown_count]
            formatted, cat = self._format_entry(raw)
            self._all_entries.append((raw, formatted, cat))
            
            # Check if it passes current filter
            if self._matches_filter(raw, cat):
                self.text_edit.append(formatted)
                if self.autoscroll_cb.isChecked():
                    sb = self.text_edit.verticalScrollBar()
                    sb.setValue(sb.maximum())
            self._shown_count += 1

    def _matches_filter(self, raw_str, cat):
        # Category match
        if self.active_category == "ERRORS" and cat != "ERRORS":
            return False
        if self.active_category == "ACKS" and cat != "ACKS":
            return False
            
        # Keyword match
        query = self.filter_input.text().strip().lower()
        if query and query not in raw_str.lower():
            return False
            
        return True

    def _reapply_filter(self):
        self.text_edit.clear()
        for raw, formatted, cat in self._all_entries:
            if self._matches_filter(raw, cat):
                self.text_edit.append(formatted)
        if self.autoscroll_cb.isChecked():
            sb = self.text_edit.verticalScrollBar()
            sb.setValue(sb.maximum())

    def clear_logs(self):
        self.text_edit.clear()
        self._all_entries.clear()
