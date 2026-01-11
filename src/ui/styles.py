"""Modern stylesheet for Writer Platform."""

# Color palette - inspired by creative writing tools
COLORS = {
    # Primary colors - warm, creative tones
    'primary': '#6366f1',      # Indigo
    'primary_dark': '#4f46e5',
    'primary_light': '#818cf8',

    # Accent colors
    'accent': '#ec4899',       # Pink for creative elements
    'accent_light': '#f9a8d4',

    # Neutrals - comfortable for long writing sessions
    'bg_primary': '#1e1e1e',   # Dark background
    'bg_secondary': '#2a2a2a',
    'bg_tertiary': '#353535',
    'bg_light': '#f5f5f5',     # Light mode background

    # Text colors
    'text_primary': '#e5e5e5',
    'text_secondary': '#a3a3a3',
    'text_muted': '#737373',
    'text_dark': '#1a1a1a',    # For light backgrounds

    # Semantic colors
    'success': '#10b981',
    'warning': '#f59e0b',
    'error': '#ef4444',
    'info': '#3b82f6',
}

# Modern stylesheet
MODERN_STYLE = f"""
/* Global styles */
QWidget {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13px;
    color: {COLORS['text_dark']};
}}

/* Main window */
QMainWindow {{
    background-color: {COLORS['bg_light']};
}}

/* Tab widget - modern, minimal */
QTabWidget::pane {{
    border: none;
    background-color: white;
    border-radius: 8px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {COLORS['text_secondary']};
    padding: 12px 24px;
    margin-right: 4px;
    border: none;
    border-bottom: 3px solid transparent;
    font-weight: 500;
    font-size: 14px;
}}

QTabBar::tab:selected {{
    color: {COLORS['primary']};
    border-bottom: 3px solid {COLORS['primary']};
}}

QTabBar::tab:hover {{
    color: {COLORS['primary_light']};
    background-color: rgba(99, 102, 241, 0.05);
}}

/* Buttons - modern, rounded */
QPushButton {{
    background-color: {COLORS['primary']};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
    font-size: 13px;
    min-height: 28px;
}}

QPushButton:hover {{
    background-color: {COLORS['primary_dark']};
}}

QPushButton:pressed {{
    background-color: {COLORS['primary_dark']};
}}

QPushButton:disabled {{
    background-color: {COLORS['text_muted']};
    color: {COLORS['text_secondary']};
}}

/* Secondary button style */
QPushButton[secondary="true"] {{
    background-color: transparent;
    color: {COLORS['primary']};
    border: 1px solid {COLORS['primary']};
}}

QPushButton[secondary="true"]:hover {{
    background-color: rgba(99, 102, 241, 0.1);
}}

/* Text input fields - clean, minimal */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 8px 12px;
    color: {COLORS['text_dark']};
    selection-background-color: {COLORS['primary_light']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {COLORS['primary']};
    outline: none;
}}

/* List widgets - clean cards */
QListWidget {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}}

QListWidget::item {{
    background-color: transparent;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 2px 0;
    color: {COLORS['text_dark']};
}}

QListWidget::item:selected {{
    background-color: {COLORS['primary']};
    color: white;
}}

QListWidget::item:hover {{
    background-color: rgba(99, 102, 241, 0.1);
}}

/* Group boxes - subtle cards */
QGroupBox {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px;
    font-weight: 600;
    color: {COLORS['text_dark']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    background-color: white;
    color: {COLORS['primary']};
    font-size: 14px;
}}

/* Scrollbars - minimal, modern */
QScrollBar:vertical {{
    background-color: transparent;
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['text_muted']};
    border-radius: 6px;
    min-height: 30px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['text_secondary']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 12px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS['text_muted']};
    border-radius: 6px;
    min-width: 30px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['text_secondary']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* Combo boxes - modern dropdown */
QComboBox {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 28px;
    color: {COLORS['text_dark']};
}}

QComboBox:hover {{
    border-color: {COLORS['primary_light']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {COLORS['text_secondary']};
    margin-right: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    selection-background-color: {COLORS['primary']};
    selection-color: white;
    outline: none;
    padding: 4px;
}}

/* Spin boxes */
QSpinBox {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 28px;
}}

/* Menu bar - clean and minimal */
QMenuBar {{
    background-color: white;
    border-bottom: 1px solid #e5e7eb;
    padding: 4px;
}}

QMenuBar::item {{
    background-color: transparent;
    padding: 8px 12px;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background-color: rgba(99, 102, 241, 0.1);
    color: {COLORS['primary']};
}}

QMenu {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 8px 24px 8px 12px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {COLORS['primary']};
    color: white;
}}

/* Status bar */
QStatusBar {{
    background-color: white;
    border-top: 1px solid #e5e7eb;
    color: {COLORS['text_secondary']};
    padding: 4px 8px;
}}

/* Toolbar - minimal */
QToolBar {{
    background-color: white;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    spacing: 8px;
    padding: 8px;
}}

QToolBar::separator {{
    background-color: #e5e7eb;
    width: 1px;
    margin: 4px 8px;
}}

/* Labels - hierarchy */
QLabel {{
    color: {COLORS['text_dark']};
}}

QLabel[heading="true"] {{
    font-size: 24px;
    font-weight: 700;
    color: {COLORS['text_dark']};
}}

QLabel[subheading="true"] {{
    font-size: 16px;
    font-weight: 600;
    color: {COLORS['text_dark']};
}}

QLabel[muted="true"] {{
    color: {COLORS['text_secondary']};
    font-size: 12px;
}}

/* Splitter - invisible */
QSplitter::handle {{
    background-color: transparent;
    width: 1px;
}}

QSplitter::handle:hover {{
    background-color: {COLORS['primary_light']};
}}

/* Chat widget - special styling */
#chatWidget {{
    background-color: white;
    border-left: 1px solid #e5e7eb;
}}

/* Cards for content sections */
.card {{
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px;
}}

.card:hover {{
    border-color: {COLORS['primary_light']};
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}}
"""

# Icon mappings for modern UI
ICONS = {
    'worldbuilding': '🌍',
    'characters': '👥',
    'story': '📖',
    'manuscript': '✍️',
    'images': '🎨',
    'grader': '📊',
    'agents': '📧',
    'save': '💾',
    'export': '📤',
    'import': '📥',
    'ai': '✨',
    'chat': '💬',
}


def get_modern_style():
    """Get the modern stylesheet."""
    return MODERN_STYLE


def get_icon(name: str) -> str:
    """Get icon for a given name."""
    return ICONS.get(name, '')
