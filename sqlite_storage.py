"""Resolve project SQLite files exclusively inside extension-owned storage."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any


ROOT = Path.home() / ".local/share/flow-steward/extensions/sqlite"


def connection(
    config: dict[str, Any], context: dict[str, Any], root: Path, *, prepare: bool = True
) -> dict[str, Any]:
    if set(config) - {"prebuilt", "database"}:
        raise ValueError("SQLite supports only a project database filename")
    name = config.get("database")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.db", name):
        raise ValueError("SQLite database must be a simple .db filename inside project storage")
    scope = []
    for key in ("account_id", "project_id"):
        value = context.get(key)
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("SQLite requires project-scoped account and project")
        scope.append(value)
    namespace = hashlib.sha256("\x00".join(scope).encode()).hexdigest()
    if root.is_symlink():
        raise ValueError("SQLite storage cannot be a symbolic link")
    if prepare:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = root / namespace
    if directory.is_symlink():
        raise ValueError("SQLite project storage cannot be a symbolic link")
    if prepare:
        directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / name
    if path.is_symlink() or any(
        (directory / (name + suffix)).is_symlink() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ValueError("SQLite database and journal files cannot be symbolic links")
    if path.exists() and not path.is_file():
        raise ValueError("SQLite database must be a regular file")
    return {**config, "database": str(path.resolve())}
