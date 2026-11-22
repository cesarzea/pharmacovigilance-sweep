# Snowflake setup

One-time steps by a person, then everything is `make` targets.

## 1. Create the trial account (manual)

[signup.snowflake.com](https://signup.snowflake.com): **Enterprise** edition, cloud **Azure**, an **EU
region** (for example West Europe or Sweden). The trial lasts 30 days and is then suspended, so create
it when the build is ready to use it. Note the account identifier (`<org>-<account>`) and the admin user.

## 2. Configure two CLI connections (manual, local only)

The Snowflake CLI stores connections in `~/.snowflake/config.toml`; no credential enters the repository.

```bash
snow connection add -n pvsweep-admin --account <org>-<account> --user <admin-user> --role ACCOUNTADMIN --warehouse PVSWEEP_WH
```

```bash
snow connection add -n pvsweep --account <org>-<account> --user <admin-user> --role PVSWEEP_ADMIN --warehouse PVSWEEP_WH
```

Answer the password prompts yourself, or configure key-pair authentication for your user. Test with
`snow connection test -c pvsweep-admin`.

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

## Trial limitations that shape the design

- No external network access: model calls cannot run inside Snowflake; the Container Apps job does them.
- AI features are off until a credit card is added; the POC does not use Cortex.
- Masking policies and Streamlit need Enterprise edition, chosen at sign-up.
