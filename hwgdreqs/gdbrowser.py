import base64
import re

import requests

GD_DATABASE_URL = "https://www.boomlings.com/database"
GD_SECRET = "Wmfd2893gb7"
GD_GAME_VERSION = 22
GD_BINARY_VERSION = 51
GD_HEADERS = {"User-Agent": "", "Content-Type": "application/x-www-form-urlencoded"}

LENGTH_NAMES = {
    0: "Tiny", 1: "Short", 2: "Medium", 3: "Long", 4: "XL", 5: "Platformer",
}

FACE_DIFFICULTY_NAMES = {
    0: "Unrated", 1: "Easy", 2: "Normal", 3: "Hard", 4: "Harder", 5: "Insane",
}

DEMON_FACE_DIFFICULTY_NAMES = {
    3: "Easy Demon", 4: "Medium Demon", 0: "Hard Demon", 5: "Insane Demon", 6: "Extreme Demon",
}


def _decode_description(value: str) -> str:
    if not value:
        return ""
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return value


def _parse_level_response(text: str) -> list[dict[str, str]]:
    levels = []
    for level_text in text.split("|"):
        level = {}
        fields = level_text.split(":")
        for index in range(0, len(fields) - 1, 2):
            level[fields[index]] = fields[index + 1]
        if level:
            levels.append(level)
    return levels


def _post_database(endpoint: str, data: dict) -> str:
    response = requests.post(
        f"{GD_DATABASE_URL}/{endpoint}",
        data=data,
        headers=GD_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    if not response.text or response.text == "-1":
        raise ValueError(f"{endpoint} returned no result")
    return response.text


def resolve_creator_name(player_id: str) -> str:
    """Resolve the level creator's username without downloading level data."""
    data = {
        "secret": GD_SECRET,
        "str": player_id,
        "gameVersion": GD_GAME_VERSION,
    }
    try:
        users = _parse_level_response(_post_database("getGJUsers20.php", data))
        return users[0].get("1", "Unknown") if users else "Unknown"
    except (requests.RequestException, ValueError):
        return "Unknown"


def _face_difficulty(level: dict[str, str]) -> str:
    if _safe_int(level.get("8")) != 10:
        return "Unrated"
    if level.get("25") == "1":
        return "Auto"
    if level.get("17") == "1":
        return DEMON_FACE_DIFFICULTY_NAMES.get(_safe_int(level.get("43")), "Unrated")
    return FACE_DIFFICULTY_NAMES.get(_safe_int(level.get("9")) // 10, "Unrated")


def _level_to_data(level: dict[str, str], potentially_unlisted: bool) -> dict:
    return {
        "id": level.get("1", ""),
        "name": level.get("2", ""),
        "author": resolve_creator_name(level.get("6", "")),
        "difficulty": _face_difficulty(level),
        "description": _decode_description(level.get("3", "")),
        "length": LENGTH_NAMES.get(_safe_int(level.get("15")), "Unknown"),
        "large": False,
        "twoPlayer": level.get("31") == "1",
        "disliked": False,
        "likes": _safe_int(level.get("14")),
        "downloads": _safe_int(level.get("10")),
        "version": _safe_int(level.get("5")),
        "potentially_unlisted": potentially_unlisted,
    }

_LEVEL_ID_RE = re.compile(r"^\d{1,10}$")


class GDBrowserError(Exception):
    pass

class LevelNotFoundError(GDBrowserError):
    pass

class PotentiallyUnlistedError(LevelNotFoundError):
    pass

class LevelFetchTimeoutError(GDBrowserError):
    pass

def fetch_level(level_id: str, allow_potentially_unlisted: bool = True) -> dict:
    level_id = str(level_id).strip()
    if not _LEVEL_ID_RE.match(level_id):
        raise LevelNotFoundError(f"Level ID {level_id!r} is not a valid Geometry Dash level ID")

    try:
        response = _post_database("getGJLevels21.php", {
            "secret": GD_SECRET,
            "gameVersion": GD_GAME_VERSION,
            "binaryVersion": GD_BINARY_VERSION,
            "gdw": 0,
            "type": 0,
            "str": level_id,
            "page": 0,
            "total": 0,
            "uncompleted": 0,
            "onlyCompleted": 0,
            "featured": 0,
            "original": 0,
            "twoPlayer": 0,
            "coins": 0,
            "epic": 0,
            "demonFilter": -1,
            "star": 0,
            "noStar": 0,
            "len": -1,
        })
        levels = [level for level in _parse_level_response(response) if level.get("1") == level_id]
        if not levels or not levels[0].get("2"):
            raise ValueError("Level not found in normal level search")
        return _level_to_data(levels[0], potentially_unlisted=False)
    except (requests.RequestException, ValueError):
        if not allow_potentially_unlisted:
            raise PotentiallyUnlistedError(level_id)
        try:
            response = _post_database("downloadGJLevel22.php", {
                "secret": GD_SECRET,
                "gameVersion": GD_GAME_VERSION,
                "binaryVersion": GD_BINARY_VERSION,
                "levelID": level_id,
            })
            levels = _parse_level_response(response)
            if not levels or levels[0].get("1") != level_id or not levels[0].get("2"):
                raise ValueError("Level not found in level download")
            return _level_to_data(levels[0], potentially_unlisted=True)
        except (requests.RequestException, ValueError) as download_error:
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers") from download_error



def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_level_normalized(level_id: str, allow_potentially_unlisted: bool = True) -> dict:
    data = dict(fetch_level(level_id, allow_potentially_unlisted))
    difficulty = str(data.get("difficulty", "Unrated"))
    if difficulty in ("NA", "Unknown"):
        difficulty = "Unrated"
    data["difficulty"] = difficulty
    data["likes"] = _safe_int(data.get("likes"), 0)
    data["downloads"] = _safe_int(data.get("downloads"), 0)
    data["version"] = _safe_int(data.get("version"), 0)
    data["potentially_unlisted"] = bool(data.get("potentially_unlisted", False))
    return data


def placeholder_level_data(level_id: str) -> dict:
    return {
        "id": level_id,
        "name": f"\u26a0\ufe0f {level_id}",
        "author": "Unknown",
        "difficulty": "Unrated",
        "description": "no data... i guess",
        "length": "",
        "large": False,
        "twoPlayer": False,
        "disliked": False,
        "likes": 0,
        "downloads": 0,
        "version": 0,
    }