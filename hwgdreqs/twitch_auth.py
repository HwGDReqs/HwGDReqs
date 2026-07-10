from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from hwgdreqs.config import (
    TWITCH_CHANNEL_MODERATE_SCOPE,
    TWITCH_CHAT_EDIT_SCOPE,
    TWITCH_CLIENT_ID,
    TWITCH_DEVICE_URL,
    TWITCH_SCOPES,
    TWITCH_TOKEN_URL,
    TWITCH_USERS_URL,
    load_auth,
    save_auth,
)


class TwitchAuthError(Exception):
    pass


@dataclass
class DeviceFlowStart:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass
class TwitchSession:
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
    def from_auth_dict(cls, data: dict) -> TwitchSession:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            login=data["login"],
            display_name=data.get("display_name", data["login"]),
            user_id=data["user_id"],
            chat_edit_scope=bool(data.get("chat_edit_scope")),
            queue_command_enabled=bool(data.get("queue_command_enabled")),
            channel_moderate_scope=bool(data.get("channel_moderate_scope")),
            channel_moderate_enabled=bool(data.get("channel_moderate_enabled")),
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
    data = load_auth()
    return bool(data and data.get("chat_edit_scope"))


def get_queue_command_enabled() -> bool:
    data = load_auth()
    return bool(
        data
        and data.get("chat_edit_scope")
        and data.get("queue_command_enabled")
    )


def set_queue_command_enabled(enabled: bool) -> None:
    data = load_auth()
    if not data:
        return
    data["queue_command_enabled"] = enabled
    save_auth(data)


def has_channel_moderate_scope() -> bool:
    data = load_auth()
    return bool(data and data.get("channel_moderate_scope"))


def get_channel_moderate_enabled() -> bool:
    data = load_auth()
    return bool(
        data
        and data.get("channel_moderate_scope")
        and data.get("channel_moderate_enabled")
    )


def set_channel_moderate_enabled(enabled: bool) -> None:
    data = load_auth()
    if not data:
        return
    data["channel_moderate_enabled"] = enabled
    save_auth(data)


def _require_client_id() -> str:
    if not TWITCH_CLIENT_ID:
        raise TwitchAuthError(
            "TWITCH_CLIENT_ID is not set, set one in env var"
        )
    return TWITCH_CLIENT_ID


def start_device_flow(*, include_chat_edit: bool = False, include_channel_moderate: bool = False) -> DeviceFlowStart:
    client_id = _require_client_id()
    scopes = list(TWITCH_SCOPES)
    if include_chat_edit:
        scopes.append(TWITCH_CHAT_EDIT_SCOPE)
    if include_channel_moderate:
        if isinstance(TWITCH_CHANNEL_MODERATE_SCOPE, list):
            scopes.extend(TWITCH_CHANNEL_MODERATE_SCOPE)
        else:
            scopes.append(TWITCH_CHANNEL_MODERATE_SCOPE)
    response = requests.post(
        TWITCH_DEVICE_URL,
        data={
            "client_id": client_id,
            "scopes": " ".join(scopes),
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise TwitchAuthError(f"Device flow failed: {response.text}")

    payload = response.json()
    return DeviceFlowStart(
        device_code=payload["device_code"],
        user_code=payload["user_code"],
        verification_uri=payload["verification_uri"],
        expires_in=int(payload["expires_in"]),
        interval=int(payload.get("interval", 5)),
    )


def _oauth_error(payload: dict) -> str:
    return str(payload.get("error") or payload.get("message") or "").lower()


def poll_device_token(
    device_code: str,
    interval: int,
    *,
    expires_in: int | None = None,
    on_pending: Callable[[int], None] | None = None,
) -> dict:
    client_id = _require_client_id()
    deadline = time.time() + expires_in if expires_in else None
    attempt = 0

    while True:
        if deadline and time.time() >= deadline:
            raise TwitchAuthError("Login expired. Please try again.")

        time.sleep(interval)
        attempt += 1
        if on_pending:
            on_pending(attempt)

        try:
            response = requests.post(
                TWITCH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=15,
            )
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        if response.status_code == 200 and payload.get("access_token"):
            return payload

        error = _oauth_error(payload)
        if error in ("authorization_pending", "pending"):
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error in ("expired_token", "invalid device code"):
            raise TwitchAuthError("Login expired. Please try again.")
        if error == "access_denied":
            raise TwitchAuthError("Login was denied.")
        if error:
            raise TwitchAuthError(payload.get("message") or payload.get("error") or error)
        if response.status_code >= 500:
            continue
        continue


def fetch_user(access_token: str) -> dict:
    client_id = _require_client_id()
    response = requests.get(
        TWITCH_USERS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Client-Id": client_id,
        },
        timeout=15,
    )
    if response.status_code == 401:
        raise TwitchAuthError("Token invalid or expired")
    response.raise_for_status()
    users = response.json().get("data", [])
    if not users:
        raise TwitchAuthError("Could not fetch Twitch user profile")
    return users[0]


def session_from_token(
    token_data: dict,
    *,
    chat_edit_scope: bool = False,
    channel_moderate_scope: bool = False,
) -> TwitchSession:
    user = fetch_user(token_data["access_token"])
    session = TwitchSession(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        login=user["login"],
        display_name=user.get("display_name", user["login"]),
        user_id=user["id"],
        chat_edit_scope=chat_edit_scope,
        queue_command_enabled=chat_edit_scope,
        channel_moderate_scope=channel_moderate_scope,
        channel_moderate_enabled=channel_moderate_scope,
    )
    save_auth(session.to_auth_dict())
    return session


def complete_device_login(
    device_code: str,
    interval: int,
    *,
    expires_in: int | None = None,
    chat_edit_scope: bool = False,
    channel_moderate_scope: bool = False,
    on_pending: Callable[[int], None] | None = None,
) -> TwitchSession:
    token_data = poll_device_token(
        device_code,
        interval,
        expires_in=expires_in,
        on_pending=on_pending,
    )
    return session_from_token(
        token_data,
        chat_edit_scope=chat_edit_scope,
        channel_moderate_scope=channel_moderate_scope,
    )


def ban_twitch_user(session: TwitchSession, target_username: str) -> str | None:
    """
    Bans a Twitch user.
    Returns None on success, or a string describing the error on failure.
    """
    client_id = _require_client_id()
    
    # 1. Get the user ID of the target user
    try:
        response = requests.get(
            TWITCH_USERS_URL,
            headers={
                "Authorization": f"Bearer {session.access_token}",
                "Client-Id": client_id,
            },
            params={"login": target_username},
            timeout=15,
        )
        if response.status_code == 401:
            return "Unauthorized (token might be expired or invalid)"
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            return f"User '{target_username}' not found on Twitch"
        target_user_id = data[0]["id"]
    except Exception as exc:
        return f"Failed to retrieve User ID for {target_username}: {exc}"

    # 2. Perform the ban
    ban_url = "https://api.twitch.tv/helix/moderation/bans"
    headers = {
        "Authorization": f"Bearer {session.access_token}",
        "Client-Id": client_id,
        "Content-Type": "application/json",
    }
    params = {
        "broadcaster_id": session.user_id,
        "moderator_id": session.user_id,
    }
    body = {
        "data": {
            "user_id": target_user_id,
            "reason": "Banned from HwGDReqs",
        }
    }
    try:
        response = requests.post(
            ban_url,
            headers=headers,
            params=params,
            json=body,
            timeout=15,
        )
        if response.status_code in (200, 201):
            return None # Success
        else:
            try:
                err_data = response.json()
                msg = err_data.get("message", response.text)
            except Exception:
                msg = response.text
            return f"Twitch API error: {msg}"
    except Exception as exc:
        return f"Failed to perform ban request: {exc}"


def load_session() -> TwitchSession | None:
    data = load_auth()
    if not data or not data.get("access_token"):
        return None
    return TwitchSession.from_auth_dict(data)


def refresh_session(session: TwitchSession) -> TwitchSession | None:
    if not session.refresh_token:
        return None
    client_id = _require_client_id()
    try:
        response = requests.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": session.refresh_token,
            },
            timeout=15,
        )
        if response.status_code != 200:
            return None
        token_data = response.json()
        session.access_token = token_data["access_token"]
        if token_data.get("refresh_token"):
            session.refresh_token = token_data["refresh_token"]
        save_auth(session.to_auth_dict())
        return session
    except requests.RequestException:
        return None


def validate_session(
    session: TwitchSession,
    interval: int = 5,
    *,
    on_pending: Callable[[], None] | None = None,
) -> TwitchSession | None:
    while True:
        if on_pending:
            on_pending()
        try:
            user = fetch_user(session.access_token)
            session.login = user["login"]
            session.display_name = user.get("display_name", user["login"])
            session.user_id = user["id"]
            save_auth(session.to_auth_dict())
            return session
        except TwitchAuthError:
            refreshed = refresh_session(session)
            if refreshed:
                continue
            return None
        except requests.RequestException:
            time.sleep(interval)
