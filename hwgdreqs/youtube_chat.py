from __future__ import annotations

import re
import signal
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

try:
    from yt_dlp import YoutubeDL
    import pytchat
except ImportError:
    YoutubeDL = None
    pytchat = None

from hwgdreqs.config import LEVEL_ID_PATTERN
from hwgdreqs.gdbrowser import fetch_level
from hwgdreqs.logging_service import get_logger
from hwgdreqs.queue_manager import QueueManager

LEVEL_RE = re.compile(LEVEL_ID_PATTERN)
COMMA_LEVEL_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")

logger = get_logger()


def _extract_video_info(channel_url: str) -> dict:

    if not YoutubeDL:
        return None
    
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(channel_url, download=False)
    except Exception as e:
        return {"error": str(e)}


class YoutubeChatWorker(QObject):
    message_received = Signal(str, str)
    level_detected = Signal(str, str)
    status_changed = Signal(str)
    connection_failed = Signal(str)
    not_streaming = Signal()

    def __init__(self, username: str, queue: QueueManager) -> None:
        super().__init__()
        self._username = username
        self._queue = queue
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._chat = None
        self._video_id: Optional[str] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._chat:
            try:
                self._chat.terminate()
            except Exception:
                pass
        self._chat = None

    def _handle_commands(self, requester: str, message: str) -> bool:
        parts = message.strip().split()
        if not parts:
            return False

        command = parts[0].lower()

        if command == "!del" and len(parts) >= 2:
            level_id = parts[1].replace(",", "")
            logger.info(f"!del command from {requester}: level_id={level_id}")
            self._delete_level_command(requester, level_id)
            return True

        if command == "!replace" and len(parts) >= 3:
            old_level_id = parts[1].replace(",", "")
            new_level_id = parts[2].replace(",", "")
            logger.info(
                f"!replace command from {requester}: {old_level_id} -> {new_level_id}"
            )
            self._replace_level_command(
                requester, old_level_id, new_level_id, message=message
            )
            return True

        return False

    def _delete_level_command(self, requester: str, level_id: str) -> None:
        logger.info(f"Attempting to delete level {level_id} from {requester}")
        for entry in self._queue.levels:
            if entry.id == level_id and entry.requester.lower() == requester.lower():
                logger.info(f"Found matching level {level_id}, deleting")
                self._queue.remove_level(level_id)
                self.status_changed.emit(
                    f"Deleted level {level_id} requested by {requester}"
                )
                return
        logger.warning(f"Level {level_id} not found or not requested by {requester}")

    def _replace_level_command(
        self, requester: str, old_level_id: str, new_level_id: str, message: str
    ) -> None:
        logger.info(
            f"Attempting to replace level {old_level_id} with {new_level_id} from {requester}"
        )
        old_index = None
        for i, entry in enumerate(self._queue.levels):
            if entry.id == old_level_id and entry.requester.lower() == requester.lower():
                old_index = i
                break

        if old_index is None:
            logger.warning(f"Level {old_level_id} not found in queue for {requester}")
            self.status_changed.emit(
                f"Level {old_level_id} not found in queue for {requester}"
            )
            return

        data = fetch_level(new_level_id)
        if not data:
            logger.warning(f"Could not fetch new level {new_level_id}")
            self.status_changed.emit(f"Could not fetch new level {new_level_id}")
            return

        difficulty = str(data.get("difficulty", "Unrated"))
        if difficulty in ["NA", "Unknown"]:
            difficulty = "Unrated"

        logger.info(f"Replacing {old_level_id} with {new_level_id}")
        self._queue.replace_level(
            old_level_id,
            level_id=str(data.get("id", new_level_id)),
            name=str(data.get("name", "Unknown")),
            author=str(data.get("author", "Unknown")),
            difficulty=difficulty,
            requester=requester,
            message=message,
            description=str(data.get("description", "")),
            length=str(data.get("length", "")),
            large=bool(data.get("large", False)),
            two_player=bool(data.get("twoPlayer", False)),
            disliked=bool(data.get("disliked", False)),
            platform="youtube",
        )
        self.status_changed.emit(
            f"Replaced level {old_level_id} with {new_level_id} for {requester}"
        )

    def _enqueue_level(self, requester: str, level_id: str, message: str) -> None:

        data = fetch_level(level_id)
        if not data:
            logger.warning(f"Failed to fetch level {level_id}")
            return
        
        difficulty = str(data.get("difficulty", "Unrated"))
        if difficulty in ["NA", "Unknown"]:
            difficulty = "Unrated"
        
        added = self._queue.add_level(
            level_id=str(data.get("id", level_id)),
            name=str(data.get("name", "Unknown")),
            author=str(data.get("author", "Unknown")),
            difficulty=difficulty,
            requester=requester,
            message=message,
            description=str(data.get("description", "")),
            length=str(data.get("length", "")),
            large=bool(data.get("large", False)),
            two_player=bool(data.get("twoPlayer", False)),
            disliked=bool(data.get("disliked", False)),
            platform="youtube",
        )
        if added:
            logger.info(f"Queued: '{data.get('name')}' by '{data.get('author')}' from '{requester}'")
            self.status_changed.emit(f"Queued: '{data.get('name')}' by '{data.get('author')}' from '{requester}'")

    def _run(self) -> None:
        if not YoutubeDL or not pytchat:
            self.connection_failed.emit("YouTube support requires: yt-dlp and pytchat")
            return

        self.status_changed.emit(f"Connecting to YouTube live stream ({self._username})...")

        try:
            channel_url = f"https://www.youtube.com/{self._username}/live"

            ydl_opts = {
                "quiet": True,
                "skip_download": True,
            }

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            if not info.get("is_live"):
                logger.info(f"YouTube channel {self._username} is not currently live")
                self.not_streaming.emit()
                return

            url = info["webpage_url"]
            self._video_id = info.get("id")

            original_signal = signal.signal
            try:
                signal.signal = lambda *args: None
                self._chat = pytchat.create(video_id=self._video_id)
            finally:
                signal.signal = original_signal
            
            self.status_changed.emit(f"Connected to YouTube live chat ({self._username})")

            while not self._stop_event.is_set() and self._chat.is_alive():
                try:
                    for c in self._chat.get().sync_items():
                        if self._stop_event.is_set():
                            break

                        author = c.author.name
                        message = c.message

                        logger.info(f"YouTube Chat [{author}]: {message}")
                        
                        self.message_received.emit(author, message)

                        if self._handle_commands(author, message):
                            continue

                        matches = []
                        for m in LEVEL_RE.finditer(message):
                            matches.append((m.start(), m.group(1)))
                        for m in COMMA_LEVEL_RE.finditer(message):
                            matches.append((m.start(), m.group(1).replace(",", "")))

                        matches.sort(key=lambda x: x[0])
                        
                        level_ids = []
                        for _, lid in matches:
                            if lid not in level_ids:
                                level_ids.append(lid)

                        if level_ids:
                            if not self._queue.check_and_update_cooldown(author):
                                continue
                            for level_id in level_ids:
                                logger.info(f"Level detected: {level_id} from {author}")
                                self.level_detected.emit(level_id, author)
                                self._enqueue_level(author, level_id, message)
                except Exception as e:
                    if not self._stop_event.is_set():
                        self.status_changed.emit(f"YouTube chat error: {str(e)}")
                    break

        except Exception as e:
            if not self._stop_event.is_set():
                err_msg = str(e)
                if "not currently live" in err_msg:
                    logger.info(f"YouTube channel {self._username} is not currently live (caught: {err_msg})")
                    self.not_streaming.emit()
                else:
                    self.connection_failed.emit(f"Failed to connect to YouTube: {err_msg}")
