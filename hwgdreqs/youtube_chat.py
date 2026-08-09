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
from hwgdreqs.gdbrowser import fetch_level_normalized, placeholder_level_data, GDBrowserError, LevelNotFoundError, LevelFetchTimeoutError
from hwgdreqs.logging_service import get_logger
from hwgdreqs.queue_manager import QueueManager

LEVEL_RE = re.compile(LEVEL_ID_PATTERN)
COMMA_LEVEL_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")

logger = get_logger()

# M3 fix: pytchat.create() may internally call signal.signal(), which raises
# outside the main thread on older pytchat versions that don't support
# interruptable=False. The old fallback monkey-patched the global
# `signal.signal` attribute with no synchronization, which is a process-wide
# race if two YouTube (re)connect attempts hit the TypeError fallback at the
# same time. Guard the patch/restore with a dedicated lock so only one thread
# can have `signal.signal` patched out at a time.
_signal_patch_lock = threading.Lock()


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

        try:
            data = fetch_level_normalized(new_level_id)
        except LevelFetchTimeoutError:
            logger.warning(f"Could not fetch new level {new_level_id} (timeout - gdbrowser took too long)")
            self.status_changed.emit(f"Could not fetch new level {new_level_id} (timeout - gdbrowser took too long)")
            return
        except LevelNotFoundError:
            logger.warning(f"Level ID {new_level_id} not found on Geometry Dash servers")
            self.status_changed.emit(f"Level ID {new_level_id} not found on Geometry Dash servers")
            return
        except GDBrowserError as e:
            logger.warning(f"Could not fetch new level {new_level_id}: {str(e)}")
            self.status_changed.emit(f"Could not fetch new level {new_level_id}: {str(e)}")
            return

        logger.info(f"Replacing {old_level_id} with {new_level_id}")
        self._queue.replace_level(
            old_level_id,
            level_id=str(data.get("id", new_level_id)),
            name=str(data.get("name", "Unknown")),
            author=str(data.get("author", "Unknown")),
            difficulty=data.get("difficulty", "Unrated"),
            requester=requester,
            message=message,
            description=str(data.get("description", "")),
            length=str(data.get("length", "")),
            large=bool(data.get("large", False)),
            two_player=bool(data.get("twoPlayer", False)),
            disliked=bool(data.get("disliked", False)),
            platform="youtube",
            likes=int(data.get("likes", 0)),
            downloads=int(data.get("downloads", 0)),
            version=int(data.get("version", 0)),
        )
        self.status_changed.emit(
            f"Replaced level {old_level_id} with {new_level_id} for {requester}"
        )

    def _enqueue_level(self, requester: str, level_id: str, message: str, *,
                       priority: bool = False, superchat: bool = False,
                       superchat_amount: str = "", member: bool = False) -> bool:
        try:
            data = fetch_level_normalized(level_id)
        except LevelFetchTimeoutError:
            return self._enqueue_placeholder(
                requester, level_id, message, priority, superchat, superchat_amount, member,
                reason="timeout - gdbrowser took too long",
            )
        except LevelNotFoundError:
            logger.warning(f"Level ID {level_id} not found on Geometry Dash servers")
            if not self._queue.allow_any_level:
                self.status_changed.emit(f"Level ID {level_id} not found on Geometry Dash servers")
                return False
            return self._enqueue_placeholder(
                requester, level_id, message, priority, superchat, superchat_amount, member,
                reason=f"Level ID {level_id} not found on Geometry Dash servers",
                status_text=f"Level ID {level_id} not found on Geometry Dash servers, so added bare ID",
            )
        except GDBrowserError as e:
            return self._enqueue_placeholder(
                requester, level_id, message, priority, superchat, superchat_amount, member,
                reason=str(e),
            )

        added = self._queue.add_level(
            level_id=str(data.get("id", level_id)),
            name=str(data.get("name", "Unknown")),
            author=str(data.get("author", "Unknown")),
            difficulty=data.get("difficulty", "Unrated"),
            requester=requester,
            message=message,
            description=str(data.get("description", "")),
            length=str(data.get("length", "")),
            large=bool(data.get("large", False)),
            two_player=bool(data.get("twoPlayer", False)),
            disliked=bool(data.get("disliked", False)),
            platform="youtube",
            likes=int(data.get("likes", 0)),
            downloads=int(data.get("downloads", 0)),
            version=int(data.get("version", 0)),
            priority=priority,
            superchat=superchat,
            superchat_amount=superchat_amount,
            member=member,
        )
        if added:
            logger.info(f"Queued: '{data.get('name')}' by '{data.get('author')}' from '{requester}'")
            self.status_changed.emit(f"Queued: '{data.get('name')}' by '{data.get('author')}' from '{requester}'")
        return added

    def _enqueue_placeholder(
        self, requester: str, level_id: str, message: str, priority: bool,
        superchat: bool, superchat_amount: str, member: bool,
        reason: str, status_text: str | None = None,
    ) -> bool:
        if not self._queue.allow_any_level:
            logger.warning(f"Failed to fetch level {level_id} ({reason})")
            return False
        placeholder = placeholder_level_data(level_id)
        added = self._queue.add_level(
            level_id=level_id,
            name=placeholder["name"],
            author=placeholder["author"],
            difficulty=placeholder["difficulty"],
            requester=requester,
            message=message,
            description=placeholder["description"],
            length=placeholder["length"],
            large=placeholder["large"],
            two_player=placeholder["twoPlayer"],
            disliked=placeholder["disliked"],
            platform="youtube",
            likes=placeholder["likes"],
            downloads=placeholder["downloads"],
            priority=priority,
            superchat=superchat,
            superchat_amount=superchat_amount,
            member=member,
        )
        if added:
            text = status_text or f"Failed to fetch level ({reason}), so added bare ID"
            logger.info(text)
            self.status_changed.emit(text)
        return added

    def _run(self) -> None:
        if not YoutubeDL or not pytchat:
            self.connection_failed.emit("YouTube support requires: yt-dlp and pytchat")
            return

        while not self._stop_event.is_set():
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
                    # Wait 15 seconds and try again
                    self._stop_event.wait(15)
                    continue

                url = info["webpage_url"]
                self._video_id = info.get("id")

                try:
                    self._chat = pytchat.create(video_id=self._video_id, interruptable=False)
                except TypeError:
                    with _signal_patch_lock:
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

                            is_superchat = getattr(c, "type", "") == "superChat"
                            superchat_amount = ""
                            if is_superchat:
                                currency = getattr(c, "currency", "")
                                amount = getattr(c, "amount", "")
                                if currency and amount:
                                    superchat_amount = f"{currency} {amount}"
                                elif amount:
                                    superchat_amount = str(amount)

                            is_member = False
                            try:
                                badges = c.author.badges or []
                                for badge in badges:
                                    if getattr(badge, "type", "") == "member":
                                        is_member = True
                                        break
                            except Exception: # 🤑🤑🤑
                                pass

                            if self._handle_commands(author, message):
                                continue

                            if self._queue.youtube_members_only and not is_member and not is_superchat:
                                continue
                            if self._queue.youtube_superchats_only and not is_superchat:
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
                                if self._queue.is_on_cooldown(author):
                                    continue

                                priority = False
                                if is_superchat and self._queue.youtube_superchat_priority:
                                    priority = True
                                elif is_member and self._queue.youtube_member_priority:
                                    priority = True

                                added_any = False
                                for level_id in level_ids:
                                    logger.info(f"Level detected: {level_id} from {author}")
                                    self.level_detected.emit(author, level_id)
                                    if self._enqueue_level(author, level_id, message,
                                                          priority=priority,
                                                          superchat=is_superchat,
                                                          superchat_amount=superchat_amount,
                                                          member=is_member):
                                        added_any = True
                                if added_any:
                                    self._queue.update_cooldown(author)
                    except Exception as e:
                        if not self._stop_event.is_set():
                            logger.error(f"YouTube chat error: {str(e)}")
                            self.status_changed.emit(f"YouTube chat read error: {str(e)}")
                        break
                
                if not self._stop_event.is_set():
                    self._stop_event.wait(6)

            except Exception as e:
                if not self._stop_event.is_set():
                    err_msg = str(e)
                    if "not currently live" in err_msg:
                        logger.info(f"YouTube channel {self._username} is not currently live (caught: {err_msg})")
                        self.not_streaming.emit()
                        self._stop_event.wait(15)
                    else:
                        logger.warning(f"Failed to connect to YouTube: {err_msg}")
                        self.connection_failed.emit(f"Failed to connect to YouTube: {err_msg}")
                        self._stop_event.wait(60)
