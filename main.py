"""Project-scoped SQLite workflow reads, schema inspection and bounded DML."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from flowsteward_extension_sdk import runtime_context_from_payload

import sql_runtime as runtime
from sqlite_storage import ROOT as SQLITE_STORAGE_ROOT
from sqlite_storage import connection as sqlite_connection


def _connection(request: dict[str, Any], operation: str) -> tuple[dict[str, Any], dict[str, Any]]:
    action = request.get("action")
    if not isinstance(action, dict):
        raise ValueError("A workflow action is required")
    raw = action.get("input")
    fields = (
        {"connection_ref"}
        if operation == "inspect_schema"
        else {"connection_ref", "sql", "params", "param_schema"}
    )
    if not isinstance(raw, dict) or set(raw) - fields:
        raise ValueError("Unsupported SQLite action input")
    reference = raw.get("connection_ref")
    selected = runtime._as_dict(runtime._as_dict(action.get("target")).get("connection"))
    if (
        not isinstance(reference, str)
        or not reference.strip()
        or selected.get("connection_id") != reference
    ):
        raise ValueError("Select the matching SQLite project connection")
    if (selected.get("connection_type") or selected.get("connection_type_id")) != "sqlite":
        raise ValueError("A SQLite project connection is required")
    context = runtime._as_dict(request.get("runtime_context"))
    if type(context.get("test_mode", False)) is not bool:
        raise ValueError("test_mode must be boolean")
    for key in ("account_id", "project_id"):
        if not isinstance(context.get(key), str) or not context[key].strip():
            raise ValueError("An account and project scope are required")
        if key in selected and selected[key] != context[key]:
            raise ValueError("The connection belongs to a different project scope")
    config = selected.get("config")
    if not isinstance(config, dict) or config.get("prebuilt") != "sqlite":
        raise ValueError("A SQLite database filename is required")
    if selected.get("secrets"):
        raise ValueError("Local SQLite does not accept connection secrets")
    config = sqlite_connection(dict(config), context, SQLITE_STORAGE_ROOT, prepare=False)
    if (
        not (operation == "execute_write" and context.get("test_mode") is True)
        and not Path(config["database"]).is_file()
    ):
        raise ValueError("An administrator must provision the project SQLite file and schema first")
    return raw, config


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    try:
        if len(json.dumps(request, allow_nan=False).encode()) > 256 * 1024:
            raise ValueError("Input exceeds 256 KiB")
        runtime_context_from_payload(request)
        if request.get("mode") != "action":
            raise ValueError("A workflow action is required")
        operation = runtime._as_dict(request.get("action")).get("action_id")
        if operation not in {"read_query", "inspect_schema", "execute_write"}:
            raise ValueError("Unknown SQLite workflow operation")
        raw, config = _connection(request, str(operation))
        if operation == "execute_write":
            return runtime._execute_write(request)
        if operation == "inspect_schema":
            sql = "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name LIMIT 101"
            params: dict[str, Any] = {}
        else:
            candidate = raw.get("sql")
            if (
                not isinstance(candidate, str)
                or not candidate.strip()
                or len(candidate.encode()) > 65536
            ):
                raise ValueError("A bounded SELECT statement is required")
            sql = runtime._template_sql({"sql": candidate}, require_predicate=False)
            sql = runtime._limited_sql("sqlite", sql, 101)
            schema, values = raw.get("param_schema", {}), raw.get("params", {})
            if not isinstance(schema, dict) or not isinstance(values, dict):
                raise ValueError("params and param_schema must be objects")
            params = runtime._validated_params(schema, runtime._placeholder_names(sql), values)
        bound = runtime._compile_bound_query("sqlite", sql, params)
        raw_rows = runtime._invoke_toolbox(config, {}, "execute_sql", bound, timeout_seconds=30)
        rows = [runtime._normalize_toolbox_value(row) for row in runtime._toolbox_rows(raw_rows)]
        response = runtime._envelope(
            ok=True,
            result={
                "rows": rows[:100],
                "row_count": min(len(rows), 100),
                "truncated": len(rows) > 100,
            },
        )
        if len(json.dumps(response, allow_nan=False).encode()) > 480 * 1024:
            raise ValueError("SQLite result exceeds inline budget")
        return response
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        response = runtime._envelope(
            ok=False,
            errors=[
                runtime._error(
                    "invalid_payload",
                    "Invalid bounded project SQLite request or database not provisioned",
                )
            ],
        )
        response.update(
            definitely_no_external_effect=True,
            retryable=False,
            external_effect_status="not_applied",
        )
        return response
    except Exception:
        response = runtime._envelope(
            ok=False, errors=[runtime._error("provider_unavailable", "SQLite read failed")]
        )
        response.update(
            definitely_no_external_effect=True,
            retryable=False,
            external_effect_status="not_applied",
        )
        return response


def main() -> int:
    raw = sys.stdin.buffer.read(256 * 1024 + 1)
    try:
        if len(raw) > 256 * 1024:
            response = runtime._envelope(
                ok=False, errors=[runtime._error("invalid_payload", "Input exceeds 256 KiB")]
            )
        else:
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                response = runtime._envelope(
                    ok=False, errors=[runtime._error("invalid_json", "Malformed JSON input")]
                )
            else:
                response = (
                    handle_request(payload)
                    if isinstance(payload, dict)
                    else runtime._envelope(
                        ok=False,
                        errors=[runtime._error("invalid_payload", "A JSON object is required")],
                    )
                )
    except Exception:
        response = runtime._envelope(
            ok=False, errors=[runtime._error("invalid_payload", "Invalid request")]
        )
    print(json.dumps(response, allow_nan=False))
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
