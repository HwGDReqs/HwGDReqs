from __future__ import annotations

import re
from typing import TYPE_CHECKING

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
    QToolTip,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from hwgdreqs.queue_manager import QueueManager

from hwgdreqs.config import LEVEL_ID_PATTERN

LEVEL_RE = re.compile(LEVEL_ID_PATTERN)

# Individual message block stored alongside its metadata

class ChatMessage:
    """Stores one chat message with metadata for hover/highlight."""

    def __init__(self, username: str, text: str) -> None:
        self.username = username
        self.text = text
        self.queue_level_ids: list[str] = []


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

        self._messages: list[ChatMessage] = []

        font = QFont("Segoe UI", 9)
        self.setFont(font)

    # Public helpers

    def add_message(self, msg: ChatMessage) -> None:
        self._messages.append(msg)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt_base = cursor.blockCharFormat()
        fmt_base.setForeground(QColor("#dddddd"))

        fmt_name = cursor.blockCharFormat()
        fmt_name.setForeground(QColor("#9b59b6"))
        fmt_name.setFontWeight(QFont.Weight.Bold)

        fmt_text = cursor.blockCharFormat()
        if msg.queue_level_ids:

            fmt_text.setForeground(QColor("#e74c3c"))
        else:
            fmt_text.setForeground(QColor("#dddddd"))


        if self.document().blockCount() > 1 or self.toPlainText():
            cursor.insertBlock()

        cursor.insertText(f"{msg.username}", fmt_name)
        cursor.insertText(f" {msg.text}", fmt_text)

        # Auto-scroll
        vsb = self.verticalScrollBar()
        vsb.setValue(vsb.maximum())

    def get_message_at_block(self, block_number: int) -> ChatMessage | None:
        if 0 <= block_number < len(self._messages):
            return self._messages[block_number]
        return None

    # Events

    def mouseMoveEvent(self, event) -> None:
        cursor = self.cursorForPosition(event.position().toPoint())
        block_no = cursor.blockNumber()
        msg = self.get_message_at_block(block_no)
        if msg and msg.queue_level_ids:
            tooltip_text = "\n".join(msg.queue_level_ids)
            QToolTip.showText(event.globalPosition().toPoint(), tooltip_text, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def _on_context_menu_requested(self, pos: QPoint) -> None:
        cursor = self.cursorForPosition(pos)
        block_no = cursor.blockNumber()
        msg = self.get_message_at_block(block_no)
        if msg:
            self.message_right_clicked.emit(msg.username, msg.text, self.mapToGlobal(pos))

# Main Chat Window dialog

class ChatWindow(QDialog):
    """
    A non-modal dialog that shows either Twitch or YouTube live chat messages.

    Parameters
    ----------
    platform : "twitch" | "youtube"
    queue : QueueManager – used to look up level IDs in messages
    session : TwitchSession | None – needed so we can send messages
    chat_worker : TwitchChatWorker | YoutubeChatWorker | None
    can_send : bool – True when chat:edit scope is active (Twitch only)
    can_ban : bool – True when moderation scope is active (Twitch only)
    parent : QWidget | None
    child : no hes an orphan
    """

    def __init__(
        self,
        platform: str,
        queue: "QueueManager",
        session=None,
        chat_worker=None,
        can_send: bool = False,
        can_ban: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._platform = platform
        self._queue = queue
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

        # Twitch only, when chat:edit
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

    # Public API – connect the chat worker signals to this

    def on_message(self, username: str, text: str) -> None:
        msg = ChatMessage(username, text)

        queue_ids = {entry.id for entry in self._queue.levels}
        tooltip_parts = []
        for m in LEVEL_RE.finditer(text):
            lid = m.group(1)
            if lid in queue_ids:
                # Find the entry to get name + author
                for entry in self._queue.levels:
                    if entry.id == lid:
                        tooltip_parts.append(f"{entry.name} by {entry.author} (ID: {lid})")
                        break
                msg.queue_level_ids.append(f"{lid}")

        # Replace tooltip_parts with richer info
        if tooltip_parts:
            msg.queue_level_ids = tooltip_parts

        self._view.add_message(msg)

    def update_queue(self) -> None:
        pass

    # Internal
    def _send_message(self) -> None:
        if not self._input or not self._chat_worker:
            return
        raw = self._input.text().strip()
        if not raw:
            return
        # Replace literal \n with actual newline... Twitch IRC strips newlines
        # but the worker's safe_message replaces them with spaces, which is fine.
        message = raw.replace("\\n", "\n")
        self._chat_worker._send_chat_message(message)
        self._input.clear()

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

        # Don't allow banning yourself
        if username.lower() == self._session.login.lower():
            QMessageBox.warning(self, "Ban User", "SON you cant ban yourself😭") # OG
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
