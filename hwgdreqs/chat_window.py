from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QFont, QTextCursor, QAction
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class _ChatView(QPlainTextEdit):
    message_right_clicked = Signal(str, str, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu_requested)

        # parallel list: entry i = message at document block i
        self._usernames: list[str] = []

        font = QFont("Segoe UI", 9)
        self.setFont(font)

    def add_message(self, username: str, text: str) -> None:
        self._usernames.append(username)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt_name = cursor.blockCharFormat()
        fmt_name.setForeground(QColor("#9b59b6"))
        fmt_name.setFontWeight(QFont.Weight.Bold)

        fmt_text = cursor.blockCharFormat()
        fmt_text.setForeground(QColor("#dddddd"))
        fmt_text.setFontWeight(QFont.Weight.Normal)

        if self.document().blockCount() > 1 or self.toPlainText():
            cursor.insertBlock()

        cursor.insertText(username, fmt_name)
        cursor.insertText(f" {text}", fmt_text)

        vsb = self.verticalScrollBar()
        vsb.setValue(vsb.maximum())

    def _username_at_block(self, block_number: int) -> str | None:
        if 0 <= block_number < len(self._usernames):
            return self._usernames[block_number]
        return None

    def _on_context_menu_requested(self, pos: QPoint) -> None:
        cursor = self.cursorForPosition(pos)
        username = self._username_at_block(cursor.blockNumber())
        # get the plain text of that block as the message
        block = self.document().findBlockByNumber(cursor.blockNumber())
        text = block.text()
        if username and text:
            self.message_right_clicked.emit(username, text, self.mapToGlobal(pos))


class ChatWindow(QDialog):
    """
    Non-modal dialog showing Twitch or YouTube live chat.
    Create it (hidden) as soon as the worker starts, so it buffers from the beginning.
    Call .on_message() to append incoming messages.
    Call .show()/.raise_() to make it visible to the user.

    Parameters
    ----------
    platform : "twitch" | "youtube"
    session  : TwitchSession | None   (needed to send/ban on Twitch)
    chat_worker : worker object with _send_chat_message()
    can_send : bool  – True when Twitch chat:edit scope is active
    can_ban  : bool  – True when Twitch moderation scope is active
    parent   : QWidget | None
    child    : no he's an orphan
    """

    def __init__(
        self,
        platform: str,
        session=None,
        chat_worker=None,
        can_send: bool = False,
        can_ban: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._platform = platform
        self._session = session
        self._chat_worker = chat_worker
        self._can_send = can_send
        self._can_ban = can_ban

        title = "Twitch Chat" if platform == "twitch" else "YouTube Chat"
        self.setWindowTitle(title)
        self.resize(460, 540)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMinimizeButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._header = QLabel(title)
        hdr_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self._header.setFont(hdr_font)
        layout.addWidget(self._header)

        self._view = _ChatView(self)
        self._view.message_right_clicked.connect(self._on_message_right_clicked)
        layout.addWidget(self._view, stretch=1)

        # Send bar. Twitch only, when chat:edit scope is on
        if platform == "twitch" and can_send:
            send_layout = QHBoxLayout()
            self._input = QLineEdit()
            self._input.setPlaceholderText("Type your message to chat here (\\n for new lines)")
            self._input.returnPressed.connect(self._send_message)
            send_layout.addWidget(self._input, stretch=1)

            send_btn = QPushButton("Send")
            send_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            send_btn.clicked.connect(self._send_message)
            send_layout.addWidget(send_btn)
            layout.addLayout(send_layout)
        else:
            self._input = None

    # Public API

    def on_message(self, username: str, text: str) -> None:
        """Append an incoming message to the log."""
        self._view.add_message(username, text)

    # Internal
    def _send_message(self) -> None:
        if not self._input or not self._chat_worker:
            return
        raw = self._input.text().strip()
        if not raw:
            return
        message = raw.replace("\\n", "\n")
        self._chat_worker._send_chat_message(message)
        self._input.clear()
        sender = (
            self._session.display_name
            if self._session and self._session.display_name
            else (self._session.login if self._session else "You")
        )
        self.on_message(sender, message)

    def _on_message_right_clicked(self, username: str, text: str, global_pos: QPoint) -> None:
        if self._platform != "twitch" or not self._can_ban:
            return

        menu = QMenu(self)
        ban_act = QAction(f"Ban user '{username}'", self)
        ban_act.triggered.connect(lambda: self._ban_user(username))
        menu.addAction(ban_act)
        menu.exec(global_pos)

    def _ban_user(self, username: str) -> None:
        if not self._session:
            return
        from PySide6.QtWidgets import QMessageBox
        from hwgdreqs.twitch_auth import ban_twitch_user

        if username.lower() == self._session.login.lower():
            QMessageBox.warning(self, "Ban User", "SON you cant ban yourself😭")  # OG
            return

        reply = QMessageBox.question(
            self,
            "Ban User",
            f"Are you sure you want to ban '{username}' from your Twitch channel?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            error = ban_twitch_user(self._session, username)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if error:
            QMessageBox.warning(self, "Ban Failed", f"Could not ban {username}:\n{error}")
        else:
            QMessageBox.information(self, "Banned", f"Successfully banned '{username}' on Twitch.")
