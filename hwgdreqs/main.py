import json
import sys
import time
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplashScreen,
    QVBoxLayout,
    QWidget,
)


from hwgdreqs.config import APP_NAME, APP_VERSION, asset_path, data_dir, exec_dir
from hwgdreqs.main_window import MainWindow
from hwgdreqs.queue_manager import QueueManager


def _notices_file():
    return data_dir() / "notices.json"


def _has_shown_notice(key: str) -> bool:
    path = _notices_file()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get(key, False))
    except Exception:
        return False


def _mark_notice_shown(key: str) -> None:
    path = _notices_file()
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = True
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


_BAD_PEOPLE_NOTICE_KEY = "bad_people_reporting_v1"


class BadPeopleNoticeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("NEW! Bad People Reporting.")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 20)

        title = QLabel("NEW! Bad People Reporting.")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        msg = QLabel(
            "If you've been hit by a troll or NSFW level and want to protect "
            "other streamers from the same person:<br><br>"
            "1. Go to the level queue (or the Level History tab in Settings).<br>"
            "2. Take a screenshot (yes, a screenshot) of the details or the "
            "exact level entry.<br>"
            "3. Send it to me either on Discord (<code>malikhw</code>) or via "
            "<a href=\"https://github.com/HwGDReqs/HwGDReqs/issues\">GitHub Issues</a>.<br><br>"
            "After I verify the details, I will add them to an online list so "
            "that anyone using the latest HwGDReqs version will be informed."
        )
        msg.setWordWrap(True)
        msg.setOpenExternalLinks(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(msg)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("Got it")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)


def _donate_config_file():
    return data_dir() / "donate_config.json"


def _should_show_donate() -> bool:
    path = _donate_config_file()
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return not data.get("never_show_donate", False)
    except Exception:
        return True


def _save_never_show_donate() -> None:
    path = _donate_config_file()
    try:
        path.write_text(json.dumps({"never_show_donate": True}), encoding="utf-8")
    except Exception:
        pass


class DonationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("HwGDReqs - Free & Open Source")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._never_show = False

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 20)

        msg = QLabel(
            "<b>This Tool is made for free!</b><br>"
            "and will always stay free and open source<br><br>"
            "If you'd like to Donate it will be a W thing to make me "
            "continue coding shit"
        )
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        next_time_btn = QPushButton("Next Time")
        next_time_btn.setToolTip("Close this popup for now")
        next_time_btn.clicked.connect(self.accept)
        btn_layout.addWidget(next_time_btn)

        never_btn = QPushButton("Never Show Again")
        never_btn.setToolTip("Close and never show this again")
        never_btn.clicked.connect(self._on_never)
        btn_layout.addWidget(never_btn)

        donate_btn = QPushButton("Donate")
        donate_btn.setToolTip("support the developer!")
        donate_btn.clicked.connect(self._on_donate)
        btn_layout.addWidget(donate_btn)

        layout.addLayout(btn_layout)

    def _on_never(self) -> None:
        self._never_show = True
        self.accept()

    def _on_donate(self) -> None:
        webbrowser.open("https://malikhw.github.io/donate/")
        self.accept()


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

    class NonHidingSplashScreen(QSplashScreen):
        def mousePressEvent(self, event):
            pass

    splash_path = asset_path("splash.png")
    splash = None
    if splash_path.exists():
        splash = NonHidingSplashScreen(QPixmap(str(splash_path)))
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

    report_status("checking for known bad requesters...")
    queue.refresh_bad_people_list()

    if not window.startup(report_status if splash else None):
        if splash:
            splash.close()
        window.close()
        return 0

    if splash:
        splash.finish(window)

    window.show()
    window.raise_()
    window.activateWindow()

    if not _has_shown_notice(_BAD_PEOPLE_NOTICE_KEY):
        BadPeopleNoticeDialog(window).exec()
        _mark_notice_shown(_BAD_PEOPLE_NOTICE_KEY)

    if _should_show_donate():
        dlg = DonationDialog(window)
        dlg.exec()
        if dlg._never_show:
            _save_never_show_donate()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())