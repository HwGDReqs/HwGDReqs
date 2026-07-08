import json
import logging
from datetime import datetime
from pathlib import Path

from hwgdreqs.config import data_dir


def get_logger() -> logging.Logger:
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "hwgdreqs.log"

    logger = logging.getLogger("hwgdreqs")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger


def log_level_added(level_id: str, level_name: str, requester: str, platform: str) -> None:
    logger = get_logger()
    logger.info(f"Level added | ID: {level_id} | Name: {level_name} | Requester: {requester} | Platform: {platform}")


def log_level_deleted(level_id: str, level_name: str, requester: str) -> None:
    logger = get_logger()
    logger.info(f"Level deleted | ID: {level_id} | Name: {level_name} | Requested by: {requester}")


def log_level_swapped(old_level_id: str, old_level_name: str, new_level_id: str, new_level_name: str) -> None:
    logger = get_logger()
    logger.info(f"Level swapped | Old ID: {old_level_id} ({old_level_name}) | New ID: {new_level_id} ({new_level_name})")


def log_requester_blacklisted(requester: str) -> None:
    logger = get_logger()
    logger.info(f"Requester blacklisted | {requester}")


def log_level_blacklisted(level_id: str, level_name: str) -> None:
    logger = get_logger()
    logger.info(f"Level blacklisted | ID: {level_id} | Name: {level_name}")


def log_author_blacklisted(author: str) -> None:
    logger = get_logger()
    logger.info(f"Author blacklisted | {author}")


def log_requester_unblacklisted(requester: str) -> None:
    logger = get_logger()
    logger.info(f"Requester unblacklisted | {requester}")


def log_level_unblacklisted(level_id: str) -> None:
    logger = get_logger()
    logger.info(f"Level unblacklisted | ID: {level_id}")


def log_author_unblacklisted(author: str) -> None:
    logger = get_logger()
    logger.info(f"Author unblacklisted | {author}")


def log_queue_cleared() -> None:
    logger = get_logger()
    logger.info("Queue cleared")
