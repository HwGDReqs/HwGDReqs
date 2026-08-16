import platform
import sys
import os
import subprocess
from pathlib import Path
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
    QSlider,
    QComboBox,
)

from hwgdreqs.config import clear_auth, data_dir, asset_path, exec_dir, APP_VERSION
from hwgdreqs.queue_manager import QueueManager
from hwgdreqs.login_dialog import TwitchLoginDialog
from hwgdreqs.twitch_auth import (
    get_queue_command_enabled,
    has_chat_edit_scope,
    load_session,
    set_queue_command_enabled,
    has_channel_moderate_scope,
    get_channel_moderate_enabled,
    set_channel_moderate_enabled,
)
from hwgdreqs.youtube_auth import load_youtube_session, save_youtube_session, clear_youtube_auth, YoutubeSession
from hwgdreqs.cloudflared import CloudflaredManager


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

        cooldown_layout = QHBoxLayout()
        cooldown_layout.addWidget(QLabel("Request cooldown (seconds):"))
        self._cooldown_spinbox = QSpinBox()
        self._cooldown_spinbox.setRange(0, 9999)
        self._cooldown_spinbox.setValue(queue.requester_cooldown)
        self._cooldown_spinbox.setSpecialValueText("Unlimited")
        self._cooldown_spinbox.setToolTip("Seconds to wait before a requester can submit another level (0 = unlimited)")
        cooldown_layout.addWidget(self._cooldown_spinbox)
        cooldown_layout.addStretch()
        layout.addLayout(cooldown_layout)

        self._allow_any_level_cb = QCheckBox("Allow ANY level even if not on servers (for unlisted levels)")
        self._allow_any_level_cb.setChecked(queue.allow_any_level)
        self._allow_any_level_cb.setToolTip(
            "When enabled, levels that can't be found via GDBrowser (e.g. unlisted) are still added.\n"
            "They will show as '⚠️ <id>' with no data in the queue. (At your own motherf*cking risk)"
        )
        layout.addWidget(self._allow_any_level_cb)

        self._auto_blacklist_cb = QCheckBox("auto blacklist level upon deletion")
        self._auto_blacklist_cb.setChecked(queue.auto_blacklist_on_delete)
        self._auto_blacklist_cb.setToolTip("Don't get the same level again")
        self._auto_blacklist_cb.toggled.connect(self._on_auto_blacklist_toggled)
        layout.addWidget(self._auto_blacklist_cb)

        self._unless_updated_cb = QCheckBox("unless updated")
        self._unless_updated_cb.setChecked(queue.auto_blacklist_unless_updated)
        self._unless_updated_cb.setToolTip("Don't get the same level again UNLESS it has an update")
        self._unless_updated_cb.setStyleSheet("margin-left: 20px;")
        layout.addWidget(self._unless_updated_cb)
        self._unless_updated_cb.setEnabled(queue.auto_blacklist_on_delete)

        self._print_full_log_cb = QCheckBox("print full log to console (devs only)")
        self._print_full_log_cb.setChecked(queue.print_full_log_to_console)
        self._print_full_log_cb.setToolTip("When enabled, logs everything to the console alongside the hwgdreqs.log file. (Right now its broken...)")
        layout.addWidget(self._print_full_log_cb)

        # Queue Popout Scale
        layout.addSpacing(8)
        scale_header = QLabel("Queue Popout Window Scale (for OBS capture):")
        layout.addWidget(scale_header)

        scale_row = QHBoxLayout()
        self._popout_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._popout_scale_slider.setRange(30, 300)
        self._popout_scale_slider.setSingleStep(5)
        self._popout_scale_slider.setPageStep(10)
        self._popout_scale_slider.setTickInterval(50)
        self._popout_scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        # convert float [0.3, 3.0] -> int [30, 300]
        current_scale_pct = max(30, min(300, int(round(queue.queue_popout_scale * 100))))
        self._popout_scale_slider.setValue(current_scale_pct)
        self._popout_scale_label = QLabel(f"{current_scale_pct}%")
        self._popout_scale_label.setFixedWidth(42)
        self._popout_scale_slider.valueChanged.connect(
            lambda v: self._popout_scale_label.setText(f"{v}%")
        )
        scale_row.addWidget(self._popout_scale_slider)
        scale_row.addWidget(self._popout_scale_label)
        layout.addLayout(scale_row)

        layout.addStretch()

    def _on_auto_blacklist_toggled(self, checked):
        self._unless_updated_cb.setEnabled(checked)

    def apply(self) -> None:
        self._queue.thumbnail_cache_size = self._thumb_cache_spinbox.value()
        self._queue.requester_cooldown = self._cooldown_spinbox.value()
        self._queue.allow_any_level = self._allow_any_level_cb.isChecked()
        self._queue.auto_blacklist_on_delete = self._auto_blacklist_cb.isChecked()
        self._queue.auto_blacklist_unless_updated = self._unless_updated_cb.isChecked()
        self._queue.print_full_log_to_console = self._print_full_log_cb.isChecked()
        self._queue.queue_popout_scale = self._popout_scale_slider.value() / 100.0


class EditableCommandLabel(QWidget):
    def __init__(self, initial_text, on_changed_callback, parent=None):
        super().__init__(parent)
        self.on_changed = on_changed_callback
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(initial_text)
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setToolTip("Click to edit command")
        font = self.label.font()
        font.setBold(True)
        self.label.setFont(font)
        
        self.edit = QLineEdit(initial_text)
        self.edit.setFont(font)
        self.edit.hide()
        
        layout.addWidget(self.label)
        layout.addWidget(self.edit)
        layout.addStretch()
        
        self.label.mousePressEvent = self._start_editing
        self.edit.editingFinished.connect(self._finish_editing)
        
    def _start_editing(self, event):
        self.label.hide()
        self.edit.show()
        self.edit.setFocus()
        
    def _finish_editing(self):
        new_text = self.edit.text().strip()
        if not new_text:
            new_text = self.label.text()
            self.edit.setText(new_text)
        elif new_text != self.label.text():
            self.label.setText(new_text)
            self.on_changed(new_text)
            
        self.edit.hide()
        self.label.show()

class CommandsTab(QWidget):
    def __init__(self, queue: QueueManager, parent=None, *, show_queue_command: bool = False) -> None:
        super().__init__(parent)
        self._queue = queue
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        
        layout = QVBoxLayout(self)
        
        title = QLabel("Available Chat Commands")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title.setFont(title_font)
        layout.addWidget(title)
        
        hint = QLabel("(Click on a command to edit it)")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)
        layout.addSpacing(10)
        
        commands = [
            (queue.command_del, "Delete a level from the queue. Only works for the user who requested it.", self._set_cmd_del),
            (queue.command_replace, "Replace a level in the queue with a new one. Only works for the user who requested it. Maintains the position in queue btw", self._set_cmd_replace),
            (queue.command_commands, "Reply with the available commands", self._set_cmd_commands),
        ]
        if show_queue_command:
            commands.append(
                (queue.command_queue, "Sends as you the queue contents to the chat (TWITCH ONLY)", self._set_cmd_queue),
            )
            commands.append(
                (queue.command_whereami, "Replies with your current position in the queue and details about your levels (TWITCH ONLY)", self._set_cmd_whereami),
            )
        
        for command, description, callback in commands:
            cmd_widget = EditableCommandLabel(command, callback)
            layout.addWidget(cmd_widget)
            
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)
            layout.addSpacing(10)
        
        layout.addStretch()

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

    def _set_cmd_del(self, text):
        self._queue.command_del = text

    def _set_cmd_replace(self, text):
        self._queue.command_replace = text

    def _set_cmd_commands(self, text):
        self._queue.command_commands = text

    def _set_cmd_queue(self, text):
        self._queue.command_queue = text

    def _set_cmd_whereami(self, text):
        self._queue.command_whereami = text



class KeybindsTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        title = QLabel("Application Keybinds")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title.setFont(title_font)
        layout.addWidget(title)
        layout.addSpacing(10)
        
        keybinds = [
            ("Ctrl+C", "Copy the ID of the currently selected level."),
            ("Delete", "Delete the currently selected level from the queue."),
        ]
        
        for key, description in keybinds:
            key_label = QLabel(key)
            key_font = key_label.font()
            key_font.setBold(True)
            key_label.setFont(key_font)
            layout.addWidget(key_label)
            
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

        # Search bar
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search history (name, author, requester)…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search_box)

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
        self._apply_filter(self._search_box.text())

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            visible = (
                not query
                or query in entry.name.lower()
                or query in entry.author.lower()
                or query in entry.requester.lower()
            )
            item.setHidden(not visible)

    def _on_item_clicked(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        if hasattr(self, "_status_label"):
            self._status_label.setText(f'"{entry.requester}" gave it - \'{entry.id}\'')

    def _on_item_double_clicked(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        QGuiApplication.clipboard().setText(entry.id)

from hwgdreqs.config import get_local_ip


class ApiTab(QWidget):
    def __init__(self, queue: QueueManager, cloudflared, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("API Settings"))
        
        warning_label = QLabel("This is by the way mainly used by the Geode mod integration, if you didnt understand shit about what this is, do NOT touch it, if you need to change for example the port, please assign it also to the geode mod settigs in game, this is used also for integrations...")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)
        layout.addSpacing(10)
        
        # local API port
        local_port_layout = QHBoxLayout()
        local_port_layout.addWidget(QLabel("Local API port:"))
        self._local_port_spin = QSpinBox()
        self._local_port_spin.setRange(1, 65535)
        self._local_port_spin.setValue(queue.api_local_port)
        self._local_port_spin.valueChanged.connect(self._update_urls)
        local_port_layout.addWidget(self._local_port_spin)
        local_port_layout.addStretch()
        layout.addLayout(local_port_layout)
        
        # Local API URL
        self._local_url_label = QLabel()
        self._local_url_label.setWordWrap(True)
        self._local_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._local_url_label)
        
        layout.addSpacing(10)
        
        # host to local network toggle
        self._host_network_check = QCheckBox("Host to local network")
        self._host_network_check.setChecked(queue.api_host_to_network)
        self._host_network_check.toggled.connect(self._on_host_network_toggled)
        layout.addWidget(self._host_network_check)
        
        # network API URL
        self._network_url_label = QLabel()
        self._network_url_label.setWordWrap(True)
        self._network_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._network_url_label)
        
        layout.addSpacing(10)
        
        # network API port
        network_port_layout = QHBoxLayout()
        network_port_layout.addWidget(QLabel("Network API port:"))
        self._network_port_spin = QSpinBox()
        self._network_port_spin.setRange(1, 65535)
        self._network_port_spin.setValue(queue.api_network_port)
        self._network_port_spin.valueChanged.connect(self._update_urls)
        network_port_layout.addWidget(self._network_port_spin)
        network_port_layout.addStretch()
        self._network_port_widget = QWidget()
        self._network_port_widget.setLayout(network_port_layout)
        self._network_port_widget.setEnabled(queue.api_host_to_network)
        layout.addWidget(self._network_port_widget)

        # Port conflict / privileged port warning (updates live as ports/host-toggle change)
        self._port_warning_label = QLabel()
        self._port_warning_label.setWordWrap(True)
        self._port_warning_label.setStyleSheet("color: #d9822b;")  # amber warning color
        self._port_warning_label.hide()
        layout.addWidget(self._port_warning_label)
        
        layout.addSpacing(10)

        # cloudflared manager
        self._cloudflared = cloudflared
        self._cloudflared.link_ready.connect(self._on_cloudflared_link)
        self._cloudflared.stopped.connect(self._on_cloudflared_stopped)

        # expose API via cloudflared
        cloudflared_layout = QHBoxLayout()
        if self._cloudflared.is_running():
            _initial_btn_text = "Unexpose API to public"
        elif self._cloudflared._connecting:
            _initial_btn_text = "Cancel Exposal of API"
        else:
            _initial_btn_text = "Expose API to public"
        self._expose_btn = QPushButton(_initial_btn_text)
        self._expose_btn.setToolTip("tho it is not persistent, only use it to connect with external chatbots/discord bot hosted outside... do NOT send the link to anyone as they can access your queue")
        self._expose_btn.clicked.connect(self._toggle_expose)
        cloudflared_layout.addWidget(self._expose_btn)

        if sys.platform == "darwin":
            self._expose_btn.setEnabled(False)
            macos_label = QLabel("Yes won't add this to macOS because of i don't know how permissions work there so...")
            macos_label.setWordWrap(True)
            cloudflared_layout.addWidget(macos_label)

        self._cloudflared_link_label = QLabel()
        self._cloudflared_link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cloudflared_layout.addWidget(self._cloudflared_link_label)

        self._cloudflared_copy_btn = QPushButton("Copy link")
        self._cloudflared_copy_btn.clicked.connect(self._copy_cloudflared_link)
        cloudflared_layout.addWidget(self._cloudflared_copy_btn)

        cloudflared_layout.addStretch()
        layout.addLayout(cloudflared_layout)
        self._cloudflared_patience_label = QLabel(
            "This could (WILL) take some secondes depending on your internet/device/cloudflare servers, so please be patient or cancel."
        )
        self._cloudflared_patience_label.setWordWrap(True)
        self._cloudflared_patience_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._cloudflared_patience_label)
        self._cloudflared_patience_label.setVisible(self._cloudflared._connecting)
        running = self._cloudflared.is_running()
        self._cloudflared_link_label.setVisible(running)
        self._cloudflared_copy_btn.setVisible(running)
        if running and self._cloudflared._url:
            self._cloudflared_link_label.setText(f"link: {self._cloudflared._url}")

        layout.addStretch()
        
        self._update_urls()
        
    def _update_urls(self):
        # Update local URL
        local_port = self._local_port_spin.value()
        self._local_url_label.setText(f"Local API URL: http://127.0.0.1:{local_port}")
        
        # Update network URL
        host_enabled = self._host_network_check.isChecked()
        network_port = self._network_port_spin.value()
        local_ip = get_local_ip()
        if host_enabled:
            self._network_url_label.setText(f"Network API URL: http://{local_ip}:{network_port}")
            self._network_url_label.show()
        else:
            self._network_url_label.hide()

        self._update_port_warning()

    def _port_conflict_message(self) -> str | None:
        """Return a warning message if the current port configuration looks
        problematic, or None if it's fine. Checked live in the UI and again
        (blocking) before apply()."""
        local_port = self._local_port_spin.value()
        network_port = self._network_port_spin.value()
        host_enabled = self._host_network_check.isChecked()

        warnings = []
        if host_enabled and local_port == network_port:
            warnings.append(
                "Local API port and Network API port are both set to "
                f"{local_port}. Only one server can bind that port at a time, "
                "so one of the two API servers will fail to start."
            )
        privileged = [p for p in (local_port, (network_port if host_enabled else None)) if p and p < 1024]
        if privileged:
            ports_str = ", ".join(str(p) for p in sorted(set(privileged)))
            warnings.append(
                f"Port(s) {ports_str} are privileged (<1024). On most systems "
                "binding to them without elevated/admin permissions will fail."
            )
        return " ".join(warnings) if warnings else None

    def _update_port_warning(self):
        message = self._port_conflict_message()
        if message:
            self._port_warning_label.setText(f"⚠️ {message}")
            self._port_warning_label.show()
        else:
            self._port_warning_label.clear()
            self._port_warning_label.hide()

    def _on_host_network_toggled(self, checked):
        self._network_port_widget.setEnabled(checked)
        self._update_urls()

    def _toggle_expose(self):
        if self._cloudflared.is_running():
            self._expose_btn.setText("Unexposing...")
            self._expose_btn.setEnabled(False)
            self._cloudflared_patience_label.hide()
            self._cloudflared.stop()
        elif self._cloudflared._connecting:
            self._cloudflared._connecting = False
            self._cloudflared_patience_label.hide()
            self._expose_btn.setText("Expose API to public")
            self._cloudflared.stop()
        else:
            if not CloudflaredManager.is_installed():
                self._show_cloudflared_missing_dialog()
                return

            self._cloudflared._connecting = True
            self._expose_btn.setText("Cancel Exposal of API")
            self._cloudflared_patience_label.show()
            self._cloudflared.start(self._local_port_spin.value())

    def _show_cloudflared_missing_dialog(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Dependency Missing")
        
        if sys.platform == "win32":
            msg.setText("This feature needs a dependency Cloudflare Tunnel which is not installed, please insatll it to continue using this")
            dl_btn = msg.addButton("Download", QMessageBox.ButtonRole.ActionRole)
            cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == dl_btn:
                QDesktopServices.openUrl(QUrl("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.msi"))
                
        else: # linux
            msg.setText("This feature needs a dependency Cloudflare Tunnel which is not installed, please insatll it to continue using this using your distro's instructions")
            how_btn = msg.addButton("How", QMessageBox.ButtonRole.ActionRole)
            cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == how_btn:
                QDesktopServices.openUrl(QUrl("https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/#linux"))
                
    def _on_cloudflared_link(self, url: str):
        self._cloudflared._connecting = False
        self._expose_btn.setText("Unexpose API to public")
        self._expose_btn.setEnabled(True)
        self._cloudflared_patience_label.hide()
        self._cloudflared_link_label.setText(f"link: {url}")
        self._cloudflared_link_label.show()
        self._cloudflared_copy_btn.show()

    def _on_cloudflared_stopped(self):
        self._cloudflared._connecting = False
        self._expose_btn.setText("Expose API to public")
        self._expose_btn.setEnabled(True)
        self._cloudflared_patience_label.hide()
        self._cloudflared_link_label.hide()
        self._cloudflared_copy_btn.hide()
        
    def _copy_cloudflared_link(self):
        text = self._cloudflared_link_label.text().replace("link: ", "")
        QGuiApplication.clipboard().setText(text)

    def apply(self) -> bool:
        """Apply the API settings. Returns False (and leaves settings
        unapplied) if the user was warned about a port conflict/privileged
        port and chose not to proceed, so the caller can keep the dialog open."""
        message = self._port_conflict_message()
        if message:
            reply = QMessageBox.warning(
                self,
                "API Port Warning",
                f"{message}\n\nApply these settings anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        self._queue.api_local_port = self._local_port_spin.value()
        self._queue.api_host_to_network = self._host_network_check.isChecked()
        self._queue.api_network_port = self._network_port_spin.value()
        return True


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


from hwgdreqs.updater import UpdaterTab


class GeodeIntegrationTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(15)

        title_label = QLabel("Geode Integration")
        title_font = title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        subtitle = QLabel(
            "Install or reinstall the HwGDReqs Geode mod for Geometry Dash."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: gray;")
        layout.addWidget(subtitle)

        layout.addSpacing(10)


        self._reinstall_btn = QPushButton("(re)download + (re)install (run frequently)")
        self._reinstall_btn.setFixedWidth(260)
        self._reinstall_btn.clicked.connect(self._on_install)
        layout.addWidget(self._reinstall_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        from hwgdreqs.geode_installer import GEODE_EXPLANATION_TEXT

        explanation_label = QLabel(GEODE_EXPLANATION_TEXT)
        explanation_label.setWordWrap(True)
        explanation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        explanation_label.setStyleSheet(
            "padding: 12px; background-color: #2b2b2b; border-radius: 6px; color: #d0d0d0;"
        )
        layout.addWidget(explanation_label)

        layout.addStretch()

    def _on_install(self) -> None:
        from hwgdreqs.geode_installer import install_geode_integration
        install_geode_integration(self)


class SettingsDialog(QDialog):
    logged_out = Signal()
    youtube_updated = Signal()
    twitch_logged_in = Signal(object)
    queue_command_changed = Signal(bool)

    def __init__(self, queue: QueueManager, streamer_name: str, cloudflared, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self.setWindowTitle("Settings")
        self.setMinimumSize(1000, 550)
        
        layout = QVBoxLayout(self)
        from PySide6.QtWidgets import QGridLayout, QStackedWidget
        
        self.tabs_grid = QGridLayout()
        self.tabs_grid.setSpacing(5)
        self.tabs_stacked = QStackedWidget()
        self.tab_buttons = []

        def add_tab(widget, title):
            idx = self.tabs_stacked.count()
            self.tabs_stacked.addWidget(widget)
            btn = QPushButton(title)
            btn.setCheckable(True)
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, i=idx: self._select_tab(i))
            self.tab_buttons.append(btn)
            row = idx // 7
            col = idx % 7
            self.tabs_grid.addWidget(btn, row, col)
            
        class _FakeTabs:
            def addTab(self, widget, title):
                add_tab(widget, title)
                
        tabs = _FakeTabs()

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
        
        self._commands_tab = CommandsTab(self._queue, show_queue_command=has_chat_edit_scope())
        tabs.addTab(self._commands_tab, "Commands")

        twitch_tab = QWidget()
        twitch_tab_outer_layout = QVBoxLayout(twitch_tab)
        twitch_tab_outer_layout.setContentsMargins(0, 0, 0, 0)
        twitch_scroll = QScrollArea()
        twitch_scroll.setWidgetResizable(True)
        twitch_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        twitch_inner = QWidget()
        twitch_layout = QVBoxLayout(twitch_inner)
        twitch_scroll.setWidget(twitch_inner)
        twitch_tab_outer_layout.addWidget(twitch_scroll)
        twitch_layout.addWidget(QLabel(f"Data folder:\n{data_dir()}"))

        self._twitch_session = load_session()
        self._queue_command_cb = None
        self._channel_moderate_cb = None

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

            self._has_channel_moderate_scope = has_channel_moderate_scope()
            self._channel_moderate_cb = QCheckBox(
                "want to moderate chat to ban a requester from the app?(eg they requested a bad level)"
            )
            self._channel_moderate_cb.setChecked(get_channel_moderate_enabled())
            self._channel_moderate_cb.toggled.connect(self._on_channel_moderate_toggled)
            twitch_layout.addWidget(self._channel_moderate_cb)

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

            self._login_channel_moderate_cb = QCheckBox(
                "want to moderate chat to ban a requester from the app?(eg they requested a bad level)"
            )
            twitch_layout.addWidget(self._login_channel_moderate_cb)

            login_btn = QPushButton("Login with Twitch")
            login_btn.clicked.connect(self._login_twitch)
            twitch_layout.addWidget(login_btn)
            self._has_chat_edit_scope = False
            self._has_channel_moderate_scope = False

        # Bot channel
        twitch_layout.addSpacing(15)
        self._twitch_bot_channel_input = QLineEdit()
        self._twitch_bot_channel_input.setPlaceholderText("See Requests from another twitch channel (username)")
        self._twitch_bot_channel_input.setText(queue.twitch_bot_channel_name)
        twitch_layout.addWidget(QLabel("Custom chat channel (leave empty for your own):"))
        twitch_layout.addWidget(self._twitch_bot_channel_input)

        # prio + onli
        twitch_layout.addSpacing(15)
        priority_group_label = QLabel("Twitch Priorities & Restrictions:")
        priority_group_font = priority_group_label.font()
        priority_group_font.setBold(True)
        priority_group_label.setFont(priority_group_font)
        twitch_layout.addWidget(priority_group_label)

        self._twitch_sub_priority_cb = QCheckBox("Subscriber Priority")
        self._twitch_sub_priority_cb.setChecked(queue.twitch_sub_priority)
        twitch_layout.addWidget(self._twitch_sub_priority_cb)

        self._twitch_vip_priority_cb = QCheckBox("VIP Priority")
        self._twitch_vip_priority_cb.setChecked(queue.twitch_vip_priority)
        twitch_layout.addWidget(self._twitch_vip_priority_cb)

        self._twitch_mod_priority_cb = QCheckBox("Moderator Priority")
        self._twitch_mod_priority_cb.setChecked(queue.twitch_mod_priority)
        twitch_layout.addWidget(self._twitch_mod_priority_cb)

        self._twitch_subs_only_cb = QCheckBox("Subs Only")
        self._twitch_subs_only_cb.setChecked(queue.twitch_subs_only)
        twitch_layout.addWidget(self._twitch_subs_only_cb)

        self._twitch_vip_only_cb = QCheckBox("VIP Only")
        self._twitch_vip_only_cb.setChecked(queue.twitch_vip_only)
        twitch_layout.addWidget(self._twitch_vip_only_cb)

        self._twitch_followers_only_cb = QCheckBox("Followers Only")
        self._twitch_followers_only_cb.setChecked(queue.twitch_followers_only)
        twitch_layout.addWidget(self._twitch_followers_only_cb)

        from PySide6.QtWidgets import QFrame
        twitch_layout.addSpacing(15)
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.Shape.HLine)
        sep_line.setFrameShadow(QFrame.Shadow.Sunken)
        twitch_layout.addWidget(sep_line)

        bot_replies_label = QLabel("Things that the bot is allowed to say:")
        bot_replies_font = bot_replies_label.font()
        bot_replies_font.setBold(True)
        bot_replies_label.setFont(bot_replies_font)
        twitch_layout.addWidget(bot_replies_label)

        disabled_replies = queue.twitch_bot_disabled_replies

        self._bot_reply_toggles: list[tuple[str, QCheckBox]] = []
        bot_reply_definitions = [
            ("added_to_queue", "\"Your level got added to the queue in #N spot\"", "Sent when a level is successfully queued"),
            ("already_in_queue", "\"Your level is already in the queue\"", "Sent when the same level is submitted twice"),
            ("cooldown", "\"You're on cooldown\"", "Sent when a requester submits while on cooldown"),
            ("max_levels", "\"You have reached the maximum number of levels\"", "Sent when the per-requester limit is hit"),
            ("not_found_gd", "\"Level was not found on Geometry Dash servers\"", "Sent when the level ID doesn't exist on GD"),
            ("filtered_out", "\"Your level could not be added because of Filters\"", "Sent when a level is rejected by the active filters"),
            ("placeholder_added", "\"Level didn't find assets, but added anyways\"", "Sent when a level is added as a bare-ID placeholder"),
            ("del_not_found", "\"Level not found or you didn't request it\" (for !del)\"", "Sent when !del fails to find the level"),
            ("replace_not_found", "\"Level not found or you didn't request it\" (for !replace)", "Sent when !replace fails to find the old level"),
            ("queue_empty", "\"Queue is empty\" (for !queue)", "Sent when !queue is used and the queue is empty"),
            ("queue_list", "\"[queue list]\" (for !queue)", "Sends the full queue list when !queue is used"),
            ("whereami_empty", "\"You don't have any levels in the queue\" (for !whereami)", "Sent when !whereami finds no levels"),
            ("whereami_pos", "\"You're in position N\" (for !whereami)", "Sent with the requester's queue position"),
            ("requests_toggle", "\"Requests enabled/disabled\" announcement", "Sent when you enable or disable requests"),
        ]

        for key, label_text, tooltip in bot_reply_definitions:
            cb = QCheckBox(label_text)
            cb.setChecked(key not in disabled_replies)
            cb.setToolTip(tooltip)
            twitch_layout.addWidget(cb)
            self._bot_reply_toggles.append((key, cb))

        twitch_layout.addSpacing(8)
        self._twitch_bot_no_prefix_cb = QCheckBox("Remove the [HwGDReqs] prefix from bot messages")
        self._twitch_bot_no_prefix_cb.setChecked(queue.twitch_bot_no_prefix)
        self._twitch_bot_no_prefix_cb.setToolTip("When enabled, bot messages will not start with [HwGDReqs]")
        twitch_layout.addWidget(self._twitch_bot_no_prefix_cb)

        twitch_layout.addSpacing(15)
        sep_line_rewards = QFrame()
        sep_line_rewards.setFrameShape(QFrame.Shape.HLine)
        sep_line_rewards.setFrameShadow(QFrame.Shadow.Sunken)
        twitch_layout.addWidget(sep_line_rewards)

        # custom rewards
        twitch_layout.addSpacing(15)
        rewards_group_label = QLabel("Twitch Custom Rewards:")
        rewards_group_font = rewards_group_label.font()
        rewards_group_font.setBold(True)
        rewards_group_label.setFont(rewards_group_font)
        twitch_layout.addWidget(rewards_group_label)

        rewards_row = QHBoxLayout()
        self._fetch_rewards_btn = QPushButton("Fetch Custom Rewards")
        self._fetch_rewards_btn.clicked.connect(self._on_fetch_custom_rewards_clicked)
        rewards_row.addWidget(self._fetch_rewards_btn)

        self._twitch_rewards_combo = QComboBox()
        self._twitch_rewards_combo.addItem("None", "")
        if queue.twitch_reward_name:
            self._twitch_rewards_combo.addItem(queue.twitch_reward_name, queue.twitch_reward_id)
            self._twitch_rewards_combo.setCurrentIndex(1)
        rewards_row.addWidget(self._twitch_rewards_combo)
        twitch_layout.addLayout(rewards_row)

        self._twitch_reward_only_cb = QCheckBox("By reward redemption only")
        self._twitch_reward_only_cb.setChecked(queue.twitch_reward_only)
        twitch_layout.addWidget(self._twitch_reward_only_cb)

        self._twitch_reward_priority_cb = QCheckBox("By reward redemption priority")
        self._twitch_reward_priority_cb.setChecked(queue.twitch_reward_priority)
        twitch_layout.addWidget(self._twitch_reward_priority_cb)

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

        youtube_layout.addSpacing(15)
        yt_priority_group_label = QLabel("YouTube Priorities & Restrictions:")
        yt_priority_group_font = yt_priority_group_label.font()
        yt_priority_group_font.setBold(True)
        yt_priority_group_label.setFont(yt_priority_group_font)
        youtube_layout.addWidget(yt_priority_group_label)

        self._youtube_member_priority_cb = QCheckBox("Member Priority")
        self._youtube_member_priority_cb.setChecked(queue.youtube_member_priority)
        youtube_layout.addWidget(self._youtube_member_priority_cb)

        self._youtube_superchat_priority_cb = QCheckBox("Superchat Priority")
        self._youtube_superchat_priority_cb.setChecked(queue.youtube_superchat_priority)
        youtube_layout.addWidget(self._youtube_superchat_priority_cb)

        self._youtube_members_only_cb = QCheckBox("Members Only (ONLY accept the level if its a member)")
        self._youtube_members_only_cb.setChecked(queue.youtube_members_only)
        youtube_layout.addWidget(self._youtube_members_only_cb)

        self._youtube_superchats_only_cb = QCheckBox("Superchats Only (ONLY accept the level if its a superchat)")
        self._youtube_superchats_only_cb.setChecked(queue.youtube_superchats_only)
        youtube_layout.addWidget(self._youtube_superchats_only_cb) # 🤑🤑🤑

        youtube_layout.addStretch()
        tabs.addTab(youtube_tab, "YouTube")

        self._api_tab = ApiTab(queue, cloudflared)
        tabs.addTab(self._api_tab, "API")

        self._level_history_tab = LevelHistoryTab(queue)
        tabs.addTab(self._level_history_tab, "Level History")

        self._keybinds_tab = KeybindsTab()
        tabs.addTab(self._keybinds_tab, "Keybinds")

        self._info_tab = InfoTab()
        tabs.addTab(self._info_tab, "Info")

        self._geode_tab = GeodeIntegrationTab()
        tabs.addTab(self._geode_tab, "Geode Integration")

        self._updater_tab = UpdaterTab(self)
        tabs.addTab(self._updater_tab, "Updater")

        layout.addLayout(self.tabs_grid)
        layout.addWidget(self.tabs_stacked)

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
        # ApiTab.apply() returns False if the user was warned about a port
        # conflict/privileged port and chose not to proceed; keep the dialog
        # open in that case instead of discarding the warning silently.
        if not self._api_tab.apply():
            return

        bot_channel = self._twitch_bot_channel_input.text().strip()
        if bot_channel and self._twitch_session:
            from hwgdreqs.twitch_auth import check_twitch_user_exists
            if not check_twitch_user_exists(self._twitch_session, bot_channel):
                QMessageBox.warning(self, "Error", "Channel doesnt exist, recheck")
                for i in range(self.tabs_stacked.count()):
                    if self.tabs_stacked.widget(i) is self._twitch_bot_channel_input.parent():
                        self._select_tab(i)
                        break
                return

        self._queue.twitch_bot_channel_name = bot_channel
        self._queue.max_levels_per_requester = self._general_tab._max_levels_spinbox.value()
        self._queue.twitch_sub_priority = self._twitch_sub_priority_cb.isChecked()
        self._queue.twitch_vip_priority = self._twitch_vip_priority_cb.isChecked()
        self._queue.twitch_mod_priority = self._twitch_mod_priority_cb.isChecked()
        self._queue.twitch_subs_only = self._twitch_subs_only_cb.isChecked()
        self._queue.twitch_vip_only = self._twitch_vip_only_cb.isChecked()
        self._queue.twitch_followers_only = self._twitch_followers_only_cb.isChecked()
        
        self._queue.twitch_reward_id = self._twitch_rewards_combo.currentData()
        self._queue.twitch_reward_name = self._twitch_rewards_combo.currentText()
        self._queue.twitch_reward_only = self._twitch_reward_only_cb.isChecked()
        self._queue.twitch_reward_priority = self._twitch_reward_priority_cb.isChecked()

        self._queue.youtube_member_priority = self._youtube_member_priority_cb.isChecked()
        self._queue.youtube_superchat_priority = self._youtube_superchat_priority_cb.isChecked()
        self._queue.youtube_members_only = self._youtube_members_only_cb.isChecked()
        self._queue.youtube_superchats_only = self._youtube_superchats_only_cb.isChecked()

        disabled_replies = [key for key, cb in self._bot_reply_toggles if not cb.isChecked()]
        self._queue.twitch_bot_disabled_replies = disabled_replies
        self._queue.twitch_bot_no_prefix = self._twitch_bot_no_prefix_cb.isChecked()

        self.accept()

    def _select_tab(self, index: int) -> None:
        self.tabs_stacked.setCurrentIndex(index)
        for i, btn in enumerate(self.tab_buttons):
            btn.setChecked(i == index)

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

    def _on_channel_moderate_toggled(self, checked: bool) -> None:
        if self._channel_moderate_cb is None:
            return
        if checked and not self._has_channel_moderate_scope:
            self._channel_moderate_cb.blockSignals(True)
            self._channel_moderate_cb.setChecked(False)
            self._channel_moderate_cb.blockSignals(False)
            QMessageBox.information(self, "Twitch", "You need to re-login")
            return
        set_channel_moderate_enabled(checked)

    def _login_twitch(self) -> None:
        include_chat_edit = self._login_queue_command_cb.isChecked()
        include_channel_moderate = self._login_channel_moderate_cb.isChecked()
        dialog = TwitchLoginDialog(
            self,
            include_chat_edit=include_chat_edit,
            include_channel_moderate=include_channel_moderate,
            hide_queue_checkbox=True,
            hide_moderate_checkbox=True,
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
                "Please enter your YouTube username. (dw about the @, I added it for you)",
            )
            return
        
        if not username.startswith("@"):
            username = "@" + username
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

        youtube_layout.addSpacing(15)
        yt_priority_group_label = QLabel("YouTube Priorities & Restrictions:")
        yt_priority_group_font = yt_priority_group_label.font()
        yt_priority_group_font.setBold(True)
        yt_priority_group_label.setFont(yt_priority_group_font)
        youtube_layout.addWidget(yt_priority_group_label)

        self._youtube_member_priority_cb = QCheckBox("Member Priority")
        self._youtube_member_priority_cb.setChecked(queue.youtube_member_priority)
        youtube_layout.addWidget(self._youtube_member_priority_cb)

        self._youtube_superchat_priority_cb = QCheckBox("Superchat Priority")
        self._youtube_superchat_priority_cb.setChecked(queue.youtube_superchat_priority)
        youtube_layout.addWidget(self._youtube_superchat_priority_cb)

        self._youtube_members_only_cb = QCheckBox("Members Only (ONLY accept the level if its a member)")
        self._youtube_members_only_cb.setChecked(queue.youtube_members_only)
        youtube_layout.addWidget(self._youtube_members_only_cb)

        self._youtube_superchats_only_cb = QCheckBox("Superchats Only (ONLY accept the level if its a superchat)")
        self._youtube_superchats_only_cb.setChecked(queue.youtube_superchats_only)
        youtube_layout.addWidget(self._youtube_superchats_only_cb) # 🤑🤑🤑

        youtube_layout.addStretch()
        tabs.addTab(youtube_tab, "YouTube")

        self._api_tab = ApiTab(queue, cloudflared)
        tabs.addTab(self._api_tab, "API")

        self._level_history_tab = LevelHistoryTab(queue)
        tabs.addTab(self._level_history_tab, "Level History")

        self._keybinds_tab = KeybindsTab()
        tabs.addTab(self._keybinds_tab, "Keybinds")

        self._info_tab = InfoTab()
        tabs.addTab(self._info_tab, "Info")

        self._geode_tab = GeodeIntegrationTab()
        tabs.addTab(self._geode_tab, "Geode Integration")

        self._updater_tab = UpdaterTab(self)
        tabs.addTab(self._updater_tab, "Updater")

        layout.addLayout(self.tabs_grid)
        layout.addWidget(self.tabs_stacked)

        self._level_history_label = QLabel()
        self._level_history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._level_history_label.setWordWrap(True)
        layout.addWidget(self._level_history_label)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self._on_close)
        layout.addWidget(close_btn)

        self._level_history_tab._status_label = self._level_history_label

        self.refresh()

    def _on_close(self) -> None:
        self._general_tab.apply()
        self._filters_tab.apply_filters()
        if not self._api_tab.apply():
            return

        bot_channel = self._twitch_bot_channel_input.text().strip()
        if bot_channel and self._twitch_session:
            from hwgdreqs.twitch_auth import check_twitch_user_exists
            if not check_twitch_user_exists(self._twitch_session, bot_channel):
                QMessageBox.warning(self, "Error", "Channel doesnt exist, recheck")
                for i in range(self.tabs_stacked.count()):
                    if self.tabs_stacked.widget(i) is self._twitch_bot_channel_input.parent():
                        self._select_tab(i)
                        break
                return

        self._queue.twitch_bot_channel_name = bot_channel
        self._queue.max_levels_per_requester = self._general_tab._max_levels_spinbox.value()
        self._queue.twitch_sub_priority = self._twitch_sub_priority_cb.isChecked()
        self._queue.twitch_vip_priority = self._twitch_vip_priority_cb.isChecked()
        self._queue.twitch_mod_priority = self._twitch_mod_priority_cb.isChecked()
        self._queue.twitch_subs_only = self._twitch_subs_only_cb.isChecked()
        self._queue.twitch_vip_only = self._twitch_vip_only_cb.isChecked()
        self._queue.twitch_followers_only = self._twitch_followers_only_cb.isChecked()
        
        self._queue.twitch_reward_id = self._twitch_rewards_combo.currentData()
        self._queue.twitch_reward_name = self._twitch_rewards_combo.currentText()
        self._queue.twitch_reward_only = self._twitch_reward_only_cb.isChecked()
        self._queue.twitch_reward_priority = self._twitch_reward_priority_cb.isChecked()

        self._queue.youtube_member_priority = self._youtube_member_priority_cb.isChecked()
        self._queue.youtube_superchat_priority = self._youtube_superchat_priority_cb.isChecked()
        self._queue.youtube_members_only = self._youtube_members_only_cb.isChecked()
        self._queue.youtube_superchats_only = self._youtube_superchats_only_cb.isChecked()

        disabled_replies = [key for key, cb in self._bot_reply_toggles if not cb.isChecked()]
        self._queue.twitch_bot_disabled_replies = disabled_replies
        self._queue.twitch_bot_no_prefix = self._twitch_bot_no_prefix_cb.isChecked()

        self.accept()

    def _select_tab(self, index: int) -> None:
        self.tabs_stacked.setCurrentIndex(index)
        for i, btn in enumerate(self.tab_buttons):
            btn.setChecked(i == index)

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

    def _on_channel_moderate_toggled(self, checked: bool) -> None:
        if self._channel_moderate_cb is None:
            return
        if checked and not self._has_channel_moderate_scope:
            self._channel_moderate_cb.blockSignals(True)
            self._channel_moderate_cb.setChecked(False)
            self._channel_moderate_cb.blockSignals(False)
            QMessageBox.information(self, "Twitch", "You need to re-login")
            return
        set_channel_moderate_enabled(checked)

    def _login_twitch(self) -> None:
        include_chat_edit = self._login_queue_command_cb.isChecked()
        include_channel_moderate = self._login_channel_moderate_cb.isChecked()
        dialog = TwitchLoginDialog(
            self,
            include_chat_edit=include_chat_edit,
            include_channel_moderate=include_channel_moderate,
            hide_queue_checkbox=True,
            hide_moderate_checkbox=True,
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
                "Please enter your YouTube username. (dw about the @, I added it for you)",
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
        self.youtube_updated.emit()
        QMessageBox.information(
            self,
            "YouTube Disconnected",
            "Disconnected from YouTube.",
        )
        self.accept()  # close dialog

    def _on_fetch_custom_rewards_clicked(self) -> None:
        if not self._twitch_session:
            QMessageBox.warning(self, "Twitch", "You must be logged in to Twitch to fetch custom rewards.")
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Account Check")
        msg.setText("Are you logged in under your main streamer account or a bot one?")
        main_btn = msg.addButton("Main Account", QMessageBox.ButtonRole.AcceptRole)
        bot_btn = msg.addButton("Bot Account", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        
        if msg.clickedButton() == bot_btn:
            bot_msg = QMessageBox(self)
            bot_msg.setWindowTitle("Oops!")
            bot_msg.setText("Well this shit can NOT fetch from your main acc if you're not logged in into it, so you gotta logout, login with the main one, select the reward, relogout, login again with the bot💀")
            logout_btn = bot_msg.addButton("Logout Twitch", QMessageBox.ButtonRole.ActionRole)
            cancel_btn = bot_msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            bot_msg.exec()
            if bot_msg.clickedButton() == logout_btn:
                self._logout()
            return
            
        url = "https://api.twitch.tv/helix/channel_points/custom_rewards"
        from hwgdreqs.config import TWITCH_CLIENT_ID
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {self._twitch_session.access_token}"
        }
        params = {
            "broadcaster_id": self._twitch_session.user_id,
            "only_manageable_rewards": "false"
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                rewards = response.json().get("data", [])
                text_rewards = [r for r in rewards if r.get("is_user_input_required")]
                
                self._twitch_rewards_combo.clear()
                self._twitch_rewards_combo.addItem("None", "")
                for r in text_rewards:
                    self._twitch_rewards_combo.addItem(r["title"], r["id"])
                    
                idx = self._twitch_rewards_combo.findData(self._queue.twitch_reward_id)
                if idx >= 0:
                    self._twitch_rewards_combo.setCurrentIndex(idx)
                else:
                    self._twitch_rewards_combo.setCurrentIndex(0)
                    
                QMessageBox.information(self, "Success", f"Fetched {len(text_rewards)} rewards that require text input.")
            else:
                QMessageBox.critical(self, "Error", f"Failed to fetch rewards: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error fetching rewards: {e}")
