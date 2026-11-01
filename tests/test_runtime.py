"""SQLite workflow contracts and a real packaged-driver lifecycle in owned storage."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
import yaml

import main
import sql_runtime as runtime
import sqlite_storage

SCOPE = {
    "account_id": "account-1",
    "project_id": "project-1",
    "group_id": None,
    "for_each_id": None,
    "step_id": "sqlite",
    "step_execution_id": "4d3c2b1a-0f9e-4d8c-b7a6-5f4e3d2c0001",
    "test_mode": False,
    "external_effect_id": "effect-1",
}
CONFIG = {"prebuilt": "sqlite", "database": "orders.db"}


def request(operation="read_query", **inputs):
    schema = inputs.get("param_schema")
    if isinstance(schema, dict) and schema and "properties" not in schema:
        inputs["param_schema"] = {
            "type": "object",
            "properties": {name: {"type": kind} for name, kind in schema.items()},
        }
    return {
        "contract_version": "extension_host_v2",
        "runtime_context": dict(SCOPE),
        "mode": "action",
        "action": {
            "action_id": operation,
            "target": {
                "connection": {
                    "connection_id": "sqlite-1",
                    "connection_type": "sqlite",
                    "config": dict(CONFIG),
                    "secrets": {},
                }
            },
            "input": {"connection_ref": "sqlite-1", **inputs},
        },
    }


@pytest.fixture
def provisioned(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    monkeypatch.setattr(main, "SQLITE_STORAGE_ROOT", root)
    monkeypatch.setattr(runtime, "SQLITE_STORAGE_ROOT", root)
    selected = sqlite_storage.connection(CONFIG, SCOPE, root)
    fixture = Path(__file__).with_name("fixtures") / "products-empty.b64"
    Path(selected["database"]).write_bytes(base64.b64decode(fixture.read_bytes()))
    return root


def test_workflow_identity_does_not_claim_legacy_dataset_registration():
    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "extension.yaml").read_text())
    assert manifest["extension_id"] == "flowsteward.sqlite"
    contract = manifest["runtime"]["extension_contract_v2"]
    assert not contract.get("dataset_connectors")
    assert {row["operation_id"] for row in contract["operation_manifest"]} == {
        "read_query",
        "inspect_schema",
        "execute_write",
    }
    assert sqlite_storage.ROOT == Path.home() / ".local/share/flow-steward/extensions/sqlite"


def test_read_values_remain_separate(provisioned, monkeypatch):
    captured = []

    def invoke(config, secrets, tool, params, **kwargs):
        captured.append((config, params))
        return [{"sku": "a"}]

    monkeypatch.setattr(runtime, "_invoke_toolbox", invoke)
    value = "x' OR 1=1 --"
    payload = request(
        sql="SELECT sku FROM products WHERE sku=:sku",
        params={"sku": value},
        param_schema={"sku": "string"},
    )
    before = copy.deepcopy(payload)
    response = main.handle_request(payload)
    assert response["ok"] is True, response
    assert captured[0][1]["sql"] == "SELECT sku FROM products WHERE sku=? LIMIT 101"
    assert json.loads(captured[0][1]["params_json"]) == {"sku": value}
    assert captured[0][1]["binding"] == "positional"
    assert Path(captured[0][0]["database"]).is_relative_to(provisioned)
    assert payload == before


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM products",
        "PRAGMA table_info(products)",
        "ATTACH DATABASE '/app/core.db' AS core",
        "SELECT load_extension(:file)",
        "SELECT * FROM products; DELETE FROM products",
    ],
)
def test_reads_reject_writes_and_filesystem_functions(provisioned, monkeypatch, sql):
    monkeypatch.setattr(
        runtime, "_invoke_toolbox", lambda *a, **k: pytest.fail("must not call driver")
    )
    assert main.handle_request(request(sql=sql))["ok"] is False


@pytest.mark.parametrize("field", ["account_id", "project_id", "step_execution_id"])
def test_exact_project_step_scope_is_required(provisioned, monkeypatch, field):
    payload = request(sql="SELECT sku FROM products")
    payload["runtime_context"].pop(field)
    monkeypatch.setattr(
        runtime, "_invoke_toolbox", lambda *a, **k: pytest.fail("must not call driver")
    )
    assert main.handle_request(payload)["ok"] is False


def test_connection_ref_and_project_cannot_be_substituted(provisioned, monkeypatch):
    monkeypatch.setattr(
        runtime, "_invoke_toolbox", lambda *a, **k: pytest.fail("must not call driver")
    )
    for change in ("reference", "scope", "inline"):
        payload = request(sql="SELECT sku FROM products")
        if change == "reference":
            payload["action"]["input"]["connection_ref"] = "other"
        elif change == "scope":
            payload["action"]["target"]["connection"]["project_id"] = "other"
        else:
            payload["action"]["input"]["connection_config"] = {"database": "/app/core.db"}
        assert main.handle_request(payload)["ok"] is False


def test_write_claim_and_unknown_outcomes(provisioned, monkeypatch):
    payload = request(
        "execute_write",
        sql="DELETE FROM products WHERE sku=:sku",
        params={"sku": "a"},
        param_schema={"sku": "string"},
    )
    no_claim = copy.deepcopy(payload)
    no_claim["runtime_context"].pop("external_effect_id")
    monkeypatch.setattr(
        runtime, "_invoke_toolbox", lambda *a, **k: pytest.fail("must not call driver")
    )
    assert main.handle_request(no_claim)["definitely_no_external_effect"] is True
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("transport lost after write")

    monkeypatch.setattr(runtime, "_invoke_toolbox", fail)
    result = main.handle_request(payload)
    assert len(calls) == 1
    assert result["external_effect_status"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False
    assert result["retryable"] is False


def test_test_mode_does_not_start_driver_or_create_storage(tmp_path, monkeypatch):
    root = tmp_path / "not-created"
    monkeypatch.setattr(main, "SQLITE_STORAGE_ROOT", root)
    monkeypatch.setattr(runtime, "SQLITE_STORAGE_ROOT", root)
    monkeypatch.setattr(
        runtime, "_invoke_toolbox", lambda *a, **k: pytest.fail("must not call driver")
    )
    payload = request(
        "execute_write",
        sql="DELETE FROM products WHERE sku=:sku",
        params={"sku": "a"},
        param_schema={"sku": "string"},
    )
    payload["runtime_context"]["test_mode"] = True
    payload["runtime_context"].pop("external_effect_id")
    result = main.handle_request(payload)
    assert result["external_effect_status"] == "suppressed", result
    assert not root.exists()


def test_read_result_budgets(provisioned, monkeypatch):
    monkeypatch.setattr(
        runtime, "_invoke_toolbox", lambda *a, **k: [{"sku": str(i)} for i in range(101)]
    )
    result = main.handle_request(request(sql="SELECT sku FROM products"))["result"]
    assert result["row_count"] == 100 and result["truncated"] is True
    monkeypatch.setattr(runtime, "_invoke_toolbox", lambda *a, **k: [{"value": "x" * (480 * 1024)}])
    assert main.handle_request(request(sql="SELECT sku FROM products"))["ok"] is False


def test_packaged_driver_insert_read_update_inspect_delete(provisioned):
    try:
        runtime._toolbox_command(CONFIG)
    except ValueError as exc:
        pytest.skip(str(exc))
    value = "O'Reilly; DELETE FROM products --"

    def call(operation, sql, params, schema):
        result = main.handle_request(
            request(operation, sql=sql, params=params, param_schema=schema)
        )
        assert result["ok"] is True, result
        return result["result"]

    call(
        "execute_write",
        "INSERT INTO products(sku,name) VALUES (:sku,:name)",
        {"sku": "a", "name": value},
        {"sku": "string", "name": "string"},
    )
    selected = call(
        "read_query", "SELECT name FROM products WHERE sku=:sku", {"sku": "a"}, {"sku": "string"}
    )
    assert selected["rows"] == [{"name": value}]
    call(
        "execute_write",
        "UPDATE products SET name=:name WHERE sku=:sku",
        {"sku": "a", "name": "updated"},
        {"sku": "string", "name": "string"},
    )
    assert call(
        "read_query", "SELECT name FROM products WHERE sku=:sku", {"sku": "a"}, {"sku": "string"}
    )["rows"] == [{"name": "updated"}]
    schema = main.handle_request(request("inspect_schema"))
    assert schema["ok"] is True, schema
    assert any(row["name"] == "products" for row in schema["result"]["rows"])
    call("execute_write", "DELETE FROM products WHERE sku=:sku", {"sku": "a"}, {"sku": "string"})
    assert (
        call(
            "read_query",
            "SELECT name FROM products WHERE sku=:sku",
            {"sku": "a"},
            {"sku": "string"},
        )["rows"]
        == []
    )


def test_packaged_native_read_guard_protects_sentinel_and_caps_rows(provisioned):
    try:
        runtime._toolbox_command(CONFIG)
    except ValueError as exc:
        pytest.skip(str(exc))
    config = sqlite_storage.connection(CONFIG, SCOPE, provisioned)
    native = {
        "params_json": "{}",
        "param_order": [],
        "binding": "write-positional",
        "sql": "INSERT INTO products(sku,name) VALUES ('sentinel','keep')",
    }
    runtime._invoke_toolbox(config, {}, "execute_sql", native)
    payload = {
        "sql": r"SELECT '\'; DELETE FROM products; -- '",
        "params_json": "{}",
        "param_order": [],
        "binding": "positional",
    }
    with pytest.raises(RuntimeError):
        runtime._invoke_toolbox(config, {}, "execute_sql", payload)
    check = {
        "sql": "SELECT name FROM products WHERE sku='sentinel' LIMIT 1",
        "params_json": "{}",
        "param_order": [],
        "binding": "positional",
    }
    assert runtime._toolbox_rows(runtime._invoke_toolbox(config, {}, "execute_sql", check)) == [
        {"name": "keep"}
    ]
    native["sql"] = (
        "INSERT INTO products(sku,name) WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers WHERE n<300) SELECT CAST(n AS TEXT), 'row' FROM numbers"
    )
    runtime._invoke_toolbox(config, {}, "execute_sql", native)
    payload["sql"] = "SELECT sku FROM products LIMIT 1+1000000"
    rows = runtime._toolbox_rows(runtime._invoke_toolbox(config, {}, "execute_sql", payload))
    assert len(rows) <= 101
