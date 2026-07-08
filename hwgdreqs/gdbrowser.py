import requests

GDBROWSER_LEVEL_URL = "https://gdbrowser.com/api/level/{level_id}"

def fetch_level(level_id: str) -> dict | None:
    try:
        response = requests.get(
            GDBROWSER_LEVEL_URL.format(level_id=level_id),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("name"):
            return None
        return data
    except (requests.RequestException, ValueError):
        return None
