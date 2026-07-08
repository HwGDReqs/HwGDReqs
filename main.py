import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from hwgdreqs.config import APP_NAME, APP_VERSION, asset_path, exec_dir
from hwgdreqs.main_window import MainWindow
from hwgdreqs.queue_manager import QueueManager


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HwGDReqs")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("HwGDReqs")
    app.setApplicationVersion(APP_VERSION)

    icon_path = asset_path("logo.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    splash_path = asset_path("splash.png")
    splash = None
    if splash_path.exists():
        splash = QSplashScreen(QPixmap(str(splash_path)))
        splash.show()
        app.processEvents()

    queue = QueueManager()
    window = MainWindow(queue)

    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    def report_status(message: str) -> None:
        if splash:
            splash.showMessage(
                message,
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            )
        app.processEvents()

    if splash:
        report_status("...")
        time.sleep(0.4)

    if not window.startup(report_status if splash else None):
        if splash:
            splash.close()
        return 0

    if splash:
        splash.finish(window)

    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())