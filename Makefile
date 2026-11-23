# Pharmacovigilance Sweep: deploy from scratch, build, run, tear down.
# Needs: az (logged in), docker or az acr build, uv. Parameters: infra/main.parameters.local.json.

ENV        ?= dev
LOCATION   ?= swedencentral
PARAMS     ?= infra/main.parameters.local.json
RG          = rg-pvsweep-$(ENV)
IMAGE_TAG  ?= $(shell git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)

.PHONY: dbx-stop dbx-app-stop dbx-setup dbx-dry-run dbx-bootstrap dbx-migrate dbx-load dbx-export dbx-import dbx-sync dbx-app dbx-app-smoke deploy outputs build-agent build-runner kv-secrets run-sweep-job deploy-agents spike-models spike-agent stage-data snow-keys snow-bootstrap snow-migrate snow-load snow-app teardown

# The Snowflake agent key (from `make snow-keys`) goes into a Foundry project connection when it exists;
# SNOWFLAKE_ACCOUNT comes from .env (PVSWEEP_SNOWFLAKE_ACCOUNT) unless given on the command line.
SNOWFLAKE_ACCOUNT ?= $(shell grep -s '^PVSWEEP_SNOWFLAKE_ACCOUNT=' .env | cut -d= -f2)
SNOWFLAKE_PARAMS   = $(if $(SNOWFLAKE_ACCOUNT),-p snowflakeAccount='$(SNOWFLAKE_ACCOUNT)',)
DBX_PARAMS         = $(if $(DEPLOY_DATABRICKS),-p deployDatabricks=true,)
AGENT_KEY_PARAMS   = $(if $(and $(wildcard .secrets/snowflake_agent.p8),$(SNOWFLAKE_ACCOUNT)),-p snowflakeAgentPrivateKey="$$(cat .secrets/snowflake_agent.p8)",)

# Runner job (docs/ops/runner-job.md). DEPLOY_RUNNER=1 adds Log Analytics, App Insights, Key Vault, the
# Container Apps environment and the sweep job with image pvsweep-runner:$(IMAGE_TAG). RUNNER_JOBS=0 skips
# the jobs: first pass only, before `make kv-secrets` has stored the keys they reference.
DEPLOY_RUNNER ?= 0
RUNNER_JOBS   ?= 1
RUNNER_PARAMS  = $(if $(filter 1,$(DEPLOY_RUNNER)),-p deployRunnerJob=true -p runnerImageTag=$(IMAGE_TAG) -p deployRunnerJobs=$(if $(filter 0,$(RUNNER_JOBS)),false,true),)

deploy:
	az deployment sub create -n pvsweep-$(ENV)-$$(date +%Y%m%d%H%M%S) -l $(LOCATION) \
	  -f infra/main.bicep -p @$(PARAMS) $(SNOWFLAKE_PARAMS) $(AGENT_KEY_PARAMS) $(RUNNER_PARAMS) $(DBX_PARAMS) --only-show-errors -o none
	$(MAKE) outputs

# Writes the outputs of the latest successful deployment to .env.$(ENV) (ignored by git) for the other targets.
outputs:
	az deployment sub list --query "[?contains(name,'pvsweep-$(ENV)-') && properties.provisioningState=='Succeeded'] | sort_by(@,&properties.timestamp) | [-1].properties.outputs" -o json \
	  | python3 -I scripts/outputs_to_env.py > .env.$(ENV)
	@cat .env.$(ENV)

build-agent:
	. ./.env.$(ENV) && az acr build -r $$REGISTRYNAME -g $$RESOURCEGROUP -t pvsweep-agent:$(IMAGE_TAG) --platform linux/amd64 -f agent/Dockerfile .

build-runner:
	. ./.env.$(ENV) && az acr build -r $$REGISTRYNAME -g $$RESOURCEGROUP -t pvsweep-runner:$(IMAGE_TAG) --platform linux/amd64 -f runner/Dockerfile .

# Snowflake runner and agent keys into the runner Key Vault (needs a DEPLOY_RUNNER=1 deployment first).
kv-secrets:
	@. ./.env.$(ENV) && test -n "$$KEYVAULTNAME" || { echo "KEYVAULTNAME is empty in .env.$(ENV): run make deploy DEPLOY_RUNNER=1 RUNNER_JOBS=0 first"; exit 1; }
	. ./.env.$(ENV) && scripts/kv_secrets.sh $$KEYVAULTNAME .secrets

# One execution of the sweep job with SWEEP_ARGS, then its console logs (scripts/run_sweep_job.sh refuses
# to start without --limit unless ALLOW_FULL_SWEEP=1).
SWEEP_ARGS ?= --limit 6 --concurrency 2 --match agent --backend snowflake --provider gpt
run-sweep-job:
	. ./.env.$(ENV) && scripts/run_sweep_job.sh $$RESOURCEGROUP $$SWEEPJOBNAME $$LOGANALYTICSWORKSPACEID -- $(SWEEP_ARGS)

# PLATFORM=snowflake|databricks picks which data platform the hosted agents read (one version per switch).
PLATFORM ?= snowflake
deploy-agents:
	. ./.env.$(ENV) && { [ -f .env ] && set -a && . ./.env && set +a; }; uv run -q --no-project --with azure-ai-projects --with azure-identity python -I scripts/deploy_agents.py \
	  --project-endpoint $$PROJECTENDPOINT --image $$REGISTRYLOGINSERVER/pvsweep-agent:$(IMAGE_TAG) \
	  --provider gpt --deployment $$GPTSMALLDEPLOYMENT \
	  --snowflake-account '$(SNOWFLAKE_ACCOUNT)' --snowflake-connection "$$SNOWFLAKEAGENTCONNECTION" \
	  --account-id "$$FOUNDRYACCOUNTID" \
	  --platform $(PLATFORM) $(if $(filter databricks,$(PLATFORM)),--databricks-host "$$PVSWEEP_DATABRICKS_HOST" --databricks-http-path "$$PVSWEEP_DATABRICKS_HTTP_PATH" --databricks-catalog "$$PVSWEEP_DATABRICKS_CATALOG",) \
	  $(if $(CLAUDE_DEPLOYMENT),--provider claude --deployment $(CLAUDE_DEPLOYMENT),)

spike-models:
	. ./.env.$(ENV) && uv run -q --no-project --with anthropic --with openai --with azure-identity python -I spike/01_entra_model_calls.py \
	  --account $$FOUNDRYACCOUNTNAME --gpt $$GPTSMALLDEPLOYMENT --claude "$$CLAUDESMALLDEPLOYMENT"

spike-agent:
	. ./.env.$(ENV) && uv run -q --no-project --with azure-identity --with httpx python -I spike/02_invoke_hosted_agent.py \
	  --project-endpoint $$PROJECTENDPOINT --agent pvsweep-matcher-gpt \
	  --message "Probe https://www.snowflakecomputing.com/robots.txt and https://example.com, then submit the result."

teardown:
	az group delete -n $(RG) --yes --no-wait
	az consumption budget delete --budget-name budget-pvsweep-$(ENV) -o none || true

# ---- Data and Snowflake -------------------------------------------------------------------
# Connection names from `snow connection add`: SNOW_ADMIN_CONN has ACCOUNTADMIN (bootstrap only).
SNOW_CONN       ?= pvsweep
SNOW_ADMIN_CONN ?= pvsweep-admin

# Downloads the pinned public datasets (cached in data/cache) and writes Parquet files to data/stage.
stage-data:
	uv run -q --project runner python -I -m pvsweep_load --out data/stage --brands config/brands.json

snow-keys:
	scripts/snow_keys.sh .secrets

# One-time, as ACCOUNTADMIN: roles, warehouse, database, service users with the public keys.
snow-bootstrap: snow-keys
	snow sql -c $(SNOW_ADMIN_CONN) -f snowflake/bootstrap/bootstrap.sql \
	  -D runner_public_key="$$(cat .secrets/snowflake_runner.pub.body)" \
	  -D agent_public_key="$$(cat .secrets/snowflake_agent.pub.body)"

snow-migrate:
	scripts/snow_migrate.sh $(SNOW_CONN)

snow-load: stage-data
	scripts/snow_load.sh $(SNOW_CONN) data/stage

snow-app:
	scripts/snow_app.sh $(SNOW_CONN)

# ---- Databricks (second data platform, databricks/ and docs/ops/databricks.md) -----------------
# Workspace from `make deploy DEPLOY_DATABRICKS=1`; warehouse from dbx-setup; SQL through the Statement
# API with the deploying user's Azure CLI login. DBX_PRINCIPAL is the grantee/owner for a single-user
# POC run (an e-mail); in a team setup pass the seven group variables instead (databricks/README.md).
# Recipes load .env (git-ignored) for PVSWEEP_DATABRICKS_HOST and PVSWEEP_DATABRICKS_WAREHOUSE_ID.
DBX_RUN       = set -a; . ./.env; set +a; uv run -q --no-project --with databricks-sdk --with azure-cli-core python -I
DBX_HOST      = $(shell grep -s '^DATABRICKSWORKSPACEURL=' .env.$(ENV) | cut -d= -f2)
DBX_PRINCIPAL ?= $(shell az account show --query user.name -o tsv 2>/dev/null)
DBX_GRANTEES  = $(foreach g,pvsweep_admin pvsweep_pipeline pvsweep_agent pvsweep_review_app pvsweep_reviewer pvsweep_analyst pvsweep_ci,--var $(g)=$(DBX_PRINCIPAL))
# Application ids printed in the bootstrap's membership checklist (runner identity, hosted agent identity).
DBX_PRINCIPALS = --var runner_principal=$(shell grep -s '^RUNNERIDENTITYCLIENTID=' .env.$(ENV) | cut -d= -f2) --var agent_principal=$(DBX_AGENT_PRINCIPAL)
DBX_AGENT_PRINCIPAL ?= <agent-client-id>
# Managed location for the catalog when the metastore has no storage root (printed by dbx-setup, kept in .env).
DBX_LOCATION   = $(if $(shell grep -s '^PVSWEEP_DATABRICKS_MANAGED_LOCATION=' .env),--var "managed_location_clause=MANAGED LOCATION '$$PVSWEEP_DATABRICKS_MANAGED_LOCATION'",)

dbx-setup:
	$(DBX_RUN) scripts/dbx_setup.py --host $(DBX_HOST)

dbx-dry-run:
	$(DBX_RUN) scripts/dbx_migrate.py --dry-run --bootstrap $(DBX_GRANTEES) $(DBX_PRINCIPALS) $(DBX_LOCATION)
	$(DBX_RUN) scripts/dbx_load.py --dry-run

dbx-bootstrap:
	$(DBX_RUN) scripts/dbx_migrate.py --bootstrap $(DBX_GRANTEES) $(DBX_PRINCIPALS) $(DBX_LOCATION)

dbx-migrate:
	$(DBX_RUN) scripts/dbx_migrate.py $(DBX_GRANTEES) $(DBX_PRINCIPALS)

dbx-load: stage-data
	$(DBX_RUN) scripts/dbx_load.py

# Copy processed results from Snowflake (export, read-only there) into Databricks (import).
dbx-export:
	python3 -I scripts/dbx_sync.py export $(if $(RUN),--run $(RUN),) $(if $(TABLES),--tables $(TABLES),) --conn $(SNOW_CONN)

dbx-import:
	$(DBX_RUN) scripts/dbx_sync.py import $(if $(REPLACE),--replace,) $(if $(TABLES),--tables $(TABLES),)

dbx-sync: dbx-export dbx-import

dbx-app:
	uv run -q --no-project -p 3.11 --with databricks-sdk python -I scripts/dbx_app.py $(if $(APPLY_GRANTS),--apply-grants,)

dbx-app-smoke:
	uv run -q --no-project -p 3.11 --with streamlit==1.38.0 --with duckdb --with pandas python -I databricks/app/smoke_test.py

# Compute is billed while it runs: stop the app and the warehouse after a demo (the warehouse also
# auto-stops after 10 idle minutes); dbx-app starts the app again, any query wakes the warehouse.
dbx-stop:
	$(DBX_RUN) -c "import os; from databricks.sdk import WorkspaceClient; w = WorkspaceClient(host=os.environ['PVSWEEP_DATABRICKS_HOST'], auth_type='azure-cli'); [w.warehouses.stop_and_wait(x.id) for x in w.warehouses.list() if str(x.state).endswith('RUNNING')]; print('warehouses stopped')"
	$(MAKE) dbx-app-stop

dbx-app-stop:
	$(DBX_RUN) -c "import os; from databricks.sdk import WorkspaceClient; w = WorkspaceClient(host=os.environ['PVSWEEP_DATABRICKS_HOST'], auth_type='azure-cli'); a = w.apps.get('pvsweep-review'); st = str(a.compute_status.state) if a.compute_status else ''; (w.apps.stop_and_wait('pvsweep-review'), print('pvsweep-review stopped')) if st.endswith('ACTIVE') else print('pvsweep-review already ' + (st or 'stopped'))"
