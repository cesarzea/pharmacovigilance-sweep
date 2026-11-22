# Pharmacovigilance Sweep: deploy from scratch, build, run, tear down.
# Needs: az (logged in), docker or az acr build, uv. Parameters: infra/main.parameters.local.json.

ENV        ?= dev
LOCATION   ?= swedencentral
PARAMS     ?= infra/main.parameters.local.json
RG          = rg-pvsweep-$(ENV)
IMAGE_TAG  ?= $(shell git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)

.PHONY: deploy outputs build-agent deploy-agents spike-models spike-agent stage-data snow-keys snow-bootstrap snow-migrate snow-load snow-app teardown

deploy:
	az deployment sub create -n pvsweep-$(ENV)-$$(date +%Y%m%d%H%M%S) -l $(LOCATION) \
	  -f infra/main.bicep -p @$(PARAMS) --only-show-errors -o none
	$(MAKE) outputs

# Writes the deployment outputs to .env.$(ENV) (ignored by git) for the other targets.
outputs:
	az deployment sub list --query "[?contains(name,'pvsweep-$(ENV)-')] | sort_by(@,&properties.timestamp) | [-1].properties.outputs" -o json \
	  | python3 -I scripts/outputs_to_env.py > .env.$(ENV)
	@cat .env.$(ENV)

build-agent:
	. ./.env.$(ENV) && az acr build -r $$REGISTRYNAME -g $$RESOURCEGROUP -t pvsweep-agent:$(IMAGE_TAG) --platform linux/amd64 -f agent/Dockerfile .

deploy-agents:
	. ./.env.$(ENV) && uv run -q --no-project --with azure-ai-projects --with azure-identity python -I scripts/deploy_agents.py \
	  --project-endpoint $$PROJECTENDPOINT --image $$REGISTRYLOGINSERVER/pvsweep-agent:$(IMAGE_TAG) \
	  --provider gpt --deployment $$GPTSMALLDEPLOYMENT \
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
