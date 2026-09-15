import re
import time

import requests

from dashlib import (
    fetchLevel, downloadLevel, getUserInfo,
    LENGTH_TINY, LENGTH_SHORT, LENGTH_MEDIUM, LENGTH_LONG, LENGTH_XL, LENGTH_PLAT,
    DIFFICULTY_NA, DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD,
    DIFFICULTY_HARDER, DIFFICULTY_INSANE, DIFFICULTY_EASYDEMON,
    DIFFICULTY_MEDIUMDEMON, DIFFICULTY_HARDDEMON, DIFFICULTY_INSANEDEMON,
    DIFFICULTY_EXTREMEDEMON, DIFFICULTY_AUTO,
    parseDoubleColonString, int_handled,
)

LENGTH_NAMES = {
    LENGTH_TINY:   "Tiny",
    LENGTH_SHORT:  "Short",
    LENGTH_MEDIUM: "Medium",
    LENGTH_LONG:   "Long",
    LENGTH_XL:     "XL",
    LENGTH_PLAT:   "Platformer",
}

DIFFICULTY_NAMES = {
    DIFFICULTY_NA:           "N/A",
    DIFFICULTY_EASY:         "Easy",
    DIFFICULTY_NORMAL:       "Normal",
    DIFFICULTY_HARD:         "Hard",
    DIFFICULTY_HARDER:       "Harder",
    DIFFICULTY_INSANE:       "Insane",
    DIFFICULTY_EASYDEMON:    "Easy Demon",
    DIFFICULTY_MEDIUMDEMON:  "Medium Demon",
    DIFFICULTY_HARDDEMON:    "Hard Demon",
    DIFFICULTY_INSANEDEMON:  "Insane Demon",
    DIFFICULTY_EXTREMEDEMON: "Extreme Demon",
    DIFFICULTY_AUTO:         "Auto",
}

def resolve_account_id(player_id: int) -> int | None:
    """Convert a player ID to an account ID via getGJUsers20.php."""
    data = {
        "secret": "Wmfd2893gb7",
        "str": str(player_id),
        "gameVersion": 22,
    }
    headers = {"User-Agent": ""}
    try:
        req = requests.post(
            "http://www.boomlings.com/database/getGJUsers20.php",
            data=data,
            headers=headers,
        )
    except requests.RequestException:
        return None

    text = req.text
    if not text or text == "-1":
        return None

    first_user = text.split("|")[0].split("#")[0]
    dic = parseDoubleColonString(first_user)
    account_id = int_handled(dic.get("16", "0"))
    return account_id or None

def fetch_level_dashlib(level_id: int):
    try:
        level = fetchLevel(level_id)
        if not (level.levelID == level_id and level.levelName):
            raise Exception("fetchLevel failed")
    except Exception:
        time.sleep(0.5)
        try:
            level = downloadLevel(level_id)
        except Exception as e:
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers") from e
    
    if not level.levelID or not level.levelName:
        raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers")

    raw_likes    = (level.likes + level.dislikes) // 2
    raw_dislikes = (level.dislikes + level.likes) // 2

    creator_name = "Unknown"
    account_id = resolve_account_id(level.playerID)
    if account_id:
        try:
            user = getUserInfo(account_id)
            creator_name = user.username or "Unknown"
        except Exception:
            pass

    length_name     = LENGTH_NAMES.get(level.length, f"Unknown ({level.length})")
    difficulty_name = DIFFICULTY_NAMES.get(level.difficulty, "Unrated")
    
    if difficulty_name == "N/A":
        difficulty_name = "Unrated"

    return {
        "id": str(level.levelID),
        "name": level.levelName,
        "author": creator_name,
        "difficulty": difficulty_name,
        "description": "",
        "length": length_name,
        "large": False,
        "twoPlayer": False,
        "disliked": False,
        "likes": raw_likes + raw_dislikes,
        "downloads": level.downloads,
        "version": level.version,
        "potentially_unlisted": True,
    }

GDBROWSER_LEVEL_URL = "https://gdbrowser.com/api/level/{level_id}"

_LEVEL_ID_RE = re.compile(r"^\d{1,10}$")


class GDBrowserError(Exception):
    pass

class LevelNotFoundError(GDBrowserError):
    pass

class LevelFetchTimeoutError(GDBrowserError):
    pass

def fetch_level(level_id: str) -> dict:
    level_id = str(level_id).strip()
    if not _LEVEL_ID_RE.match(level_id):
        raise LevelNotFoundError(f"Level ID {level_id!r} is not a valid Geometry Dash level ID")

    try:
        response = requests.get(
            GDBROWSER_LEVEL_URL.format(level_id=level_id),
            timeout=10,
        )
        if response.status_code == 404:
            raise Exception("404 from gdbrowser")
        
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and (data.get("error") == "-1" or data.get("error") == "Level not found"):
            raise Exception("Level not found from gdbrowser")
        if data == -1 or data == "-1":
            raise Exception("-1 from gdbrowser")
            
        if not isinstance(data, dict) or not data.get("name"):
            raise Exception("Invalid response from gdbrowser")
        
        data["potentially_unlisted"] = False
        return data
    except Exception as e:
        try:
            return fetch_level_dashlib(int(level_id))
        except LevelNotFoundError:
            raise
        except Exception as dashlib_e:
            raise GDBrowserError(f"Fallback to dashlib failed: {str(dashlib_e)}") from dashlib_e



def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_level_normalized(level_id: str) -> dict:
    data = dict(fetch_level(level_id))
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