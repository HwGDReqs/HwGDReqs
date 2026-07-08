import json
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
    requester_level_counts: dict[str, int] = field(default_factory=dict)


class QueueManager(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._data = QueueData()
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
        )

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
        }
        queue_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
            self.save()
            self._notify()
            if level_name:
                log_level_blacklisted(level_id, level_name)

    def blacklist_author(self, author: str) -> None:
        key = author.lower()
        if key not in [a.lower() for a in self._data.blacklist_authors]:
            self._data.blacklist_authors.append(author)
            self.save()
            self._notify()
            log_author_blacklisted(author)

    def blacklist_requester(self, requester: str) -> None:
        key = requester.lower()
        if key not in [r.lower() for r in self._data.blacklist_requesters]:
            self._data.blacklist_requesters.append(requester)
            self.save()
            self._notify()
            log_requester_blacklisted(requester)

    def remove_blacklist_level(self, level_id: str) -> None:
        self._data.blacklist_levels = [
            lid for lid in self._data.blacklist_levels if lid != level_id
        ]
        self.save()
        self._notify()
        log_level_unblacklisted(level_id)

    def remove_blacklist_author(self, author: str) -> None:
        key = author.lower()
        self._data.blacklist_authors = [
            a for a in self._data.blacklist_authors if a.lower() != key
        ]
        self.save()
        self._notify()
        log_author_unblacklisted(author)

    def remove_blacklist_requester(self, requester: str) -> None:
        key = requester.lower()
        self._data.blacklist_requesters = [
            r for r in self._data.blacklist_requesters if r.lower() != key
        ]
        self.save()
        self._notify()
        log_requester_unblacklisted(requester)

    def clear_queue(self) -> None:
        self._data.levels = []
        self.save()
        self._notify()
        log_queue_cleared()


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
