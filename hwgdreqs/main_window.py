import sys
from collections.abc import Callable

from PySide6.QtCore import QEventLoop, Qt, QThread, Signal, QUrl, QSize, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap, QFont, QIcon, QKeySequence, QShortcut, QAction
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
    QMessageBox,
    QDialog,
    QFrame,
    QGridLayout,
    QMenu,
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
from hwgdreqs.toast_notification import ToastNotification
from hwgdreqs.session_worker import SessionValidationWorker
from hwgdreqs.settings_dialog import SettingsDialog
from hwgdreqs.twitch_auth import TwitchSession, get_queue_command_enabled, load_session
from hwgdreqs.twitch_chat import TwitchChatWorker
from hwgdreqs.youtube_auth import load_youtube_session, save_youtube_session, YoutubeSession
from hwgdreqs.youtube_chat import YoutubeChatWorker
from hwgdreqs.config import asset_path, exec_dir
from hwgdreqs.chat_window import ChatWindow
from hwgdreqs.queue_popout_window import QueuePopoutWindow
from hwgdreqs.cloudflared import CloudflaredManager


class DraggableListWidget(QListWidget):
    model_reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        
        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.timeout.connect(self._on_hold_timeout)
        self._drag_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                self._drag_start_pos = event.position().toPoint()
                self.setDragEnabled(False)
                self._press_timer.start(1000)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos and not self.dragEnabled():
            delta = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            if delta > 10:
                self._press_timer.stop()
                self._drag_start_pos = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_timer.stop()
        self._drag_start_pos = None
        self.setDragEnabled(False)
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def _on_hold_timeout(self):
        if self._drag_start_pos:
            self.setDragEnabled(True)
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.setDragEnabled(False)
        self._drag_start_pos = None
        self.unsetCursor()
        self.model_reordered.emit()


class StatisticsDialog(QDialog):
    def __init__(self, queue: QueueManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.setModal(True)
        self.resize(500, 280)
        
        import time
        from datetime import datetime, date
        from collections import Counter
        
        today_date = date.today()
        
        def is_today(ts: float) -> bool:
            if ts <= 0.0:
                return False
            try:
                return datetime.fromtimestamp(ts).date() == today_date
            except Exception:
                return False

        all_entries = queue.levels + queue.level_history
        
        # Today
        today_entries = [e for e in all_entries if is_today(e.timestamp)]
        today_levels = len(today_entries)
        today_requesters = len(set(e.requester.lower() for e in today_entries))
        today_creators = len(set(e.author.lower() for e in today_entries))
        
        # Blacklisted requesters today
        blacklist_req_timestamps = queue._data.blacklist_timestamps.get("requesters", {})
        today_blacklisted_reqs = sum(1 for ts in blacklist_req_timestamps.values() if is_today(ts))
        
        # Most active requester today
        today_req_counts = Counter(e.requester for e in today_entries)
        if today_req_counts:
            most_active_today_req, _ = today_req_counts.most_common(1)[0]
            most_active_today = f'"{most_active_today_req}"'
        else:
            most_active_today = "N/A"
            
        # Always
        always_levels = len(all_entries)
        always_requesters = len(set(e.requester.lower() for e in all_entries))
        always_creators = len(set(e.author.lower() for e in all_entries))
        
        # Blacklisted requesters always
        always_blacklisted_reqs = len(queue.blacklist_requesters)
        
        # Most active requester always
        always_req_counts = Counter(e.requester for e in all_entries)
        if always_req_counts:
            most_active_always_req, _ = always_req_counts.most_common(1)[0]
            most_active_always = f'"{most_active_always_req}"'
        else:
            most_active_always = "N/A"
            
        main_layout = QVBoxLayout(self)
        
        grid = QGridLayout()
        grid.setSpacing(12)
        
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(11)
        
        today_hdr = QLabel("Today (today, not session):")
        today_hdr.setFont(header_font)
        grid.addWidget(today_hdr, 0, 0)
        
        always_hdr = QLabel("Always:")
        always_hdr.setFont(header_font)
        grid.addWidget(always_hdr, 0, 2)
        
        # Vertical separator
        vline = QFrame()
        vline.setFrameShape(QFrame.Shape.VLine)
        vline.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(vline, 0, 1, 6, 1)
        
        grid.addWidget(QLabel(f"{today_levels} levels so far"), 1, 0)
        grid.addWidget(QLabel(f"{always_levels} levels so far"), 1, 2)
        
        grid.addWidget(QLabel(f"{today_requesters} requesters so far"), 2, 0)
        grid.addWidget(QLabel(f"{always_requesters} requesters so far"), 2, 2)
        
        grid.addWidget(QLabel(f"{today_creators} creators so far"), 3, 0)
        grid.addWidget(QLabel(f"{always_creators} creators so far"), 3, 2)
        
        grid.addWidget(QLabel(f"{today_blacklisted_reqs} blacklisted requesters so far"), 4, 0)
        grid.addWidget(QLabel(f"{always_blacklisted_reqs} blacklisted requesters so far"), 4, 2)
        
        grid.addWidget(QLabel(f"most active requester {most_active_today}"), 5, 0)
        grid.addWidget(QLabel(f"most active requester {most_active_always}"), 5, 2)
        
        main_layout.addLayout(grid)
        main_layout.addSpacing(10)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)


class AutoClearingStatusBar(QStatusBar):
    def showMessage(self, message: str, timeout: int = 0) -> None:
        if message and timeout == 0:
            timeout = 5000
        super().showMessage(message, timeout)


class MainWindow(QMainWindow):
    def __init__(self, queue: QueueManager, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._session: TwitchSession | None = None
        self._kick_session = None
        self._youtube_session: YoutubeSession | None = None
        self._chat_worker: TwitchChatWorker | None = None
        self._kick_chat_worker = None
        self._youtube_chat_worker: YoutubeChatWorker | None = None
        self._twitch_connected = False
        self._kick_connected = False
        self._youtube_connected = False
        self._youtube_not_streaming = False
        self._network_manager = QNetworkAccessManager(self)
        self._current_pixmap = None
        self._thumbnail_cache: dict[str, QPixmap] = {}
        self._thumbnail_cache_order: list[str] = []
        self._api_server = ApiServer(queue)
        self._check_update_worker = None
        # Chat windows, lazily created, kept alive between openings
        self._twitch_chat_window: ChatWindow | None = None
        self._kick_chat_window: ChatWindow | None = None
        self._youtube_chat_window: ChatWindow | None = None
        # Queue popout window
        self._popout_window: QueuePopoutWindow | None = None
        
        self._aredl_cache: dict[str, int] | None = None
        self._aredl_fetching = False
        self._active_toast = None
        self._cloudflared = CloudflaredManager(self)

        self._queue.first_level_added.connect(self._show_toast)
        
        # Load platform icons
        self._twitch_icon = QIcon(str(asset_path("twitch.svg")))
        self._youtube_icon = QIcon(str(asset_path("youtube.svg")))
        self._kick_icon = QIcon(str(asset_path("kick.svg")))

        self.setWindowTitle("HwGDReqs")
        self.setMinimumSize(900, 520)
        
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        self._streamer_label = QLabel("Not connected to Twitch")
        header.addWidget(self._streamer_label)
        header.addStretch()
        self._refresh_youtube_btn = QPushButton("Refresh Youtube")
        self._refresh_youtube_btn.clicked.connect(self._refresh_youtube)
        header.addWidget(self._refresh_youtube_btn)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        
        self._get_form_link_btn = QPushButton("Get Form Link")
        self._get_form_link_btn.setToolTip("Expose your API and generate a form link")
        self._get_form_link_btn.clicked.connect(self._on_get_form_link_clicked)
        header.addWidget(self._get_form_link_btn)

        self._toggle_requests_btn = QPushButton("Disable requests" if self._queue.requests_enabled else "Enable requests")
        self._toggle_requests_btn.clicked.connect(self._toggle_requests)
        header.addWidget(self._toggle_requests_btn)

        self._chat_btn = QPushButton("Chat ▾")
        self._chat_btn.setToolTip("Show chat windows")
        self._chat_btn.clicked.connect(self._show_chat_menu)
        header.addWidget(self._chat_btn)

        self._popout_btn = QPushButton("popout Queue")
        self._popout_btn.setToolTip("Open queue popout window (for OBS capture)")
        self._popout_btn.clicked.connect(self._open_queue_popout)
        header.addWidget(self._popout_btn)

        root.addLayout(header)

        content_layout = QHBoxLayout()
        
        self._list = DraggableListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.model_reordered.connect(self._on_list_reordered)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        content_layout.addWidget(self._list, stretch=2)
        
        self._details_panel = QWidget()
        details_layout = QVBoxLayout(self._details_panel)
        
        # scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        self._thumbnail_label = QLabel()
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setMinimumSize(300, 300)
        self._thumbnail_label.hide()
        scroll_layout.addWidget(self._thumbnail_label)
        
        self._name_label = QLabel()
        self._name_label.setWordWrap(True)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        scroll_layout.addWidget(self._name_label)
        scroll_layout.addSpacing(10)
        
        self._author_label = QLabel()
        self._author_label.setWordWrap(True)
        scroll_layout.addWidget(self._author_label)
        scroll_layout.addSpacing(10)
        
        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        scroll_layout.addWidget(self._description_label)
        scroll_layout.addSpacing(10)
        
        self._sender_label = QLabel()
        self._sender_label.setWordWrap(True)
        scroll_layout.addWidget(self._sender_label)
        scroll_layout.addSpacing(10)
        
        self._timestamp_label = QLabel()
        self._timestamp_label.setWordWrap(True)
        scroll_layout.addWidget(self._timestamp_label)
        scroll_layout.addSpacing(10)
        
        self._difficulty_label = QLabel()
        self._difficulty_label.setWordWrap(True)
        scroll_layout.addWidget(self._difficulty_label)
        scroll_layout.addSpacing(10)
        
        self._platform_label = QLabel()
        self._platform_label.setWordWrap(True)
        scroll_layout.addWidget(self._platform_label)
        scroll_layout.addSpacing(10)
        
        self._message_label = QLabel()
        self._message_label.setWordWrap(True)
        scroll_layout.addWidget(self._message_label)
        scroll_layout.addSpacing(10)
        
        self._length_label = QLabel()
        self._length_label.setWordWrap(True)
        scroll_layout.addWidget(self._length_label)
        scroll_layout.addSpacing(10)
        
        self._aredl_rank_label = QLabel()
        self._aredl_rank_label.setWordWrap(True)
        self._aredl_rank_label.hide()
        scroll_layout.addWidget(self._aredl_rank_label)
        scroll_layout.addSpacing(10)
        
        self._tags_label = QLabel()
        self._tags_label.setWordWrap(True)
        scroll_layout.addWidget(self._tags_label)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        details_layout.addWidget(scroll)
        content_layout.addWidget(self._details_panel, stretch=1)
        
        root.addLayout(content_layout, stretch=1)


        actions = QHBoxLayout()
        self._copy_btn = QPushButton("Copy ID")
        self._delete_btn = QPushButton("Delete")
        self._blacklist_level_btn = QPushButton("Blacklist Level")
        self._blacklist_sender_btn = QPushButton("Blacklist Sender")
        self._blacklist_author_btn = QPushButton("Blacklist Author")
        self._ban_requester_btn = QPushButton("Ban Requester")
        self._shuffle_btn = QPushButton("Shuffle")
        self._clear_queue_btn = QPushButton("Clear Queue ▾")

        for btn in (
            self._copy_btn,
            self._delete_btn,
            self._blacklist_level_btn,
            self._blacklist_sender_btn,
            self._blacklist_author_btn,
            self._ban_requester_btn,
        ):
            btn.setEnabled(False)
            actions.addWidget(btn)
        
        self._ban_requester_btn.hide()
        
        actions.addWidget(self._shuffle_btn)
        actions.addWidget(self._clear_queue_btn)
        self._stats_btn = QPushButton("Statistics")
        self._stats_btn.clicked.connect(self._show_statistics)
        actions.addWidget(self._stats_btn)

        # Build the clear dropdown menu
        self._clear_menu = QMenu(self)
        self._clear_all_action = self._clear_menu.addAction("All")
        self._clear_menu.addSeparator()
        self._clear_by_requester_action = self._clear_menu.addAction("From (requester)")
        self._clear_by_author_action = self._clear_menu.addAction("From (author)")
        self._clear_by_requester_action.setVisible(False)
        self._clear_by_author_action.setVisible(False)

        self._clear_all_action.triggered.connect(self._queue.clear_queue)
        self._clear_by_requester_action.triggered.connect(self._clear_from_requester)
        self._clear_by_author_action.triggered.connect(self._clear_from_author)

        self._clear_queue_btn.clicked.connect(self._show_clear_menu)

        self._copy_btn.clicked.connect(self._copy_id)
        self._delete_btn.clicked.connect(self._delete_selected)
        self._blacklist_level_btn.clicked.connect(self._blacklist_level)
        self._blacklist_sender_btn.clicked.connect(self._blacklist_sender)
        self._blacklist_author_btn.clicked.connect(self._blacklist_author)
        self._ban_requester_btn.clicked.connect(self._ban_requester)
        self._shuffle_btn.clicked.connect(self._shuffle_queue)

        root.addLayout(actions)

        self.setStatusBar(AutoClearingStatusBar())
        self._queue.add_listener(self.refresh_queue)
        self._queue.add_listener(self._configure_api_server)
        self._queue.add_listener(self._refresh_popout_if_open)
        self.refresh_queue()
        self._set_action_buttons_enabled(False)

        # Shortcuts
        self._copy_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_C), self)
        self._copy_shortcut.activated.connect(self._copy_id)
        
        self._delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self._delete_shortcut.activated.connect(self._delete_selected)
        
        # conf and start API server
        self._configure_api_server()
        self._api_server.start()

    def _show_toast(self, entry) -> None:
        self._active_toast = ToastNotification(
            "New level to queue!",
            f"{entry.name} From {entry.requester}"
        )
        self._active_toast.show_toast()

    def _get_level_thumbnail(self, level_id: str) -> None:
        if level_id in self._thumbnail_cache:
            self._display_thumbnail(self._thumbnail_cache[level_id])
            return

        self._thumbnail_label.setText("Loading thumbnail...")
        self._thumbnail_label.show()
        
        req = QNetworkRequest(QUrl(f"https://raw.githubusercontent.com/cdc-sys/level-thumbnails/main/thumbs/{level_id}.png"))
        reply = self._network_manager.get(req)
        reply.finished.connect(lambda r=reply, lid=level_id: self._on_thumbnail_downloaded(r, lid))

    def _configure_api_server(self):
        self._api_server.set_config(
            self._queue.api_local_port,
            self._queue.api_host_to_network,
            self._queue.api_network_port
        )
        
    def _check_for_updates_on_startup(self):
        from hwgdreqs.updater import check_for_updates_on_startup
        check_for_updates_on_startup(self)
        
    def _check_internet(self) -> bool:
        import socket
        # connect to google twice
        for _ in range(2):
            try:
                socket.create_connection(("www.google.com", 80), timeout=2)
                return True
            except OSError:
                pass
        return False
        
    def startup(self, status_callback: Callable[[str], None] | None = None) -> bool:
        # check internet 1st
        if not self._check_internet():
            QMessageBox.warning(
                self,
                "No Internet",
                "You don't seem connected to the internet, please check your connection",
                QMessageBox.StandardButton.Close
            )
        result = self._ensure_session(status_callback)
        if result:
            # check updates after a short delay
            QTimer.singleShot(1000, self._check_for_updates_on_startup)
        return result

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

        from hwgdreqs.kick_auth import load_session as _load_kick_session
        kick_active = _load_kick_session() is not None

        if kick_active:
            msg = QMessageBox(self if self.isVisible() else None)
            msg.setWindowTitle("Kick Support Suspended")
            msg.setText("for Now kick support is temporarily down, if you (unlikely) happen to stream GD Level Requests to kick (why the fuck bro) just join the discord server and tell me, so i start reworking on it :3")
            
            logout_btn = msg.addButton("logout from kick", QMessageBox.ButtonRole.ActionRole)
            discord_btn = msg.addButton("join discord server", QMessageBox.ButtonRole.ActionRole)
            
            msg.exec()
            
            if msg.clickedButton() == discord_btn:
                import webbrowser
                webbrowser.open("https://discord.gg/9rXye9jdKD")
                
            from hwgdreqs.config import save_kick_auth
            save_kick_auth({})
            kick_active = False

        forms_active = bool(self._queue.forms_display_name.strip())

        if not session and not youtube_active and not kick_active and not forms_active:
            dialog = LoginDialog(None if not self.isVisible() else self, queue=self._queue)
            if dialog.exec() != LoginDialog.DialogCode.Accepted:
                return False
            
            session = dialog.session
            if dialog.youtube_session:
                save_youtube_session(dialog.youtube_session)
            if dialog.kick_session:
                from hwgdreqs.kick_auth import save_kick_auth
                save_kick_auth(dialog.kick_session.to_auth_dict())
                self._kick_session = dialog.kick_session
            
            forms_active = bool(self._queue.forms_display_name.strip())
            if (
                not session
                and not dialog.youtube_session
                and not dialog.kick_session
                and not forms_active
            ):
                return False
        
        self._apply_session(session)
        if self._queue.forms_display_name.strip():
            QTimer.singleShot(500, self._show_forms_link_notice)
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
        self._api_server.set_session(session)
        self._youtube_session = load_youtube_session()
        self._start_chat(session)

    def _show_forms_link_notice(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Form Links Aren't Persistent!")
        msg.setText(
            "Form links aren't persistent between sessions.\n\n"
            "Everytime you boot up the app, for forms to work:\n"
            "1. Click the \"Get Form Link\" button on top to expose your queue to the forms server.\n"
            "2. It'll tell you to visit a page — paste that link there and edit as your preferences.\n"
            "3. Then the form link will be active!"
        )
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _start_chat(self, session: TwitchSession | None) -> None:
        self._stop_chat()
        self._twitch_connected = False
        self._kick_connected = False
        self._youtube_connected = False
        self._youtube_not_streaming = False
        self._youtube_refreshing = False
        
        # Always reload YouTube and Kick sessions in case they were updated in settings
        self._youtube_session = load_youtube_session()
        from hwgdreqs.kick_auth import load_session as _load_kick_session
        self._kick_session = _load_kick_session()
        
        if session:
            self._chat_worker = TwitchChatWorker(
                session,
                self._queue,
                queue_command_enabled=get_queue_command_enabled(),
            )
            self._chat_worker.status_changed.connect(self._on_twitch_status_changed)
            self._chat_worker.connection_failed.connect(self._on_chat_failed)
            self._chat_worker.auth_failed.connect(self._on_chat_auth_failed)
            self._chat_worker.message_received.connect(self._on_twitch_message_received)
            self._chat_worker.start()
            self._twitch_connected = True

            from hwgdreqs.twitch_auth import has_chat_edit_scope, get_channel_moderate_enabled
            can_send = has_chat_edit_scope()
            can_ban = get_channel_moderate_enabled()
            if self._twitch_chat_window is None:
                self._twitch_chat_window = ChatWindow(
                    platform="twitch",
                    session=session,
                    chat_worker=self._chat_worker,
                    can_send=can_send,
                    can_ban=can_ban,
                    parent=None,
                )
            else:
                self._twitch_chat_window._session = session
                self._twitch_chat_window._chat_worker = self._chat_worker
                self._twitch_chat_window._can_send = can_send
                self._twitch_chat_window._can_ban = can_ban

        self._api_server.set_chat_callback(self._api_requests_chat_callback)

        if self._kick_session:
            from hwgdreqs.kick_chat import KickChatWorker
            from hwgdreqs.kick_auth import get_queue_command_enabled as get_kick_queue_command_enabled
            self._kick_chat_worker = KickChatWorker(
                self._kick_session,
                self._queue,
                queue_command_enabled=get_kick_queue_command_enabled(),
            )
            self._kick_chat_worker.status_changed.connect(self._on_kick_status_changed)
            self._kick_chat_worker.connection_failed.connect(self._on_kick_chat_failed)
            self._kick_chat_worker.auth_failed.connect(self._on_kick_chat_auth_failed)
            self._kick_chat_worker.message_received.connect(self._on_kick_message_received)
            self._kick_chat_worker.start()

            can_send = bool(self._kick_session.chat_edit_scope)
            can_ban = bool(self._kick_session.channel_moderate_enabled)
            if self._kick_chat_window is None:
                self._kick_chat_window = ChatWindow(
                    platform="kick",
                    session=self._kick_session,
                    chat_worker=self._kick_chat_worker,
                    can_send=can_send,
                    can_ban=can_ban,
                    parent=None,
                )
            else:
                self._kick_chat_window._session = self._kick_session
                self._kick_chat_window._chat_worker = self._kick_chat_worker
                self._kick_chat_window._can_send = can_send
                self._kick_chat_window._can_ban = can_ban
        
        if self._youtube_session:
            self._youtube_refreshing = True
            self._youtube_chat_worker = YoutubeChatWorker(self._youtube_session.username, self._queue)
            self._youtube_chat_worker.status_changed.connect(self._on_youtube_status_changed)
            self._youtube_chat_worker.connection_failed.connect(self._on_youtube_chat_failed)
            self._youtube_chat_worker.not_streaming.connect(self._on_youtube_not_streaming)
            self._youtube_chat_worker.message_received.connect(self._on_youtube_message_received)
            self._youtube_chat_worker.start()
        
        self._update_connection_label()
    
    def _update_connection_label(self) -> None:
        youtube_refreshing = getattr(self, "_youtube_refreshing", False)

        platforms = []
        if self._twitch_connected and self._session:
            platforms.append(f"Twitch: {self._session.display_name}")
        if self._kick_connected and self._kick_session:
            platforms.append(f"Kick: {self._kick_session.display_name}")
        if self._youtube_connected and self._youtube_session:
            platforms.append(f"YouTube: {self._youtube_session.username}")
        elif youtube_refreshing and self._youtube_session:
            platforms.append(f"YouTube: {self._youtube_session.username} (refreshing...)")
        elif self._youtube_not_streaming and self._youtube_session:
            platforms.append(f"YouTube: {self._youtube_session.username} (not streaming)")

        label = " | ".join(platforms) if platforms else "Not connected"
        self._streamer_label.setText(label)
    
    def _on_twitch_status_changed(self, message: str) -> None:
        if "Connected to" in message:
            self._twitch_connected = True
            self._update_connection_label()
    
    def _on_kick_status_changed(self, message: str) -> None:
        if "Connected to" in message:
            self._kick_connected = True
            self._update_connection_label()
    
    def _on_youtube_status_changed(self, message: str) -> None:
        if "Connected to YouTube" in message:
            self._youtube_connected = True
            self._youtube_not_streaming = False
            self._youtube_refreshing = False
            self._update_connection_label()
            if self._youtube_chat_window is None:
                self._youtube_chat_window = ChatWindow(
                    platform="youtube",
                    session=None,
                    chat_worker=self._youtube_chat_worker,
                    can_send=False,
                    can_ban=False,
                    parent=None,
                )
            else:
                self._youtube_chat_window._chat_worker = self._youtube_chat_worker
    
    def _on_youtube_not_streaming(self) -> None:
        was_refreshing = getattr(self, "_youtube_refreshing", False)
        self._youtube_not_streaming = True
        self._youtube_connected = False
        self._youtube_refreshing = False
        self._update_connection_label()
        
        if was_refreshing:
            username = self._youtube_session.username if self._youtube_session else "@youtube"
            QMessageBox.warning(
                self,
                "YouTube Chat",
                f"you {username} dont appear to be live, but we'll keep checking in the background."
            )

    def _stop_chat(self) -> None:
        if self._chat_worker:
            self._chat_worker.stop()
        self._chat_worker = None

        if self._kick_chat_worker:
            self._kick_chat_worker.stop()
        self._kick_chat_worker = None
        self._kick_connected = False
        
        if self._youtube_chat_worker:
            self._youtube_chat_worker.stop()
        self._youtube_chat_worker = None

    def _on_chat_failed(self, message: str) -> None:
        pass

    def _on_kick_chat_failed(self, message: str) -> None:
        self._kick_connected = False
        self._update_connection_label()

    def _on_youtube_chat_failed(self, message: str) -> None:
        self._youtube_connected = False
        self._youtube_not_streaming = False
        self._youtube_refreshing = False
        self._update_connection_label()

    def _on_chat_auth_failed(self) -> None:
        self._stop_chat()
        if not self.relogin("Twitch session expired. Log in again..."):
            self._session = None
            self._api_server.set_session(None)
            if self._youtube_session:
                self._streamer_label.setText(f"YouTube: {self._youtube_session.username}")
            else:
                self._streamer_label.setText("Not connected")

    def refresh_queue(self) -> None:
        selected_id = self._selected_entry().id if self._selected_entry() else None
        index_to_select = self._list.currentRow()
        self._list.clear()
        for index, entry in enumerate(self._queue.levels):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry)
            
            text = f'[{index+1}] "{entry.name}" by {entry.author}'
            platform_icon = None
            if entry.platform == "youtube":
                platform_icon = self._youtube_icon
            elif entry.platform == "twitch":
                platform_icon = self._twitch_icon
            elif entry.platform == "kick":
                platform_icon = self._kick_icon
            
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
        self._toggle_requests_btn.setText("Disable requests" if self._queue.requests_enabled else "Enable requests")
        if hasattr(self, '_get_form_link_btn'):
            self._get_form_link_btn.setVisible(bool(self._queue.forms_display_name))

    def _selected_entry(self) -> LevelEntry | None:
        item = self._list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self) -> None:
        entry = self._selected_entry()
        self._set_action_buttons_enabled(entry is not None)
        has_entry = entry is not None
        self._clear_by_requester_action.setVisible(has_entry)
        self._clear_by_author_action.setVisible(has_entry)
        if entry:
            self._clear_by_requester_action.setText(f'From requester "{entry.requester}"')
            self._clear_by_author_action.setText(f'From author "{entry.author}"')
            self._update_details(entry)
            if entry.platform == "twitch":
                self._ban_requester_btn.show()
            else:
                self._ban_requester_btn.hide()
        else:
            self._clear_details()
            self._ban_requester_btn.hide()

    def _update_details(self, entry: LevelEntry) -> None:
        self._name_label.setText(entry.name)
        self._author_label.setText(f"by '{entry.author}'")
        
        # add likes/downloads text
        if entry.disliked:
            likes_text = f"👎{entry.likes}"
        else:
            likes_text = f"👍{entry.likes}"
        downloads_text = f"⬇️{entry.downloads}"
        self._description_label.setText(f"{likes_text} {downloads_text}\ndescription: '{entry.description}'")
        
        self._sender_label.setText(f"from '{entry.requester}'")
        if entry.timestamp > 0:
            from datetime import datetime
            time_str = datetime.fromtimestamp(entry.timestamp).strftime("%I:%M %p").lstrip('0')
            self._timestamp_label.setText(f"timestamp: {time_str}")
        else:
            self._timestamp_label.setText("timestamp: Unknown")
        self._difficulty_label.setText(f"difficulty: {entry.difficulty}")
        self._platform_label.setText(f"platform: {entry.platform}")
        self._message_label.setText(f"message: '{entry.message}'")
        self._length_label.setText(f"length: '{entry.length}'")
        
        self._aredl_rank_label.hide()
        if entry.difficulty == "Extreme Demon":
            if self._aredl_cache is None:
                self._aredl_rank_label.setText("AREDL Rank: Loading...")
                self._aredl_rank_label.show()
                if not getattr(self, "_aredl_fetching", False):
                    self._fetch_aredl_list()
            else:
                rank = self._aredl_cache.get(str(entry.id))
                if rank:
                    self._aredl_rank_label.setText(f"AREDL Rank: #{rank}")
                    self._aredl_rank_label.show()
        
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
            self._thumbnail_label.show()
            self._thumbnail_label.setMinimumSize(0, 0)
            self._update_thumbnail()
            return

        self._thumbnail_label.hide()
        url = QUrl(f"https://levelthumbs.prevter.me/thumbnail/{entry.id}/small")
        request = QNetworkRequest(url)
        reply = self._network_manager.get(request)
        reply.finished.connect(lambda r=reply, level_id=entry.id: self._on_thumbnail_loaded(r, level_id))

    def _clear_details(self) -> None:
        self._name_label.clear()
        self._author_label.clear()
        self._description_label.clear()
        self._sender_label.clear()
        self._timestamp_label.clear()
        self._difficulty_label.clear()
        self._platform_label.clear()
        self._message_label.clear()
        self._length_label.clear()
        self._aredl_rank_label.clear()
        self._aredl_rank_label.hide()
        self._tags_label.clear()
        self._thumbnail_label.clear()
        self._thumbnail_label.hide()
        self._current_pixmap = None

    def _on_thumbnail_loaded(self, reply: QNetworkReply, level_id: str) -> None:
        # H5 fix: this reply may complete after the user has already selected a
        # different level. Only touch the cache/current pixmap/UI for THIS
        # level_id if it's still cache-worthy; only update the visible thumbnail
        # if the selection hasn't moved on to something else in the meantime.
        selected_entry = self._selected_entry()
        is_still_selected = selected_entry is not None and selected_entry.id == level_id

        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                cache_limit = max(0, int(self._queue.thumbnail_cache_size))
                if cache_limit > 0:
                    self._thumbnail_cache[level_id] = pixmap
                    if level_id in self._thumbnail_cache_order:
                        self._thumbnail_cache_order.remove(level_id)
                    self._thumbnail_cache_order.append(level_id)
                    while len(self._thumbnail_cache_order) > cache_limit:
                        old_id = self._thumbnail_cache_order.pop(0)
                        self._thumbnail_cache.pop(old_id, None)

                if is_still_selected:
                    self._current_pixmap = pixmap
                    self._thumbnail_label.show()
                    self._thumbnail_label.setMinimumSize(0, 0)
                    self._update_thumbnail()
            elif is_still_selected:
                self._current_pixmap = None
                self._thumbnail_label.hide()
        elif is_still_selected:
            self._current_pixmap = None
            self._thumbnail_label.hide()
        reply.deleteLater()

    def _fetch_aredl_list(self) -> None:
        self._aredl_fetching = True
        url = QUrl("https://api.aredl.net/v2/api/aredl/levels")
        request = QNetworkRequest(url)
        reply = self._network_manager.get(request)
        reply.finished.connect(lambda r=reply: self._on_aredl_loaded(r))

    def _on_aredl_loaded(self, reply: QNetworkReply) -> None:
        self._aredl_fetching = False
        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                import json
                data = json.loads(reply.readAll().data().decode('utf-8'))
                self._aredl_cache = {}
                for item in data:
                    self._aredl_cache[str(item.get("level_id"))] = item.get("position")
                
                entry = self._selected_entry()
                if entry and entry.difficulty == "Extreme Demon":
                    rank = self._aredl_cache.get(str(entry.id))
                    if rank:
                        self._aredl_rank_label.setText(f"AREDL Rank: #{rank}")
                    else:
                        self._aredl_rank_label.hide()
            except Exception as e:
                print("Failed to parse AREDL API response:", e)
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


    def _show_clear_menu(self) -> None:
        btn = self._clear_queue_btn
        self._clear_menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _clear_from_requester(self) -> None:
        entry = self._selected_entry()
        if entry:
            self._queue.clear_by_requester(entry.requester)

    def _clear_from_author(self) -> None:
        entry = self._selected_entry()
        if entry:
            self._queue.clear_by_author(entry.author)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        for btn in (
            self._copy_btn,
            self._delete_btn,
            self._blacklist_level_btn,
            self._blacklist_sender_btn,
            self._blacklist_author_btn,
            self._ban_requester_btn,
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
        if entry.requester2:
            self._queue.blacklist_requester2(entry.requester2)

    def _blacklist_author(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._queue.blacklist_author(entry.author)

    def _platform_ban_capability(self, platform: str):
        if platform == "twitch":
            from hwgdreqs.twitch_auth import get_channel_moderate_enabled, ban_twitch_user
            if not self._session or not get_channel_moderate_enabled():
                return None
            return self._session, ban_twitch_user, "Twitch"
        return None

    def _ban_requester(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return

        capability = self._platform_ban_capability(entry.platform)
        if capability is None:
            if entry.platform == "twitch":
                QMessageBox.warning(
                    self,
                    "Ban Requester",
                    "You must enable the option 'want to moderate chat to ban a requester...' in Twitch settings (and log in with it) to use this feature."
                )
            else:
                QMessageBox.warning(self, "Ban Requester", f"Banning is not supported for the '{entry.platform}' platform.")
            return

        session, ban_fn, label = capability
        if entry.requester.lower() == session.login.lower():
            QMessageBox.warning(self, "Ban Requester Failed", "SON you cant ban yourself😭")
            return

        reply = QMessageBox.question(
            self,
            "Ban Requester",
            f"Are you sure you want to ban '{entry.requester}' from your {label} channel?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            error = ban_fn(session, entry.requester)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if error:
            QMessageBox.warning(self, "Ban Requester Failed", f"Could not ban {entry.requester}:\n{error}")
        else:
            QMessageBox.information(self, "Ban Requester", f"Successfully banned '{entry.requester}' on {label}.")

    def _toggle_requests(self) -> None:
        self._queue.requests_enabled = not self._queue.requests_enabled
        self._toggle_requests_btn.setText("Disable requests" if self._queue.requests_enabled else "Enable requests")
        self._api_requests_chat_callback(self._queue.requests_enabled)

    def _api_requests_chat_callback(self, enabled: bool) -> None:
        if self._chat_worker and self._session and self._session.chat_edit_scope:
            if enabled:
                self._chat_worker._maybe_send("requests_toggle", f"[HwGDReqs] @{self._session.login} has enabled requests, any level sent from now on will be added")
            else:
                self._chat_worker._maybe_send("requests_toggle", f"[HwGDReqs] @{self._session.login} has disabled requests, any level sent from now on will not be added")

        if self._kick_chat_worker and self._kick_session and self._kick_session.chat_edit_scope:
            if enabled:
                self._kick_chat_worker._maybe_send("requests_toggle", f"[HwGDReqs] @{self._kick_session.login} has enabled requests, any level sent from now on will be added")
            else:
                self._kick_chat_worker._maybe_send("requests_toggle", f"[HwGDReqs] @{self._kick_session.login} has disabled requests, any level sent from now on will not be added")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self._queue,
            self._session.display_name if self._session else "",
            self._cloudflared,
            self,
        )
        dialog.logged_out.connect(self._on_logged_out)
        dialog.kick_logged_in.connect(self._on_kick_logged_in)
        dialog.kick_logged_out.connect(self._on_kick_logged_out)
        dialog.youtube_updated.connect(lambda: self._start_chat(self._session))
        dialog.twitch_logged_in.connect(self._on_twitch_logged_in)
        dialog.queue_command_changed.connect(self._on_queue_command_changed)
        dialog.kick_queue_command_changed.connect(self._on_kick_queue_command_changed)
        dialog.exec()
        self.refresh_queue()

    def _on_queue_command_changed(self, enabled: bool) -> None:
        if self._chat_worker:
            self._chat_worker.queue_command_enabled = enabled

    def _on_kick_queue_command_changed(self, enabled: bool) -> None:
        if self._kick_chat_worker:
            self._kick_chat_worker.queue_command_enabled = enabled

    def _on_twitch_logged_in(self, session: TwitchSession) -> None:
        self._apply_session(session)

    def _on_kick_logged_in(self, session) -> None:
        self._kick_session = session
        self._start_chat(self._session)

    def _on_kick_logged_out(self) -> None:
        self._kick_session = None
        if self._kick_chat_worker:
            self._kick_chat_worker.stop()
        self._kick_chat_worker = None
        self._kick_connected = False
        self._update_connection_label()

    def _on_logged_out(self) -> None:
        self._stop_chat()
        self._session = None
        self._api_server.set_session(None)
        self._streamer_label.setText("Not connected to Twitch")
        if not self.relogin("Logged out. Log in again to reconnect chat."):
            self.statusBar().showMessage("Not connected to Twitch.")

    def _on_list_reordered(self) -> None:
        new_levels = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry:
                new_levels.append(entry)
        self._queue.reorder_levels(new_levels)

    def _show_statistics(self) -> None:
        dialog = StatisticsDialog(self._queue, self)
        dialog.exec()

    def _shuffle_queue(self) -> None:
        if self._queue.levels:
            self._queue.shuffle_queue()
            self.statusBar().showMessage("Queue shuffled!")

    def _open_queue_popout(self) -> None:
        if self._popout_window is None:
            self._popout_window = QueuePopoutWindow(self._queue, parent=None)
        self._popout_window.show()
        self._popout_window.raise_()
        self._popout_window.activateWindow()

    def _refresh_popout_if_open(self) -> None:
        if self._popout_window is not None and self._popout_window.isVisible():
            self._popout_window.refresh()

    def _refresh_youtube(self) -> None:
        if self._youtube_chat_worker:
            self._youtube_chat_worker.stop()
            self._youtube_chat_worker = None
        
        self._youtube_connected = False
        self._youtube_not_streaming = False
        self._youtube_refreshing = False
        
        self._youtube_session = load_youtube_session()
        if self._youtube_session:
            self._youtube_refreshing = True
            self.statusBar().showMessage("Refreshing YouTube chat...")
            self._youtube_chat_worker = YoutubeChatWorker(self._youtube_session.username, self._queue)
            self._youtube_chat_worker.status_changed.connect(self._on_youtube_status_changed)
            self._youtube_chat_worker.connection_failed.connect(self._on_youtube_chat_failed)
            self._youtube_chat_worker.not_streaming.connect(self._on_youtube_not_streaming)
            self._youtube_chat_worker.message_received.connect(self._on_youtube_message_received)
            self._youtube_chat_worker.start()
            if self._youtube_chat_window:
                self._youtube_chat_window._chat_worker = self._youtube_chat_worker
        else:
            self.statusBar().showMessage("YouTube is not configured.")
        self._update_connection_label()

    def _show_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        self._list.setCurrentItem(item)

        menu = QMenu(self)

        copy_id_act = QAction("copy id", self)
        copy_id_act.triggered.connect(self._copy_id)
        menu.addAction(copy_id_act)

        idx = self._list.row(item)
        move_down_act = QAction("move down", self)
        move_down_act.setEnabled(idx < self._list.count() - 1)
        move_down_act.triggered.connect(lambda: self._move_level_down(entry.id))
        menu.addAction(move_down_act)

        move_up_act = QAction("move up", self)
        move_up_act.setEnabled(idx > 0)
        move_up_act.triggered.connect(lambda: self._move_level_up(entry.id))
        menu.addAction(move_up_act)

        menu.addSeparator()

        copy_req_act = QAction("copy requester", self)
        copy_req_act.triggered.connect(lambda: self._copy_text(entry.requester, "requester"))
        menu.addAction(copy_req_act)

        copy_name_act = QAction("copy name", self)
        copy_name_act.triggered.connect(lambda: self._copy_text(entry.name, "name"))
        menu.addAction(copy_name_act)

        copy_author_act = QAction("copy author", self)
        copy_author_act.triggered.connect(lambda: self._copy_text(entry.author, "author"))
        menu.addAction(copy_author_act)

        menu.addSeparator()

        delete_act = QAction("delete", self)
        delete_act.triggered.connect(self._delete_selected)
        menu.addAction(delete_act)

        del_req_act = QAction("delete all same requester", self)
        del_req_act.triggered.connect(lambda: self._delete_all_same_requester(entry.requester))
        menu.addAction(del_req_act)

        del_author_act = QAction("delete all same author", self)
        del_author_act.triggered.connect(lambda: self._delete_all_same_author(entry.author))
        menu.addAction(del_author_act)

        menu.addSeparator()

        bl_del_act = QAction("Blacklist Requester + Delete All Their Levels", self)
        bl_del_act.triggered.connect(lambda: self._blacklist_requester_and_delete_levels(entry.requester))
        menu.addAction(bl_del_act)

        is_bannable = self._platform_ban_capability(entry.platform) is not None

        ban_del_act = QAction("Ban Requester + Delete All Their Levels (Twitch only, moderation on)", self)
        ban_del_act.setEnabled(is_bannable)
        ban_del_act.triggered.connect(lambda: self._ban_requester_and_delete_levels(entry.requester, entry.platform))
        menu.addAction(ban_del_act)

        ban_bl_del_act = QAction("Ban+blacklist Requester + Delete All Their Levels (Twitch only, moderation on)", self)
        ban_bl_del_act.setEnabled(is_bannable)
        ban_bl_del_act.triggered.connect(lambda: self._ban_blacklist_requester_and_delete_levels(entry.requester, entry.platform))
        menu.addAction(ban_bl_del_act)

        menu.exec(self._list.mapToGlobal(pos))

    def _copy_text(self, text: str, label: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {label} to clipboard")

    def _move_level_up(self, level_id: str) -> None:
        self._queue.move_level_up(level_id)

    def _move_level_down(self, level_id: str) -> None:
        self._queue.move_level_down(level_id)

    def _delete_all_same_requester(self, requester: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete All Same Requester",
            f"Are you sure you want to delete all levels from requester '{requester}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._queue.remove_levels_by_requester(requester)
            self.statusBar().showMessage(f"Deleted all levels from '{requester}'")

    def _delete_all_same_author(self, author: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete All Same Author",
            f"Are you sure you want to delete all levels from author '{author}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._queue.remove_levels_by_author(author)
            self.statusBar().showMessage(f"Deleted all levels from author '{author}'")

    def _blacklist_requester_and_delete_levels(self, requester: str) -> None:
        reply = QMessageBox.question(
            self,
            "Blacklist and Delete Levels",
            f"Are you sure you want to blacklist '{requester}' and delete all their levels?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._queue.blacklist_requester(requester)
            for entry in list(self._queue.levels) + list(self._queue.level_history):
                if entry.requester.lower() == requester.lower() and entry.requester2:
                    self._queue.blacklist_requester2(entry.requester2)
                    break
            self._queue.remove_levels_by_requester(requester)
            self.statusBar().showMessage(f"Blacklisted '{requester}' and deleted their levels")

    def _ban_requester_and_delete_levels(self, requester: str, platform: str = "twitch") -> None:
        capability = self._platform_ban_capability(platform)
        if capability is None:
            if platform == "twitch":
                QMessageBox.warning(self, "Ban Requester Failed", "No active moderatable Twitch session found.")
            else:
                QMessageBox.warning(self, "Ban Requester Failed", f"Banning is not supported for the '{platform}' platform.")
            return
        session, ban_fn, label = capability

        if requester.lower() == session.login.lower():
            QMessageBox.warning(self, "Ban Requester Failed", "SON you cant ban yourself😭")
            return

        reply = QMessageBox.question(
            self,
            "Ban Requester and Delete Levels",
            f"Are you sure you want to ban '{requester}' on {label} and delete all their levels?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            error = ban_fn(session, requester)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if error:
            QMessageBox.warning(self, "Ban Requester Failed", f"Could not ban {requester}:\n{error}")
        else:
            self._queue.remove_levels_by_requester(requester)
            QMessageBox.information(self, "Ban Requester", f"Successfully banned '{requester}' and deleted all their levels.")

    def _ban_blacklist_requester_and_delete_levels(self, requester: str, platform: str = "twitch") -> None:
        capability = self._platform_ban_capability(platform)
        if capability is None:
            if platform == "twitch":
                QMessageBox.warning(self, "Ban & Blacklist Requester Failed", "No active moderatable Twitch session found.")
            else:
                QMessageBox.warning(self, "Ban & Blacklist Requester Failed", f"Banning is not supported for the '{platform}' platform.")
            return
        session, ban_fn, label = capability

        if requester.lower() == session.login.lower():
            QMessageBox.warning(self, "Ban & Blacklist Requester Failed", "SON you cant ban yourself😭")
            return

        reply = QMessageBox.question(
            self,
            "Ban & Blacklist Requester",
            f"Are you sure you want to ban '{requester}' on {label}, blacklist them locally, and delete all their levels?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            error = ban_fn(session, requester)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if error:
            QMessageBox.warning(self, "Ban Requester Failed", f"Could not ban {requester}:\n{error}")
        else:
            self._queue.blacklist_requester(requester)
            for entry in list(self._queue.levels) + list(self._queue.level_history):
                if entry.requester.lower() == requester.lower() and entry.requester2:
                    self._queue.blacklist_requester2(entry.requester2)
                    break
            self._queue.remove_levels_by_requester(requester)
            QMessageBox.information(self, "Ban & Blacklist Requester", f"Successfully banned & blacklisted '{requester}' and deleted all their levels.")


    def _on_twitch_message_received(self, username: str, message: str) -> None:
        if self._twitch_chat_window:
            self._twitch_chat_window.on_message(username, message)

    def _on_kick_message_received(self, username: str, message: str) -> None:
        if self._kick_chat_window:
            self._kick_chat_window.on_message(username, message)

    def _on_kick_chat_auth_failed(self) -> None:
        from hwgdreqs.kick_auth import refresh_session as refresh_kick_session

        if not self._kick_session:
            return

        refreshed = refresh_kick_session(self._kick_session)
        if refreshed:
            self._kick_session = refreshed
            if self._kick_chat_window:
                self._kick_chat_window._session = refreshed
            return

        self._kick_session = None
        self._kick_connected = False
        if self._kick_chat_worker:
            self._kick_chat_worker.stop()
        self._kick_chat_worker = None
        self._update_connection_label()

    def _on_youtube_message_received(self, username: str, message: str) -> None:
        if self._youtube_chat_window:
            self._youtube_chat_window.on_message(username, message)

    def _show_chat_menu(self) -> None:
        menu = QMenu(self)

        twitch_act = QAction("Show Twitch Chat", self)
        twitch_act.setEnabled(self._twitch_chat_window is not None)
        twitch_act.triggered.connect(self._open_twitch_chat)
        menu.addAction(twitch_act)

        kick_act = QAction("Show Kick Chat", self)
        kick_act.setEnabled(self._kick_chat_window is not None)
        kick_act.triggered.connect(self._open_kick_chat)
        menu.addAction(kick_act)

        youtube_act = QAction("Show YouTube Chat", self)
        youtube_act.setEnabled(self._youtube_chat_window is not None)
        youtube_act.triggered.connect(self._open_youtube_chat)
        menu.addAction(youtube_act)

        btn_pos = self._chat_btn.mapToGlobal(self._chat_btn.rect().bottomLeft())
        menu.exec(btn_pos)

    def _open_twitch_chat(self) -> None:
        if self._twitch_chat_window is None:
            return
        self._twitch_chat_window.show()
        self._twitch_chat_window.raise_()
        self._twitch_chat_window.activateWindow()

    def _open_kick_chat(self) -> None:
        if self._kick_chat_window is None:
            return
        self._kick_chat_window.show()
        self._kick_chat_window.raise_()
        self._kick_chat_window.activateWindow()

    def _open_youtube_chat(self) -> None:
        if self._youtube_chat_window is None:
            return
        self._youtube_chat_window.show()
        self._youtube_chat_window.raise_()
        self._youtube_chat_window.activateWindow()

    def closeEvent(self, event) -> None:
        self._stop_chat()
        self._api_server.stop()
        self._cloudflared.stop()
        # kill chat window
        if self._twitch_chat_window:
            self._twitch_chat_window.close()
        if self._kick_chat_window:
            self._kick_chat_window.close()
        if self._youtube_chat_window:
            self._youtube_chat_window.close()
        # kill popout window
        if self._popout_window:
            self._popout_window.shutdown()
        super().closeEvent(event)

    def _on_get_form_link_clicked(self) -> None:
        if not self._cloudflared.is_installed():
            msg = QMessageBox(self)
            msg.setWindowTitle("Dependency Missing")
            if sys.platform == "win32":
                msg.setText("This feature needs a dependency Cloudflare Tunnel which is not installed, please insatll it to continue using this")
                dl_btn = msg.addButton("Download", QMessageBox.ButtonRole.ActionRole)
                cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                if msg.clickedButton() == dl_btn:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.msi"))
            else: # linux
                msg.setText("This feature needs a dependency Cloudflare Tunnel which is not installed, please insatll it to continue using this using your distro's instructions")
                how_btn = msg.addButton("How", QMessageBox.ButtonRole.ActionRole)
                cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                if msg.clickedButton() == how_btn:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl("https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/#linux"))
            return

        if self._cloudflared.is_running() and self._cloudflared._url:
            self._handle_form_link_ready(self._cloudflared._url)
            return

        from PySide6.QtWidgets import QProgressDialog
        self._cloudflared_progress = QProgressDialog("Starting Cloudflare Tunnel...", "Cancel", 0, 0, self)
        self._cloudflared_progress.setWindowTitle("Please Wait")
        self._cloudflared_progress.setModal(True)
        self._cloudflared_progress.canceled.connect(self._cloudflared.stop)
        
        # Connect to link ready
        self._cloudflared.link_ready.connect(self._on_form_cloudflared_link)
        self._cloudflared.stopped.connect(self._on_form_cloudflared_stopped)
        
        self._cloudflared.start(self._queue.api_local_port)
        self._cloudflared_progress.exec()

    def _on_form_cloudflared_link(self, url: str) -> None:
        try:
            self._cloudflared.link_ready.disconnect(self._on_form_cloudflared_link)
            self._cloudflared.stopped.disconnect(self._on_form_cloudflared_stopped)
        except Exception:
            pass
        if hasattr(self, '_cloudflared_progress') and self._cloudflared_progress:
            self._cloudflared_progress.accept()
            self._cloudflared_progress = None
        self._handle_form_link_ready(url)

    def _on_form_cloudflared_stopped(self) -> None:
        try:
            self._cloudflared.link_ready.disconnect(self._on_form_cloudflared_link)
            self._cloudflared.stopped.disconnect(self._on_form_cloudflared_stopped)
        except Exception:
            pass
        if hasattr(self, '_cloudflared_progress') and self._cloudflared_progress:
            self._cloudflared_progress.reject()
            self._cloudflared_progress = None
        QMessageBox.warning(self, "Error", "Cloudflare Tunnel failed to start or was stopped.")

    def _handle_form_link_ready(self, url: str) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        import urllib.parse
        
        QGuiApplication.clipboard().setText(url)
        
        msg = QMessageBox(self)
        msg.setWindowTitle("API Link Ready!")
        msg.setText("The queue access link is copied to your clipboard.\n\nOpen the forms setup page and paste it there along with your preferences.")
        
        open_btn = msg.addButton("Open Setup", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg.exec()
        
        if msg.clickedButton() == open_btn:
            alias = urllib.parse.quote(self._queue.forms_display_name)
            QDesktopServices.openUrl(QUrl(f"https://hwgdreqs-forms.gamer.gd/?alias={alias}"))