import sys
import os
import subprocess
import requests
from PySide6.QtCore import Signal, Qt, QUrl, QThread, QTimer
from PySide6.QtGui import QPixmap, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QSpinBox,
    QScrollArea,
    QLineEdit,
    QSizePolicy,
    QProgressDialog,
    QApplication,
)

from hwgdreqs.config import clear_auth, data_dir, asset_path, exec_dir, APP_VERSION
from hwgdreqs.queue_manager import QueueManager
from hwgdreqs.login_dialog import TwitchLoginDialog
from hwgdreqs.twitch_auth import (
    get_queue_command_enabled,
    has_chat_edit_scope,
    load_session,
    set_queue_command_enabled,
)
from hwgdreqs.youtube_auth import load_youtube_session, save_youtube_session, clear_youtube_auth, YoutubeSession


class BlacklistTab(QWidget):
    def __init__(self, title: str, queue: QueueManager, getter, remover, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._getter = getter
        self._remover = remover

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        self._list = QListWidget()
        layout.addWidget(self._list)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        layout.addWidget(remove_btn)

    def refresh(self) -> None:
        self._list.clear()
        items = self._getter() if callable(self._getter) else self._getter
        self._list.addItems(items)

    def _remove_selected(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        self._remover(item.text())
        self.refresh()


class FiltersTab(QWidget):
    LENGTH_OPTIONS = ["Tiny", "Short", "Medium", "Long", "XL", "Plat"]
    DIFFICULTY_OPTIONS = [
        "Unrated", "Auto", "Easy", "Normal", "Hard", "Harder", "Insane",
        "Easy Demon", "Medium Demon", "Hard Demon", "Insane Demon", "Extreme Demon"
    ]

    def __init__(self, queue: QueueManager, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Allowed Lengths:"))
        self._length_list = QListWidget()
        for length in self.LENGTH_OPTIONS:
            item = QListWidgetItem(length)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if length in queue.allowed_lengths else Qt.CheckState.Unchecked)
            self._length_list.addItem(item)
        layout.addWidget(self._length_list)
        
        layout.addWidget(QLabel("Allowed Difficulties:"))
        self._difficulty_list = QListWidget()
        for diff in self.DIFFICULTY_OPTIONS:
            item = QListWidgetItem(diff)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if diff in queue.allowed_difficulties else Qt.CheckState.Unchecked)
            self._difficulty_list.addItem(item)
        layout.addWidget(self._difficulty_list)
        
        self._no_disliked_checkbox = QCheckBox("No Disliked Levels")
        self._no_disliked_checkbox.setChecked(queue.no_disliked)
        layout.addWidget(self._no_disliked_checkbox)

    def apply_filters(self) -> None:
        allowed_lengths = []
        for i in range(self._length_list.count()):
            item = self._length_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                allowed_lengths.append(item.text())
        self._queue.allowed_lengths = allowed_lengths
        
        allowed_difficulties = []
        for i in range(self._difficulty_list.count()):
            item = self._difficulty_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                allowed_difficulties.append(item.text())
        self._queue.allowed_difficulties = allowed_difficulties
        
        self._queue.no_disliked = self._no_disliked_checkbox.isChecked()


class GeneralTab(QWidget):
    def __init__(self, queue: QueueManager, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue

        layout = QVBoxLayout(self)

        cache_layout = QHBoxLayout()
        cache_layout.addWidget(QLabel("How many thumbnails to cache per session:"))
        self._thumb_cache_spinbox = QSpinBox()
        self._thumb_cache_spinbox.setRange(0, 9999)
        self._thumb_cache_spinbox.setValue(queue.thumbnail_cache_size)
        self._thumb_cache_spinbox.setToolTip("0 disables caching. Cache is cleared when the app closes.")
        cache_layout.addWidget(self._thumb_cache_spinbox)
        cache_layout.addStretch()
        layout.addLayout(cache_layout)

        max_layout = QHBoxLayout()
        max_layout.addWidget(QLabel("How many levels per requester:"))
        self._max_levels_spinbox = QSpinBox()
        self._max_levels_spinbox.setRange(0, 9999)
        self._max_levels_spinbox.setValue(queue.max_levels_per_requester)
        self._max_levels_spinbox.setSpecialValueText("Infinite")
        self._max_levels_spinbox.setToolTip("Limit of how many levels can a requester send per session")
        max_layout.addWidget(self._max_levels_spinbox)
        max_layout.addStretch()
        layout.addLayout(max_layout)

        layout.addStretch()

    def apply(self) -> None:
        self._queue.thumbnail_cache_size = self._thumb_cache_spinbox.value()


class CommandsTab(QWidget):
    def __init__(self, parent=None, *, show_queue_command: bool = False) -> None:
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        title = QLabel("Available Chat Commands")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title.setFont(title_font)
        layout.addWidget(title)
        layout.addSpacing(10)
        
        commands = [
            ("!del <id>", "Delete a level from the queue. Only works for the user who requested it."),
            ("!replace <id> <new-id>", "Replace a level in the queue with a new one. Only works for the user who requested it. Maintains the position in queue btw"),
        ]
        if show_queue_command:
            commands.append(
                ("!queue", "Sends as you the queue contents to the chat (TWITCH ONLY)"),
            )
            commands.append(
                ("!whereami", "Replies with your current position in the queue and details about your levels (TWITCH ONLY)"),
            )
        
        for command, description in commands:
            cmd_label = QLabel(command)
            cmd_font = cmd_label.font()
            cmd_font.setBold(True)
            cmd_label.setFont(cmd_font)
            layout.addWidget(cmd_label)
            
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)
            layout.addSpacing(10)
        
        layout.addStretch()


class HistoryListItemWidget(QWidget):
    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self._entry = entry
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        difficulty_icon_map = {
            "Unrated": "unrated.png",
            "Auto": "auto.png",
            "Easy": "easy.png",
            "Normal": "normal.png",
            "Hard": "hard.png",
            "Harder": "harder.png",
            "Insane": "insane.png",
        }
        
        if entry.difficulty.endswith("Demon"):
            icon_filename = "demon.png"
        else:
            icon_filename = difficulty_icon_map.get(entry.difficulty, "unrated.png")
        
        difficulty_icon_path = asset_path(icon_filename)
        if difficulty_icon_path.exists():
            self.diff_icon_label = QLabel()
            diff_pixmap = QPixmap(str(difficulty_icon_path))
            self.diff_icon_label.setPixmap(diff_pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(self.diff_icon_label)
        
        self.text_label = QLabel(f'"{entry.name}" by {entry.author}')
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.text_label)
        
        platform_icon = None
        if entry.platform == "youtube":
            platform_icon_path = asset_path("youtube.svg")
            if platform_icon_path.exists():
                self.platform_icon_label = QLabel()
                plat_pixmap = QPixmap(str(platform_icon_path))
                self.platform_icon_label.setPixmap(plat_pixmap.scaled(24, 24))
                layout.addWidget(self.platform_icon_label)
        elif entry.platform == "twitch":
            platform_icon_path = asset_path("twitch.svg")
            if platform_icon_path.exists():
                self.platform_icon_label = QLabel()
                plat_pixmap = QPixmap(str(platform_icon_path))
                self.platform_icon_label.setPixmap(plat_pixmap.scaled(24, 24))
                layout.addWidget(self.platform_icon_label)
    
    def get_entry(self):
        return self._entry

class LevelHistoryTab(QWidget):
    def __init__(self, queue, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)
        
        self.refresh()
    
    def refresh(self):
        self._list.clear()
        for entry in self._queue.level_history:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry)
            widget = HistoryListItemWidget(entry)
            item.setSizeHint(widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)
    
    def _on_item_clicked(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        if hasattr(self, "_status_label"):
            self._status_label.setText(f'"{entry.requester}" gave it - \'{entry.id}\'')
    
    def _on_item_double_clicked(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        QGuiApplication.clipboard().setText(entry.id)

class InfoTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pfp_label = QLabel()
        pfp_path = asset_path("pfp.jpg")
        if pfp_path.exists():
            pfp_pixmap = QPixmap(str(pfp_path))
            pfp_label.setPixmap(pfp_pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        pfp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(pfp_label)
        layout.addSpacing(15)
        info_text = QLabel("HwGDReqs info:")
        info_font = info_text.font()
        info_font.setBold(True)
        info_font.setPointSize(12)
        info_text.setFont(info_font)
        info_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_text)
        youtube_issue_text = QLabel("If youtube chat did not work (no ids gets added to the chat) despite you got the right username, open an issue here and tell me with the stream VOD link") # qlabel
        youtube_issue_text.setWordWrap(True)
        youtube_issue_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(youtube_issue_text)
        
        issue_btn = QPushButton("Open Issue")
        issue_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/MalikHw/HwGDReqs/issues")))
        issue_btn.setFixedWidth(120)
        layout.addWidget(issue_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(20)
        dev_text = QLabel("By MalikHw47, a geometry dash player/level creator, a Geode modder, and a developer")
        dev_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_text.setWordWrap(True)
        layout.addWidget(dev_text)
        layout.addSpacing(20)
        buttons_row1 = QHBoxLayout()
        buttons_row1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        portfolio_btn = QPushButton("Portfolio")
        portfolio_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://malikhw.github.io")))
        buttons_row1.addWidget(portfolio_btn)
        
        youtube_btn = QPushButton("Youtube")
        youtube_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://youtube.com/@MalikHw47")))
        buttons_row1.addWidget(youtube_btn)
        
        github_btn = QPushButton("Github")
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/malikhw")))
        buttons_row1.addWidget(github_btn)
        
        twitch_btn = QPushButton("Twitch")
        twitch_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://twitch.tv/MalikHw47")))
        buttons_row1.addWidget(twitch_btn)
        
        layout.addLayout(buttons_row1)
        layout.addSpacing(10)

        buttons_row2 = QHBoxLayout()
        buttons_row2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        discord_btn = QPushButton("Discord Server")
        discord_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/5kn2uX5B8x")))
        buttons_row2.addWidget(discord_btn)
        
        donate_btn = QPushButton("Donate to me")
        donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://malikhw.github.io/donate")))
        buttons_row2.addWidget(donate_btn)
        
        layout.addLayout(buttons_row2)
        layout.addStretch()


class UpdateCheckerWorker(QThread):
    finished = Signal(str, str)  # tag_name, download_url
    error = Signal(str)

    def run(self) -> None:
        try:
            headers = {"User-Agent": "HwGDReqs-Updater"}
            response = requests.get(
                "https://api.github.com/repos/HwGDReqs/HwGDReqs/releases/latest",
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            tag_name = data.get("tag_name", "").strip()
            
            # Use the explicit latest download link provided by the user
            download_url = "https://github.com/HwGDReqs/HwGDReqs/releases/latest/download/hwgdreqs-windows-portable.zip"
            
            self.finished.emit(tag_name, download_url)
        except Exception as e:
            self.error.emit(str(e))


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, url: str, dest_path: str, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            dest_dir = os.path.dirname(self.dest_path)
            os.makedirs(dest_dir, exist_ok=True)

            headers = {"User-Agent": "HwGDReqs-Updater"}
            response = requests.get(self.url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            total_length = response.headers.get('content-length')
            if total_length is None:
                with open(self.dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                            self._cleanup()
                            return
                        if chunk:
                            f.write(chunk)
                if not self._is_cancelled:
                    self.progress.emit(100)
                    self.finished.emit()
            else:
                total_length = int(total_length)
                dl = 0
                with open(self.dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                            self._cleanup()
                            return
                        if chunk:
                            f.write(chunk)
                            dl += len(chunk)
                            percent = int((dl / total_length) * 100)
                            self.progress.emit(percent)
                if not self._is_cancelled:
                    self.finished.emit()
        except Exception as e:
            self._cleanup()
            if not self._is_cancelled:
                self.error.emit(str(e))

    def _cleanup(self) -> None:
        try:
            if os.path.exists(self.dest_path):
                os.remove(self.dest_path)
        except Exception:
            pass


class UpdaterTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._check_worker = None
        self._download_worker = None
        self._progress_dialog = None

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(15)

        title_label = QLabel("Application Updater")
        title_font = title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        self._version_label = QLabel(f"Current Version: {APP_VERSION}")
        version_font = self._version_label.font()
        version_font.setPointSize(12)
        self._version_label.setFont(version_font)
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._version_label)

        self._status_label = QLabel("Check for new updates of HwGDReqs.")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("color: gray;")
        layout.addWidget(self._status_label)

        self._check_btn = QPushButton("Check For Updates")
        self._check_btn.setFixedWidth(200)
        self._check_btn.clicked.connect(self._check_for_updates)
        layout.addWidget(self._check_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()

    def _check_for_updates(self) -> None:
        self._check_btn.setEnabled(False)
        self._status_label.setText("Checking for updates...")
        self._status_label.setStyleSheet("color: #007acc;")

        self._check_worker = UpdateCheckerWorker(self)
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.error.connect(self._on_check_error)
        self._check_worker.start()

    def _on_check_finished(self, latest_version: str, download_url: str) -> None:
        self._check_btn.setEnabled(True)
        
        norm_latest = latest_version.strip().lower().lstrip('v')
        norm_current = APP_VERSION.strip().lower().lstrip('v')

        if norm_latest != norm_current:
            self._status_label.setText(f"Update available: {latest_version}")
            self._status_label.setStyleSheet("color: #4caf50; font-weight: bold;")

            reply = QMessageBox.question(
                self,
                "Update Available",
                f"There is an update ({latest_version}), want to download and install?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._download_update(download_url)
        else:
            self._status_label.setText("You are running the latest version.")
            self._status_label.setStyleSheet("color: green;")
            QMessageBox.information(
                self,
                "Up to Date",
                "You are already using the latest version of HwGDReqs."
            )

    def _on_check_error(self, error_msg: str) -> None:
        self._check_btn.setEnabled(True)
        self._status_label.setText("Failed to check for updates.")
        self._status_label.setStyleSheet("color: red;")
        QMessageBox.warning(
            self,
            "Check Failed",
            f"Could not check for updates:\n{error_msg}"
        )

    def _download_update(self, download_url: str) -> None:
        self._check_btn.setEnabled(False)
        self._status_label.setText("Downloading update...")
        self._status_label.setStyleSheet("color: #007acc;")

        tmp_dir = exec_dir() / "tmp"
        dest_file = tmp_dir / "hwgdreqs-windows-portable.zip"

        self._progress_dialog = QProgressDialog("Downloading update...", "Cancel", 0, 100, self)
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setValue(0)

        self._download_worker = UpdateDownloadWorker(download_url, str(dest_file), self)
        self._download_worker.progress.connect(self._progress_dialog.setValue)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)

        self._progress_dialog.canceled.connect(self._cancel_download)
        self._download_worker.start()

    def _cancel_download(self) -> None:
        if self._download_worker:
            self._download_worker.cancel()
            self._download_worker.wait()
        self._check_btn.setEnabled(True)
        self._status_label.setText("Download cancelled.")
        self._status_label.setStyleSheet("color: orange;")
        QMessageBox.information(self, "Cancelled", "Update download was cancelled.")

    def _on_download_finished(self) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
        
        self._status_label.setText("Download complete. Launching updater in 2 seconds...")
        self._status_label.setStyleSheet("color: green; font-weight: bold;")
        self._check_btn.setEnabled(False)

        QTimer.singleShot(2000, self._run_updater_and_exit)

    def _on_download_error(self, error_msg: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
        
        self._check_btn.setEnabled(True)
        self._status_label.setText("Download failed.")
        self._status_label.setStyleSheet("color: red;")
        QMessageBox.warning(
            self,
            "Download Failed",
            f"An error occurred while downloading the update:\n{error_msg}"
        )

    def _run_updater_and_exit(self) -> None:
        updater_path = exec_dir() / "updater.bat"
        try:
            subprocess.Popen([str(updater_path)], cwd=str(exec_dir()))
        except Exception:
            pass
        
        QApplication.quit()
        sys.exit(0)


class SettingsDialog(QDialog):
    logged_out = Signal()
    youtube_updated = Signal()
    twitch_logged_in = Signal(object)
    queue_command_changed = Signal(bool)

    def __init__(self, queue: QueueManager, streamer_name: str, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self.setWindowTitle("Settings")
        self.setMinimumSize(1000, 550)
        
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        self._general_tab = GeneralTab(queue)
        tabs.addTab(self._general_tab, "General")

        self._levels_tab = BlacklistTab(
            "Blacklisted level IDs will not be added to the queue.",
            queue,
            lambda: queue.blacklist_levels,
            queue.remove_blacklist_level,
        )
        tabs.addTab(self._levels_tab, "Blacklisted Levels")

        self._authors_tab = BlacklistTab(
            "Blacklisted authors will not be added to the queue.",
            queue,
            lambda: queue.blacklist_authors,
            queue.remove_blacklist_author,
        )
        tabs.addTab(self._authors_tab, "Blacklisted Authors")

        self._requesters_tab = BlacklistTab(
            "Blacklisted requesters will not be added to the queue.",
            queue,
            lambda: queue.blacklist_requesters,
            queue.remove_blacklist_requester,
        )
        tabs.addTab(self._requesters_tab, "Blacklisted Requesters")
        
        self._filters_tab = FiltersTab(queue)
        tabs.addTab(self._filters_tab, "Filters")
        
        self._commands_tab = CommandsTab(show_queue_command=has_chat_edit_scope())
        tabs.addTab(self._commands_tab, "Commands")

        twitch_tab = QWidget()
        twitch_layout = QVBoxLayout(twitch_tab)
        twitch_layout.addWidget(QLabel(f"Data folder:\n{data_dir()}"))

        self._twitch_session = load_session()
        self._queue_command_cb = None

        if self._twitch_session:
            twitch_layout.addWidget(
                QLabel(f"Logged in as: {self._twitch_session.display_name}")
            )
            twitch_layout.addSpacing(15)

            self._has_chat_edit_scope = has_chat_edit_scope()
            self._queue_command_cb = QCheckBox(
                "Want people to type !queue to see current queue "
                "(will respond under your account)"
            )
            self._queue_command_cb.setChecked(get_queue_command_enabled())
            self._queue_command_cb.toggled.connect(self._on_queue_command_toggled)
            twitch_layout.addWidget(self._queue_command_cb)

            logout_btn = QPushButton("Log Out from Twitch")
            logout_btn.clicked.connect(self._logout)
            twitch_layout.addWidget(logout_btn)
        else:
            twitch_layout.addWidget(QLabel("Twitch Status: Not connected"))
            twitch_layout.addSpacing(15)

            self._login_queue_command_cb = QCheckBox(
                "Want people to type !queue to see current queue "
                "(will respond under your account)"
            )
            twitch_layout.addWidget(self._login_queue_command_cb)

            login_btn = QPushButton("Login with Twitch")
            login_btn.clicked.connect(self._login_twitch)
            twitch_layout.addWidget(login_btn)
            self._has_chat_edit_scope = False

        twitch_layout.addStretch()
        tabs.addTab(twitch_tab, "Twitch")

        youtube_tab = QWidget()
        youtube_layout = QVBoxLayout(youtube_tab)
        
        self._youtube_session = load_youtube_session()
        if self._youtube_session:
            # logged in
            youtube_layout.addWidget(QLabel(f"YouTube Status: Connected as {self._youtube_session.username}"))
            youtube_layout.addSpacing(15)
            disconnect_btn = QPushButton("Logout YouTube")
            disconnect_btn.clicked.connect(self._disconnect_youtube)
            youtube_layout.addWidget(disconnect_btn)
            self._youtube_disconnect_btn = disconnect_btn
        else:
            # logged out
            youtube_layout.addWidget(QLabel("YouTube Status: Not connected"))
            youtube_layout.addSpacing(15)
            
            username_label = QLabel("YouTube Username (@username):")
            youtube_layout.addWidget(username_label)
            
            self._youtube_username_input = QLineEdit()
            self._youtube_username_input.setPlaceholderText("@YourUsername")
            youtube_layout.addWidget(self._youtube_username_input)
            
            youtube_layout.addSpacing(10)
            
            connect_btn = QPushButton("Connect YouTube")
            connect_btn.clicked.connect(self._connect_youtube)
            youtube_layout.addWidget(connect_btn)
        
        youtube_layout.addStretch()
        tabs.addTab(youtube_tab, "YouTube")

        self._level_history_tab = LevelHistoryTab(queue)
        tabs.addTab(self._level_history_tab, "Level History")

        self._info_tab = InfoTab()
        tabs.addTab(self._info_tab, "Info")

        self._updater_tab = UpdaterTab(self)
        tabs.addTab(self._updater_tab, "Updater")

        layout.addWidget(tabs)

        self._level_history_label = QLabel()
        self._level_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._level_history_label.setWordWrap(True)
        layout.addWidget(self._level_history_label)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self._on_close)
        layout.addWidget(close_btn)

        # give LevelHistoryTab access to the label
        self._level_history_tab._status_label = self._level_history_label

        self.refresh()

    def _on_close(self) -> None:
        self._general_tab.apply()
        self._filters_tab.apply_filters()
        self._queue.max_levels_per_requester = self._general_tab._max_levels_spinbox.value()
        self.accept()

    def refresh(self) -> None:
        self._levels_tab.refresh()
        self._authors_tab.refresh()
        self._requesters_tab.refresh()

    def _on_queue_command_toggled(self, checked: bool) -> None:
        if self._queue_command_cb is None:
            return
        if checked and not self._has_chat_edit_scope:
            self._queue_command_cb.blockSignals(True)
            self._queue_command_cb.setChecked(False)
            self._queue_command_cb.blockSignals(False)
            QMessageBox.information(self, "Twitch", "You need to re-login")
            return
        set_queue_command_enabled(checked)
        self.queue_command_changed.emit(checked)

    def _login_twitch(self) -> None:
        include_chat_edit = self._login_queue_command_cb.isChecked()
        dialog = TwitchLoginDialog(
            self,
            include_chat_edit=include_chat_edit,
            hide_queue_checkbox=True,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.session:
            return
        self.twitch_logged_in.emit(dialog.session)
        self.accept()

    def _logout(self) -> None:
        answer = QMessageBox.question(
            self,
            "Log Out",
            "Log out from Twitch? You can log in again immediately.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        clear_auth()
        self.logged_out.emit()
        self.accept()

    def _connect_youtube(self) -> None:
        username = self._youtube_username_input.text().strip()
        
        if not username:
            QMessageBox.warning(
                self,
                "YouTube Connection",
                "Please enter your YouTube username.",
            )
            return
        
        if not username.startswith("@"):
            username = "@" + username
        
        session = YoutubeSession(username=username)
        save_youtube_session(session)
        self._youtube_session = session
        
        QMessageBox.information(
            self,
            "YouTube Connected",
            f"Connected to YouTube channel: {username}",
        )
        self.youtube_updated.emit()
        self.accept()  # close dialog

    def _disconnect_youtube(self) -> None:
        answer = QMessageBox.question(
            self,
            "Disconnect YouTube",
            "Disconnect from YouTube? The app will no longer monitor your YouTube chat.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        
        clear_youtube_auth()
        self._youtube_session = None
        
        QMessageBox.information(
            self,
            "YouTube Disconnected",
            "Disconnected from YouTube.",
        )
        self.youtube_updated.emit()
        self.accept()  # close dialog
