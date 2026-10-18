from __future__ import annotations

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from hwgdreqs.queue_manager import QueueManager
from hwgdreqs.twitch_auth import TwitchSession, get_channel_moderate_enabled, ban_twitch_user
from hwgdreqs.config import asset_path, DEFAULT_BROWSER_SOURCE_HTML
from hwgdreqs.browser_source import render_queue_html
from hwgdreqs.logging_service import get_logger

logger = get_logger()


import urllib.request

_aredl_cache = None
_aredl_lock = threading.Lock()

def get_aredl_position(level_id):
    global _aredl_cache
    if _aredl_cache is None:
        with _aredl_lock:
            if _aredl_cache is None:
                try:
                    req = urllib.request.Request("https://api.aredl.net/v2/api/aredl/levels")
                    req.add_header('User-Agent', 'Mozilla/5.0')
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read())
                        _aredl_cache = {str(item.get("level_id")): item.get("position") for item in data}
                except Exception:
                    _aredl_cache = {}
    return _aredl_cache.get(str(level_id))


_chat_buffers: dict[str, list[dict]] = {
    "twitch": [],
    "youtube": [],
    "kick": [],
}
_chat_lock = threading.Lock()
_MAX_CHAT_HISTORY = 500


def add_chat_message(platform: str, message: dict) -> None:
    with _chat_lock:
        buf = _chat_buffers.setdefault(platform, [])
        buf.append(message)
        if len(buf) > _MAX_CHAT_HISTORY:
            del buf[: len(buf) - _MAX_CHAT_HISTORY]


def get_chat_messages(platform: str, last: int | None = None) -> list[dict]:
    with _chat_lock:
        buf = list(_chat_buffers.get(platform, []))
    if last is not None and last > 0:
        return buf[-last:]
    return buf


def clear_chat_messages(platform: str | None = None) -> None:
    with _chat_lock:
        if platform:
            _chat_buffers[platform] = []
        else:
            for k in _chat_buffers:
                _chat_buffers[k] = []

def _make_handler(queue: QueueManager, session: TwitchSession | None = None, chat_callback=None, api_server=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, payload: object, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()


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

        def _is_mobile_client(self, params: dict) -> bool:
            client_id = self.headers.get("X-Client-Id", "") or params.get("client", "") or params.get("client_id", "")
            user_agent = self.headers.get("User-Agent", "")
            return client_id.lower() == "hwgdreqs-mobile" or "hwgdreqs-mobile" in user_agent.lower()

        def _is_mobile_authenticated(self, params: dict) -> bool:
            device_id = self.headers.get("X-Device-Id", "") or params.get("device_id", "")
            token = self.headers.get("X-Auth-Token", "") or params.get("token", "") or params.get("auth", "")
            if not token:
                auth_hdr = self.headers.get("Authorization", "")
                if auth_hdr.lower().startswith("bearer "):
                    token = auth_hdr[7:].strip()
            if device_id and token:
                if queue.is_device_paired(device_id, token):
                    queue.update_paired_device_seen(device_id)
                    return True
            return False

        def do_GET(self) -> None:
            try:
                self._do_GET()
            except Exception:
                logger.exception("Unhandled error in GET %s", self.path)
                try:
                    self._send_json({"ok": False, "error": "internal_error"}, status=500)
                except Exception:
                    pass

        def _do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/health":
                self._send_json({"ok": True})
                return

            if path == "/callback":
                params = self._params()
                code = params.get("code")
                state = params.get("state")
                
                error_msg = None
                if api_server and api_server._kick_callback:
                    error_msg = api_server._kick_callback(code, state)
                
                if error_msg:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(f"<html><body><h1>Login failed</h1><p>{error_msg}</p></body></html>".encode("utf-8"))
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html><body><h1>Login successful!</h1><p>You can close this window now.</p></body></html>")
                return

            if path == "/swagger" or path == "/swagger/":
                try:
                    with open(asset_path("swagger/swagger.html"), "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                return
            if path in ("/openapi.json", "/swagger-ui.css", "/swagger-ui-bundle.js", "/swagger-ui-standalone-preset.js"):
                import mimetypes
                try:
                    with open(asset_path(f"swagger{path}"), "rb") as f:
                        data = f.read()
                    mime, _ = mimetypes.guess_type(path)
                    self.send_response(200)
                    self.send_header("Content-Type", mime or "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                return

            if path == "/source/queue":
                template = queue.browser_source_html or DEFAULT_BROWSER_SOURCE_HTML
                html = render_queue_html(template, queue)
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path.startswith("/source/assets/"):
                import mimetypes
                filename = path[len("/source/assets/"):]
                if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                    return
                try:
                    with open(asset_path(filename), "rb") as f:
                        data = f.read()
                    mime, _ = mimetypes.guess_type(filename)
                    self.send_response(200)
                    self.send_header("Content-Type", mime or "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
                return

            if path == "/queue/count":
                self._send_json({"count": len(queue.levels)})
                return
            if path == "/blacklist":
                self._send_json({
                    "levels": queue.blacklist_levels,
                    "authors": queue.blacklist_authors,
                    "requesters": queue.blacklist_requesters,
                    "requester2s": queue.blacklist_requester2s,
                })
                return
            if path == "/search":
                params = self._params()
                q = params.get("q", "").lower()
                matches = []
                for e in queue.levels:
                    if q in e.name.lower() or q in str(e.id).lower() or q in e.author.lower() or q in e.requester.lower():
                        d = asdict(e)
                        d["aredl_position"] = get_aredl_position(d["id"])
                        matches.append(d)
                self._send_json({"levels": matches})
                return

            if path == "/queue":
                params = self._params()
                if "row" in params:
                    try:
                        row = int(params["row"])
                        levels = queue.levels
                        if row >= 0 and row < len(levels):
                            d = asdict(levels[row])
                            d["aredl_position"] = get_aredl_position(d["id"])
                            self._send_json({"level": d})
                        else:
                            self._send_json({"ok": False, "error": "invalid_row"}, status=400)
                    except ValueError:
                        self._send_json({"ok": False, "error": "invalid_row"}, status=400)
                else:
                    arr = []
                    for e in queue.levels:
                        d = asdict(e)
                        d["aredl_position"] = get_aredl_position(d["id"])
                        arr.append(d)
                    self._send_json({"levels": arr})
                return
            if path == "/current":
                levels = queue.levels
                if levels:
                    d = asdict(levels[0])
                    d["aredl_position"] = get_aredl_position(d["id"])
                    self._send_json({"level": d})
                else:
                    self._send_json({"level": None})
                return

            if path == "/requests-state":
                self._send_json({"enabled": queue.requests_enabled})
                return

            if path == "/filters":
                diffs = ["Unrated", "Auto", "Easy", "Normal", "Hard", "Harder", "Insane", "Easy Demon", "Medium Demon", "Hard Demon", "Insane Demon", "Extreme Demon"]
                lengths = ["Tiny", "Short", "Medium", "Long", "XL", "Plat"]
                filters = {}
                for d in diffs:
                    filters[d] = (d in queue.allowed_difficulties)
                for l in lengths:
                    filters[l] = (l in queue.allowed_lengths)
                self._send_json(filters)
                return

            if path == "/info":
                from hwgdreqs.config import load_auth, load_kick_auth
                from hwgdreqs.youtube_auth import load_youtube_session
                
                twitch_auth = load_auth()
                kick_auth = load_kick_auth()
                yt_session = load_youtube_session()
                
                info = {
                    "twitch": twitch_auth.get("login") if twitch_auth else None,
                    "kick": kick_auth.get("username") if kick_auth else None,
                    "youtube": yt_session.username if yt_session else None,
                }
                self._send_json(info)
                return

            if path == "/mobile/status":
                from hwgdreqs.config import APP_VERSION
                params = self._params()
                device_id = params.get("device_id") or self.headers.get("X-Device-Id") or ""
                token = params.get("token") or self.headers.get("X-Auth-Token") or ""
                is_paired = queue.is_device_paired(device_id, token) if (device_id and token) else False
                self._send_json({
                    "ok": True,
                    "server": "HwGDReqs",
                    "version": APP_VERSION,
                    "requests_enabled": queue.requests_enabled,
                    "queue_count": len(queue.levels),
                    "is_paired": is_paired,
                    "auth_enabled": queue.api_auth_enabled,
                })
                return

            if path in ("/mobile/auth", "/auth/mobile"):
                from hwgdreqs.config import APP_VERSION
                params = self._params()
                device_id = params.get("device_id") or self.headers.get("X-Device-Id") or ""
                token = params.get("token") or self.headers.get("X-Auth-Token") or params.get("auth") or ""
                if not token:
                    auth_hdr = self.headers.get("Authorization", "")
                    if auth_hdr.lower().startswith("bearer "):
                        token = auth_hdr[7:].strip()

                if not device_id or not token:
                    self._send_json({"ok": False, "error": "missing_credentials", "paired": False}, status=400)
                    return

                if queue.is_device_paired(device_id, token):
                    queue.update_paired_device_seen(device_id)
                    device = queue.get_paired_device(device_id)
                    self._send_json({
                        "ok": True,
                        "paired": True,
                        "server_name": "HwGDReqs",
                        "version": APP_VERSION,
                        "device_name": device.get("device_name", "") if device else "",
                        "requests_enabled": queue.requests_enabled,
                    })
                else:
                    self._send_json({"ok": False, "error": "unauthorized", "paired": False}, status=401)
                return

            if path in ("/chat/twitch", "/chat/twitch/"):
                from hwgdreqs.config import load_auth
                from hwgdreqs.twitch_auth import load_session as load_twitch_session

                auth = load_auth()
                sess = (api_server._session if api_server else None) or load_twitch_session()
                if not auth and not sess:
                    self._send_json({"ok": False, "error": "not logged in"}, status=401)
                    return

                params = self._params()
                last_n = None
                if "last" in params:
                    try:
                        last_n = int(params["last"])
                        if last_n < 1:
                            self._send_json({"ok": False, "error": "invalid_last_param"}, status=400)
                            return
                    except ValueError:
                        self._send_json({"ok": False, "error": "invalid_last_param"}, status=400)
                        return

                messages = get_chat_messages("twitch", last=last_n)
                self._send_json({"messages": messages})
                return

            if path in ("/chat/youtube", "/chat/youtube/"):
                from hwgdreqs.youtube_auth import load_youtube_session

                yt_sess = load_youtube_session()
                if not yt_sess or not yt_sess.username:
                    self._send_json({"ok": False, "error": "not logged in"}, status=401)
                    return

                params = self._params()
                last_n = None
                if "last" in params:
                    try:
                        last_n = int(params["last"])
                        if last_n < 1:
                            self._send_json({"ok": False, "error": "invalid_last_param"}, status=400)
                            return
                    except ValueError:
                        self._send_json({"ok": False, "error": "invalid_last_param"}, status=400)
                        return

                messages = get_chat_messages("youtube", last=last_n)
                self._send_json({"messages": messages})
                return

            if path in ("/chat/kick", "/chat/kick/"):
                from hwgdreqs.config import load_kick_auth
                from hwgdreqs.kick_auth import load_session as load_kick_session

                kick_auth = load_kick_auth()
                kick_sess = load_kick_session()
                if not kick_auth and not kick_sess:
                    self._send_json({"ok": False, "error": "not logged in"}, status=401)
                    return

                params = self._params()
                last_n = None
                if "last" in params:
                    try:
                        last_n = int(params["last"])
                        if last_n < 1:
                            self._send_json({"ok": False, "error": "invalid_last_param"}, status=400)
                            return
                    except ValueError:
                        self._send_json({"ok": False, "error": "invalid_last_param"}, status=400)
                        return

                messages = get_chat_messages("kick", last=last_n)
                self._send_json({"messages": messages})
                return

            self._send_json({"ok": False, "error": "not_found"}, status=404)

        def do_DELETE(self) -> None:
            try:
                self._do_DELETE()
            except Exception:
                logger.exception("Unhandled error in DELETE %s", self.path)
                try:
                    self._send_json({"ok": False, "error": "internal_error"}, status=500)
                except Exception:
                    pass

        def _do_DELETE(self) -> None:
            path = urlparse(self.path).path
            if path == "/queue":
                queue.clear_queue()
                self._send_json({"ok": True})
                return
            self._send_json({"ok": False, "error": "not_found"}, status=404)

        def do_POST(self) -> None:
            try:
                self._do_POST()
            except Exception:
                logger.exception("Unhandled error in POST %s", self.path)
                try:
                    self._send_json({"ok": False, "error": "internal_error"}, status=500)
                except Exception:
                    pass

        def _do_POST(self) -> None:
            path = urlparse(self.path).path
            params = self._params()

            if path in ("/mobile/pair", "/auth/pair"):
                device_id = params.get("device_id") or self.headers.get("X-Device-Id") or ""
                device_name = params.get("device_name", "hwgdreqs-mobile")
                pin = str(params.get("pin", "")).strip()
                client_id = params.get("client") or params.get("client_id") or self.headers.get("X-Client-Id") or ""
                user_agent = self.headers.get("User-Agent", "")

                if client_id.lower() != "hwgdreqs-mobile" and "hwgdreqs-mobile" not in user_agent.lower():
                    self._send_json({"ok": False, "error": "invalid_client", "message": "Expected hwgdreqs-mobile client"}, status=400)
                    return

                if not device_id:
                    self._send_json({"ok": False, "error": "missing_device_id"}, status=400)
                    return

                existing = queue.get_paired_device(device_id)
                if existing:
                    self._send_json({
                        "ok": True,
                        "paired": True,
                        "token": existing["token"],
                        "device_name": existing.get("device_name", device_name),
                        "already_paired": True
                    })
                    return

                if not api_server or not api_server._mobile_pair_callback:
                    self._send_json({"ok": False, "error": "desktop_pair_unavailable"}, status=503)
                    return

                import secrets
                success, entered_pin = api_server._mobile_pair_callback(device_id, device_name, pin)
                if not success:
                    self._send_json({"ok": False, "error": "pairing_canceled"}, status=403)
                    return

                if pin and entered_pin != pin:
                    self._send_json({"ok": False, "error": "invalid_pin", "message": "The 4-digit code did not match"}, status=400)
                    return

                token = secrets.token_hex(20)
                queue.add_paired_device(device_id, device_name, token)
                logger.info("Paired new mobile device: %s (%s)", device_name, device_id)

                self._send_json({
                    "ok": True,
                    "paired": True,
                    "token": token,
                    "device_id": device_id,
                    "device_name": device_name,
                    "message": "Paired successfully"
                })
                return

            if path in ("/mobile/auth", "/auth/mobile"):
                from hwgdreqs.config import APP_VERSION
                device_id = params.get("device_id") or self.headers.get("X-Device-Id") or ""
                token = params.get("token") or self.headers.get("X-Auth-Token") or params.get("auth") or ""
                if not token:
                    auth_hdr = self.headers.get("Authorization", "")
                    if auth_hdr.lower().startswith("bearer "):
                        token = auth_hdr[7:].strip()

                if not device_id or not token:
                    self._send_json({"ok": False, "error": "missing_credentials", "paired": False}, status=400)
                    return

                if queue.is_device_paired(device_id, token):
                    queue.update_paired_device_seen(device_id)
                    device = queue.get_paired_device(device_id)
                    self._send_json({
                        "ok": True,
                        "paired": True,
                        "server_name": "HwGDReqs",
                        "version": APP_VERSION,
                        "device_name": device.get("device_name", "") if device else "",
                        "requests_enabled": queue.requests_enabled,
                    })
                else:
                    self._send_json({"ok": False, "error": "unauthorized", "paired": False}, status=401)
                return

            if path in ("/mobile/unpair", "/auth/unpair"):
                device_id = params.get("device_id") or self.headers.get("X-Device-Id") or ""
                token = params.get("token") or self.headers.get("X-Auth-Token") or params.get("auth") or ""
                if not token:
                    auth_hdr = self.headers.get("Authorization", "")
                    if auth_hdr.lower().startswith("bearer "):
                        token = auth_hdr[7:].strip()
                if not device_id or not token or not queue.is_device_paired(device_id, token):
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                queue.remove_paired_device(device_id)
                self._send_json({"ok": True, "unpaired": True})
                return

            if queue.api_auth_enabled:
                if not self._is_mobile_authenticated(params):
                    auth = params.get("auth") or self.headers.get("X-Auth-Token") or self.headers.get("Authorization")
                    if not auth:
                        self._send_json({"ok": False, "error": "needs_auth"}, status=401)
                        return
                    if auth != queue.api_auth_password:
                        self._send_json({"ok": False, "error": "wrong_password_i_suppose"}, status=403)
                        return

            level_id = params.get("id") or params.get("level_id") or ""

            if path == "/add":
                from hwgdreqs.gdbrowser import fetch_level_normalized, GDBrowserError, LevelNotFoundError, LevelFetchTimeoutError, PotentiallyUnlistedError
                if not level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return

                try:
                    level_data = fetch_level_normalized(level_id, queue.allow_potentially_unlisted)
                except LevelFetchTimeoutError as e:
                    self._send_json({"ok": False, "error": str(e)}, status=504)
                    return
                except PotentiallyUnlistedError:
                    self._send_json({"ok": False, "error": "potentially_unlisted_rejected"}, status=403)
                    return
                except LevelNotFoundError as e:
                    self._send_json({"ok": False, "error": str(e)}, status=404)
                    return
                except GDBrowserError as e:
                    level_data = {
                        "id": level_id,
                        "name": "⚠️ Unknown",
                        "author": "-",
                        "difficulty": "Unrated",
                        "description": str(e),
                        "length": "Tiny",
                    }

                requester = params.get("requester", "API")
                platform = params.get("platform", "custom")
                message = params.get("message", "")
                priority = str(params.get("prio", "")).lower() == "true"
                platform_icon = params.get("platform-icon", "")
                requester2 = params.get("requester2", "")

                success = queue.add_level(
                    level_id=level_id,
                    name=level_data.get("name", ""),
                    author=level_data.get("author", ""),
                    difficulty=level_data.get("difficulty", ""),
                    requester=requester,
                    platform=platform,
                    platform_icon=platform_icon,
                    message=message,
                    description=level_data.get("description", ""),
                    length=level_data.get("length", ""),
                    large=bool(level_data.get("large", False)),
                    two_player=bool(level_data.get("twoPlayer", False)),
                    disliked=bool(level_data.get("disliked", False)),
                    likes=int(level_data.get("likes", 0)),
                    downloads=int(level_data.get("downloads", 0)),
                    priority=priority,
                    version=int(level_data.get("version", 0)),
                    requester2=requester2,
                    potentially_unlisted=bool(level_data.get("potentially_unlisted", False)),
                )

                if success:
                    spot = 0
                    for i, e in enumerate(queue.levels):
                        if str(e.id) == str(level_id):
                            spot = i + 1
                            break
                    self._send_json({"ok": True, "spot": spot})
                else:
                    self._send_json({"ok": False, "error": "add_failed"}, status=400)
                return

            if path == "/replace":
                from hwgdreqs.gdbrowser import fetch_level_normalized, GDBrowserError, LevelNotFoundError, LevelFetchTimeoutError, PotentiallyUnlistedError
                old_level_id = params.get("id") or params.get("old_id") or ""
                new_level_id = params.get("new_id") or params.get("new_level_id") or ""
                if not old_level_id or not new_level_id:
                    self._send_json({"ok": False, "error": "missing_id"}, status=400)
                    return

                try:
                    level_data = fetch_level_normalized(new_level_id, queue.allow_potentially_unlisted)
                except LevelFetchTimeoutError as e:
                    self._send_json({"ok": False, "error": str(e)}, status=504)
                    return
                except PotentiallyUnlistedError:
                    self._send_json({"ok": False, "error": "potentially_unlisted_rejected"}, status=403)
                    return
                except LevelNotFoundError as e:
                    self._send_json({"ok": False, "error": str(e)}, status=404)
                    return
                except GDBrowserError as e:
                    level_data = {
                        "id": new_level_id,
                        "name": "⚠️ Unknown",
                        "author": "-",
                        "difficulty": "Unrated",
                        "description": str(e),
                        "length": "Tiny",
                    }

                requester = params.get("requester", "API")
                platform = params.get("platform", "custom")
                if platform.lower() in ["twitch", "youtube"]:
                    platform = "custom"
                message = params.get("message", "")
                platform_icon = params.get("platform-icon", "")

                queue.replace_level(
                    old_level_id,
                    level_id=str(level_data.get("id", new_level_id)),
                    name=level_data.get("name", ""),
                    author=level_data.get("author", ""),
                    difficulty=level_data.get("difficulty", ""),
                    requester=requester,
                    platform=platform,
                    platform_icon=platform_icon,
                    message=message,
                    description=level_data.get("description", ""),
                    length=level_data.get("length", ""),
                    large=bool(level_data.get("large", False)),
                    two_player=bool(level_data.get("twoPlayer", False)),
                    disliked=bool(level_data.get("disliked", False)),
                    likes=int(level_data.get("likes", 0)),
                    downloads=int(level_data.get("downloads", 0)),
                    version=int(level_data.get("version", 0)),
                    potentially_unlisted=bool(level_data.get("potentially_unlisted", False)),
                )
                self._send_json({"ok": True})
                return

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
                if entry.requester2:
                    queue.blacklist_requester2(entry.requester2)
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

            if path == "/requests-on":
                queue.requests_enabled = True
                if params.get("send-twitch", "").lower() == "true" and chat_callback:
                    chat_callback(True)
                self._send_json({"ok": True})
                return

            if path == "/requests-off":
                queue.requests_enabled = False
                if params.get("send-twitch", "").lower() == "true" and chat_callback:
                    chat_callback(False)
                self._send_json({"ok": True})
                return

            if path == "/requests-state":
                self._send_json({"enabled": queue.requests_enabled})
                return

            self._send_json({"ok": False, "error": "not_found"}, status=404)

    return Handler


_active_api_server: ApiServer | None = None
_zeroconf = None
_service_info = None


class ApiServer:
    def __init__(self, queue: QueueManager) -> None:
        global _active_api_server
        _active_api_server = self
        self._queue = queue
        self._local_httpd: ThreadingHTTPServer | None = None
        self._local_thread: threading.Thread | None = None
        self._network_httpd: ThreadingHTTPServer | None = None
        self._network_thread: threading.Thread | None = None
        self._session: TwitchSession | None = None
        self._local_port: int = 6767
        self._host_to_network: bool = False
        self._network_port: int = 0
        self._chat_callback = None
        self._kick_callback = None
        self._mobile_pair_callback = None

    def set_mobile_pair_callback(self, callback) -> None:
        self._mobile_pair_callback = callback

    def set_kick_callback(self, callback) -> None:
        self._kick_callback = callback

    def set_chat_callback(self, callback) -> None:
        self._chat_callback = callback

    def _dispatch_chat_callback(self, enabled: bool) -> None:
        if self._chat_callback:
            self._chat_callback(enabled)

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
            handler = _make_handler(self._queue, self._session, self._dispatch_chat_callback, self)
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
                handler = _make_handler(self._queue, self._session, self._dispatch_chat_callback, self)
                try:
                    self._network_httpd = ThreadingHTTPServer(("0.0.0.0", self._network_port), handler)
                    self._network_thread = threading.Thread(target=self._network_httpd.serve_forever, daemon=True)
                    self._network_thread.start()
                    success = True

                    global _zeroconf, _service_info
                    if _zeroconf is None:
                        try:
                            from zeroconf import Zeroconf, ServiceInfo
                            from hwgdreqs.config import get_local_ip, APP_VERSION
                            import socket

                            ip = get_local_ip()
                            desc = {
                                "port": str(self._network_port),
                                "name": "HwGDReqs",
                                "version": APP_VERSION,
                                "path": "/",
                                "login": self._session.login if self._session else "",
                                "type": "hwgdreqs-desktop",
                                "client": "hwgdreqs-desktop",
                            }
                            
                            _service_info = ServiceInfo(
                                "_hwgdreqs._tcp.local.",
                                "HwGDReqs._hwgdreqs._tcp.local.",
                                addresses=[socket.inet_aton(ip)],
                                port=self._network_port,
                                properties=desc,
                                server=f"{ip.replace('.', '-')}.local.",
                            )
                            _zeroconf = Zeroconf()
                            _zeroconf.register_service(_service_info)
                            logger.info("Registered mDNS service")
                        except Exception as e:
                            logger.error("Failed to register mDNS service: %s", e)
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

            global _zeroconf, _service_info
            if _zeroconf is not None:
                try:
                    _zeroconf.unregister_service(_service_info)
                    _zeroconf.close()
                except Exception as e:
                    logger.error("Failed to unregister mDNS service: %s", e)
                _zeroconf = None
                _service_info = None