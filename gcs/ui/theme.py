"""
PythonGCS Design System & Theme Engine
Provides cohesive design tokens, typography scales, light/dark themes,
and component style generators for field-grade ground control station operation.
"""

from typing import Dict, Any

# Primary Font Stacks
# QFont expects a family name, not a CSS font stack. Passing the stack as one
# family can select a symbol font and render every label as missing glyphs.
FONT_FAMILY_PRIMARY = "Segoe UI"
FONT_FAMILY_MONO = "Consolas"

THEME_LIGHT: Dict[str, str] = {
    'name': 'light',
    'bg': '#eeede7',              # Warm stone canvas
    'surface': '#faf9f5',         # Ivory cards
    'surface_elevated': '#f3f2ec',
    'surface_sunken': '#e5e5dc',
    'border': '#dcded3',
    'border_strong': '#a1a798',
    'text': '#343d35',
    'text_secondary': '#596153',
    'text_muted': '#707769',
    'text_inverse': '#faf9f5',
    
    # Semantic Colors
    'primary': '#536b57',
    'primary_hover': '#445b48',
    'primary_subtle': '#e1e7da',
    
    'success': '#526e52',
    'success_hover': '#425d43',
    'success_subtle': '#e1e9da',
    
    'warning': '#936c32',
    'warning_hover': '#7b5725',
    'warning_subtle': '#f1e6cd',
    
    'danger': '#ac5147',          # Clay red remains distinct for alerts
    'danger_hover': '#944238',
    'danger_subtle': '#f2e1d9',
    
    'info': '#677b73',
    'info_subtle': '#e2e8e1',
    
    # PFD / Instrument Colors
    'pfd_sky': '#637b80',         # Muted sky and earth retain horizon cues
    'pfd_ground': '#89745f',
    'pfd_pitch_line': '#ffffff',
    'pfd_crosshair': '#f1dfad',
    
    'plot_bg': '#faf9f5',
    'plot_grid': '#dcded3',
    'map_bg': '#f0f1e9',
    'map_grid': '#e4e7dc',
    'shadow': 'rgba(52, 61, 53, 0.06)'
}

THEME_DARK: Dict[str, str] = {
    'name': 'dark',
    'bg': '#090d16',              # Deep night cockpit background
    'surface': '#111827',         # Gray 900
    'surface_elevated': '#1f2937',# Gray 800
    'surface_sunken': '#0b0f19',  # Pitch dark
    'border': '#1f2937',          # Gray 800
    'border_strong': '#374151',   # Gray 700
    'text': '#f8fafc',            # Slate 50: High-contrast night text
    'text_secondary': '#cbd5e1',  # Slate 300
    'text_muted': '#94a3b8',      # Slate 400
    'text_inverse': '#0f172a',
    
    # Semantic Colors (High luminance for dark backgrounds)
    'primary': '#38bdf8',         # Sky 400
    'primary_hover': '#0284c7',   # Sky 600
    'primary_subtle': '#082f49',  # Sky 950
    
    'success': '#34d399',         # Emerald 400
    'success_hover': '#059669',
    'success_subtle': '#064e3b',
    
    'warning': '#fbbf24',         # Amber 400
    'warning_hover': '#d97706',
    'warning_subtle': '#451a03',
    
    'danger': '#f87171',          # Red 400
    'danger_hover': '#dc2626',
    'danger_subtle': '#450a0a',
    
    'info': '#818cf8',            # Indigo 400
    'info_subtle': '#1e1b4b',
    
    # PFD / Instrument Colors
    'pfd_sky': '#0c4a6e',         # Sky 900
    'pfd_ground': '#3b1d11',      # Dark umber
    'pfd_pitch_line': '#ffffff',
    'pfd_crosshair': '#facc15',   # Aviation yellow
    
    'plot_bg': '#0f172a',
    'plot_grid': '#1e293b',
    'map_bg': '#152033',
    'map_grid': '#243147',
    'shadow': 'rgba(0, 0, 0, 0.4)'
}

# Warm neutrals and sage are the default; dark mode is an explicit preference.
active_theme = THEME_LIGHT


def set_active_theme(is_dark: bool = False):
    global active_theme
    active_theme = THEME_DARK if is_dark else THEME_LIGHT


def get_theme() -> Dict[str, str]:
    return active_theme


def get_app_stylesheet(t: Dict[str, str] = None) -> str:
    """Generates the master stylesheet for the Qt application."""
    if t is None:
        t = active_theme
        
    return f"""
    QMainWindow, QDialog, QWidget {{
        background-color: {t['bg']};
        color: {t['text']};
        font-family: {FONT_FAMILY_PRIMARY};
        font-size: 12px;
    }}
    
    QToolTip {{
        background-color: {t['surface_elevated']};
        color: {t['text']};
        border: 1px solid {t['border_strong']};
        padding: 4px 8px;
        font-size: 11px;
    }}

    QLabel {{ background: transparent; border: none; }}
    
    QScrollBar:vertical {{
        background: {t['surface']};
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t['border_strong']};
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t['primary']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    
    QScrollBar:horizontal {{
        background: {t['surface']};
        height: 8px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['border_strong']};
        min-width: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {t['primary']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    QTabWidget::pane {{
        border: 1px solid {t['border']};
        background: {t['surface']};
        border-radius: 8px;
    }}
    
    QTabBar::tab {{
        background-color: {t['surface']};
        color: {t['text_secondary']};
        border: 1px solid {t['border']};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 8px 18px;
        font-family: {FONT_FAMILY_PRIMARY};
        font-weight: 600;
        font-size: 12px;
        margin-right: 4px;
    }}
    QTabBar::tab:selected {{
        background-color: {t['primary_subtle']};
        color: {t['primary']};
        border-color: {t['primary']};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {t['surface_elevated']};
        color: {t['text']};
    }}

    QTableWidget, QTreeWidget, QListWidget {{
        background-color: {t['surface']};
        color: {t['text']};
        gridline-color: {t['border']};
        border: 1px solid {t['border']};
        border-radius: 6px;
        selection-background-color: {t['primary_subtle']};
        selection-color: {t['text']};
    }}
    QHeaderView::section {{
        background-color: {t['surface_elevated']};
        color: {t['primary']};
        padding: 6px 8px;
        font-weight: bold;
        border: 1px solid {t['border']};
        font-size: 11px;
    }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 6px;
        padding: 5px 8px;
        font-family: {FONT_FAMILY_PRIMARY};
        font-size: 12px;
        selection-background-color: {t['primary']};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1.5px solid {t['primary']};
    }}
    
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border-left: 1px solid {t['border']};
    }}
    QComboBox QAbstractItemView {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border_strong']};
        selection-background-color: {t['primary_subtle']};
        selection-color: {t['text']};
    }}

    QCheckBox {{
        color: {t['text']};
        font-size: 12px;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1.5px solid {t['border_strong']};
        background: {t['surface']};
    }}
    QCheckBox::indicator:checked {{
        background: {t['primary']};
        border-color: {t['primary']};
    }}
    """


def get_button_style(
    variant: str = 'primary',
    size: str = 'md',
    t: Dict[str, str] = None
) -> str:
    """Generates consistent button styling based on semantic variant."""
    if t is None:
        t = active_theme
        
    pad = "6px 14px" if size == 'md' else ("4px 10px" if size == 'sm' else "10px 20px")
    fsize = "12px" if size == 'md' else ("11px" if size == 'sm' else "13px")
    
    if variant == 'primary':
        bg = t['primary']
        fg = t['text_inverse']
        hover_bg = t['primary_hover']
        border = t['primary']
    elif variant == 'success':
        bg = t['success']
        fg = t['text_inverse']
        hover_bg = t['success_hover']
        border = t['success']
    elif variant == 'danger':
        bg = t['danger']
        fg = t['text_inverse']
        hover_bg = t['danger_hover']
        border = t['danger']
    elif variant == 'warning':
        bg = t['warning']
        fg = t['text_inverse']
        hover_bg = t['warning_hover']
        border = t['warning']
    elif variant == 'secondary':
        bg = t['surface_elevated']
        fg = t['text']
        hover_bg = t['surface_sunken']
        border = t['border_strong']
    else:  # outline
        bg = 'transparent'
        fg = t['primary']
        hover_bg = t['primary_subtle']
        border = t['primary']

    return f"""
        QPushButton {{
            background-color: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 6px;
            font-family: {FONT_FAMILY_PRIMARY};
            font-weight: 700;
            font-size: {fsize};
            padding: {pad};
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
        }}
        QPushButton:pressed {{
            opacity: 0.8;
        }}
        QPushButton:disabled {{
            background-color: {t['surface_sunken']};
            color: {t['text_muted']};
            border-color: {t['border']};
        }}
    """


def get_pill_style(
    variant: str = 'neutral',
    filled: bool = False,
    t: Dict[str, str] = None
) -> str:
    """Generates pill / badge styles for status indicators."""
    if t is None:
        t = active_theme
        
    color_map = {
        'primary': (t['primary'], t['primary_subtle']),
        'success': (t['success'], t['success_subtle']),
        'warning': (t['warning'], t['warning_subtle']),
        'danger': (t['danger'], t['danger_subtle']),
        'neutral': (t['text_muted'], t['surface_elevated']),
    }
    
    border_color, bg_subtle = color_map.get(variant, (t['text_muted'], t['surface_elevated']))
    
    if filled:
        bg = border_color
        text_color = t['text_inverse']
    else:
        bg = bg_subtle
        text_color = border_color
        
    return f"""
        QLabel {{
            background-color: {bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 10px;
            padding: 2px 7px;
            font-family: {FONT_FAMILY_PRIMARY};
            font-weight: 700;
            font-size: 10px;
        }}
    """
