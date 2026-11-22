"""Push the staged Parquet files into Snowflake from the load job (PUT to the internal stage, then
the same COPY statements as snowflake/load/load_stage.sql). Uses the runner's key-pair connection.

Not exercised yet: no Snowflake account at the time of writing.
"""

from __future__ import annotations

from pathlib import Path


def push(stage_dir: Path, load_sql: Path) -> None:
    from pvsweep_runner.snowflake_store import connect

    con = connect(role="PVSWEEP_ADMIN")
    cur = con.cursor()
    try:
        for f in sorted(stage_dir.glob("*.parquet")):
            cur.execute(f"PUT file://{f.resolve()} @PVSWEEP.OPS.LOAD_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
            print(f"  put {f.name}", flush=True)
        statements = [s.strip() for s in load_sql.read_text().split(";") if s.strip() and not s.strip().startswith("--")]
        for stmt in statements:
            if stmt.upper().startswith(("USE ", "--")):
                continue
            cur.execute(stmt)
        for row in cur.fetchall():
            print("  ", row)
    finally:
        cur.close()
        con.close()
