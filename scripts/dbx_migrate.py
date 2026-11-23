#!/usr/bin/env python3
"""Apply databricks/migrations/V*.sql to Azure Databricks (Unity Catalog), once each, recording them in
<catalog>.OPS.MIGRATION. Port of scripts/snow_migrate.sh.

Statements go through the SQL Statement Execution API on a SQL warehouse, one call per statement. Files
are split on `;` outside quotes and comments, and `${var}` placeholders are substituted first (the API
does not resolve them). Authentication is the Azure CLI login (`az login`); no token is read or printed.

Usage:
  python scripts/dbx_migrate.py [--bootstrap] [--var name=value ...] [--host URL] [--warehouse-id ID]
  python scripts/dbx_migrate.py --dry-run [--bootstrap] [--var name=value ...]

  --bootstrap   run databricks/bootstrap.sql first (needs --var runner_principal=... --var agent_principal=...)
  --dry-run     print the statements after substitution; no workspace, no databricks-sdk needed

Environment: PVSWEEP_DATABRICKS_HOST, PVSWEEP_DATABRICKS_WAREHOUSE_ID (or --host / --warehouse-id).

A statement preceded by a comment `-- @ignore-error CODE[, CODE...]` treats a failure whose message
contains one of those error classes as already done (used for ALTER TABLE ... ADD COLUMNS, which has no
IF NOT EXISTS form in Databricks).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DBX_DIR = ROOT / "databricks"
BOOTSTRAP = DBX_DIR / "bootstrap.sql"
MIGRATIONS = DBX_DIR / "migrations"

# Defaults for every ${var} the SQL uses; --var name=value overrides one. The principal variables name the
# grantee or owner of each role-equivalent (group name, user e-mail or service principal application id);
# the SQL quotes them with backticks.
PRINCIPAL_VARS = {
    "pvsweep_admin": "PVSWEEP_ADMIN",
    "pvsweep_pipeline": "PVSWEEP_PIPELINE",
    "pvsweep_agent": "PVSWEEP_AGENT",
    "pvsweep_review_app": "PVSWEEP_REVIEW_APP",
    "pvsweep_reviewer": "PVSWEEP_REVIEWER",
    "pvsweep_analyst": "PVSWEEP_ANALYST",
    "pvsweep_ci": "PVSWEEP_CI",
}
DEFAULT_VARS = {"catalog": "pvsweep", "managed_location_clause": "", **PRINCIPAL_VARS}
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
IGNORE_RE = re.compile(r"--\s*@ignore-error\s+([A-Za-z0-9_,\s]+)")
NOT_FOUND = ("TABLE_OR_VIEW_NOT_FOUND", "SCHEMA_NOT_FOUND", "NO_SUCH_CATALOG_EXCEPTION", "CATALOG_NOT_FOUND")


class StatementFailed(RuntimeError):
    pass


@dataclass
class Statement:
    sql: str
    ignore_errors: list[str] = field(default_factory=list)

    def first_line(self, width: int = 110) -> str:
        line = " ".join(self.sql.split())
        return line if len(line) <= width else line[: width - 3] + "..."


# ---- parsing --------------------------------------------------------------------------------------

def split_statements(text: str) -> list[Statement]:
    """Split SQL text on `;` outside '...', "...", `...`, -- comments and /* */ comments.

    Comments are dropped from the statement text; `-- @ignore-error` annotations are kept as metadata
    of the statement they precede. Empty statements are skipped. Raises ValueError on an unterminated
    quote or block comment.
    """
    out: list[Statement] = []
    buf: list[str] = []
    comments: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        two = text[i : i + 2]
        if two == "--":
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments.append(text[i:j])
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            if j == -1:
                raise ValueError(f"unterminated /* comment at offset {i}")
            comments.append(text[i : j + 2])
            buf.append(" ")
            i = j + 2
        elif c in "'\"`":
            j = i + 1
            while j < n:
                if text[j] == "\\" and c != "`":
                    j += 2
                    continue
                if text[j] == c:
                    break
                j += 1
            if j >= n:
                raise ValueError(f"unterminated {c} quote starting at offset {i}: {text[i:i + 60]!r}")
            buf.append(text[i : j + 1])
            i = j + 1
        elif c == ";":
            _flush(buf, comments, out)
            buf, comments = [], []
            i += 1
        else:
            buf.append(c)
            i += 1
    _flush(buf, comments, out)
    return out


def _flush(buf: list[str], comments: list[str], out: list[Statement]) -> None:
    sql = "\n".join(line.rstrip() for line in "".join(buf).strip().splitlines() if line.strip())
    if not sql:
        return
    ignore: list[str] = []
    for comment in comments:
        m = IGNORE_RE.search(comment)
        if m:
            ignore += [code.strip() for code in m.group(1).split(",") if code.strip()]
    out.append(Statement(sql=sql, ignore_errors=ignore))


def substitute(text: str, variables: dict[str, str]) -> tuple[str, set[str]]:
    """Replace ${name} with variables[name]; return the text and the names left unresolved."""
    missing: set[str] = set()

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in variables:
            return variables[name]
        missing.add(name)
        return m.group(0)

    return VAR_RE.sub(repl, text), missing


def load_file(path: Path, variables: dict[str, str], strict: bool) -> list[Statement]:
    """Split first, then substitute, so placeholders in comments are ignored and values may hold `;`."""
    statements = split_statements(path.read_text(encoding="utf-8"))
    missing: set[str] = set()
    for stmt in statements:
        stmt.sql, left = substitute(stmt.sql, variables)
        missing |= left
    if missing:
        msg = f"{path.relative_to(ROOT)}: unresolved variables {sorted(missing)} (pass --var name=value)"
        if strict:
            raise SystemExit(msg)
        print(f"WARNING {msg}", file=sys.stderr)
    return statements


def parse_vars(pairs: list[str]) -> dict[str, str]:
    variables = dict(DEFAULT_VARS)
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--var expects name=value, got {pair!r}")
        name, value = pair.split("=", 1)
        variables[name.strip()] = value
    # Unity Catalog stores names in lower case; volume paths use the stored name.
    variables["catalog"] = variables["catalog"].lower()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", variables["catalog"]):
        raise SystemExit(f"catalog name {variables['catalog']!r} must be a plain identifier")
    # Principals go inside `...` (grants, owners) and '...' (bootstrap checklist): refuse quote characters.
    for name in list(PRINCIPAL_VARS) + ["runner_principal", "agent_principal"]:
        value = variables.get(name)
        if value is not None and (not value.strip() or any(q in value for q in "`'\\")):
            raise SystemExit(f"--var {name} must be a non-empty principal name without quotes or backslashes")
    return variables


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("V*.sql"))


def version_of(path: Path) -> str:
    return path.name.split("__", 1)[0]


# ---- execution ------------------------------------------------------------------------------------

class Runner:
    """Runs statements on a SQL warehouse through the Statement Execution API."""

    def __init__(self, host: str, warehouse_id: str):
        from databricks.sdk import WorkspaceClient  # imported here so --dry-run works without the SDK

        self.w = WorkspaceClient(host=host, auth_type="azure-cli")
        self.warehouse_id = warehouse_id

    def execute(self, sql: str) -> tuple[list[str], list[list]]:
        from databricks.sdk.service.sql import StatementState

        resp = self.w.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=sql, wait_timeout="50s"
        )
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = self.w.statement_execution.get_statement(resp.statement_id)
        state = resp.status.state if resp.status else None
        if state != StatementState.SUCCEEDED:
            err = resp.status.error if resp.status else None
            code = getattr(err, "error_code", None)
            message = getattr(err, "message", None) or "no error message"
            raise StatementFailed(f"{state.value if state else 'UNKNOWN'}: {message} ({code})")
        columns = [c.name for c in (resp.manifest.schema.columns or [])] if resp.manifest and resp.manifest.schema else []
        rows = (resp.result.data_array or []) if resp.result else []
        return columns, rows

    def run(self, stmt: Statement, label: str) -> None:
        print(f"  {label} {stmt.first_line()}")
        try:
            columns, rows = self.execute(stmt.sql)
        except StatementFailed as exc:
            if any(code in str(exc) for code in stmt.ignore_errors):
                print(f"    already done ({exc})")
                return
            raise StatementFailed(f"{label} failed: {exc}\n--- statement ---\n{stmt.sql}") from None
        if columns and rows:
            print_table(columns, rows)


def print_table(columns: list[str], rows: list[list]) -> None:
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(col), *(len(r[i]) for r in cells)) for i, col in enumerate(columns)]
    print("    " + "  ".join(col.ljust(widths[i]) for i, col in enumerate(columns)))
    for r in cells:
        print("    " + "  ".join(v.ljust(widths[i]) for i, v in enumerate(r)))


def run_file(runner: Runner | None, path: Path, variables: dict[str, str]) -> None:
    statements = load_file(path, variables, strict=runner is not None)
    print(f"{path.relative_to(ROOT)}: {len(statements)} statements")
    for k, stmt in enumerate(statements, 1):
        label = f"[{k}/{len(statements)}]"
        if runner is None:
            note = f"  -- ignore-error: {', '.join(stmt.ignore_errors)}" if stmt.ignore_errors else ""
            print(f"-- {label}{note}\n{stmt.sql};\n")
        else:
            runner.run(stmt, label)


def applied_versions(runner: Runner, catalog: str) -> set[str]:
    try:
        _, rows = runner.execute(f"SELECT version FROM {catalog}.OPS.MIGRATION")
    except StatementFailed as exc:
        if any(code in str(exc) for code in NOT_FOUND):
            return set()
        raise
    return {row[0] for row in rows}


def connect(args: argparse.Namespace) -> Runner:
    host = args.host or os.environ.get("PVSWEEP_DATABRICKS_HOST")
    warehouse_id = args.warehouse_id or os.environ.get("PVSWEEP_DATABRICKS_WAREHOUSE_ID")
    if not host or not warehouse_id:
        raise SystemExit("set PVSWEEP_DATABRICKS_HOST and PVSWEEP_DATABRICKS_WAREHOUSE_ID (or --host/--warehouse-id)")
    print(f"workspace {host}, warehouse {warehouse_id}, auth azure-cli")
    return Runner(host, warehouse_id)


def common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="workspace URL (default: $PVSWEEP_DATABRICKS_HOST)")
    parser.add_argument("--warehouse-id", help="SQL warehouse id (default: $PVSWEEP_DATABRICKS_WAREHOUSE_ID)")
    parser.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                        help="substitute ${NAME} in the SQL files (catalog defaults to pvsweep)")
    parser.add_argument("--dry-run", action="store_true", help="print the statements; no workspace needed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common_args(parser)
    parser.add_argument("--bootstrap", action="store_true", help="run databricks/bootstrap.sql first")
    args = parser.parse_args()
    variables = parse_vars(args.var)
    catalog = variables["catalog"]
    files = migration_files()
    if not files:
        raise SystemExit(f"no migrations in {MIGRATIONS}")

    if args.dry_run:
        if args.bootstrap:
            run_file(None, BOOTSTRAP, variables)
        for path in files:
            run_file(None, path, variables)
        print(f"-- dry run: catalog {catalog}, {len(files)} migrations{', plus bootstrap' if args.bootstrap else ''}")
        return 0

    # Resolve every file before touching the workspace, so a missing --var fails early.
    for path in ([BOOTSTRAP] if args.bootstrap else []) + files:
        load_file(path, variables, strict=True)

    runner = connect(args)
    try:
        if args.bootstrap:
            run_file(runner, BOOTSTRAP, variables)
        applied = applied_versions(runner, catalog)
        for path in files:
            version = version_of(path)
            if version in applied:
                print(f"{version} already applied")
                continue
            print(f"applying {path.name}")
            run_file(runner, path, variables)
            runner.execute(
                f"INSERT INTO {catalog}.OPS.MIGRATION (version, applied_at) VALUES ('{version}', current_timestamp())"
            )
    except StatementFailed as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print("migrations up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
