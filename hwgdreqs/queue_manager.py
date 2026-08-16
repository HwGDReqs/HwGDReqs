import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

from hwgdreqs.config import queue_file
from hwgdreqs.logging_service import (
    log_level_added,
    log_level_deleted,
    log_level_swapped,
    log_requester_blacklisted,
    log_level_blacklisted,
    log_author_blacklisted,
    log_requester_unblacklisted,
    log_level_unblacklisted,
    log_author_unblacklisted,
    log_queue_cleared,
)


@dataclass
class LevelEntry:
    id: str
    name: str
    author: str
    difficulty: str
    requester: str
    platform: str = "twitch"
    platform_icon: str = ""
    message: str = ""
    description: str = ""
    length: str = ""
    large: bool = False
    two_player: bool = False
    timestamp: float = 0.0
    likes: int = 0
    downloads: int = 0
    disliked: bool = False
    priority: bool = False
    version: int = 0
    superchat: bool = False
    superchat_amount: str = ""
    member: bool = False


import random

@dataclass
class QueueData:
    levels: list[LevelEntry] = field(default_factory=list)
    level_history: list[LevelEntry] = field(default_factory=list)
    blacklist_levels: list[str] = field(default_factory=list)
    blacklist_authors: list[str] = field(default_factory=list)
    blacklist_requesters: list[str] = field(default_factory=list)
    allowed_lengths: list[str] = field(default_factory=lambda: ["Tiny", "Short", "Medium", "Long", "XL", "Plat"])
    allowed_difficulties: list[str] = field(default_factory=lambda: ["Unrated", "Auto", "Easy", "Normal", "Hard", "Harder", "Insane", "Easy Demon", "Medium Demon", "Hard Demon", "Insane Demon", "Extreme Demon"])
    no_disliked: bool = False
    max_levels_per_requester: int = 0
    thumbnail_cache_size: int = 25
    requester_cooldown: int = 0
    requester_level_counts: dict[str, int] = field(default_factory=dict)
    blacklist_timestamps: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "levels": {},
        "authors": {},
        "requesters": {}
    })
    # API settings
    api_local_port: int = 6767
    api_host_to_network: bool = False
    api_network_port: int = 6767

    # prio + onli
    twitch_sub_priority: bool = False
    twitch_vip_priority: bool = False
    twitch_mod_priority: bool = False
    twitch_subs_only: bool = False
    twitch_vip_only: bool = False
    twitch_followers_only: bool = False
    twitch_bot_channel_name: str = ""
    twitch_reward_id: str = ""
    twitch_reward_name: str = ""
    twitch_reward_only: bool = False
    twitch_reward_priority: bool = False

    youtube_members_only: bool = False
    youtube_superchats_only: bool = False
    youtube_superchat_priority: bool = False
    youtube_member_priority: bool = False

    allow_any_level: bool = False
    print_full_log_to_console: bool = False
    queue_popout_scale: float = 1.0
    requests_enabled: bool = True
    auto_blacklist_on_delete: bool = False
    auto_blacklist_unless_updated: bool = False

    # bot reply toggles
    twitch_bot_disabled_replies: list = field(default_factory=list)
    twitch_bot_no_prefix: bool = False

    # custom commands
    command_del: str = "!del"
    command_replace: str = "!replace"
    command_queue: str = "!queue"
    command_whereami: str = "!whereami"
    command_commands: str = "!commands"



class QueueManager(QObject):
    changed = Signal()
    first_level_added = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        # Guards all reads/writes of self._data and self._requester_last_request_time,
        # since QueueManager is mutated concurrently from the Twitch/YouTube chat
        # worker threads, the API server's per-request threads, and the Qt main thread.
        self._lock = threading.RLock()
        self._data = QueueData()
        self._requester_last_request_time: dict[str, float] = {}
        self.load()

    def add_listener(self, callback: Callable[[], None]) -> None:
        # Threading improvement: QueueManager is mutated from the Twitch/YouTube
        # chat worker threads and the API server's per-request threads, but
        # listeners (refresh_queue, popout refresh, etc.) touch Qt widgets and
        # must only ever run on the main GUI thread. QueuedConnection makes Qt
        # marshal the call onto QueueManager's own thread (the main thread)
        # via the event loop instead of invoking it directly on whichever
        # worker thread called _notify()/emit().

        # i regret looking at ts now ppl will think ts is vibecoded
        self.changed.connect(callback, Qt.ConnectionType.QueuedConnection)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        try:
            self.changed.disconnect(callback)
        except (RuntimeError, TypeError):
            pass

    def _notify(self) -> None:
        self.changed.emit()

    @property
    def levels(self) -> list[LevelEntry]:
        with self._lock:
            return list(self._data.levels)

    @property
    def level_history(self) -> list[LevelEntry]:
        with self._lock:
            return list(self._data.level_history)

    @property
    def blacklist_levels(self) -> list[str]:
        with self._lock:
            return list(self._data.blacklist_levels)

    @property
    def blacklist_authors(self) -> list[str]:
        with self._lock:
            return list(self._data.blacklist_authors)

    @property
    def blacklist_requesters(self) -> list[str]:
        with self._lock:
            return list(self._data.blacklist_requesters)

    @property
    def allowed_lengths(self) -> list[str]:
        with self._lock:
            return list(self._data.allowed_lengths)

    @allowed_lengths.setter
    def allowed_lengths(self, value: list[str]) -> None:
        with self._lock:
            self._data.allowed_lengths = list(value)
            self.save()
        self._notify()

    @property
    def allowed_difficulties(self) -> list[str]:
        with self._lock:
            return list(self._data.allowed_difficulties)

    @allowed_difficulties.setter
    def allowed_difficulties(self, value: list[str]) -> None:
        with self._lock:
            self._data.allowed_difficulties = list(value)
            self.save()
        self._notify()

    @property
    def no_disliked(self) -> bool:
        with self._lock:
            return self._data.no_disliked

    @no_disliked.setter
    def no_disliked(self, value: bool) -> None:
        with self._lock:
            self._data.no_disliked = value
            self.save()
        self._notify()

    @property
    def max_levels_per_requester(self) -> int:
        with self._lock:
            return self._data.max_levels_per_requester

    @max_levels_per_requester.setter
    def max_levels_per_requester(self, value: int) -> None:
        with self._lock:
            self._data.max_levels_per_requester = value
            self.save()
        self._notify()

    @property
    def thumbnail_cache_size(self) -> int:
        with self._lock:
            return self._data.thumbnail_cache_size

    @thumbnail_cache_size.setter
    def thumbnail_cache_size(self, value: int) -> None:
        with self._lock:
            self._data.thumbnail_cache_size = int(value)
            self.save()
        self._notify()

    @property
    def requester_cooldown(self) -> int:
        with self._lock:
            return self._data.requester_cooldown

    @requester_cooldown.setter
    def requester_cooldown(self, value: int) -> None:
        with self._lock:
            self._data.requester_cooldown = int(value)
            self.save()
        self._notify()

    @property
    def twitch_sub_priority(self) -> bool:
        with self._lock:
            return self._data.twitch_sub_priority

    @twitch_sub_priority.setter
    def twitch_sub_priority(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_sub_priority = value
            self.save()
        self._notify()

    @property
    def twitch_vip_priority(self) -> bool:
        with self._lock:
            return self._data.twitch_vip_priority

    @twitch_vip_priority.setter
    def twitch_vip_priority(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_vip_priority = value
            self.save()
        self._notify()

    @property
    def twitch_mod_priority(self) -> bool:
        with self._lock:
            return self._data.twitch_mod_priority

    @twitch_mod_priority.setter
    def twitch_mod_priority(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_mod_priority = value
            self.save()
        self._notify()

    @property
    def twitch_bot_channel_name(self) -> str:
        with self._lock:
            return self._data.twitch_bot_channel_name

    @twitch_bot_channel_name.setter
    def twitch_bot_channel_name(self, value: str) -> None:
        with self._lock:
            self._data.twitch_bot_channel_name = value
            self.save()
        self._notify()

    @property
    def twitch_subs_only(self) -> bool:
        with self._lock:
            return self._data.twitch_subs_only

    @twitch_subs_only.setter
    def twitch_subs_only(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_subs_only = value
            self.save()
        self._notify()

    @property
    def twitch_vip_only(self) -> bool:
        with self._lock:
            return self._data.twitch_vip_only

    @twitch_vip_only.setter
    def twitch_vip_only(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_vip_only = value
            self.save()
        self._notify()

    @property
    def twitch_followers_only(self) -> bool:
        with self._lock:
            return self._data.twitch_followers_only

    @twitch_followers_only.setter
    def twitch_followers_only(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_followers_only = value
        self.save()
        self._notify()

    @property
    def twitch_reward_id(self) -> str:
        with self._lock:
            return self._data.twitch_reward_id

    @twitch_reward_id.setter
    def twitch_reward_id(self, value: str) -> None:
        with self._lock:
            self._data.twitch_reward_id = value
        self.save()
        self._notify()

    @property
    def twitch_reward_name(self) -> str:
        with self._lock:
            return self._data.twitch_reward_name

    @twitch_reward_name.setter
    def twitch_reward_name(self, value: str) -> None:
        with self._lock:
            self._data.twitch_reward_name = value
        self.save()
        self._notify()

    @property
    def twitch_reward_only(self) -> bool:
        with self._lock:
            return self._data.twitch_reward_only

    @twitch_reward_only.setter
    def twitch_reward_only(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_reward_only = value
        self.save()
        self._notify()

    @property
    def twitch_reward_priority(self) -> bool:
        with self._lock:
            return self._data.twitch_reward_priority

    @twitch_reward_priority.setter
    def twitch_reward_priority(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_reward_priority = value
        self.save()
        self._notify()

    @property
    def youtube_members_only(self) -> bool:
        with self._lock:
            return self._data.youtube_members_only

    @youtube_members_only.setter
    def youtube_members_only(self, value: bool) -> None:
        with self._lock:
            self._data.youtube_members_only = value
            self.save()
        self._notify()

    @property
    def youtube_superchats_only(self) -> bool:
        with self._lock:
            return self._data.youtube_superchats_only

    @youtube_superchats_only.setter
    def youtube_superchats_only(self, value: bool) -> None:
        with self._lock:
            self._data.youtube_superchats_only = value
            self.save()
        self._notify()

    @property
    def youtube_superchat_priority(self) -> bool:
        with self._lock:
            return self._data.youtube_superchat_priority

    @youtube_superchat_priority.setter
    def youtube_superchat_priority(self, value: bool) -> None:
        with self._lock:
            self._data.youtube_superchat_priority = value
            self.save()
        self._notify()

    @property
    def youtube_member_priority(self) -> bool:
        with self._lock:
            return self._data.youtube_member_priority

    @youtube_member_priority.setter
    def youtube_member_priority(self, value: bool) -> None:
        with self._lock:
            self._data.youtube_member_priority = value
            self.save()
        self._notify() # 🤑🤑🤑

    @property
    def allow_any_level(self) -> bool:
        with self._lock:
            return self._data.allow_any_level

    @allow_any_level.setter
    def allow_any_level(self, value: bool) -> None:
        with self._lock:
            self._data.allow_any_level = value
            self.save()
        self._notify()

    @property
    def print_full_log_to_console(self) -> bool:
        with self._lock:
            return self._data.print_full_log_to_console

    @print_full_log_to_console.setter
    def print_full_log_to_console(self, value: bool) -> None:
        with self._lock:
            self._data.print_full_log_to_console = bool(value)
            self.save()
        try:
            from hwgdreqs.logging_service import update_console_logging
            update_console_logging(bool(value))
        except Exception:
            pass

    @property
    def requests_enabled(self) -> bool:
        with self._lock:
            return self._data.requests_enabled

    @requests_enabled.setter
    def requests_enabled(self, value: bool) -> None:
        with self._lock:
            self._data.requests_enabled = bool(value)
            self.save()
        self._notify()

    @property
    def queue_popout_scale(self) -> float:
        with self._lock:
            return self._data.queue_popout_scale

    @queue_popout_scale.setter
    def queue_popout_scale(self, value: float) -> None:
        with self._lock:
            self._data.queue_popout_scale = float(value)
            self.save()
        # no notify.. not queue data, just UI pref

    @property
    def auto_blacklist_on_delete(self) -> bool:
        with self._lock:
            return self._data.auto_blacklist_on_delete

    @auto_blacklist_on_delete.setter
    def auto_blacklist_on_delete(self, value: bool) -> None:
        with self._lock:
            self._data.auto_blacklist_on_delete = bool(value)
            self.save()
        self._notify()

    @property
    def auto_blacklist_unless_updated(self) -> bool:
        with self._lock:
            return self._data.auto_blacklist_unless_updated

    @auto_blacklist_unless_updated.setter
    def auto_blacklist_unless_updated(self, value: bool) -> None:
        with self._lock:
            self._data.auto_blacklist_unless_updated = bool(value)
            self.save()
        self._notify()

    @property
    def twitch_bot_disabled_replies(self) -> list:
        with self._lock:
            return list(self._data.twitch_bot_disabled_replies)

    @twitch_bot_disabled_replies.setter
    def twitch_bot_disabled_replies(self, value: list) -> None:
        with self._lock:
            self._data.twitch_bot_disabled_replies = list(value)
            self.save()

    @property
    def twitch_bot_no_prefix(self) -> bool:
        with self._lock:
            return self._data.twitch_bot_no_prefix

    @twitch_bot_no_prefix.setter
    def twitch_bot_no_prefix(self, value: bool) -> None:
        with self._lock:
            self._data.twitch_bot_no_prefix = bool(value)
            self.save()

    def is_reply_enabled(self, key: str) -> bool:
        """Return True if the bot is allowed to send this reply type."""
        with self._lock:
            return key not in self._data.twitch_bot_disabled_replies

    @property
    def command_del(self) -> str:
        with self._lock:
            return self._data.command_del

    @command_del.setter
    def command_del(self, value: str) -> None:
        with self._lock:
            self._data.command_del = value
            self.save()

    @property
    def command_replace(self) -> str:
        with self._lock:
            return self._data.command_replace

    @command_replace.setter
    def command_replace(self, value: str) -> None:
        with self._lock:
            self._data.command_replace = value
            self.save()

    @property
    def command_queue(self) -> str:
        with self._lock:
            return self._data.command_queue

    @command_queue.setter
    def command_queue(self, value: str) -> None:
        with self._lock:
            self._data.command_queue = value
            self.save()

    @property
    def command_whereami(self) -> str:
        with self._lock:
            return self._data.command_whereami

    @command_whereami.setter
    def command_whereami(self, value: str) -> None:
        with self._lock:
            self._data.command_whereami = value
            self.save()

    @property
    def command_commands(self) -> str:
        with self._lock:
            return self._data.command_commands

    @command_commands.setter
    def command_commands(self, value: str) -> None:
        with self._lock:
            self._data.command_commands = value
            self.save()



    def is_on_cooldown(self, requester: str) -> bool:
        with self._lock:
            if self._data.requester_cooldown <= 0:
                return False
            now = time.time()
            last_time = self._requester_last_request_time.get(requester.lower(), 0.0)
            return (now - last_time) < self._data.requester_cooldown

    def get_remaining_cooldown(self, requester: str) -> int:
        with self._lock:
            if self._data.requester_cooldown <= 0:
                return 0
            now = time.time()
            last_time = self._requester_last_request_time.get(requester.lower(), 0.0)
            remaining = self._data.requester_cooldown - (now - last_time)
            return max(0, int(remaining))

    def update_cooldown(self, requester: str) -> None:
        with self._lock:
            self._requester_last_request_time[requester.lower()] = time.time()

    def check_and_update_cooldown(self, requester: str) -> bool:
        with self._lock:
            if self.is_on_cooldown(requester):
                return False
            self.update_cooldown(requester)
            return True

    def get_requester_level_count(self, requester: str) -> int:
        with self._lock:
            return self._data.requester_level_counts.get(requester.lower(), 0)

    def increment_requester_level_count(self, requester: str) -> None:
        with self._lock:
            key = requester.lower()
            self._data.requester_level_counts[key] = self._data.requester_level_counts.get(key, 0) + 1

    def clear_requester_level_counts(self) -> None:
        with self._lock:
            self._data.requester_level_counts.clear()

    def load(self) -> None:
        path = queue_file()
        if not path.exists():
            with self._lock:
                self._data = QueueData()
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            with self._lock:
                self._data = QueueData()
            return

        new_data = QueueData(
            levels=[
                LevelEntry(
                    id=entry.get("id", ""),
                    name=entry.get("name", ""),
                    author=entry.get("author", ""),
                    difficulty=entry.get("difficulty", ""),
                    requester=entry.get("requester", ""),
                    platform=entry.get("platform", "twitch"),
                    platform_icon=entry.get("platform_icon", ""),
                    message=entry.get("message", ""),
                    description=entry.get("description", ""),
                    length=entry.get("length", ""),
                    large=entry.get("large", False),
                    two_player=entry.get("two_player", False),
                    timestamp=entry.get("timestamp", 0.0),
                    likes=entry.get("likes", 0),
                    downloads=entry.get("downloads", 0),
                    disliked=entry.get("disliked", False),
                    priority=entry.get("priority", False),
                    version=int(entry.get("version", 0)),
                    superchat=entry.get("superchat", False),
                    superchat_amount=entry.get("superchat_amount", ""),
                    member=entry.get("member", False),
                )
                for entry in raw.get("levels", [])
            ],
            level_history=[
                LevelEntry(
                    id=entry.get("id", ""),
                    name=entry.get("name", ""),
                    author=entry.get("author", ""),
                    difficulty=entry.get("difficulty", ""),
                    requester=entry.get("requester", ""),
                    platform=entry.get("platform", "twitch"),
                    platform_icon=entry.get("platform_icon", ""),
                    message=entry.get("message", ""),
                    description=entry.get("description", ""),
                    length=entry.get("length", ""),
                    large=entry.get("large", False),
                    two_player=entry.get("two_player", False),
                    timestamp=entry.get("timestamp", 0.0),
                    likes=entry.get("likes", 0),
                    downloads=entry.get("downloads", 0),
                    disliked=entry.get("disliked", False),
                    priority=entry.get("priority", False),
                    version=int(entry.get("version", 0)),
                    superchat=entry.get("superchat", False),
                    superchat_amount=entry.get("superchat_amount", ""),
                    member=entry.get("member", False),
                )
                for entry in raw.get("level_history", [])
            ],
            blacklist_levels=list(raw.get("blacklist_levels", [])),
            blacklist_authors=list(raw.get("blacklist_authors", [])),
            blacklist_requesters=list(raw.get("blacklist_requesters", [])),
            allowed_lengths=list(raw.get("allowed_lengths", ["Tiny", "Short", "Medium", "Long", "XL", "Plat"])),
            allowed_difficulties=list(raw.get("allowed_difficulties", ["Unrated", "Auto", "Easy", "Normal", "Hard", "Harder", "Insane", "Easy Demon", "Medium Demon", "Hard Demon", "Insane Demon", "Extreme Demon"])),
            no_disliked=bool(raw.get("no_disliked", False)),
            max_levels_per_requester=int(raw.get("max_levels_per_requester", 0)),
            thumbnail_cache_size=int(raw.get("thumbnail_cache_size", 25)),
            requester_cooldown=int(raw.get("requester_cooldown", 0)),
            api_local_port=int(raw.get("api_local_port", 6767)),
            api_host_to_network=bool(raw.get("api_host_to_network", False)),
            api_network_port=int(raw.get("api_network_port", 6767)),
            twitch_sub_priority=bool(raw.get("twitch_sub_priority", False)),
            twitch_vip_priority=bool(raw.get("twitch_vip_priority", False)),
            twitch_mod_priority=bool(raw.get("twitch_mod_priority", False)),
            twitch_subs_only=bool(raw.get("twitch_subs_only", False)),
            twitch_vip_only=bool(raw.get("twitch_vip_only", False)),
            twitch_followers_only=bool(raw.get("twitch_followers_only", False)),
            twitch_bot_channel_name=str(raw.get("twitch_bot_channel_name", "")),
            twitch_reward_id=str(raw.get("twitch_reward_id", "")),
            twitch_reward_name=str(raw.get("twitch_reward_name", "")),
            twitch_reward_only=bool(raw.get("twitch_reward_only", False)),
            twitch_reward_priority=bool(raw.get("twitch_reward_priority", False)),
            youtube_members_only=bool(raw.get("youtube_members_only", False)),
            youtube_superchats_only=bool(raw.get("youtube_superchats_only", False)),
            youtube_superchat_priority=bool(raw.get("youtube_superchat_priority", False)),
            youtube_member_priority=bool(raw.get("youtube_member_priority", False)),
            allow_any_level=bool(raw.get("allow_any_level", False)),
            print_full_log_to_console=bool(raw.get("print_full_log_to_console", False)),
            queue_popout_scale=float(raw.get("queue_popout_scale", 1.0)),
            requests_enabled=bool(raw.get("requests_enabled", True)),
            auto_blacklist_on_delete=bool(raw.get("auto_blacklist_on_delete", False)),
            auto_blacklist_unless_updated=bool(raw.get("auto_blacklist_unless_updated", False)),
            twitch_bot_disabled_replies=list(raw.get("twitch_bot_disabled_replies", [])),
            twitch_bot_no_prefix=bool(raw.get("twitch_bot_no_prefix", False)),
            command_del=str(raw.get("command_del", "!del")),
            command_replace=str(raw.get("command_replace", "!replace")),
            command_queue=str(raw.get("command_queue", "!queue")),
            command_whereami=str(raw.get("command_whereami", "!whereami")),
            command_commands=str(raw.get("command_commands", "!commands")),
        )

        # Populate missing timestamps
        blacklist_timestamps = raw.get("blacklist_timestamps", {})
        new_data.blacklist_timestamps = {
            "levels": blacklist_timestamps.get("levels", {}),
            "authors": blacklist_timestamps.get("authors", {}),
            "requesters": blacklist_timestamps.get("requesters", {})
        }
        for item in new_data.blacklist_levels:
            if item not in new_data.blacklist_timestamps["levels"]:
                new_data.blacklist_timestamps["levels"][item] = 0.0
        for item in new_data.blacklist_authors:
            key = item.lower()
            if key not in new_data.blacklist_timestamps["authors"]:
                new_data.blacklist_timestamps["authors"][key] = 0.0
        for item in new_data.blacklist_requesters:
            key = item.lower()
            if key not in new_data.blacklist_timestamps["requesters"]:
                new_data.blacklist_timestamps["requesters"][key] = 0.0

        with self._lock:
            self._data = new_data

    def save(self) -> None:
        # C2 fix: guard the read of self._data with the lock, and write atomically
        # (temp file + os.replace) so a crash or concurrent read never observes a
        # partially-written / corrupted data.json.
        with self._lock:
            payload = {
                "levels": [asdict(entry) for entry in self._data.levels],
                "level_history": [asdict(entry) for entry in self._data.level_history],
                "blacklist_levels": self._data.blacklist_levels,
                "blacklist_authors": self._data.blacklist_authors,
                "blacklist_requesters": self._data.blacklist_requesters,
                "allowed_lengths": self._data.allowed_lengths,
                "allowed_difficulties": self._data.allowed_difficulties,
                "no_disliked": self._data.no_disliked,
                "max_levels_per_requester": self._data.max_levels_per_requester,
                "thumbnail_cache_size": self._data.thumbnail_cache_size,
                "requester_cooldown": self._data.requester_cooldown,
                "blacklist_timestamps": self._data.blacklist_timestamps,
                "api_local_port": self._data.api_local_port,
                "api_host_to_network": self._data.api_host_to_network,
                "api_network_port": self._data.api_network_port,
                "twitch_sub_priority": self._data.twitch_sub_priority,
                "twitch_vip_priority": self._data.twitch_vip_priority,
                "twitch_mod_priority": self._data.twitch_mod_priority,
                "twitch_subs_only": self._data.twitch_subs_only,
                "twitch_vip_only": self._data.twitch_vip_only,
                "twitch_followers_only": self._data.twitch_followers_only,
                "twitch_bot_channel_name": self._data.twitch_bot_channel_name,
                "twitch_reward_id": self._data.twitch_reward_id,
                "twitch_reward_name": self._data.twitch_reward_name,
                "twitch_reward_only": self._data.twitch_reward_only,
                "twitch_reward_priority": self._data.twitch_reward_priority,
                "youtube_members_only": self._data.youtube_members_only,
                "youtube_superchats_only": self._data.youtube_superchats_only,
                "youtube_superchat_priority": self._data.youtube_superchat_priority,
                "youtube_member_priority": self._data.youtube_member_priority,
                "allow_any_level": self._data.allow_any_level,
                "print_full_log_to_console": self._data.print_full_log_to_console,
                "queue_popout_scale": self._data.queue_popout_scale,
                "requests_enabled": self._data.requests_enabled,
                "auto_blacklist_on_delete": self._data.auto_blacklist_on_delete,
                "auto_blacklist_unless_updated": self._data.auto_blacklist_unless_updated,
                "twitch_bot_disabled_replies": self._data.twitch_bot_disabled_replies,
                "twitch_bot_no_prefix": self._data.twitch_bot_no_prefix,
                "command_del": self._data.command_del,
                "command_replace": self._data.command_replace,
                "command_queue": self._data.command_queue,
                "command_whereami": self._data.command_whereami,
                "command_commands": self._data.command_commands,
            }

            target_path = queue_file()
            target_dir = target_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                dir=str(target_dir),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target_path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        
    @property
    def api_local_port(self):
        with self._lock:
            return self._data.api_local_port
        
    @api_local_port.setter
    def api_local_port(self, value):
        with self._lock:
            self._data.api_local_port = value
            self.save()
        self._notify()
        
    @property
    def api_host_to_network(self):
        with self._lock:
            return self._data.api_host_to_network
        
    @api_host_to_network.setter
    def api_host_to_network(self, value):
        with self._lock:
            self._data.api_host_to_network = value
            self.save()
        self._notify()
        
    @property
    def api_network_port(self):
        with self._lock:
            return self._data.api_network_port
        
    @api_network_port.setter
    def api_network_port(self, value):
        with self._lock:
            self._data.api_network_port = value
            self.save()
        self._notify()

    def add_level(
        self,
        *,
        level_id: str,
        name: str,
        author: str,
        difficulty: str,
        requester: str,
        platform: str = "twitch",
        platform_icon: str = "",
        message: str = "",
        description: str = "",
        length: str = "",
        large: bool = False,
        two_player: bool = False,
        disliked: bool = False,
        timestamp: float | None = None,
        likes: int = 0,
        downloads: int = 0,
        priority: bool = False,
        version: int = 0,
        superchat: bool = False,
        superchat_amount: str = "",
        member: bool = False,
    ) -> bool:
        level_id = str(level_id)
        author_lower = author.lower()
        requester_lower = requester.lower()

        accepted = True
        unblacklisted_now = False
        was_empty = False
        entry = None

        with self._lock:
            if not self._data.requests_enabled:
                accepted = False
            elif level_id in self._data.blacklist_levels:
                if self._data.auto_blacklist_unless_updated:
                    old_version = 0
                    for hist_entry in self._data.level_history:
                        if hist_entry.id == level_id:
                            old_version = hist_entry.version
                            break
                    if old_version != 0 and version != old_version:
                        self._data.blacklist_levels = [lid for lid in self._data.blacklist_levels if lid != level_id]
                        self._data.blacklist_timestamps["levels"].pop(level_id, None)
                        unblacklisted_now = True
                        log_level_unblacklisted(level_id)
                    else:
                        accepted = False
                else:
                    accepted = False

            if accepted and author_lower in [a.lower() for a in self._data.blacklist_authors]:
                accepted = False
            if accepted and requester_lower in [r.lower() for r in self._data.blacklist_requesters]:
                accepted = False
            if accepted and any(entry.id == level_id for entry in self._data.levels):
                accepted = False
                
            is_placeholder = name.startswith("⚠️")
            bypass_filters = is_placeholder and self._data.allow_any_level
            
            if accepted and not bypass_filters:
                if self._data.allowed_difficulties and difficulty not in self._data.allowed_difficulties:
                    accepted = False
                elif self._data.allowed_lengths and length and length not in self._data.allowed_lengths:
                    accepted = False
                elif self._data.no_disliked and disliked:
                    accepted = False
            if accepted and self._data.max_levels_per_requester > 0:
                if self.get_requester_level_count(requester) >= self._data.max_levels_per_requester:
                    accepted = False

            if accepted:
                if timestamp is None:
                    timestamp = time.time()

                was_empty = len(self._data.levels) == 0

                entry = LevelEntry(
                    id=level_id,
                    name=name,
                    author=author,
                    difficulty=difficulty,
                    requester=requester,
                    platform=platform,
                    platform_icon=platform_icon,
                    message=message,
                    description=description,
                    length=length,
                    large=large,
                    two_player=two_player,
                    timestamp=timestamp,
                    likes=likes,
                    downloads=downloads,
                    disliked=disliked,
                    priority=priority,
                    version=version,
                    superchat=superchat,
                    superchat_amount=superchat_amount,
                    member=member,
                )

                if priority:
                    insert_idx = 0
                    for idx, e in enumerate(self._data.levels):
                        if e.priority:
                            insert_idx = idx + 1
                    self._data.levels.insert(insert_idx, entry)
                else:
                    self._data.levels.append(entry)

                self.increment_requester_level_count(requester)
                self.save()
            elif unblacklisted_now:
                self.save()

        if accepted:
            self._notify()
            if was_empty:
                self.first_level_added.emit(entry)
            log_level_added(level_id, name, requester, platform)
            return True

        if unblacklisted_now:
            self._notify()
        return False

    def remove_level(self, level_id: str) -> None:
        with self._lock:
            level_to_remove = None
            for e in self._data.levels:
                if e.id == level_id:
                    level_to_remove = e
                    break

            self._data.levels = [e for e in self._data.levels if e.id != level_id]
            if level_to_remove:
                self._data.level_history.insert(0, level_to_remove)
            self.save()

        self._notify()
        
        if level_to_remove:
            log_level_deleted(level_to_remove.id, level_to_remove.name, level_to_remove.requester)
            if self.auto_blacklist_on_delete:
                self.blacklist_level(level_id)

    def replace_level(
        self,
        old_level_id: str,
        *,
        level_id: str,
        name: str,
        author: str,
        difficulty: str,
        requester: str,
        platform: str = "twitch",
        message: str = "",
        description: str = "",
        length: str = "",
        large: bool = False,
        two_player: bool = False,
        disliked: bool = False,
        timestamp: float | None = None,
        likes: int = 0,
        downloads: int = 0,
        version: int = 0,
        superchat: bool = False,
        superchat_amount: str = "",
        member: bool = False,
    ) -> None:

        with self._lock:
            old_index = None
            old_level = None
            for i, entry in enumerate(self._data.levels):
                if entry.id == old_level_id:
                    old_index = i
                    old_level = entry
                    break

            if old_index is None:
                return

            if timestamp is None:
                timestamp = old_level.timestamp if old_level else time.time()

            entry = LevelEntry(
                id=level_id,
                name=name,
                author=author,
                difficulty=difficulty,
                requester=requester,
                platform=platform,
                platform_icon=platform_icon if platform_icon else (old_level.platform_icon if old_level else ""),
                message=message,
                description=description,
                length=length,
                large=large,
                two_player=two_player,
                timestamp=timestamp,
                likes=likes,
                downloads=downloads,
                disliked=disliked,
                priority=old_level.priority if old_level else False,
                version=version,
                superchat=superchat if superchat else (old_level.superchat if old_level else False),
                superchat_amount=superchat_amount if superchat_amount else (old_level.superchat_amount if old_level else ""),
                member=member if member else (old_level.member if old_level else False),
            )

            self._data.levels[old_index] = entry
            self.save()

        self._notify()
        if old_level:
            log_level_swapped(old_level.id, old_level.name, level_id, name)

    def blacklist_level(self, level_id: str) -> None:
        with self._lock:
            level_name = None
            for e in self._data.levels:
                if e.id == level_id:
                    level_name = e.name
                    break

            if level_id not in self._data.blacklist_levels:
                self._data.blacklist_levels.append(level_id)
                self._data.blacklist_timestamps["levels"][level_id] = time.time()
                self.save()
            else:
                return

        self._notify()
        if level_name:
            log_level_blacklisted(level_id, level_name)

    def blacklist_author(self, author: str) -> None:
        with self._lock:
            key = author.lower()
            if key in [a.lower() for a in self._data.blacklist_authors]:
                return
            self._data.blacklist_authors.append(author)
            self._data.blacklist_timestamps["authors"][key] = time.time()
            self.save()

        self._notify()
        log_author_blacklisted(author)

    def blacklist_requester(self, requester: str) -> None:
        with self._lock:
            key = requester.lower()
            if key in [r.lower() for r in self._data.blacklist_requesters]:
                return
            self._data.blacklist_requesters.append(requester)
            self._data.blacklist_timestamps["requesters"][key] = time.time()
            self.save()

        self._notify()
        log_requester_blacklisted(requester)

    def remove_blacklist_level(self, level_id: str) -> None:
        with self._lock:
            self._data.blacklist_levels = [
                lid for lid in self._data.blacklist_levels if lid != level_id
            ]
            self._data.blacklist_timestamps["levels"].pop(level_id, None)
            self.save()

        self._notify()
        log_level_unblacklisted(level_id)

    def remove_blacklist_author(self, author: str) -> None:
        with self._lock:
            key = author.lower()
            self._data.blacklist_authors = [
                a for a in self._data.blacklist_authors if a.lower() != key
            ]
            self._data.blacklist_timestamps["authors"].pop(key, None)
            self.save()

        self._notify()
        log_author_unblacklisted(author)

    def remove_blacklist_requester(self, requester: str) -> None:
        with self._lock:
            key = requester.lower()
            self._data.blacklist_requesters = [
                r for r in self._data.blacklist_requesters if r.lower() != key
            ]
            self._data.blacklist_timestamps["requesters"].pop(key, None)
            self.save()

        self._notify()
        log_requester_unblacklisted(requester)

    def clear_queue(self) -> None:
        with self._lock:
            self._data.level_history = self._data.levels + self._data.level_history
            self._data.levels = []
            self.save()

        self._notify()
        log_queue_cleared()

    def clear_by_requester(self, requester: str) -> None:
        with self._lock:
            removed = [e for e in self._data.levels if e.requester.lower() == requester.lower()]
            kept = [e for e in self._data.levels if e.requester.lower() != requester.lower()]
            self._data.level_history = removed + self._data.level_history
            self._data.levels = kept
            self.save()

        self._notify()

    def clear_by_author(self, author: str) -> None:
        with self._lock:
            removed = [e for e in self._data.levels if e.author.lower() == author.lower()]
            kept = [e for e in self._data.levels if e.author.lower() != author.lower()]
            self._data.level_history = removed + self._data.level_history
            self._data.levels = kept
            self.save()

        self._notify()

    def reorder_levels(self, new_levels: list[LevelEntry]) -> None:
        with self._lock:
            self._data.levels = list(new_levels)
            self.save()

        self._notify()

    def shuffle_queue(self) -> None:
        with self._lock:
            shuffled = list(self._data.levels)
            random.shuffle(shuffled)
            self._data.levels = shuffled
            self.save()

        self._notify()

    def move_level_up(self, level_id: str) -> None:
        with self._lock:
            levels = list(self._data.levels)
            moved = False
            for i, entry in enumerate(levels):
                if entry.id == level_id:
                    if i > 0:
                        levels[i], levels[i - 1] = levels[i - 1], levels[i]
                        self._data.levels = levels
                        self.save()
                        moved = True
                    break
        if moved:
            self._notify()

    def move_level_down(self, level_id: str) -> None:
        with self._lock:
            levels = list(self._data.levels)
            moved = False
            for i, entry in enumerate(levels):
                if entry.id == level_id:
                    if i < len(levels) - 1:
                        levels[i], levels[i + 1] = levels[i + 1], levels[i]
                        self._data.levels = levels
                        self.save()
                        moved = True
                    break
        if moved:
            self._notify()

    def remove_levels_by_requester(self, requester: str) -> None:
        with self._lock:
            requester_lower = requester.lower()
            to_remove = [e for e in self._data.levels if e.requester.lower() == requester_lower]
            if not to_remove:
                return
            self._data.levels = [e for e in self._data.levels if e.requester.lower() != requester_lower]
            for e in reversed(to_remove):
                self._data.level_history.insert(0, e)
            self.save()

        self._notify()
        for e in reversed(to_remove):
            log_level_deleted(e.id, e.name, e.requester)

    def remove_levels_by_author(self, author: str) -> None:
        with self._lock:
            author_lower = author.lower()
            to_remove = [e for e in self._data.levels if e.author.lower() == author_lower]
            if not to_remove:
                return
            self._data.levels = [e for e in self._data.levels if e.author.lower() != author_lower]
            for e in reversed(to_remove):
                self._data.level_history.insert(0, e)
            self.save()

        self._notify()
        for e in reversed(to_remove):
            log_level_deleted(e.id, e.name, e.requester)


def add_level_to_queue(
    queue: QueueManager,
    *,
    level_id: str,
    name: str,
    author: str,
    difficulty: str,
    requester: str,
    platform: str = "twitch",
) -> bool:

    return queue.add_level(
        level_id=level_id,
        name=name,
        author=author,
        difficulty=difficulty,
        requester=requester,
        platform=platform,
    )
