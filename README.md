# SQLite workflows for Flow Steward

`flowsteward.sqlite` version **1.0.0** is a standalone workflow tool for project-scoped SQLite reads, schema inspection and parameterized writes. Its public repository is [Flow-Steward/ext-data-sqlite](https://github.com/Flow-Steward/ext-data-sqlite). Separate Linux AMD64 and ARM64 archives include the native SQLite driver through pinned Google MCP Toolbox.

This new identity exposes `read_query`, `inspect_schema` and `execute_write`. It does not register a dataset connector. The existing `flowsteward.data-connector-mcp-toolbox-sqlite` remains a separate legacy read-only family extension; its existing dataset connections are not migrated or silently redirected.

## Persistent project files

The storage root is fixed at `Path.home() / '.local/share/flow-steward/extensions/sqlite'`, outside the extension installation. Host-provided HOME determines this root; a caller cannot supply a root or filesystem path. Files are scoped under `SHA-256(account_id + '\0' + project_id)/<filename>.db`.

An administrator provisions an existing SQLite database and schema in that directory. No generic DDL or trigger operation is exposed. The project connection type is `sqlite`; configuration contains `prebuilt: sqlite` and a simple filename such as `orders.db`. Absolute paths, URIs, traversal, environment overrides, secrets and symlink database/journal files are refused. Core database paths are never accepted. Back up persistent project files as application data.

## Operations

- `read_query`: one SELECT with named `:parameter` placeholders, `params` and JSON `param_schema`; native driver parameters stay separate from SQL. Results are capped at 100 rows and 480 KiB. Only known read-only SQL functions are accepted.
- `inspect_schema`: bounded table/view names and SQL definitions from the selected project's database.
- `execute_write`: one INSERT, UPDATE or DELETE with the same parameter convention. A durable host external-effect claim is required. Test mode suppresses writes before a driver starts. Dedicated connections dispatch DML once, including on `driver.ErrBadConn`; uncertain outcomes return `retryable: false` and must be inspected before a manual retry.

All operations require the matching `connection_ref`, the host-resolved project connection, account/project IDs and the exact host-v2 step execution context. Inline connection configuration and secrets are rejected. A database file must already be provisioned for live operations.

## Rebuild and package

```sh
./scripts/build_toolbox.sh
python3 scripts/package_extension.py --runtime-target linux-amd64
python3 scripts/package_extension.py --runtime-target linux-arm64
```

The resource-capped Docker builder pins Google MCP Toolbox tag `v1.3.0`, commit `b0010060a939455d91e4f8ba62dc3e72b1892469`, and the Go image by digest. It compiles only SQLite source/tools, runs native parameter tests and a real temporary-file INSERT/UPDATE/DELETE lifecycle, then builds both architectures. `toolbox-provenance.json` records source, patch and native hashes. Root `SHA256SUMS` records binaries; `dist/SHA256SUMS` records installer archives. Installation and runtime do not download drivers.

`LICENSE` is the byte-exact upstream Apache artifact (SHA-256 `58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd`); see `NOTICE` and `THIRD_PARTY.yml`.

Read SQL containing a raw backslash or a dollar-quote delimiter (`$$` / `$tag$`), including inside identifiers, is refused before comment/quote parsing; put data values in bound parameters. Top-level LIMIT accepts one integer literal and an optional integer OFFSET; arithmetic limits and comma-offset forms are refused. SQL Server set queries are refused by the bounded TOP form.

Write SQL also refuses raw dollar-quote delimiters before the single-DML scanner, including delimiters inside identifiers. Dollar text and backslashes remain supported in bound data values.

The SQL subset rejects **every raw `$` character** before any read/write lexer, including Unicode dollar tags, quoted text and identifiers. Use named `:parameters` for dollar-containing data. Driver placeholders such as PostgreSQL `$1` are generated only after validation; bound values are unchanged.
