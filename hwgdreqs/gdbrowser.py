import re

import requests

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
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers")
        
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and (data.get("error") == "-1" or data.get("error") == "Level not found"):
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers")
        if data == -1 or data == "-1":
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers")
            
        if not isinstance(data, dict) or not data.get("name"):
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers")
            
        return data
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
        raise LevelFetchTimeoutError("timeout - gdbrowser took too long") from e
    except requests.RequestException as e:
        if e.response is not None and e.response.status_code == 404:
            raise LevelNotFoundError(f"Level ID {level_id} not found on Geometry Dash servers") from e
        raise GDBrowserError(str(e)) from e
    except ValueError as e:
        raise GDBrowserError(f"Invalid JSON response: {str(e)}") from e



def fetch_level_normalized(level_id: str) -> dict:
    data = dict(fetch_level(level_id))
    difficulty = str(data.get("difficulty", "Unrated"))
    if difficulty in ("NA", "Unknown"):
        difficulty = "Unrated"
    data["difficulty"] = difficulty
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

