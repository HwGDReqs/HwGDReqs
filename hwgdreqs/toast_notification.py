import platform
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QTimer

class ToastNotification(QWidget):
    def __init__(self, title: str, message: str):
        super().__init__(None)
        
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint 
            | Qt.WindowType.ToolTip 
            | Qt.WindowType.WindowStaysOnTopHint
        )
        
        self.setStyleSheet("""
            ToastNotification {
                background-color: #2b2b2b;
                border-radius: 8px;
                border: 1px solid #555;
            }
            QLabel#ToastTitle {
                color: #4caf50;
                font-weight: bold;
                font-size: 14px;
            }
            QLabel#ToastMessage {
                color: #eeeeee;
                font-size: 12px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        
        title_label = QLabel(title)
        title_label.setObjectName("ToastTitle")
        layout.addWidget(title_label)
        
        msg_label = QLabel(message)
        msg_label.setObjectName("ToastMessage")
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)
        
        self.adjustSize()
        
        # Position at the top right of the primary screen
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            margin = 20
            x = screen_geometry.x() + screen_geometry.width() - self.width() - margin
            y = screen_geometry.y() + margin
            self.move(x, y)
        
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(5000)

    def show_toast(self):
        self.show()
        if platform.system() == "Windows":
            try:
                import winsound
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        else:
            QApplication.beep()
