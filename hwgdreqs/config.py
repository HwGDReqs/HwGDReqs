import base64
import binascii
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

APP_NAME = "HwGDReqs"
APP_VERSION = "1.4.0"

TWITCH_CLIENT_ID = "hq65d75rdxry2cfjgemvydqp2vfr84"
TWITCH_SCOPES = ["chat:read", "user:read:email", "moderator:read:followers", "channel:read:redemptions"]
TWITCH_CHAT_EDIT_SCOPE = "chat:edit"
TWITCH_CHANNEL_MODERATE_SCOPE = ["channel:moderate", "moderator:manage:banned_users"]
TWITCH_DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"
TWITCH_CUSTOM_REWARDS_URL = "https://api.twitch.tv/helix/channel_points/custom_rewards"
TWITCH_IRC_HOST = "irc.chat.twitch.tv"
TWITCH_IRC_PORT = 6697  # SSL port; keeps the oauth token off the wire in plaintext

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
    if sys.platform == "win32":
        # Windows
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        new_path = base / APP_NAME
        
        # old data chek
        old_base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        old_path = old_base / APP_NAME
        
        if old_path.exists() and not new_path.exists():
            try:
                shutil.copytree(old_path, new_path)
                # bye old data :3
                shutil.rmtree(old_path)
            except OSError:
                pass
        
        new_path.mkdir(parents=True, exist_ok=True)
        return new_path
    elif sys.platform == "darwin":
        # macOS
        base = Path.home() / "Library" / "Application Support" / APP_NAME
        base.mkdir(parents=True, exist_ok=True)
        return base
    else:
        # Linux
        base = Path.home() / ".config" / APP_NAME
        base.mkdir(parents=True, exist_ok=True)
        return base


def asset_path(name: str) -> Path:
    return app_root() / "assets" / name


def queue_file() -> Path:
    return data_dir() / "data.json"


def token_file() -> Path:
    return data_dir() / "auth.dat"


def key_file() -> Path:
    return data_dir() / "auth.key"

_KEYRING_SERVICE = APP_NAME
_KEYRING_USERNAME = "auth_key"


def _keyring_get_key() -> bytes | None:
    try:
        import keyring
        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        return None
    if not value:
        return None
    try:
        return base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, binascii.Error):
        return None


def _keyring_set_key(key: bytes) -> bool:
    try:
        import keyring
        keyring.set_password(
            _KEYRING_SERVICE,
            _KEYRING_USERNAME,
            base64.urlsafe_b64encode(key).decode("ascii"),
        )
        return True
    except Exception:
        return False


def _get_or_create_key() -> bytes:
    existing = _keyring_get_key()
    if existing:
        return existing

    path = key_file()

    if path.exists():
        key = path.read_bytes()
        if _keyring_set_key(key):
            try:
                path.unlink()
            except OSError:
                pass
        return key

    key = Fernet.generate_key()
    if _keyring_set_key(key):
        return key

    path.write_bytes(key)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def encode_token(data: dict) -> str:
    fernet = Fernet(_get_or_create_key())
    raw = json.dumps(data).encode("utf-8")
    return fernet.encrypt(raw).decode("ascii")


def decode_token(encoded: str) -> dict | None:
    fernet = Fernet(_get_or_create_key())
    try:
        raw = fernet.decrypt(encoded.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError):
        pass

    # fall back to the old base64-only format so existing installs upgrade...
    try:
        raw = base64.b64decode(encoded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    save_auth(data)
    return data


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


def get_local_ip() -> str:
    """Get the local IPv4 address of the machine."""
    import socket
    try:
        # dummy socket to a public server to find the local IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # Doesn't need to actually connect
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"  # Fallback to localhost