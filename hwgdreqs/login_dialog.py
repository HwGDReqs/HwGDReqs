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

from hwgdreqs.login_worker import DeviceLoginWorker, KickLoginWorker
from hwgdreqs.twitch_auth import TwitchSession
from hwgdreqs.youtube_auth import YoutubeSession





class TwitchLoginDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        include_chat_edit: bool = False,
        include_channel_moderate: bool = False,
        hide_queue_checkbox: bool = False,
        hide_moderate_checkbox: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Twitch Login")
        self.setModal(True)
        self.setMinimumSize(420, 280)
        self._session: TwitchSession | None = None
        self._worker: DeviceLoginWorker | None = None
        self._verification_uri = "https://www.twitch.tv/activate"
        self._include_chat_edit = include_chat_edit
        self._include_channel_moderate = include_channel_moderate
        self._queue_command_cb: QCheckBox | None = None
        self._channel_moderate_cb: QCheckBox | None = None

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

        bot_note = QLabel(
            "If you want a custom bot account to chat in your main chat, "
            "Login with THAT account and do '/mod @your-bot-account' in your main chat"
            "And set your streamer username in the settings under the twitch tab"
        )
        bot_note.setWordWrap(True)
        bot_note.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(bot_note)

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

        if not hide_moderate_checkbox:
            self._channel_moderate_cb = QCheckBox(
                "want to moderate chat to ban a requester from the app?(eg they requested a bad level)"
            )
            self._channel_moderate_cb.setChecked(include_channel_moderate)
            layout.addWidget(self._channel_moderate_cb)

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
        include_channel_moderate = (
            self._channel_moderate_cb.isChecked()
            if self._channel_moderate_cb is not None
            else self._include_channel_moderate
        )
        self._login_btn.setEnabled(False)
        self._open_btn.setEnabled(False)
        if self._queue_command_cb is not None:
            self._queue_command_cb.setEnabled(False)
        if self._channel_moderate_cb is not None:
            self._channel_moderate_cb.setEnabled(False)
        self._code_label.setText(" ")
        self._status.setText("Starting device login...")
        self._worker = DeviceLoginWorker(
            self,
            include_chat_edit=include_chat_edit,
            include_channel_moderate=include_channel_moderate,
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
        if self._channel_moderate_cb is not None:
            self._channel_moderate_cb.setEnabled(True)
        self._code_label.setText(" ")
        self._status.setText(message)
        QMessageBox.warning(self, "Twitch Login", message)


class KickLoginDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kick Login (BETA)")
        self.setModal(True)
        self.setMinimumSize(420, 200)
        self._session = None
        self._worker: KickLoginWorker | None = None

        layout = QVBoxLayout(self)

        self._intro = QLabel(
            "Connect your Kick account to listen for level requests in chat.\n"
            "Clicking the button below will open Kick in your browser to authorize the app.\n"
            "This is still non complete, means right now it does reply to added levels, but NO commands support now"
        )
        self._intro.setWordWrap(True)
        layout.addWidget(self._intro)

        self._status = QLabel("Click below to start Kick Login (BETA).")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(48)
        layout.addWidget(self._status)

        button_row = QHBoxLayout()
        self._login_btn = QPushButton("Start Kick Login (BETA)")
        self._login_btn.clicked.connect(self._start_login)
        button_row.addWidget(self._login_btn)

        self._open_btn = QPushButton("Re-open Kick")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._reopen_browser)
        button_row.addWidget(self._open_btn)

        layout.addLayout(button_row)

        self._auth_url: str = ""

    @property
    def session(self):
        return self._session

    def _start_login(self) -> None:
        self._login_btn.setEnabled(False)
        self._open_btn.setEnabled(False)
        self._status.setText("Initializing…")
        self._worker = KickLoginWorker(self)
        self._worker.auth_url_ready.connect(self._on_auth_url_ready)
        self._worker.auth_status.connect(self._status.setText)
        self._worker.login_complete.connect(self._on_login_complete)
        self._worker.login_failed.connect(self._on_login_failed)
        self._worker.start()

    def _on_auth_url_ready(self, url: str) -> None:
        self._auth_url = url
        self._open_btn.setEnabled(True)
        webbrowser.open(url)
        self._status.setText(
            "Your browser has been opened to the Kick authorization page.\n"
            "Approve the login there, then this dialog will close automatically."
        )

    def _reopen_browser(self) -> None:
        if self._auth_url:
            webbrowser.open(self._auth_url)

    def _on_login_complete(self, session) -> None:
        self._session = session
        self._status.setText(f"Logged in as {session.display_name}.")
        self.accept()

    def _on_login_failed(self, message: str) -> None:
        self._login_btn.setEnabled(True)
        self._open_btn.setEnabled(False)
        self._status.setText(message)
        QMessageBox.warning(self, "Kick Login (BETA)", message)


class LoginDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Login")
        self.setModal(True)
        self.setMinimumSize(450, 340)

        self._session: TwitchSession | None = None
        self._youtube_session: YoutubeSession | None = None
        self._kick_session = None

        layout = QVBoxLayout(self)

        title = QLabel("Get ready to receive levels from your chat! select the corresponding platform(s) and get started")
        title.setWordWrap(True)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        layout.addSpacing(20)

        self.twitch_btn = QPushButton("Twitch Login")
        self.twitch_btn.clicked.connect(self._do_twitch_login)
        layout.addWidget(self.twitch_btn)

        layout.addSpacing(8)

        self.kick_btn = QPushButton("Kick Login (BETA)")
        self.kick_btn.clicked.connect(self._do_kick_login)
        layout.addWidget(self.kick_btn)

        layout.addSpacing(10)

        yt_label = QLabel("YouTube Username (username) NOT display name:")
        layout.addWidget(yt_label)

        self.yt_input = QLineEdit()
        self.yt_input.setPlaceholderText("@YourUsername")
        self.yt_input.textChanged.connect(self._check_done_state)
        layout.addWidget(self.yt_input)

        layout.addStretch()

        btn_layout = QHBoxLayout()

        self.done_btn = QPushButton("Done")
        self.done_btn.setEnabled(False)
        self.done_btn.clicked.connect(self._on_done)
        btn_layout.addWidget(self.done_btn)

        gd_btn_row = QHBoxLayout()
        gd_btn_row.setSpacing(4)
        self.install_gd_btn = QPushButton("install GD integration (GD)")
        self.install_gd_btn.clicked.connect(self._install_gd)
        gd_btn_row.addWidget(self.install_gd_btn)

        self.gd_info_btn = QPushButton("ℹ️")
        self.gd_info_btn.setFixedWidth(32)
        self.gd_info_btn.setToolTip("Why this won't appear in Geode index")
        self.gd_info_btn.clicked.connect(self._show_gd_info)
        gd_btn_row.addWidget(self.gd_info_btn)

        btn_layout.addLayout(gd_btn_row)

        layout.addLayout(btn_layout)

    @property
    def session(self) -> TwitchSession | None:
        return self._session

    @property
    def youtube_session(self) -> YoutubeSession | None:
        return self._youtube_session

    @property
    def kick_session(self):
        return self._kick_session

    def _do_twitch_login(self) -> None:
        twitch_dialog = TwitchLoginDialog(parent=None)
        twitch_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        if twitch_dialog.exec() == QDialog.DialogCode.Accepted:
            self._session = twitch_dialog.session
            self.twitch_btn.setText("Twitch Logged In")
            self.twitch_btn.setEnabled(False)
            self._check_done_state()
        self.raise_()
        self.activateWindow()

    def _do_kick_login(self) -> None:
        kick_dialog = KickLoginDialog(parent=None)
        kick_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        if kick_dialog.exec() == QDialog.DialogCode.Accepted:
            self._kick_session = kick_dialog.session
            self.kick_btn.setText("Kick Logged In")
            self.kick_btn.setEnabled(False)
            self._check_done_state()
        self.raise_()
        self.activateWindow()

    def _check_done_state(self) -> None:
        has_twitch = self._session is not None
        has_kick = self._kick_session is not None
        has_yt = bool(self.yt_input.text().strip())
        self.done_btn.setEnabled(has_twitch or has_yt or has_kick)

    def _on_done(self) -> None:
        yt_username = self.yt_input.text().strip()
        if yt_username:
            if not yt_username.startswith("@"):
                yt_username = "@" + yt_username
            self._youtube_session = YoutubeSession(username=yt_username)
        self.accept()

    def _install_gd(self) -> None:
        from hwgdreqs.geode_installer import install_geode_integration
        install_geode_integration(self)

    def _show_gd_info(self) -> None:
        from hwgdreqs.geode_installer import GEODE_EXPLANATION_TEXT
        QMessageBox.information(
            self,
            "About Geode Integration",
            GEODE_EXPLANATION_TEXT,
        )

