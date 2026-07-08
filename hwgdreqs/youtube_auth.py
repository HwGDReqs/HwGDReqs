import json
from dataclasses import dataclass
from pathlib import Path

from hwgdreqs.config import data_dir


@dataclass
class YoutubeSession:
    username: str


def youtube_auth_file() -> Path:
    return data_dir() / "youtube-auth.json"


def save_youtube_session(session: YoutubeSession) -> None:
    data = {"username": session.username}
    youtube_auth_file().write_text(json.dumps(data), encoding="utf-8")


def load_youtube_session() -> YoutubeSession | None:
    path = youtube_auth_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return YoutubeSession(username=data.get("username", ""))
    except (json.JSONDecodeError, OSError):
        return None


def clear_youtube_auth() -> None:
    path = youtube_auth_file()
    if path.exists():
        path.unlink()
