from __future__ import annotations

import re
from html import escape

from hwgdreqs.queue_manager import LevelEntry, QueueManager

_ITEM_TEMPLATE_RE = re.compile(
    r"<!--\s*QUEUE_ITEM_TEMPLATE\s*-->(.*?)<!--\s*END_QUEUE_ITEM_TEMPLATE\s*-->",
    re.DOTALL,
)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w-]+)\s*\}\}")

_DIFFICULTY_ICON_MAP = {
    "Unrated": "unrated.png",
    "Auto": "auto.png",
    "Easy": "easy.png",
    "Normal": "normal.png",
    "Hard": "hard.png",
    "Harder": "harder.png",
    "Insane": "insane.png",
}

_PLATFORM_ICON_MAP = {
    "youtube": "youtube.svg",
    "twitch": "twitch.svg",
    "kick": "kick.svg",
}

AVAILABLE_VARIABLES = [
    {"name": "index", "example": "[{{index}}]", "description": "The entry's position in the queue, starting at 1."},
    {"name": "level", "example": '"{{level}}"', "description": "The level's name."},
    {"name": "author", "example": "{{author}}", "description": "The level's author."},
    {"name": "requester", "example": "{{requester}}", "description": "Who requested the level."},
    {"name": "requester2", "example": "{{requester2}}", "description": "Second requester (co-op requests), if any."},
    {"name": "difficulty", "example": "{{difficulty}}", "description": "The difficulty name, e.g. 'Insane Demon'."},
    {"name": "difficulty-icon", "example": '<img class="difficulty-icon" src="{{difficulty-icon}}">', "description": "URL of the difficulty face icon (auto/easy/.../demon)."},
    {"name": "platform", "example": "{{platform}}", "description": "The platform the request came from: youtube, twitch, or kick."},
    {"name": "platform-icon", "example": '<img class="platform-icon" src="{{platform-icon}}">', "description": "URL of the platform icon (youtube.svg, twitch.svg, kick.svg)."},
    {"name": "length", "example": "{{length}}", "description": "The level's length category (Tiny, Short, Medium, Long, XL, Plat)."},
    {"name": "message", "example": "{{message}}", "description": "The message attached to the request, if any."},
    {"name": "level-id", "example": "{{level-id}}", "description": "The Geometry Dash level ID."},
]


def difficulty_icon_file(difficulty: str) -> str:
    if difficulty.endswith("Demon"):
        return "demon.png"
    return _DIFFICULTY_ICON_MAP.get(difficulty, "unrated.png")


def platform_icon_file(platform: str) -> str:
    return _PLATFORM_ICON_MAP.get(platform, "")


def _entry_variables(index: int, entry: LevelEntry, assets_prefix: str) -> dict[str, str]:
    diff_icon = difficulty_icon_file(entry.difficulty)
    plat_icon = platform_icon_file(entry.platform)
    return {
        "index": str(index + 1),
        "level": entry.name,
        "author": entry.author,
        "requester": entry.requester,
        "requester2": entry.requester2,
        "difficulty": entry.difficulty,
        "difficulty-icon": f"{assets_prefix}{diff_icon}" if diff_icon else "",
        "platform": entry.platform,
        "platform-icon": f"{assets_prefix}{plat_icon}" if plat_icon else "",
        "length": entry.length,
        "message": entry.message,
        "level-id": str(entry.id),
    }


def _fill_placeholders(item_template: str, variables: dict[str, str]) -> str:
    def _sub(match: re.Match) -> str:
        value = variables.get(match.group(1).strip(), "")
        return escape(str(value), quote=True)

    return _PLACEHOLDER_RE.sub(_sub, item_template)


def render_queue_html(template: str, queue: QueueManager, assets_prefix: str = "/source/assets/") -> str:
    match = _ITEM_TEMPLATE_RE.search(template)
    if not match:
        return template

    item_template = match.group(1)
    levels = queue.levels
    rendered_items = "".join(
        _fill_placeholders(item_template, _entry_variables(i, entry, assets_prefix))
        for i, entry in enumerate(levels)
    )
    return template[: match.start()] + rendered_items + template[match.end():]