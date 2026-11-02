# Changelog

## 1.0.1

- Use official database brand artwork with recorded source attribution.
- Document the single maintained SQLite package after removal of the unused catalog duplicate.


## 1.0.0

- Introduce workflow-only `flowsteward.sqlite` with project-scoped read_query, inspect_schema and execute_write. Legacy family SQLite dataset registrations remain separate.
- Keep pre-provisioned files in a fixed persistent HOME directory, isolated by account/project; refuse arbitrary paths and symlink database/journal files.
- Validate one bounded SELECT or one native-bound INSERT/UPDATE/DELETE. Require write claims, suppress test-mode writes, and never automatically retry uncertain writes.
- Reject raw SQL backslashes before lexing and require literal LIMIT/OFFSET clauses; values containing backslashes remain supported through bound parameters.
- Add a native SQLite read-only single-statement guard, outer row cap, byte budget and protected-sentinel regressions.
- Provide AMD64 and ARM64 native archives, reproducible pinned-source builds and the exact upstream license.
