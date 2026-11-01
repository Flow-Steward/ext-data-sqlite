"""SQLite cannot open caller-chosen filesystem paths or other project databases."""

from pathlib import Path
import pytest
from sqlite_storage import connection

CONTEXT = {"account_id": "account-1", "project_id": "project-1"}


@pytest.mark.parametrize(
    "name",
    [
        "/app/internal.db",
        "../core.db",
        "file:core.db",
        ":memory:",
        "x/owned.db",
        "a.db?mode=ro",
        "",
        None,
    ],
)
def test_arbitrary_paths_are_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        connection({"prebuilt": "sqlite", "database": name}, CONTEXT, tmp_path / "owned")


def test_projects_are_isolated_and_filename_is_preserved(tmp_path):
    root = tmp_path / "owned"
    first = connection({"prebuilt": "sqlite", "database": "orders.db"}, CONTEXT, root)
    second = connection(
        {"prebuilt": "sqlite", "database": "orders.db"},
        {**CONTEXT, "project_id": "project-2"},
        root,
    )
    assert first["database"] != second["database"]
    assert Path(first["database"]).is_relative_to(root)
    assert Path(first["database"]).name == "orders.db"


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_symlink_database_and_journals_are_rejected(tmp_path, suffix):
    config = {"prebuilt": "sqlite", "database": "orders.db"}
    selected = Path(connection(config, CONTEXT, tmp_path / "owned")["database"])
    Path(str(selected) + suffix).symlink_to(tmp_path / "private.db")
    with pytest.raises(ValueError):
        connection(config, CONTEXT, tmp_path / "owned")


def test_environment_override_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        connection(
            {
                "prebuilt": "sqlite",
                "database": "orders.db",
                "env": {"SQLITE_DATABASE": "/app/internal.db"},
            },
            CONTEXT,
            tmp_path / "owned",
        )


@pytest.mark.parametrize("field", ["account_id", "project_id"])
def test_scope_delimiter_cannot_create_namespace_collisions(tmp_path, field):
    with pytest.raises(ValueError):
        connection(
            {"prebuilt": "sqlite", "database": "orders.db"},
            {**CONTEXT, field: "a\x00b"},
            tmp_path / "owned",
        )
