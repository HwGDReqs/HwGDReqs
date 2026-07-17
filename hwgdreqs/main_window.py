import sys
from collections.abc import Callable

from PySide6.QtCore import QEventLoop, Qt, QThread, Signal, QUrl, QSize, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap, QFont, QIcon, QKeySequence, QShortcut
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
from hwgdreqs.config import asset_path, exec_dir


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
        self._check_update_worker = None
        
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
        self._refresh_youtube_btn = QPushButton("Refresh Youtube")
        self._refresh_youtube_btn.clicked.connect(self._refresh_youtube)
        header.addWidget(self._refresh_youtube_btn)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        content_layout = QHBoxLayout()
        
        self._list = DraggableListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.model_reordered.connect(self._on_list_reordered)
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
        
        self._timestamp_label = QLabel()
        self._timestamp_label.setWordWrap(True)
        details_layout.addWidget(self._timestamp_label)
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
        self._ban_requester_btn = QPushButton("Ban Requester")
        self._clear_queue_btn = QPushButton("Clear Queue")

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
        
        actions.addWidget(self._clear_queue_btn)
        self._stats_btn = QPushButton("Statistics")
        self._stats_btn.clicked.connect(self._show_statistics)
        actions.addWidget(self._stats_btn)

        self._copy_btn.clicked.connect(self._copy_id)
        self._delete_btn.clicked.connect(self._delete_selected)
        self._blacklist_level_btn.clicked.connect(self._blacklist_level)
        self._blacklist_sender_btn.clicked.connect(self._blacklist_sender)
        self._blacklist_author_btn.clicked.connect(self._blacklist_author)
        self._ban_requester_btn.clicked.connect(self._ban_requester)
        self._clear_queue_btn.clicked.connect(self._queue.clear_queue)

        root.addLayout(actions)

        self.setStatusBar(QStatusBar())
        self._queue.add_listener(self.refresh_queue)
        self._queue.add_listener(self._configure_api_server)
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

    def _configure_api_server(self):
        self._api_server.set_config(
            self._queue.api_local_port,
            self._queue.api_host_to_network,
            self._queue.api_network_port
        )
        
    def _check_for_updates_on_startup(self):
        from hwgdreqs.settings_dialog import UpdateCheckerWorker, APP_VERSION
        import sys
        
        self._check_update_worker = UpdateCheckerWorker(self)
        
        def on_finished(latest_version, download_url):
            norm_latest = latest_version.strip().lower().lstrip('v')
            norm_current = APP_VERSION.strip().lower().lstrip('v')
            
            if norm_latest != norm_current:
                if sys.platform == "win32":
                    from hwgdreqs.settings_dialog import UpdateDownloadWorker, tempfile, QProgressDialog, Qt, QTimer, subprocess, QApplication
                    reply = QMessageBox.question(
                        self,
                        "Update Available",
                        f"There is an update ({latest_version}), want to download and install?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        self._download_update_for_startup(download_url)
                elif sys.platform.startswith("linux"):
                    reply = QMessageBox.question(
                        self,
                        "Update Available",
                        f"There is an update ({latest_version}). To update, please run:\n\ncurl https://hwgdreqs.github.io/install.sh | bash\n\nWould you like to copy this command to clipboard?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        QGuiApplication.clipboard().setText("curl https://hwgdreqs.github.io/install.sh | bash")
                        QMessageBox.information(self, "Copied!", "Command copied to clipboard!")
                else:
                    QMessageBox.information(
                        self,
                        "Update Available",
                        f"There is an update ({latest_version}). Please update manually.\nIf you installed via pip, run:\n\npip install --upgrade hwgdreqs"
                    )
        
        self._check_update_worker.finished.connect(on_finished)
        self._check_update_worker.start()
        
    def _download_update_for_startup(self, download_url):
        import tempfile
        import os
        from hwgdreqs.settings_dialog import UpdateDownloadWorker
        import subprocess
        
        tmp_dir = tempfile.gettempdir()
        dest_file = os.path.join(tmp_dir, "hwgdreqs-windows-portable.zip")
        
        progress_dialog = QProgressDialog("Downloading update...", "Cancel", 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)
        
        download_worker = UpdateDownloadWorker(download_url, dest_file, self)
        
        def cancel_download():
            download_worker.cancel()
            download_worker.wait()
        
        progress_dialog.canceled.connect(cancel_download)
        download_worker.progress.connect(progress_dialog.setValue)
        
        def on_download_finished():
            progress_dialog.close()
            
            QMessageBox.information(self, "Download Complete!", "Download complete. Launching updater in 2 seconds...")
            
            def run_updater():
                updater_path = exec_dir() / "updater" / "updater.bat"
                try:
                    subprocess.Popen([str(updater_path)], cwd=str(exec_dir()))
                except Exception:
                    pass
                
                QApplication.quit()
                import sys
                sys.exit(0)
                
            QTimer.singleShot(2000, run_updater)
            
        def on_download_error(error_msg):
            progress_dialog.close()
            QMessageBox.warning(
                self,
                "Download Failed",
                f"An error occurred while downloading the update:\n{error_msg}"
            )
        
        download_worker.finished.connect(on_download_finished)
        download_worker.error.connect(on_download_error)
        download_worker.start()
        
    def startup(self, status_callback: Callable[[str], None] | None = None) -> bool:
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
        self._api_server.set_session(session)
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
        
        username = self._youtube_session.username if self._youtube_session else "@youtube"
        QMessageBox.warning(
            self,
            "YouTube Chat",
            f"you {username} dont appear to be live, when u become live click Refresh Youtube on top right to recheck"
        )

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
            if entry.platform == "twitch":
                self._ban_requester_btn.show()
            else:
                self._ban_requester_btn.hide()
        else:
            self._clear_details()
            self._ban_requester_btn.hide()

    def _update_details(self, entry: LevelEntry) -> None:
        self._name_label.setText(entry.name)
        self._author_label.setText(f"by \"{entry.author}\"")
        self._description_label.setText(f"description: \"{entry.description}\"")
        self._sender_label.setText(f"from \"{entry.requester}\"")
        if entry.timestamp > 0:
            from datetime import datetime
            time_str = datetime.fromtimestamp(entry.timestamp).strftime("%I:%M %p").lstrip('0')
            self._timestamp_label.setText(f"timestamp: {time_str}")
        else:
            self._timestamp_label.setText("timestamp: Unknown")
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
        self._timestamp_label.clear()
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

    def _blacklist_author(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._queue.blacklist_author(entry.author)

    def _ban_requester(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.platform != "twitch":
            return

        session = self._session
        if not session:
            QMessageBox.warning(self, "Ban Requester", "No active Twitch session found.")
            return

        if entry.requester.lower() == session.login.lower():
            QMessageBox.warning(self, "Ban Requester Failed", "SON you cant ban yourself😭")
            return

        from hwgdreqs.twitch_auth import get_channel_moderate_enabled, ban_twitch_user
        if not get_channel_moderate_enabled():
            QMessageBox.warning(
                self,
                "Ban Requester",
                "You must enable the option 'want to moderate chat to ban a requester...' in Twitch settings (and log in with it) to use this feature."
            )
            return

        reply = QMessageBox.question(
            self,
            "Ban Requester",
            f"Are you sure you want to ban '{entry.requester}' from your Twitch channel?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            error = ban_twitch_user(session, entry.requester)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if error:
            QMessageBox.warning(self, "Ban Requester Failed", f"Could not ban {entry.requester}:\n{error}")
        else:
            QMessageBox.information(self, "Ban Requester", f"Successfully banned '{entry.requester}' on Twitch.")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self._queue,
            self._session.display_name if self._session else "",
            self,
        )
        dialog.logged_out.connect(self._on_logged_out)
        dialog.youtube_updated.connect(lambda: self._start_chat(self._session))
        dialog.twitch_logged_in.connect(self._on_twitch_logged_in)
        dialog.queue_command_changed.connect(self._on_queue_command_changed)
        dialog.exec()
        self.refresh_queue()

    def _on_queue_command_changed(self, enabled: bool) -> None:
        if self._chat_worker:
            self._chat_worker.queue_command_enabled = enabled

    def _on_twitch_logged_in(self, session: TwitchSession) -> None:
        self._apply_session(session)

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

    def _refresh_youtube(self) -> None:
        if self._youtube_chat_worker:
            self._youtube_chat_worker.stop()
            self._youtube_chat_worker = None
        
        self._youtube_connected = False
        self._youtube_not_streaming = False
        
        self._youtube_session = load_youtube_session()
        if self._youtube_session:
            self.statusBar().showMessage("Refreshing YouTube chat...")
            self._youtube_chat_worker = YoutubeChatWorker(self._youtube_session.username, self._queue)
            self._youtube_chat_worker.status_changed.connect(self._on_youtube_status_changed)
            self._youtube_chat_worker.connection_failed.connect(self._on_youtube_chat_failed)
            self._youtube_chat_worker.not_streaming.connect(self._on_youtube_not_streaming)
            self._youtube_chat_worker.start()
        else:
            self.statusBar().showMessage("YouTube is not configured.")
        self._update_connection_label()

    def closeEvent(self, event) -> None:
        self._stop_chat()
        self._api_server.stop()
        super().closeEvent(event)
