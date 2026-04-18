PYTHONPATH=legacy/src
PYTHON=python3
HERMES_PYTHON=$(HOME)/.hermes/hermes-agent/venv/bin/python
HERMES_PROXY_PORT?=11435
COMPOSE_FILE=deploy/docker-compose.yml

.PHONY: stack-up stack-down stack-logs stack-ps proxy proxy-health verify-real verify-server host-runtime server-install legacy-chat legacy-replay legacy-inspect legacy-tts-spike legacy-smoke chat replay inspect tts-spike smoke

stack-up:
	docker compose -f $(COMPOSE_FILE) up --build -d

stack-down:
	docker compose -f $(COMPOSE_FILE) down

stack-logs:
	docker compose -f $(COMPOSE_FILE) logs -f honcho-api honcho-deriver wechat-gateway caddy

stack-ps:
	docker compose -f $(COMPOSE_FILE) ps

proxy:
	HERMES_AGENT_ROOT=$(HOME)/.hermes/hermes-agent HERMES_PROXY_PORT=$(HERMES_PROXY_PORT) $(HERMES_PYTHON) scripts/hermes_model_proxy.py

proxy-health:
	curl -s http://127.0.0.1:$(HERMES_PROXY_PORT)/healthz

verify-real:
	$(PYTHON) scripts/verify_real_integration.py

verify-server:
	$(PYTHON) scripts/verify_server_stack.py

host-runtime:
	./scripts/setup_host_runtime.sh

server-install:
	sudo ./scripts/install_server.sh --service-user $(USER)

legacy-chat:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m hermes_poc.cli chat

legacy-replay:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m hermes_poc.cli replay --script legacy/fixtures/replay/daily_stability.json

legacy-inspect:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m hermes_poc.cli inspect

legacy-tts-spike:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m hermes_poc.cli tts-spike --text "This is a sample line."

legacy-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m hermes_poc.cli replay --script legacy/fixtures/replay/daily_stability.json

chat: legacy-chat

replay: legacy-replay

inspect: legacy-inspect

tts-spike: legacy-tts-spike

smoke: legacy-smoke
