from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import requests

from hwgdreqs.config import (
    KICK_CLIENT_ID,
    KICK_CLIENT_SECRET,
    KICK_SCOPES,
    KICK_AUTH_URL,
    KICK_TOKEN_URL,
    KICK_USERS_URL,
    load_kick_auth,
    save_kick_auth,
)


class KickAuthError(Exception):
    pass


@dataclass
class KickSession:
    access_token: str
    refresh_token: str | None
    login: str
    display_name: str
    user_id: str
    chat_edit_scope: bool = False
    queue_command_enabled: bool = False
    channel_moderate_scope: bool = False
    channel_moderate_enabled: bool = False

    @classmethod
    def from_auth_dict(cls, data: dict) -> KickSession:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            login=data["login"],
            display_name=data.get("display_name", data["login"]),
            user_id=data["user_id"],
            chat_edit_scope=bool(data.get("chat_edit_scope", True)),
            queue_command_enabled=bool(data.get("queue_command_enabled", True)),
            channel_moderate_scope=bool(data.get("channel_moderate_scope", True)),
            channel_moderate_enabled=bool(data.get("channel_moderate_enabled", True)),
        )

    def to_auth_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "login": self.login,
            "display_name": self.display_name,
            "user_id": self.user_id,
            "chat_edit_scope": self.chat_edit_scope,
            "queue_command_enabled": self.queue_command_enabled,
            "channel_moderate_scope": self.channel_moderate_scope,
            "channel_moderate_enabled": self.channel_moderate_enabled,
        }


def has_chat_edit_scope() -> bool:
    data = load_kick_auth()
    return bool(data and data.get("chat_edit_scope", True))


def get_queue_command_enabled() -> bool:
    data = load_kick_auth()
    return bool(
        data
        and data.get("chat_edit_scope", True)
        and data.get("queue_command_enabled", True)
    )


def set_queue_command_enabled(enabled: bool) -> None:
    data = load_kick_auth()
    if not data:
        return
    data["queue_command_enabled"] = enabled
    save_kick_auth(data)


def _require_client_id() -> str:
    if not KICK_CLIENT_ID:
        raise KickAuthError(
            "KICK_CLIENT_ID is not set, please configure it in config.py"
        )
    return KICK_CLIENT_ID


def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode("utf-8").rstrip("=")
    code_challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def start_pkce_flow(port: int = 6767) -> tuple[str, str, str]:
    client_id = _require_client_id()
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    
    redirect_uri = f"http://localhost:{port}/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(KICK_SCOPES),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state
    }
    auth_url = f"{KICK_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return auth_url, code_verifier, state


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            query = urllib.parse.parse_qs(parsed.query)
            
            # Verify state if expected
            expected_state = getattr(self.server, "expected_state", None)
            received_state = query.get("state", [None])[0]
            if expected_state and received_state != expected_state:
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Login failed</h1><p>State mismatch. Potential CSRF attack detected.</p></body></html>") # https://media1.tenor.com/m/kgt7mWwDuOsAAAAC/funny.gif
                return

            if "code" in query:
                self.server.auth_code = query["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Login successful!</h1><p>You can close this window now.</p></body></html>")
            else:
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Login failed</h1><p>No authorization code received.</p></body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def wait_for_callback(port: int = 6767, timeout: int = 300, expected_state: str | None = None) -> str:
    from hwgdreqs.api_server import _active_api_server
    
    if _active_api_server and _active_api_server._local_httpd:
        import threading
        event = threading.Event()
        result = {"code": None, "error": None}
        
        def callback(code: str | None, state: str | None) -> str | None:
            if expected_state and state != expected_state:
                result["error"] = "State mismatch. Potential CSRF attack detected." # https://media1.tenor.com/m/kgt7mWwDuOsAAAAC/funny.gif
                event.set()
                return result["error"]
            if not code:
                result["error"] = "No authorization code received."
                event.set()
                return result["error"]
            result["code"] = code
            event.set()
            return None
            
        _active_api_server.set_kick_callback(callback)
        try:
            success = event.wait(timeout)
            if not success:
                raise KickAuthError("Login timed out. No code received.")
            if result["error"]:
                raise KickAuthError(result["error"])
            return result["code"]
        finally:
            _active_api_server.set_kick_callback(None)

    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.auth_code = None
    server.expected_state = expected_state
    
    def run_server():
        while server.auth_code is None:
            server.handle_request()

    thread = threading.Thread(target=run_server)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    
    if server.auth_code is None:
        raise KickAuthError("Login timed out. No code received.")
    return server.auth_code


def exchange_code(code: str, code_verifier: str, port: int = 6767) -> dict:
    client_id = _require_client_id()
    redirect_uri = f"http://localhost:{port}/callback"
    
    data = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier
    }
    if KICK_CLIENT_SECRET:
        data["client_secret"] = KICK_CLIENT_SECRET
    
    response = requests.post(KICK_TOKEN_URL, data=data, timeout=15)
    if response.status_code != 200:
        raise KickAuthError(f"Token exchange failed: {response.text}")
    
    return response.json()


def fetch_user(access_token: str) -> dict:
    response = requests.get(
        KICK_USERS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        },
        timeout=15,
    )
    if response.status_code == 401:
        raise KickAuthError("Token invalid or expired")
    response.raise_for_status()
    body = response.json()
    
    user_data = body.get("data")
    if not user_data:
        raise KickAuthError("Could not fetch Kick user profile: empty data payload")
        
    if isinstance(user_data, list) and user_data:
        return user_data[0]
    elif isinstance(user_data, dict):
        return user_data
        
    raise KickAuthError("Could not fetch Kick user profile: invalid data format")


def session_from_token(token_data: dict) -> KickSession:
    user = fetch_user(token_data["access_token"])
    login = user.get("name", user.get("username", "Unknown"))
    session = KickSession(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        login=login,
        display_name=user.get("display_name", login),
        user_id=str(user.get("id", "")),
        chat_edit_scope=True,
        queue_command_enabled=True,
        channel_moderate_scope=True,
        channel_moderate_enabled=True,
    )
    save_kick_auth(session.to_auth_dict())
    return session


def load_session() -> KickSession | None:
    data = load_kick_auth()
    if not data or not data.get("access_token"):
        return None
    return KickSession.from_auth_dict(data)


def refresh_session(session: KickSession) -> KickSession | None:
    if not session.refresh_token:
        return None
    client_id = _require_client_id()
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": session.refresh_token,
    }
    if KICK_CLIENT_SECRET:
        data["client_secret"] = KICK_CLIENT_SECRET
    try:
        response = requests.post(
            KICK_TOKEN_URL,
            data=data,
            timeout=15,
        )
        if response.status_code != 200:
            return None
        token_data = response.json()
        session.access_token = token_data["access_token"]
        if token_data.get("refresh_token"):
            session.refresh_token = token_data["refresh_token"]
        save_kick_auth(session.to_auth_dict())
        return session
    except requests.RequestException:
        return None


def validate_session(
    session: KickSession,
    interval: int = 5,
    *,
    on_pending: Callable[[], None] | None = None,
    max_retries: int = 6,
    max_backoff: float = 60.0,
    max_refresh_attempts: int = 3,
) -> KickSession | None:
    attempt = 0
    refresh_attempt = 0
    while True:
        if on_pending:
            on_pending()
        try:
            user = fetch_user(session.access_token)
            login = user.get("name", user.get("username", session.login))
            session.login = login
            session.display_name = user.get("display_name", login)
            session.user_id = str(user.get("id", session.user_id))
            save_kick_auth(session.to_auth_dict())
            return session
        except KickAuthError:
            refresh_attempt += 1
            if refresh_attempt > max_refresh_attempts:
                return None
            refreshed = refresh_session(session)
            if refreshed:
                continue
            return None
        except requests.RequestException:
            attempt += 1
            if attempt >= max_retries:
                return None
            backoff = min(max_backoff, interval * (2 ** (attempt - 1)))
            time.sleep(backoff)


def check_kick_user_exists(session: KickSession, target_username: str) -> bool:
    try:
        response = requests.get(
            f"https://kick.com/api/v1/users/{target_username}",
            headers={
                "Authorization": f"Bearer {session.access_token}",
            },
            timeout=15,
        )
        if response.status_code == 200:
            return True
    except Exception:
        pass
    return False