"""Database URL parsing and synchronous PyMySQL connection helpers."""

from __future__ import annotations

from os import getenv
from urllib.parse import unquote, urlparse

import pymysql


def database_config_from_url(database_url: str) -> dict[str, object]:
    """Parse a MySQL SQLAlchemy URL without ever logging the URL itself."""
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+aiomysql"}:
        raise ValueError("DATABASE_URL 必须是 MySQL 连接地址")
    if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
        raise ValueError("DATABASE_URL 必须包含主机、用户名和数据库名")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/")),
        "charset": "utf8mb4",
    }


def load_database_config() -> dict[str, object]:
    database_url = getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("环境变量 DATABASE_URL 未配置")
    config = database_config_from_url(database_url)
    if config["database"] != "spider_xhs":
        raise ValueError("DATABASE_URL 必须连接独立 spider_xhs 数据库")
    return config


def connect(config: dict[str, object], *, dict_cursor: bool = False, autocommit: bool = False):
    kwargs = dict(config)
    if dict_cursor:
        kwargs["cursorclass"] = pymysql.cursors.DictCursor
    kwargs["autocommit"] = autocommit
    return pymysql.connect(**kwargs)
