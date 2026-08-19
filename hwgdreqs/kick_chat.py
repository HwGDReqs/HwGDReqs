from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal
import websockets
from curl_cffi import requests as cffi_requests
import requests

from hwgdreqs.config import LEVEL_ID_PATTERN, COMMA_LEVEL_ID_PATTERN
from hwgdreqs.gdbrowser import fetch_level_normalized, placeholder_level_data, GDBrowserError, LevelNotFoundError, LevelFetchTimeoutError
from hwgdreqs.logging_service import get_logger
from hwgdreqs.queue_manager import QueueManager
from hwgdreqs.kick_auth import KickSession

LEVEL_RE = re.compile(LEVEL_ID_PATTERN)
COMMA_LEVEL_RE = re.compile(COMMA_LEVEL_ID_PATTERN)
logger = get_logger()

# Kick's active Pusher config
PUSHER_KEY = "32cbd69e4b950bf97679"
PUSHER_CLUSTER = "us2"


def get_channel_info(username: str) -> dict:
    url = f"https://kick.com/api/v2/channels/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": f"https://kick.com/{username}"
    }
    response = cffi_requests.get(url, headers=headers, impersonate="chrome")
    response.raise_for_status()
    data = response.json()
    broadcaster_user_id = data.get("user_id") or (data.get("user") or {}).get("id")
    return {
        "chatroom_id": data["chatroom"]["id"],
        "broadcaster_user_id": int(broadcaster_user_id) if broadcaster_user_id else None,
        "is_live": data.get("livestream") is not None
    }


class KickChatWorker(QObject):
    message_received = Signal(str, str)
    level_detected = Signal(str, str)
    status_changed = Signal(str)
    connection_failed = Signal(str)
    auth_failed = Signal()

    def __init__(
        self,
        session: KickSession,
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
        self._chatroom_id: int | None = None
        self._broadcaster_user_id: int | None = None
        self._ws = None

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

    def _run(self) -> None:
        asyncio.run(self._async_run())

    async def send_ping(self, ws):
        """Send periodic Pusher keepalive pings every 25 seconds."""
        while not self._stop_event.is_set():
            await asyncio.sleep(25)
            try:
                await ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
            except Exception:
                break

    async def check_stop(self):
        """Periodically check for thread stop_event and close ws if set."""
        while not self._stop_event.is_set():
            await asyncio.sleep(1)
        if self._ws:
            await self._ws.close()

    async def _async_run(self) -> None:
        # Use queue target if set, otherwise own login
        channel_name = (self._queue.twitch_bot_channel_name or self._session.login).lower()
        try:
            info = get_channel_info(channel_name)
            self._chatroom_id = info["chatroom_id"]
            self._broadcaster_user_id = info.get("broadcaster_user_id")
            if self._broadcaster_user_id is None:
                logger.warning(f"Could not resolve Kick broadcaster_user_id for #{channel_name}; sending will be disabled")
            self.status_changed.emit(f"Connected to Kick channel: {channel_name}")
        except Exception as e:
            self.connection_failed.emit(f"Failed to fetch Kick channel details: {e}")
            return

        ws_url = f"wss://ws-{PUSHER_CLUSTER}.pusher.com/app/{PUSHER_KEY}?protocol=7&client=js&version=7.6.0&flash=false"

        try:
            async with websockets.connect(ws_url) as ws:
                self._ws = ws
                
                subscribe_event = {
                    "event": "pusher:subscribe",
                    "data": {"auth": "", "channel": f"chatrooms.{self._chatroom_id}.v2"}
                }
                await ws.send(json.dumps(subscribe_event))
                
                asyncio.create_task(self.send_ping(ws))
                asyncio.create_task(self.check_stop())

                async for message in ws:
                    if self._stop_event.is_set():
                        break
                    
                    try:
                        event_data = json.loads(message)
                        event_type = event_data.get("event")

                        if event_type == "App\\Events\\ChatMessageEvent":
                            payload = json.loads(event_data["data"])
                            sender_info = payload.get("sender", {})
                            sender = sender_info.get("username", "Unknown")
                            sender_id = str(sender_info.get("id", "") or "")
                            content = payload.get("content", "")
                            
                            badges = sender_info.get("identity", {}).get("badges", [])
                            is_broadcaster = False
                            is_mod = False
                            is_sub = False
                            is_vip = False
                            
                            for badge in badges:
                                b_type = badge.get("type", "").lower()
                                if b_type == "broadcaster":
                                    is_broadcaster = True
                                elif b_type == "moderator":
                                    is_mod = True
                                elif b_type == "subscriber" or b_type == "founder":
                                    is_sub = True
                                elif b_type == "vip":
                                    is_vip = True

                            if sender.lower() == channel_name.lower():
                                is_broadcaster = True
                            elif (
                                not self._queue.twitch_bot_channel_name
                                and sender_id
                                and sender_id == self._session.user_id
                            ):
                                is_broadcaster = True

                            self.message_received.emit(sender, content)
                            
                            if not self._handle_commands(sender, content):
                                self._scan_for_levels(
                                    sender,
                                    content,
                                    user_id=sender_id,
                                    is_broadcaster=is_broadcaster,
                                    is_mod=is_mod,
                                    is_sub=is_sub,
                                    is_vip=is_vip,
                                )
                    except Exception as e:
                        logger.exception(f"Error handling Kick chat message: {message!r}")
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            if not self._stop_event.is_set():
                self.connection_failed.emit(f"Kick Chat connection lost: {e}")

        self.status_changed.emit("Kick Chat disconnected")

    def _scan_for_levels(
        self,
        requester: str,
        message: str,
        *,
        user_id: str = "",
        is_broadcaster: bool = False,
        is_mod: bool = False,
        is_sub: bool = False,
        is_vip: bool = False,
    ) -> None:
        if self._queue.twitch_subs_only and not is_sub and not is_mod and not is_broadcaster:
            return
        if self._queue.twitch_vip_only and not is_vip and not is_mod and not is_broadcaster:
            return
        
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
            if self._queue.is_on_cooldown(requester):
                remaining = self._queue.get_remaining_cooldown(requester)
                self._maybe_send(
                    "cooldown",
                    f"[HwGDReqs] @{requester}, you're on cooldown for {remaining} more second{'s' if remaining != 1 else ''}."
                )
                return
            
            # Priority
            priority = False
            if is_broadcaster:
                if self._queue.twitch_sub_priority or self._queue.twitch_vip_priority or self._queue.twitch_mod_priority:
                    priority = True
            elif is_mod and self._queue.twitch_mod_priority:
                priority = True
            elif is_vip and self._queue.twitch_vip_priority:
                priority = True
            elif is_sub and self._queue.twitch_sub_priority:
                priority = True

            added_any = False
            for level_id in level_ids:
                self.level_detected.emit(requester, level_id)
                if self._enqueue_level(requester, level_id, message, priority=priority, requester2=user_id):
                    added_any = True

            if added_any:
                self._queue.update_cooldown(requester)

    def _handle_commands(self, requester: str, message: str) -> bool:
        parts = message.strip().split()
        if not parts:
            return False
        
        command = parts[0].lower()
        
        if command == self._queue.command_del.lower() and len(parts) >= 2:
            level_id = parts[1]
            logger.info(f"!del command from {requester}: level_id={level_id}")
            self._delete_level_command(requester, level_id)
            return True
        
        if command == self._queue.command_replace.lower() and len(parts) >= 3:
            old_level_id = parts[1]
            new_level_id = parts[2]
            logger.info(f"!replace command from {requester}: {old_level_id} -> {new_level_id}")
            self._replace_level_command(requester, old_level_id, new_level_id, message)
            return True

        if command == self._queue.command_queue.lower() and self._queue_command_enabled:
            logger.info(f"!queue command from {requester}")
            self._queue_command()
            return True
        
        if command == self._queue.command_whereami.lower() and self._queue_command_enabled:
            logger.info(f"!whereami command from {requester}")
            self._whereami_command(requester)
            return True

        if command == self._queue.command_commands.lower():
            logger.info(f"!commands command from {requester}")
            self._commands_command(requester)
            return True
        
        return False

    def _format_queue_message(self) -> str:
        levels = self._queue.levels
        if not levels:
            return "[HwGDReqs] Queue is empty."
        parts = []
        for index, entry in enumerate(levels, start=1):
            platform_tag = "" if entry.platform == "kick" else f" ({'YT' if entry.platform == 'youtube' else entry.platform.upper()})"
            parts.append(f"{index}) {entry.name} from @{entry.requester}{platform_tag}")
        text = "[HwGDReqs] " + " ".join(parts)
        if len(text) > 500:
            text = text[:497] + "..."
        return text

    def _queue_command(self) -> None:
        levels = self._queue.levels
        if not levels:
            self._maybe_send("queue_empty", "[HwGDReqs] Queue is empty.")
        else:
            self._maybe_send("queue_list", self._format_queue_message())

    def _whereami_command(self, requester: str) -> None:
        levels = self._queue.levels
        requester_lower = requester.lower()
        
        matching_indices = []
        for index, entry in enumerate(levels):
            if entry.requester.lower() == requester_lower:
                matching_indices.append((index, entry))
                
        if not matching_indices:
            self._maybe_send("whereami_empty", "[HwGDReqs] you don't have any levels in the queue.")
            return
            
        first_index, first_entry = matching_indices[0]
        pos = first_index + 1
        name = first_entry.name
        
        if len(matching_indices) > 1:
            more_count = len(matching_indices) - 1
            msg = f"[HwGDReqs] you're in position {pos} with your level '{name}' and {more_count} more"
        else:
            msg = f"[HwGDReqs] you're in position {pos} with your level '{name}'"
            
        self._maybe_send("whereami_pos", msg)

    def _commands_command(self, requester: str) -> None:
        cmds = [
            f"{self._queue.command_del} <id> (Delete a level from your queue)",
            f"{self._queue.command_replace} <id> <new-id> (Replace a level in your queue)",
            f"{self._queue.command_commands} (Show available commands)"
        ]
        if self._queue_command_enabled:
            cmds.extend([
                f"{self._queue.command_queue} (Show the current queue)",
                f"{self._queue.command_whereami} (Show your position in the queue)"
            ])
        
        msg = f"[HwGDReqs] @{requester}, available commands: {', '.join(cmds)}"
        self._maybe_send("commands_list", msg)

    def _send_chat_message(self, message: str) -> None:
        if not self._broadcaster_user_id or not self._session.access_token:
            return

        safe_message = message.replace("\r", " ").replace("\n", " ")
        if self._queue.twitch_bot_no_prefix:
            safe_message = safe_message.replace("[HwGDReqs] ", "").replace("[HwGDReqs]", "")

        url = "https://api.kick.com/public/v1/chat"
        headers = {
            "Authorization": f"Bearer {self._session.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        data = {
            "broadcaster_user_id": self._broadcaster_user_id,
            "content": safe_message,
            "type": "user",
        }
        try:
            response = requests.post(url, headers=headers, json=data, timeout=5)
            if response.status_code == 401:
                logger.warning("Kick access token rejected while sending chat message")
                self.auth_failed.emit()
                return
            if response.status_code >= 400:
                logger.warning(f"Failed to send Kick chat message: {response.status_code} {response.text}")
                return
            body = response.json()
            if not body.get("data", {}).get("is_sent", False):
                logger.warning(f"Kick reported the chat message was not sent: {body}")
        except Exception as e:
            logger.warning(f"Failed to send Kick chat message: {e}")

    def _maybe_send(self, reply_key: str, message: str) -> None:
        if self._queue.is_reply_enabled(reply_key):
            self._send_chat_message(message)

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
            self._maybe_send(
                "del_not_found",
                f"[HwGDReqs] @{requester}, Level not found or you didn't request it"
            )

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
            self._maybe_send(
                "replace_not_found",
                f"[HwGDReqs] @{requester}, Level not found or you didn't request it"
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
            platform="kick",
            likes=int(data.get("likes", 0)),
            downloads=int(data.get("downloads", 0)),
            version=int(data.get("version", 0)),
        )
        self.status_changed.emit(f"Replaced level {old_level_id} with {new_level_id} for {requester}")

    def _enqueue_level(self, requester: str, level_id: str, message: str, priority: bool = False, requester2: str = "") -> bool:
        if any(e.id == level_id for e in self._queue.levels):
            self._maybe_send("already_in_queue", f"[HwGDReqs] @{requester} your level \"{level_id}\" is already in the queue.")
            return False
            
        if self._queue.max_levels_per_requester > 0 and self._queue.get_requester_level_count(requester) >= self._queue.max_levels_per_requester:
            self._maybe_send("max_levels", f"[HwGDReqs] @{requester} you have reached the maximum number of levels you can request.")
            return False

        try:
            data = fetch_level_normalized(level_id)
        except LevelFetchTimeoutError:
            return self._enqueue_placeholder(requester, level_id, message, priority, "timeout - gdbrowser took too long", requester2=requester2)
        except LevelNotFoundError:
            logger.warning(f"Level ID {level_id} not found on Geometry Dash servers")
            if not self._queue.allow_any_level:
                self.status_changed.emit(f"Level ID {level_id} not found on Geometry Dash servers")
                self._maybe_send("not_found_gd", f"[HwGDReqs] @{requester} level \"{level_id}\" was not found on Geometry Dash servers")
                return False
            return self._enqueue_placeholder(
                requester, level_id, message, priority,
                reason=f"Level ID {level_id} not found on Geometry Dash servers",
                status_text=f"Level ID {level_id} not found on Geometry Dash servers, so added bare ID",
                requester2=requester2,
            )
        except GDBrowserError as e:
            return self._enqueue_placeholder(requester, level_id, message, priority, str(e), requester2=requester2)

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
            platform="kick",
            likes=int(data.get("likes", 0)),
            downloads=int(data.get("downloads", 0)),
            version=int(data.get("version", 0)),
            priority=priority,
            requester2=requester2,
        )
        if added:
            self.status_changed.emit(f"Queued: '{data.get('name')}' by '{data.get('author')}' from '{requester}'")
            spot = len(self._queue.levels)
            for i, entry in enumerate(self._queue.levels):
                if entry.id == level_id and entry.requester == requester:
                    spot = i + 1
                    break
            self._maybe_send("added_to_queue", f"[HwGDReqs] @{requester} your level \"{data.get('name', 'Unknown')}\" by \"{data.get('author', 'Unknown')}\" got added to the queue in #{spot} spot")
        else:
            if not self._queue.requests_enabled:
                pass
            elif requester.lower() in [r.lower() for r in self._queue.blacklist_requesters]:
                pass
            else:
                self._maybe_send("filtered_out", f"[HwGDReqs] @{requester} your level \"{level_id}\" could not be added because of Filters")
        return added

    def _enqueue_placeholder(self, requester: str, level_id: str, message: str, priority: bool, reason: str = "", status_text: str | None = None, requester2: str = "") -> bool:
        if not self._queue.allow_any_level:
            logger.warning(f"Failed to fetch level {level_id} ({reason})")
            self._send_chat_message(f"[HwGDReqs] @{requester} your level \"{level_id}\" could not be added because of Filters")
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
            platform="kick",
            likes=placeholder["likes"],
            downloads=placeholder["downloads"],
            priority=priority,
            requester2=requester2,
        )
        if added:
            self.status_changed.emit(status_text or f"Failed to fetch level ({reason}), so added bare ID")
            spot = len(self._queue.levels)
            for i, entry in enumerate(self._queue.levels):
                if entry.id == level_id and entry.requester == requester:
                    spot = i + 1
                    break
            self._maybe_send("placeholder_added", f"[HwGDReqs] @{requester} your level \"{level_id}\" didnt find the assets, but added anyways to #{spot} spot")
        else:
            if not self._queue.requests_enabled:
                pass
            elif requester.lower() in [r.lower() for r in self._queue.blacklist_requesters]:
                pass
            else:
                self._maybe_send("filtered_out", f"[HwGDReqs] @{requester} your level \"{level_id}\" could not be added because of Filters")
        return added