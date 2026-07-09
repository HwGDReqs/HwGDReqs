import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from hwgdreqs.login_worker import DeviceLoginWorker
from hwgdreqs.twitch_auth import TwitchSession
from hwgdreqs.youtube_auth import YoutubeSession


class YoutubeLoginDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("YouTube Login")
        self.setModal(True)
        self.setMinimumSize(420, 200)
        self._session: YoutubeSession | None = None

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Enter your YouTube username (with @) to receive level requests from YouTube chat.\n\n"
            "The app will check if you're live and monitor your chat for level requests."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addSpacing(10)

        username_label = QLabel("YouTube Username (@username):")
        layout.addWidget(username_label)

        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("@YourUsername")
        layout.addWidget(self._username_input)

        layout.addSpacing(10)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Connect")
        ok_btn.clicked.connect(self._on_connect)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    @property
    def session(self) -> YoutubeSession | None:
        return self._session

    def _on_connect(self) -> None:
        username = self._username_input.text().strip()

        if not username:
            QMessageBox.warning(
                self,
                "YouTube Login",
                "Please enter your YouTube username.",
            )
            return

        if not username.startswith("@"):
            username = "@" + username

        self._session = YoutubeSession(username=username)
        self.accept()


class PlatformSelectionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Platform")
        self.setModal(True)
        self.setMinimumSize(320, 220)
        self.selected_platform: str | None = None

        layout = QVBoxLayout(self)

        title = QLabel("Connect your platform for level requests:")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        layout.addSpacing(20)

        twitch_btn = QPushButton("Login with Twitch")
        twitch_btn.clicked.connect(lambda: self._select("twitch"))
        layout.addWidget(twitch_btn)

        youtube_btn = QPushButton("Login with YouTube")
        youtube_btn.clicked.connect(lambda: self._select("youtube"))
        layout.addWidget(youtube_btn)

        both_btn = QPushButton("Login with Both")
        both_btn.clicked.connect(lambda: self._select("both"))
        layout.addWidget(both_btn)

        layout.addStretch()

    def _select(self, platform: str) -> None:
        self.selected_platform = platform
        self.accept()


class TwitchLoginDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        include_chat_edit: bool = False,
        hide_queue_checkbox: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Twitch Login")
        self.setModal(True)
        self.setMinimumSize(420, 260)
        self._session: TwitchSession | None = None
        self._worker: DeviceLoginWorker | None = None
        self._verification_uri = "https://www.twitch.tv/activate"
        self._include_chat_edit = include_chat_edit
        self._queue_command_cb: QCheckBox | None = None

        layout = QVBoxLayout(self)

        self._intro = QLabel(
            "Connect your Twitch account to listen for Geometry Dash level requests in chat."
        )
        self._intro.setWordWrap(True)
        layout.addWidget(self._intro)

        self._status = QLabel("Click below to start Twitch login.")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(48)
        layout.addWidget(self._status)

        self._code_label = QLabel(" ")
        self._code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._code_label.setFixedHeight(48)
        self._code_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        font = self._code_label.font()
        font.setPointSize(28)
        font.setBold(True)
        self._code_label.setFont(font)
        layout.addWidget(self._code_label)

        if not hide_queue_checkbox:
            self._queue_command_cb = QCheckBox(
                "Want people to type !queue to see current queue "
                "(will respond under your account)"
            )
            self._queue_command_cb.setChecked(include_chat_edit)
            layout.addWidget(self._queue_command_cb)

        button_row = QHBoxLayout()
        self._login_btn = QPushButton("Start Twitch Login")
        self._login_btn.clicked.connect(self._start_login)
        button_row.addWidget(self._login_btn)

        self._open_btn = QPushButton("Open Twitch")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_twitch)
        button_row.addWidget(self._open_btn)

        layout.addLayout(button_row)

    @property
    def session(self) -> TwitchSession | None:
        return self._session

    def _start_login(self) -> None:
        include_chat_edit = (
            self._queue_command_cb.isChecked()
            if self._queue_command_cb is not None
            else self._include_chat_edit
        )
        self._login_btn.setEnabled(False)
        self._open_btn.setEnabled(False)
        if self._queue_command_cb is not None:
            self._queue_command_cb.setEnabled(False)
        self._code_label.setText(" ")
        self._status.setText("Starting device login...")
        self._worker = DeviceLoginWorker(
            self,
            include_chat_edit=include_chat_edit,
        )
        self._worker.started_flow.connect(self._on_flow_started)
        self._worker.auth_status.connect(self._status.setText)
        self._worker.login_complete.connect(self._on_login_complete)
        self._worker.login_failed.connect(self._on_login_failed)
        self._worker.start()

    def _on_flow_started(self, flow) -> None:
        self._verification_uri = flow.verification_uri
        self._code_label.setText(flow.user_code)
        self._open_btn.setEnabled(True)
        self._status.setText(
            "Enter this code on Twitch, then approve the login in your browser."
        )

    def _open_twitch(self) -> None:
        webbrowser.open(self._verification_uri)

    def _on_login_complete(self, session: TwitchSession) -> None:
        self._session = session
        self._status.setText(f"Logged in as {session.display_name}.")
        self.accept()

    def _on_login_failed(self, message: str) -> None:
        self._login_btn.setEnabled(True)
        self._open_btn.setEnabled(False)
        if self._queue_command_cb is not None:
            self._queue_command_cb.setEnabled(True)
        self._code_label.setText(" ")
        self._status.setText(message)
        QMessageBox.warning(self, "Twitch Login", message)


class LoginFlow:
    """Handles the login flow without showing an empty dialog"""
    def __init__(self, parent=None) -> None:
        self._parent = parent
        self._session: TwitchSession | None = None
        self._youtube_session: YoutubeSession | None = None
        self._accepted = False

    def exec(self) -> int:
        """Run the login flow and return QDialog.DialogCode.Accepted or Rejected"""
        platform_dialog = PlatformSelectionDialog(self._parent)
        if platform_dialog.exec() != QDialog.DialogCode.Accepted:
            return QDialog.DialogCode.Rejected
        
        selected_platform = platform_dialog.selected_platform
        
        if selected_platform == "twitch":
            return self._login_twitch_only()
        elif selected_platform == "youtube":
            return self._login_youtube_only()
        elif selected_platform == "both":
            return self._login_both()
        
        return QDialog.DialogCode.Rejected

    @property
    def session(self) -> TwitchSession | None:
        return self._session

    @property
    def youtube_session(self) -> YoutubeSession | None:
        return self._youtube_session

    def _login_twitch_only(self) -> int:
        twitch_dialog = TwitchLoginDialog(self._parent)
        if twitch_dialog.exec() == TwitchLoginDialog.DialogCode.Accepted:
            self._session = twitch_dialog.session
            return QDialog.DialogCode.Accepted
        else:
            return QDialog.DialogCode.Rejected

    def _login_youtube_only(self) -> int:
        youtube_dialog = YoutubeLoginDialog(self._parent)
        if youtube_dialog.exec() == YoutubeLoginDialog.DialogCode.Accepted:
            self._youtube_session = youtube_dialog.session
            return QDialog.DialogCode.Accepted
        else:
            return QDialog.DialogCode.Rejected

    def _login_both(self) -> int:
        twitch_dialog = TwitchLoginDialog(self._parent)
        if twitch_dialog.exec() != TwitchLoginDialog.DialogCode.Accepted:
            return QDialog.DialogCode.Rejected
        
        self._session = twitch_dialog.session
        
        youtube_dialog = YoutubeLoginDialog(self._parent)
        if youtube_dialog.exec() == YoutubeLoginDialog.DialogCode.Accepted:
            self._youtube_session = youtube_dialog.session
        
        return QDialog.DialogCode.Accepted


# keep LoginDialog for backward compat.
class LoginDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._flow = LoginFlow(parent)
        self.setWindowTitle("Login")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True) # im dumb

    def exec(self) -> int:
        result = self._flow.exec()
        if result == QDialog.DialogCode.Accepted:
            self.accept()
        else:
            self.reject()
        return result

    @property
    def session(self) -> TwitchSession | None:
        return self._flow.session

    @property
    def youtube_session(self) -> YoutubeSession | None:
        return self._flow.youtube_session
