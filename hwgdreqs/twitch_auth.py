from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from hwgdreqs.config import (
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

    @classmethod
    def from_auth_dict(cls, data: dict) -> TwitchSession:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            login=data["login"],
            display_name=data.get("display_name", data["login"]),
            user_id=data["user_id"],
        )

    def to_auth_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "login": self.login,
            "display_name": self.display_name,
            "user_id": self.user_id,
        }


def _require_client_id() -> str:
    if not TWITCH_CLIENT_ID:
        raise TwitchAuthError(
            "TWITCH_CLIENT_ID is not set, set one in env var"
        )
    return TWITCH_CLIENT_ID


def start_device_flow() -> DeviceFlowStart:
    client_id = _require_client_id()
    response = requests.post(
        TWITCH_DEVICE_URL,
        data={
            "client_id": client_id,
            "scopes": " ".join(TWITCH_SCOPES),
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


def session_from_token(token_data: dict) -> TwitchSession:
    user = fetch_user(token_data["access_token"])
    session = TwitchSession(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        login=user["login"],
        display_name=user.get("display_name", user["login"]),
        user_id=user["id"],
    )
    save_auth(session.to_auth_dict())
    return session


def complete_device_login(
    device_code: str,
    interval: int,
    *,
    expires_in: int | None = None,
    on_pending: Callable[[int], None] | None = None,
) -> TwitchSession:
    token_data = poll_device_token(
        device_code,
        interval,
        expires_in=expires_in,
        on_pending=on_pending,
    )
    return session_from_token(token_data)


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
