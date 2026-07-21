import json
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from PySide6.QtCore import QObject, Signal

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
    message: str = ""
    description: str = ""
    length: str = ""
    large: bool = False
    two_player: bool = False
    timestamp: float = 0.0
    likes: int = 0
    downloads: int = 0
    disliked: bool = False


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
    api_network_port: int = field(default_factory=lambda: random.randint(1024, 65535))


class QueueManager(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._data = QueueData()
        self._requester_last_request_time: dict[str, float] = {}
        self.load()

    def add_listener(self, callback: Callable[[], None]) -> None:
        self.changed.connect(callback)

    def _notify(self) -> None:
        self.changed.emit()

    @property
    def levels(self) -> list[LevelEntry]:
        return list(self._data.levels)

    @property
    def level_history(self) -> list[LevelEntry]:
        return list(self._data.level_history)

    @property
    def blacklist_levels(self) -> list[str]:
        return list(self._data.blacklist_levels)

    @property
    def blacklist_authors(self) -> list[str]:
        return list(self._data.blacklist_authors)

    @property
    def blacklist_requesters(self) -> list[str]:
        return list(self._data.blacklist_requesters)

    @property
    def allowed_lengths(self) -> list[str]:
        return list(self._data.allowed_lengths)

    @allowed_lengths.setter
    def allowed_lengths(self, value: list[str]) -> None:
        self._data.allowed_lengths = list(value)
        self.save()
        self._notify()

    @property
    def allowed_difficulties(self) -> list[str]:
        return list(self._data.allowed_difficulties)

    @allowed_difficulties.setter
    def allowed_difficulties(self, value: list[str]) -> None:
        self._data.allowed_difficulties = list(value)
        self.save()
        self._notify()

    @property
    def no_disliked(self) -> bool:
        return self._data.no_disliked

    @no_disliked.setter
    def no_disliked(self, value: bool) -> None:
        self._data.no_disliked = value
        self.save()
        self._notify()

    @property
    def max_levels_per_requester(self) -> int:
        return self._data.max_levels_per_requester

    @max_levels_per_requester.setter
    def max_levels_per_requester(self, value: int) -> None:
        self._data.max_levels_per_requester = value
        self.save()
        self._notify()

    @property
    def thumbnail_cache_size(self) -> int:
        return self._data.thumbnail_cache_size

    @thumbnail_cache_size.setter
    def thumbnail_cache_size(self, value: int) -> None:
        self._data.thumbnail_cache_size = int(value)
        self.save()
        self._notify()

    @property
    def requester_cooldown(self) -> int:
        return self._data.requester_cooldown

    @requester_cooldown.setter
    def requester_cooldown(self, value: int) -> None:
        self._data.requester_cooldown = int(value)
        self.save()
        self._notify()

    def check_and_update_cooldown(self, requester: str) -> bool:
        """Returns True if the requester is NOT on cooldown (and updates their last request time), False otherwise."""
        if self._data.requester_cooldown <= 0:
            return True
        now = time.time()
        last_time = self._requester_last_request_time.get(requester.lower(), 0.0)
        if now - last_time < self._data.requester_cooldown:
            return False
        self._requester_last_request_time[requester.lower()] = now
        return True

    def get_requester_level_count(self, requester: str) -> int:
        return self._data.requester_level_counts.get(requester.lower(), 0)

    def increment_requester_level_count(self, requester: str) -> None:
        key = requester.lower()
        self._data.requester_level_counts[key] = self._data.requester_level_counts.get(key, 0) + 1

    def clear_requester_level_counts(self) -> None:
        self._data.requester_level_counts.clear()

    def load(self) -> None:
        path = queue_file()
        if not path.exists():
            self._data = QueueData()
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._data = QueueData()
            return

        self._data = QueueData(
            levels=[
                LevelEntry(
                    id=entry.get("id", ""),
                    name=entry.get("name", ""),
                    author=entry.get("author", ""),
                    difficulty=entry.get("difficulty", ""),
                    requester=entry.get("requester", ""),
                    platform=entry.get("platform", "twitch"),
                    message=entry.get("message", ""),
                    description=entry.get("description", ""),
                    length=entry.get("length", ""),
                    large=entry.get("large", False),
                    two_player=entry.get("two_player", False),
                    timestamp=entry.get("timestamp", 0.0),
                    likes=entry.get("likes", 0),
                    downloads=entry.get("downloads", 0),
                    disliked=entry.get("disliked", False),
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
                    message=entry.get("message", ""),
                    description=entry.get("description", ""),
                    length=entry.get("length", ""),
                    large=entry.get("large", False),
                    two_player=entry.get("two_player", False),
                    timestamp=entry.get("timestamp", 0.0),
                    likes=entry.get("likes", 0),
                    downloads=entry.get("downloads", 0),
                    disliked=entry.get("disliked", False),
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
            api_network_port=int(raw.get("api_network_port", random.randint(1024, 65535))),
        )

        # Populate missing timestamps
        blacklist_timestamps = raw.get("blacklist_timestamps", {})
        self._data.blacklist_timestamps = {
            "levels": blacklist_timestamps.get("levels", {}),
            "authors": blacklist_timestamps.get("authors", {}),
            "requesters": blacklist_timestamps.get("requesters", {})
        }
        for item in self._data.blacklist_levels:
            if item not in self._data.blacklist_timestamps["levels"]:
                self._data.blacklist_timestamps["levels"][item] = 0.0
        for item in self._data.blacklist_authors:
            key = item.lower()
            if key not in self._data.blacklist_timestamps["authors"]:
                self._data.blacklist_timestamps["authors"][key] = 0.0
        for item in self._data.blacklist_requesters:
            key = item.lower()
            if key not in self._data.blacklist_timestamps["requesters"]:
                self._data.blacklist_timestamps["requesters"][key] = 0.0

    def save(self) -> None:
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
        }
        queue_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")
        
    @property
    def api_local_port(self):
        return self._data.api_local_port
        
    @api_local_port.setter
    def api_local_port(self, value):
        self._data.api_local_port = value
        self.save()
        self._notify()
        
    @property
    def api_host_to_network(self):
        return self._data.api_host_to_network
        
    @api_host_to_network.setter
    def api_host_to_network(self, value):
        self._data.api_host_to_network = value
        self.save()
        self._notify()
        
    @property
    def api_network_port(self):
        return self._data.api_network_port
        
    @api_network_port.setter
    def api_network_port(self, value):
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
        message: str = "",
        description: str = "",
        length: str = "",
        large: bool = False,
        two_player: bool = False,
        disliked: bool = False,
        timestamp: float | None = None,
        likes: int = 0,
        downloads: int = 0,
    ) -> bool:
        level_id = str(level_id)
        author_lower = author.lower()
        requester_lower = requester.lower()

        if level_id in self._data.blacklist_levels:
            return False
        if author_lower in [a.lower() for a in self._data.blacklist_authors]:
            return False
        if requester_lower in [r.lower() for r in self._data.blacklist_requesters]:
            return False
        if any(entry.id == level_id for entry in self._data.levels):
            return False
        if difficulty not in self._data.allowed_difficulties:
            return False
        if length and length not in self._data.allowed_lengths:
            return False
        if self._data.no_disliked and disliked:
            return False
        
        if self._data.max_levels_per_requester > 0:
            if self.get_requester_level_count(requester) >= self._data.max_levels_per_requester:
                return False
        
        if timestamp is None:
            timestamp = time.time()

        entry = LevelEntry(
            id=level_id,
            name=name,
            author=author,
            difficulty=difficulty,
            requester=requester,
            platform=platform,
            message=message,
            description=description,
            length=length,
            large=large,
            two_player=two_player,
            timestamp=timestamp,
            likes=likes,
            downloads=downloads,
            disliked=disliked,
        )

        self._data.levels.append(entry)

        self.increment_requester_level_count(requester)
        self.save()
        self._notify()
        
        log_level_added(level_id, name, requester, platform)
        return True

    def remove_level(self, level_id: str) -> None:
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
    ) -> None:

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
            message=message,
            description=description,
            length=length,
            large=large,
            two_player=two_player,
            timestamp=timestamp,
            likes=likes,
            downloads=downloads,
            disliked=disliked,
        )
        
        self._data.levels[old_index] = entry
        self.save()
        self._notify()
        
        if old_level:
            log_level_swapped(old_level.id, old_level.name, level_id, name)

    def blacklist_level(self, level_id: str) -> None:
        level_name = None
        for e in self._data.levels:
            if e.id == level_id:
                level_name = e.name
                break
        
        if level_id not in self._data.blacklist_levels:
            self._data.blacklist_levels.append(level_id)
            self._data.blacklist_timestamps["levels"][level_id] = time.time()
            self.save()
            self._notify()
            if level_name:
                log_level_blacklisted(level_id, level_name)

    def blacklist_author(self, author: str) -> None:
        key = author.lower()
        if key not in [a.lower() for a in self._data.blacklist_authors]:
            self._data.blacklist_authors.append(author)
            self._data.blacklist_timestamps["authors"][key] = time.time()
            self.save()
            self._notify()
            log_author_blacklisted(author)

    def blacklist_requester(self, requester: str) -> None:
        key = requester.lower()
        if key not in [r.lower() for r in self._data.blacklist_requesters]:
            self._data.blacklist_requesters.append(requester)
            self._data.blacklist_timestamps["requesters"][key] = time.time()
            self.save()
            self._notify()
            log_requester_blacklisted(requester)

    def remove_blacklist_level(self, level_id: str) -> None:
        self._data.blacklist_levels = [
            lid for lid in self._data.blacklist_levels if lid != level_id
        ]
        self._data.blacklist_timestamps["levels"].pop(level_id, None)
        self.save()
        self._notify()
        log_level_unblacklisted(level_id)

    def remove_blacklist_author(self, author: str) -> None:
        key = author.lower()
        self._data.blacklist_authors = [
            a for a in self._data.blacklist_authors if a.lower() != key
        ]
        self._data.blacklist_timestamps["authors"].pop(key, None)
        self.save()
        self._notify()
        log_author_unblacklisted(author)

    def remove_blacklist_requester(self, requester: str) -> None:
        key = requester.lower()
        self._data.blacklist_requesters = [
            r for r in self._data.blacklist_requesters if r.lower() != key
        ]
        self._data.blacklist_timestamps["requesters"].pop(key, None)
        self.save()
        self._notify()
        log_requester_unblacklisted(requester)

    def clear_queue(self) -> None:
        self._data.level_history = self._data.levels + self._data.level_history
        self._data.levels = []
        self.save()
        self._notify()
        log_queue_cleared()

    def reorder_levels(self, new_levels: list[LevelEntry]) -> None:
        self._data.levels = list(new_levels)
        self.save()
        self._notify()


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
