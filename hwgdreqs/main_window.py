import sys
from collections.abc import Callable

from PySide6.QtCore import QEventLoop, Qt, QThread, Signal, QUrl, QSize
from PySide6.QtGui import QGuiApplication, QPixmap, QFont, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
    QScrollArea,
    QSizePolicy,
)


class QueueListItemWidget(QWidget):
    def __init__(self, text: str, platform_icon: QIcon | None, difficulty: str):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # difficulti
        difficulty_icon_map = {
            "Unrated": "unrated.png",
            "Auto": "auto.png",
            "Easy": "easy.png",
            "Normal": "normal.png",
            "Hard": "hard.png",
            "Harder": "harder.png",
            "Insane": "insane.png",
        }
        
        # chek if it's demon
        if difficulty.endswith("Demon"):
            icon_filename = "demon.png"
        else:
            icon_filename = difficulty_icon_map.get(difficulty, "unrated.png")  # fallllllllbak
        
        difficulty_icon_path = asset_path(icon_filename)
        if difficulty_icon_path.exists():
            self.difficulty_icon_label = QLabel()
            difficulty_pixmap = QPixmap(str(difficulty_icon_path))
            self.difficulty_icon_label.setPixmap(difficulty_pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(self.difficulty_icon_label)
        
        self.text_label = QLabel(text)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.text_label)
        
        if platform_icon:
            self.platform_icon_label = QLabel()
            self.platform_icon_label.setPixmap(platform_icon.pixmap(24, 24))
            layout.addWidget(self.platform_icon_label)


from hwgdreqs.login_dialog import LoginDialog
from hwgdreqs.api_server import ApiServer
from hwgdreqs.queue_manager import LevelEntry, QueueManager
from hwgdreqs.session_worker import SessionValidationWorker
from hwgdreqs.settings_dialog import SettingsDialog
from hwgdreqs.twitch_auth import TwitchSession, get_queue_command_enabled, load_session
from hwgdreqs.twitch_chat import TwitchChatWorker
from hwgdreqs.youtube_auth import load_youtube_session, save_youtube_session, YoutubeSession
from hwgdreqs.youtube_chat import YoutubeChatWorker
from hwgdreqs.config import asset_path


class MainWindow(QMainWindow):
    def __init__(self, queue: QueueManager, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._session: TwitchSession | None = None
        self._youtube_session: YoutubeSession | None = None
        self._chat_worker: TwitchChatWorker | None = None
        self._youtube_chat_worker: YoutubeChatWorker | None = None
        self._twitch_connected = False
        self._youtube_connected = False
        self._youtube_not_streaming = False
        self._network_manager = QNetworkAccessManager(self)
        self._current_pixmap = None
        self._thumbnail_cache: dict[str, QPixmap] = {}
        self._thumbnail_cache_order: list[str] = []
        self._api_server = ApiServer(queue)
        
        # Load platform icons
        self._twitch_icon = QIcon(str(asset_path("twitch.svg")))
        self._youtube_icon = QIcon(str(asset_path("youtube.svg")))

        self.setWindowTitle("HwGDReqs")
        self.setMinimumSize(900, 520)
        
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        self._streamer_label = QLabel("Not connected to Twitch")
        header.addWidget(self._streamer_label)
        header.addStretch()
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        content_layout = QHBoxLayout()
        
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self._list, stretch=2)
        
        self._details_panel = QWidget()
        details_layout = QVBoxLayout(self._details_panel)
        
        self._thumbnail_label = QLabel()
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setMinimumSize(300, 300)
        details_layout.addWidget(self._thumbnail_label)
        
        self._name_label = QLabel()
        self._name_label.setWordWrap(True)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        details_layout.addWidget(self._name_label)
        details_layout.addSpacing(10)
        
        self._author_label = QLabel()
        self._author_label.setWordWrap(True)
        details_layout.addWidget(self._author_label)
        details_layout.addSpacing(10)
        
        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        details_layout.addWidget(self._description_label)
        details_layout.addSpacing(10)
        
        self._sender_label = QLabel()
        self._sender_label.setWordWrap(True)
        details_layout.addWidget(self._sender_label)
        details_layout.addSpacing(10)
        
        self._difficulty_label = QLabel()
        self._difficulty_label.setWordWrap(True)
        details_layout.addWidget(self._difficulty_label)
        details_layout.addSpacing(10)
        
        self._platform_label = QLabel()
        self._platform_label.setWordWrap(True)
        details_layout.addWidget(self._platform_label)
        details_layout.addSpacing(10)
        
        self._message_label = QLabel()
        self._message_label.setWordWrap(True)
        details_layout.addWidget(self._message_label)
        details_layout.addSpacing(10)
        
        self._length_label = QLabel()
        self._length_label.setWordWrap(True)
        details_layout.addWidget(self._length_label)
        details_layout.addSpacing(10)
        
        self._tags_label = QLabel()
        self._tags_label.setWordWrap(True)
        details_layout.addWidget(self._tags_label)
        
        details_layout.addStretch()
        content_layout.addWidget(self._details_panel, stretch=1)
        
        root.addLayout(content_layout, stretch=1)


        actions = QHBoxLayout()
        self._copy_btn = QPushButton("Copy ID")
        self._delete_btn = QPushButton("Delete")
        self._blacklist_level_btn = QPushButton("Blacklist Level")
        self._blacklist_sender_btn = QPushButton("Blacklist Sender")
        self._blacklist_author_btn = QPushButton("Blacklist Author")
        self._clear_queue_btn = QPushButton("Clear Queue")

        for btn in (
            self._copy_btn,
            self._delete_btn,
            self._blacklist_level_btn,
            self._blacklist_sender_btn,
            self._blacklist_author_btn,
        ):
            btn.setEnabled(False)
            actions.addWidget(btn)
        
        actions.addWidget(self._clear_queue_btn)

        self._copy_btn.clicked.connect(self._copy_id)
        self._delete_btn.clicked.connect(self._delete_selected)
        self._blacklist_level_btn.clicked.connect(self._blacklist_level)
        self._blacklist_sender_btn.clicked.connect(self._blacklist_sender)
        self._blacklist_author_btn.clicked.connect(self._blacklist_author)
        self._clear_queue_btn.clicked.connect(self._queue.clear_queue)

        root.addLayout(actions)

        self.setStatusBar(QStatusBar())
        self._queue.add_listener(self.refresh_queue)
        self.refresh_queue()
        self._set_action_buttons_enabled(False)

        self._api_server.start()

    def startup(self, status_callback: Callable[[str], None] | None = None) -> bool:
        return self._ensure_session(status_callback)

    def relogin(self, status_message: str = "Log in to Twitch to continue.") -> bool:
        return self._ensure_session(self.statusBar().showMessage, status_message)

    def _ensure_session(
        self,
        status_callback: Callable[[str], None] | None = None,
        intro_message: str | None = None,
    ) -> bool:
        report = status_callback or self.statusBar().showMessage
        if intro_message:
            report(intro_message)

        session = None
        if load_session():
            session = self._poll_saved_session(report)
        
        youtube_session = load_youtube_session()
        youtube_active = youtube_session is not None and bool(youtube_session.username)

        if not session and not youtube_active:
            dialog = LoginDialog(None if not self.isVisible() else self)
            if dialog.exec() != LoginDialog.DialogCode.Accepted:
                return False
            
            session = dialog.session
            if dialog.youtube_session:
                save_youtube_session(dialog.youtube_session)
            
            if not session and not dialog.youtube_session:
                return False
        
        self._apply_session(session)
        return True

    def _poll_saved_session(
        self,
        status_callback: Callable[[str], None],
    ) -> TwitchSession | None:
        loop = QEventLoop()
        worker = SessionValidationWorker(self)
        result: dict[str, TwitchSession | None] = {"session": None}

        worker.validation_complete.connect(
            lambda session: self._finish_session_poll(worker, loop, result, session)
        )
        worker.validation_failed.connect(
            lambda: self._finish_session_poll(worker, loop, result, None)
        )
        worker.auth_status.connect(status_callback)
        worker.start()
        loop.exec()
        worker.wait(5000)
        return result["session"]

    def _finish_session_poll(
        self,
        worker: SessionValidationWorker,
        loop: QEventLoop,
        result: dict[str, TwitchSession | None],
        session: TwitchSession | None,
    ) -> None:
        result["session"] = session
        loop.quit()

    def _apply_session(self, session: TwitchSession | None) -> None:
        self._session = session
        self._youtube_session = load_youtube_session()
        self._start_chat(session)

    def _start_chat(self, session: TwitchSession | None) -> None:
        self._stop_chat()
        self._twitch_connected = False
        self._youtube_connected = False
        self._youtube_not_streaming = False
        
        # Always reload YouTube session in case it was just updated in settings
        self._youtube_session = load_youtube_session()
        
        if session:
            self._chat_worker = TwitchChatWorker(
                session,
                self._queue,
                queue_command_enabled=get_queue_command_enabled(),
            )
            self._chat_worker.status_changed.connect(self._on_twitch_status_changed)
            self._chat_worker.connection_failed.connect(self._on_chat_failed)
            self._chat_worker.auth_failed.connect(self._on_chat_auth_failed)
            self._chat_worker.start()
            self._twitch_connected = True
        
        if self._youtube_session:
            self._youtube_chat_worker = YoutubeChatWorker(self._youtube_session.username, self._queue)
            self._youtube_chat_worker.status_changed.connect(self._on_youtube_status_changed)
            self._youtube_chat_worker.connection_failed.connect(self._on_youtube_chat_failed)
            self._youtube_chat_worker.not_streaming.connect(self._on_youtube_not_streaming)
            self._youtube_chat_worker.start()
        
        self._update_connection_label()
    
    def _update_connection_label(self) -> None:

        if self._twitch_connected and self._youtube_connected:
            label = f"Streamer: {self._session.display_name} (+ YouTube: {self._youtube_session.username})"
        elif self._twitch_connected and self._youtube_not_streaming:
            label = f"Streamer: {self._session.display_name} | YouTube not streaming"
        elif self._twitch_connected:
            label = f"Streamer: {self._session.display_name}"
        elif self._youtube_connected:
            label = f"Connected to YouTube: {self._youtube_session.username}"
        elif self._youtube_not_streaming:
            label = f"YouTube: {self._youtube_session.username} (not streaming)"
        else:
            label = "Not connected"
        
        self._streamer_label.setText(label)
    
    def _on_twitch_status_changed(self, message: str) -> None:
        if "Connected to" in message:
            self._twitch_connected = True
            self._update_connection_label()
    
    def _on_youtube_status_changed(self, message: str) -> None:
        if "Connected to YouTube" in message:
            self._youtube_connected = True
            self._youtube_not_streaming = False
            self._update_connection_label()
    
    def _on_youtube_not_streaming(self) -> None:
        self._youtube_not_streaming = True
        self._youtube_connected = False
        self._update_connection_label()

    def _stop_chat(self) -> None:
        if self._chat_worker:
            self._chat_worker.stop()
        self._chat_worker = None
        
        if self._youtube_chat_worker:
            self._youtube_chat_worker.stop()
        self._youtube_chat_worker = None

    def _on_chat_failed(self, message: str) -> None:
        pass

    def _on_youtube_chat_failed(self, message: str) -> None:
        pass

    def _on_chat_auth_failed(self) -> None:
        self._stop_chat()
        if not self.relogin("Twitch session expired. Log in again..."):
            self._session = None
            if self._youtube_session:
                self._streamer_label.setText(f"YouTube: {self._youtube_session.username}")
            else:
                self._streamer_label.setText("Not connected")

    def refresh_queue(self) -> None:
        selected_id = self._selected_entry().id if self._selected_entry() else None
        index_to_select = self._list.currentRow()
        self._list.clear()
        for entry in self._queue.levels:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry)
            
            text = f'"{entry.name}" by {entry.author}'
            platform_icon = None
            if entry.platform == "youtube":
                platform_icon = self._youtube_icon
            elif entry.platform == "twitch":
                platform_icon = self._twitch_icon
            
            widget = QueueListItemWidget(text, platform_icon, entry.difficulty)
            item.setSizeHint(widget.sizeHint())
            
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)
            
            if selected_id and entry.id == selected_id:
                self._list.setCurrentItem(item)
        if self._list.count() > 0 and not selected_id:
            if index_to_select >= self._list.count():
                index_to_select = self._list.count() - 1
            if index_to_select >= 0:
                self._list.setCurrentRow(index_to_select)

    def _selected_entry(self) -> LevelEntry | None:
        item = self._list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self) -> None:
        entry = self._selected_entry()
        self._set_action_buttons_enabled(entry is not None)
        if entry:
            self._update_details(entry)
        else:
            self._clear_details()

    def _update_details(self, entry: LevelEntry) -> None:
        self._name_label.setText(entry.name)
        self._author_label.setText(f"by \"{entry.author}\"")
        self._description_label.setText(f"description: \"{entry.description}\"")
        self._sender_label.setText(f"from \"{entry.requester}\"")
        self._difficulty_label.setText(f"difficulty: {entry.difficulty}")
        self._platform_label.clear()
        self._message_label.setText(f"message: \"{entry.message}\"")
        self._length_label.setText(f"length: \"{entry.length}\"")
        
        tags_text = ""
        if entry.large:
            tags_text += "+40k objs"
        if entry.two_player:
            if tags_text:
                tags_text += "\n"
            tags_text += "2 player"
        self._tags_label.setText(tags_text)
        
        cache_limit = max(0, int(self._queue.thumbnail_cache_size))
        if cache_limit > 0 and entry.id in self._thumbnail_cache:
            self._current_pixmap = self._thumbnail_cache[entry.id]
            if entry.id in self._thumbnail_cache_order:
                self._thumbnail_cache_order.remove(entry.id)
            self._thumbnail_cache_order.append(entry.id)
            self._update_thumbnail()
            return

        url = QUrl(f"https://levelthumbs.prevter.me/thumbnail/{entry.id}/small")
        request = QNetworkRequest(url)
        reply = self._network_manager.get(request)
        reply.finished.connect(lambda r=reply, level_id=entry.id: self._on_thumbnail_loaded(r, level_id))

    def _clear_details(self) -> None:
        self._name_label.clear()
        self._author_label.clear()
        self._description_label.clear()
        self._sender_label.clear()
        self._difficulty_label.clear()
        self._platform_label.clear()
        self._message_label.clear()
        self._length_label.clear()
        self._tags_label.clear()
        self._thumbnail_label.clear()
        self._current_pixmap = None

    def _on_thumbnail_loaded(self, reply: QNetworkReply, level_id: str) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._current_pixmap = pixmap
                cache_limit = max(0, int(self._queue.thumbnail_cache_size))
                if cache_limit > 0:
                    self._thumbnail_cache[level_id] = pixmap
                    if level_id in self._thumbnail_cache_order:
                        self._thumbnail_cache_order.remove(level_id)
                    self._thumbnail_cache_order.append(level_id)
                    while len(self._thumbnail_cache_order) > cache_limit:
                        old_id = self._thumbnail_cache_order.pop(0)
                        self._thumbnail_cache.pop(old_id, None)
                self._update_thumbnail()
            else:
                self._current_pixmap = None
                self._thumbnail_label.clear()
        else:
            self._current_pixmap = None
            self._thumbnail_label.clear()
        reply.deleteLater()

    def _update_thumbnail(self):
        if self._current_pixmap:
            panel_width = self._details_panel.width()
            self._thumbnail_label.setPixmap(self._current_pixmap.scaledToWidth(
                max(200, panel_width - 40),
                Qt.TransformationMode.SmoothTransformation
            ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumbnail()


    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        for btn in (
            self._copy_btn,
            self._delete_btn,
            self._blacklist_level_btn,
            self._blacklist_sender_btn,
            self._blacklist_author_btn,
        ):
            btn.setEnabled(enabled)

    def _copy_id(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        QGuiApplication.clipboard().setText(entry.id)
        self.statusBar().showMessage(f"Copied level ID {entry.id}")

    def _delete_selected(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._queue.remove_level(entry.id)

    def _blacklist_level(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._queue.blacklist_level(entry.id)

    def _blacklist_sender(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._queue.blacklist_requester(entry.requester)

    def _blacklist_author(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._queue.blacklist_author(entry.author)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self._queue,
            self._session.display_name if self._session else "",
            self,
        )
        dialog.logged_out.connect(self._on_logged_out)
        dialog.youtube_updated.connect(lambda: self._start_chat(self._session))
        dialog.queue_command_changed.connect(self._on_queue_command_changed)
        dialog.exec()
        self.refresh_queue()

    def _on_queue_command_changed(self, enabled: bool) -> None:
        if self._chat_worker:
            self._chat_worker.queue_command_enabled = enabled

    def _on_logged_out(self) -> None:
        self._stop_chat()
        self._session = None
        self._streamer_label.setText("Not connected to Twitch")
        if not self.relogin("Logged out. Log in again to reconnect chat."):
            self.statusBar().showMessage("Not connected to Twitch.")

    def closeEvent(self, event) -> None:
        self._stop_chat()
        self._api_server.stop()
        super().closeEvent(event)
