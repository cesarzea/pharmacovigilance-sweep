# Snowflake setup

One-time steps by a person, then everything is `make` targets.

## 1. An account (manual)

Any Snowflake account in an EU region works; the POC was built against an existing account on
**AWS eu-west-3 (Paris)**, so the design does not depend on Snowflake running in Azure. For a new one,
[signup.snowflake.com](https://signup.snowflake.com): Enterprise edition if masking policies are wanted,
an EU region. Note the account identifier (`<org>-<account>`, shown under your user menu in Snowsight)
and your login name.

## 2. Configure two CLI connections (manual, local only)

The Snowflake CLI stores connections in `~/.snowflake/config.toml`; no credential enters the repository.

```bash
snow connection add -n pvsweep-admin --account <org>-<account> --user <admin-user> --role ACCOUNTADMIN --warehouse PVSWEEP_WH
```

```bash
snow connection add -n pvsweep --account <org>-<account> --user <admin-user> --role PVSWEEP_ADMIN --warehouse PVSWEEP_WH
```

Answer the password prompt yourself, or configure key-pair authentication for your user; leave the
other prompts empty. The second connection is the first one with another role, so it can also be added
by copying the `[connections.pvsweep-admin]` block in `config.toml` as `[connections.pvsweep]` with
`role = "PVSWEEP_ADMIN"`, `warehouse = "PVSWEEP_WH"` and `database = "PVSWEEP"`; it only works after
the bootstrap, which grants `PVSWEEP_ADMIN` to the user running it. Test with
`snow connection test -c pvsweep-admin`. On macOS the CLI writes
`~/Library/Application Support/snowflake/config.toml`.

## 3. Bootstrap, migrate, load (scripted)

```bash
make snow-bootstrap
```

Generates the two service-user key pairs in `.secrets/` (git-ignored) and runs
`snowflake/bootstrap/bootstrap.sql` as ACCOUNTADMIN: roles, warehouse, database, service users
`PVSWEEP_RUNNER` and `PVSWEEP_AGENT` with their public keys.

```bash
make snow-migrate
```

Applies `snowflake/migrations/V*.sql` in order, once each (`OPS.MIGRATION` records them).

```bash
make snow-load
```

Downloads the pinned public datasets into `data/cache/`, stages Parquet files in `data/stage/`, `PUT`s
them to `OPS.LOAD_STAGE` and `COPY`s them into the tables. Prints `REF.DATA_SOURCE` at the end.

## 4. Private keys to Azure (scripted, later)

`make deploy` will store `.secrets/snowflake_runner.p8` in Key Vault and `.secrets/snowflake_agent.p8`
as a Foundry project connection once those modules exist. Until then the keys stay local.

## Snowflake SQL notes learned on the first deployment

- `GRANT` takes one grantee and one schema per statement: `GRANT ... TO ROLE a, ROLE b` and
  `GRANT USAGE ON SCHEMA a, b` are syntax errors. The migrations list every grant separately.
- `GRANT ROLE x TO USER IDENTIFIER(CURRENT_USER())` is not accepted; the bootstrap grants the role to
  the running user through an `EXECUTE IMMEDIATE` block instead.
- `CURRENT_USER()` returns the user name, not the login name (an e-mail) used in the connection.
- `COPY INTO` from Parquet needs `USE_LOGICAL_TYPE = TRUE` in the file format. Without it Snowflake reads
  DuckDB's microsecond `TIMESTAMP` columns as nanoseconds and the intake queue dates land in year
  56,000,000; the agent's queries then fail with "Failed to convert rows" and blocking finds no queue items.
- `GRANT OWNERSHIP ON STREAMLIT` is not supported; the review app stays owned by the deploying role.
- Run-time roles are insert-only on results and audit, with one exception (V008): the runner updates its
  own `SWEEP.RUN` row to close the run.

## Trial limitations that shape the design

- No external network access: model calls cannot run inside Snowflake; the Container Apps job does them.
- AI features are off until a credit card is added; the POC does not use Cortex.
- Masking policies and Streamlit need Enterprise edition, chosen at sign-up.
