import base64
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

APP_NAME = "HwGDReqs"
APP_VERSION = "0.5.0"

TWITCH_CLIENT_ID = "hq65d75rdxry2cfjgemvydqp2vfr84"
TWITCH_SCOPES = ["chat:read", "user:read:email"]
TWITCH_CHAT_EDIT_SCOPE = "chat:edit"
TWITCH_CHANNEL_MODERATE_SCOPE = ["channel:moderate", "moderator:manage:banned_users"]
TWITCH_DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"
TWITCH_IRC_HOST = "irc.chat.twitch.tv"
TWITCH_IRC_PORT = 6667

LEVEL_ID_PATTERN = r"\b(\d{7,9})\b"
COMMA_LEVEL_ID_PATTERN = r"\b(\d{1,3}(?:,\d{3})+)\b"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        # use _MEIPASS 
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def exec_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_path(name: str) -> Path:
    return app_root() / "assets" / name


def queue_file() -> Path:
    return data_dir() / "data.json"


def token_file() -> Path:
    return data_dir() / "auth.dat"


def encode_token(data: dict) -> str:
    raw = json.dumps(data).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_token(encoded: str) -> dict | None:
    try:
        raw = base64.b64decode(encoded.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None


def save_auth(data: dict) -> None:
    token_file().write_text(encode_token(data), encoding="utf-8")


def load_auth() -> dict | None:
    path = token_file()
    if not path.exists():
        return None
    return decode_token(path.read_text(encoding="utf-8"))


def clear_auth() -> None:
    path = token_file()
    if path.exists():
        path.unlink()