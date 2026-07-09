from __future__ import annotations

import re
import socket
import threading

from PySide6.QtCore import QObject, Signal

from hwgdreqs.config import LEVEL_ID_PATTERN, TWITCH_IRC_HOST, TWITCH_IRC_PORT
from hwgdreqs.gdbrowser import fetch_level
from hwgdreqs.logging_service import get_logger
from hwgdreqs.queue_manager import QueueManager
from hwgdreqs.twitch_auth import TwitchSession

LEVEL_RE = re.compile(LEVEL_ID_PATTERN)
logger = get_logger()


class TwitchChatWorker(QObject):
    message_received = Signal(str, str)
    level_detected = Signal(str, str)
    status_changed = Signal(str)
    connection_failed = Signal(str)
    auth_failed = Signal()

    def __init__(
        self,
        session: TwitchSession,
        queue: QueueManager,
        *,
        queue_command_enabled: bool = False,
    ) -> None:
        super().__init__()
        self._session = session
        self._queue = queue
        self._queue_command_enabled = queue_command_enabled
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

    @property
    def queue_command_enabled(self) -> bool:
        return self._queue_command_enabled

    @queue_command_enabled.setter
    def queue_command_enabled(self, enabled: bool) -> None:
        self._queue_command_enabled = enabled

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _run(self) -> None:
        channel = self._session.login.lower()
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(30)
            self._socket.connect((TWITCH_IRC_HOST, TWITCH_IRC_PORT))
            sock = self._socket
            sock.send(
                f"PASS oauth:{self._session.access_token}\r\n".encode("utf-8")
            )
            sock.send(f"NICK {self._session.login}\r\n".encode("utf-8"))
            sock.send(f"JOIN #{channel}\r\n".encode("utf-8"))
            self.status_changed.emit(f"Connected to #{channel}")
        except OSError as exc:
            self.connection_failed.emit(str(exc))
            return

        buffer = ""
        while not self._stop_event.is_set():
            try:
                data = self._socket.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    self._handle_line(line)
            except socket.timeout:
                try:
                    self._socket.send(b"PING :tmi.twitch.tv\r\n")
                except OSError:
                    break
            except OSError:
                if not self._stop_event.is_set():
                    self.connection_failed.emit("Chat connection lost.")
                break

        self.status_changed.emit("Chat disconnected")

    def _handle_line(self, line: str) -> None:
        try:
            if "Login authentication failed" in line:
                self.auth_failed.emit()
                self._stop_event.set()
                return

            if line.startswith("PING"):
                try:
                    self._socket.send(b"PONG :tmi.twitch.tv\r\n")
                except OSError:
                    pass
                return

            if "PRIVMSG" not in line:
                return
            match = re.match(
                r"(?:@[^ ]+ )?:([^!]+)!.* PRIVMSG #[^ ]+ :(.*)",
                line,
            )
            if not match:
                return

            username, message = match.group(1), match.group(2)
            self.message_received.emit(username, message)
            if not self._handle_commands(username, message):
                self._scan_for_levels(username, message)
        except Exception as e:
            pass

    def _scan_for_levels(self, requester: str, message: str) -> None:
        for level_id in LEVEL_RE.findall(message):
            self.level_detected.emit(requester, level_id)
            self._enqueue_level(requester, level_id, message)

    def _handle_commands(self, requester: str, message: str) -> bool:

        parts = message.strip().split()
        if not parts:
            return False
        
        command = parts[0].lower()
        
        if command == "!del" and len(parts) >= 2:
            level_id = parts[1]
            logger.info(f"!del command from {requester}: level_id={level_id}")
            self._delete_level_command(requester, level_id)
            return True
        
        if command == "!replace" and len(parts) >= 3:
            old_level_id = parts[1]
            new_level_id = parts[2]
            logger.info(f"!replace command from {requester}: {old_level_id} -> {new_level_id}")
            self._replace_level_command(requester, old_level_id, new_level_id, message)
            return True

        if command == "!queue" and self._queue_command_enabled:
            logger.info(f"!queue command from {requester}")
            self._queue_command()
            return True
        
        if command == "!whereami" and self._queue_command_enabled:
            logger.info(f"!whereami command from {requester}")
            self._whereami_command(requester)
            return True
        
        return False

    def _queue_command(self) -> None:
        message = self._format_queue_message()
        self._send_chat_message(message)

    def _whereami_command(self, requester: str) -> None:
        levels = self._queue.levels
        requester_lower = requester.lower()
        
        matching_indices = []
        for index, entry in enumerate(levels):
            if entry.requester.lower() == requester_lower:
                matching_indices.append((index, entry))
                
        if not matching_indices:
            self._send_chat_message("[HwGDReqs] you don't have any levels in the queue.")
            return
            
        first_index, first_entry = matching_indices[0]
        pos = first_index + 1
        name = first_entry.name
        
        if len(matching_indices) > 1:
            more_count = len(matching_indices) - 1
            msg = f"[HwGDReqs] you're in position {pos} with your level '{name}' and {more_count} more"
        else:
            msg = f"[HwGDReqs] you're in position {pos} with your level '{name}'"
            
        self._send_chat_message(msg)

    def _format_queue_message(self) -> str:
        levels = self._queue.levels
        if not levels:
            return "[HwGDReqs] Queue is empty."
        parts = []
        for index, entry in enumerate(levels, start=1):
            parts.append(f"{index}) {entry.name} from @{entry.requester}")
        text = "[HwGDReqs] " + " ".join(parts)
        if len(text) > 500:
            text = text[:497] + "..."
        return text

    def _send_chat_message(self, message: str) -> None:
        channel = self._session.login.lower()
        safe_message = message.replace("\r", " ").replace("\n", " ")
        sock = self._socket
        if sock is None:
            return
        try:
            sock.send(
                f"PRIVMSG #{channel} :{safe_message}\r\n".encode("utf-8")
            )
        except OSError:
            pass

    def _delete_level_command(self, requester: str, level_id: str) -> None:

        logger.info(f"Attempting to delete level {level_id} from {requester}")
        found = False
        for entry in self._queue.levels:
            if entry.id == level_id and entry.requester.lower() == requester.lower():
                logger.info(f"Found matching level {level_id}, deleting")
                self._queue.remove_level(level_id)
                self.status_changed.emit(f"Deleted level {level_id} requested by {requester}")
                found = True
                return
        if not found:
            logger.warning(f"Level {level_id} not found or not requested by {requester}")

    def _replace_level_command(self, requester: str, old_level_id: str, new_level_id: str, message: str) -> None:

        logger.info(f"Attempting to replace level {old_level_id} with {new_level_id} from {requester}")
        levels = self._queue.levels
        old_index = None
        
        for i, entry in enumerate(levels):
            if entry.id == old_level_id and entry.requester.lower() == requester.lower():
                old_index = i
                break
        
        if old_index is None:
            logger.warning(f"Level {old_level_id} not found in queue for {requester}")
            self.status_changed.emit(f"Level {old_level_id} not found in queue for {requester}")
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
            platform="twitch",
        )
        self.status_changed.emit(f"Replaced level {old_level_id} with {new_level_id} for {requester}")

    def _enqueue_level(self, requester: str, level_id: str, message: str) -> None:
        data = fetch_level(level_id)
        if not data:
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
            platform="twitch",
        )
        if added:
            self.status_changed.emit(f"Queued: '{data.get('name')}' by '{data.get('author')}' from '{requester}'")
