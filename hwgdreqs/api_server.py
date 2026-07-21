from __future__ import annotations

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from hwgdreqs.queue_manager import QueueManager
from hwgdreqs.twitch_auth import TwitchSession, get_channel_moderate_enabled, ban_twitch_user


def _make_handler(queue: QueueManager, session: TwitchSession | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, payload: object, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict:
            length_raw = self.headers.get("Content-Length")
            if not length_raw:
                return {}
            try:
                length = int(length_raw)
            except ValueError:
                return {}
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}

        def _params(self) -> dict[str, str]:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            out: dict[str, str] = {}
            for k, v in qs.items():
                if v:
                    out[k] = v[0]
            if self.command == "POST":
                body = self._read_json()
                for k, v in body.items():
                    if isinstance(v, str):
                        out[k] = v
            return out

        def _find_entry(self, level_id: str):
            for entry in queue.levels:
                if str(entry.id) == level_id:
                    return entry
            return None

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/queue":
                params = self._params()
                if "row" in params:
                    try:
                        row = int(params["row"])
                        levels = queue.levels
                        if row >= 0 and row < len(levels):
                            self._send_json({"level": asdict(levels[row])})
                        else:
                            self._send_json({"ok": False, "error": "invalid_row"}, status=400)
                    except ValueError:
                        self._send_json({"ok": False, "error": "invalid_row"}, status=400)
                else:
                    self._send_json({"levels": [asdict(e) for e in queue.levels]})
                return
            if path == "/current":
                levels = queue.levels
                self._send_json({"level": asdict(levels[0]) if levels else None})
                return
            if path == "/add":
                from hwgdreqs.gdbrowser import fetch_level
                params = self._params()
                level_id = params.get("id") or params.get("level_id") or ""
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                
                level_data = fetch_level(level_id)
                if not level_data:
                    self._send_json({"ok": False, "error": "level_not_found"}, status=404)
                    return
                
                requester = params.get("requester", "API")
                platform = params.get("platform", "custom")
                # no yt/twitvh
                if platform.lower() in ["twitch", "youtube"]:
                    platform = "custom"
                message = params.get("message", "")
                
                success = queue.add_level(
                    level_id=level_id,
                    name=level_data.get("name", ""),
                    author=level_data.get("author", ""),
                    difficulty=level_data.get("difficulty", ""),
                    requester=requester,
                    platform=platform,
                    message=message,
                    description=level_data.get("description", ""),
                    length=level_data.get("length", ""),
                    large=bool(level_data.get("large", False)),
                    two_player=bool(level_data.get("twoPlayer", False)),
                    disliked=bool(level_data.get("disliked", False)),
                    likes=int(level_data.get("likes", 0)),
                    downloads=int(level_data.get("downloads", 0)),
                )
                
                if success:
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False, "error": "add_failed"}, status=400)
                return
            if path == "/replace":
                from hwgdreqs.gdbrowser import fetch_level
                params = self._params()
                old_level_id = params.get("id") or params.get("old_id") or ""
                new_level_id = params.get("new_id") or params.get("new_level_id") or ""
                if not old_level_id or not new_level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                
                level_data = fetch_level(new_level_id)
                if not level_data:
                    self._send_json({"ok": False, "error": "level_not_found"}, status=404)
                    return
                
                requester = params.get("requester", "API")
                platform = params.get("platform", "custom")
                if platform.lower() in ["twitch", "youtube"]:
                    platform = "custom"
                message = params.get("message", "")
                
                queue.replace_level(
                    old_level_id,
                    level_id=str(level_data.get("id", new_level_id)),
                    name=level_data.get("name", ""),
                    author=level_data.get("author", ""),
                    difficulty=level_data.get("difficulty", ""),
                    requester=requester,
                    platform=platform,
                    message=message,
                    description=level_data.get("description", ""),
                    length=level_data.get("length", ""),
                    large=bool(level_data.get("large", False)),
                    two_player=bool(level_data.get("twoPlayer", False)),
                    disliked=bool(level_data.get("disliked", False)),
                    likes=int(level_data.get("likes", 0)),
                    downloads=int(level_data.get("downloads", 0)),
                )
                self._send_json({"ok": True})
                return
            if path in ("/delete", "/banauthor", "/banrequester", "/blacklistlevel", "/clear", "/bantwitch"):
                params = self._params()
                level_id = params.get("id") or params.get("level_id") or ""

                if path == "/delete":
                    if not level_id:
                        self._send_json({"ok": False, "error": "missing_id"}, status=400)
                        return
                    queue.remove_level(level_id)
                    self._send_json({"ok": True})
                    return

                if path == "/banrequester":
                    if not level_id:
                        self._send_json({"ok": False, "error": "missing_id"}, status=400)
                        return
                    entry = self._find_entry(level_id)
                    if not entry:
                        self._send_json({"ok": False, "error": "not_found"}, status=404)
                        return
                    queue.blacklist_requester(entry.requester)
                    self._send_json({"ok": True})
                    return
                
                if path == "/banauthor":
                    if not level_id:
                        self._send_json({"ok": False, "error": "missing_id"}, status=400)
                        return
                    entry = self._find_entry(level_id)
                    if not entry:
                        self._send_json({"ok": False, "error": "not_found"}, status=404)
                        return
                    queue.blacklist_author(entry.author)
                    self._send_json({"ok": True})
                    return

                if path == "/blacklistlevel":
                    if not level_id:
                        self._send_json({"ok": False, "error": "missing_id"}, status=400)
                        return
                    queue.blacklist_level(level_id)
                    self._send_json({"ok": True})
                    return

                if path == "/bantwitch":
                    if not level_id:
                        self._send_json({"ok": False, "error": "missing_id"}, status=400)
                        return
                    entry = self._find_entry(level_id)
                    if not entry:
                        self._send_json({"ok": False, "error": "not_found"}, status=404)
                        return
                    if not session:
                        self._send_json({"ok": False, "error": "no_twitch_session"}, status=400)
                        return
                    if not get_channel_moderate_enabled():
                        self._send_json({"ok": False, "error": "moderation_not_enabled"}, status=400)
                        return
                    if entry.requester.lower() == session.login.lower():
                        self._send_json({"ok": False, "error": "cannot_ban_self"}, status=400)
                        return
                    error = ban_twitch_user(session, entry.requester)
                    if error:
                        self._send_json({"ok": False, "error": error}, status=400)
                    else:
                        self._send_json({"ok": True})
                    return

                queue.clear_queue()
                self._send_json({"ok": True})
                return
            self._send_json({"ok": False, "error": "not_found"}, status=404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            params = self._params()
            level_id = params.get("id") or params.get("level_id") or ""

            if path == "/delete":
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                queue.remove_level(level_id)
                self._send_json({"ok": True})
                return

            if path == "/banrequester":
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                entry = self._find_entry(level_id)
                if not entry:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                    return
                queue.blacklist_requester(entry.requester)
                self._send_json({"ok": True})
                return
            
            if path == "/banauthor":
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                entry = self._find_entry(level_id)
                if not entry:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                    return
                queue.blacklist_author(entry.author)
                self._send_json({"ok": True})
                return

            if path == "/blacklistlevel":
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                queue.blacklist_level(level_id)
                self._send_json({"ok": True})
                return

            if path == "/bantwitch":
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return
                entry = self._find_entry(level_id)
                if not entry:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                    return
                if not session:
                    self._send_json({"ok": False, "error": "no_twitch_session"}, status=400)
                    return
                if not get_channel_moderate_enabled():
                    self._send_json({"ok": False, "error": "moderation_not_enabled"}, status=400)
                    return
                if entry.requester.lower() == session.login.lower():
                    self._send_json({"ok": False, "error": "cannot_ban_self"}, status=400)
                    return
                error = ban_twitch_user(session, entry.requester)
                if error:
                    self._send_json({"ok": False, "error": error}, status=400)
                else:
                    self._send_json({"ok": True})
                return

            if path == "/clear":
                queue.clear_queue()
                self._send_json({"ok": True})
                return

            self._send_json({"ok": False, "error": "not_found"}, status=404)

    return Handler


class ApiServer:
    def __init__(self, queue: QueueManager) -> None:
        self._queue = queue
        self._local_httpd: ThreadingHTTPServer | None = None
        self._local_thread: threading.Thread | None = None
        self._network_httpd: ThreadingHTTPServer | None = None
        self._network_thread: threading.Thread | None = None
        self._session: TwitchSession | None = None
        self._local_port: int = 6767
        self._host_to_network: bool = False
        self._network_port: int = 0

    def set_config(self, local_port: int, host_to_network: bool, network_port: int) -> None:
        restart = (self._local_port != local_port or \
                  self._host_to_network != host_to_network or \
                  self._network_port != network_port)
        self._local_port = local_port
        self._host_to_network = host_to_network
        self._network_port = network_port
        if restart:
            self.stop()
            self.start()

    def set_session(self, session: TwitchSession | None) -> None:
        self._session = session
        self.stop()
        self.start()

    def start(self) -> bool:
        success = False
        # local server
        if self._local_thread and self._local_thread.is_alive():
            success = True
        else:
            handler = _make_handler(self._queue, self._session)
            try:
                self._local_httpd = ThreadingHTTPServer(("127.0.0.1", self._local_port), handler)
                self._local_thread = threading.Thread(target=self._local_httpd.serve_forever, daemon=True)
                self._local_thread.start()
                success = True
            except OSError:
                pass
        
        # network server if on
        if self._host_to_network:
            if not (self._network_thread and self._network_thread.is_alive()):
                handler = _make_handler(self._queue, self._session)
                try:
                    self._network_httpd = ThreadingHTTPServer(("0.0.0.0", self._network_port), handler)
                    self._network_thread = threading.Thread(target=self._network_httpd.serve_forever, daemon=True)
                    self._network_thread.start()
                    success = True
                except OSError:
                    pass
        
        return success

    def stop(self) -> None:
        # stop local server
        if self._local_httpd:
            try:
                self._local_httpd.shutdown()
            except OSError:
                pass
            try:
                self._local_httpd.server_close()
            except OSError:
                pass
            self._local_httpd = None
            
        # stop network server
        if self._network_httpd:
            try:
                self._network_httpd.shutdown()
            except OSError:
                pass
            try:
                self._network_httpd.server_close()
            except OSError:
                pass
            self._network_httpd = None
