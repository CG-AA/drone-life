# drone-life — workshop co-op drone game
# Dev quickstart:  make dev-server   (terminal 1)
#                  make dev-web      (terminal 2, hot-reload frontend on :5173)
# Production:      make image build run

ROOM_CODE ?= classroom
ADMIN_TOKEN ?= change-me
MISSION ?= delivery
HOST ?= 127.0.0.1:8000
N ?= 5
MODE ?= local
SCRIPT ?= bot_patrol

.PHONY: dev-server dev-web build image run test test-web e2e load lint fmt bots reset clean

dev-server:
	cd server && ROOM_CODE=$(ROOM_CODE) ADMIN_TOKEN=$(ADMIN_TOKEN) MISSION=$(MISSION) \
		uv run uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && npm run dev

build:
	cd web && npm run build

image:
	podman build -f runner/Containerfile -t drone-life-runner:latest .

run:
	cd server && ROOM_CODE=$(ROOM_CODE) ADMIN_TOKEN=$(ADMIN_TOKEN) MISSION=$(MISSION) \
		uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers

test:
	cd server && uv run pytest -q
	cd web && npx vitest run

e2e:
	cd server && uv run pytest -q -m e2e

load:
	cd server && uv run pytest -q -m load

lint:
	cd server && uv run ruff check app tests

fmt:
	cd server && uv run ruff check --fix app tests

# spawn demo bots: make bots N=10 MODE=container SCRIPT=bot_courier
bots:
	curl -s -X POST http://$(HOST)/api/v1/admin/bots \
		-H "X-Admin-Token: $(ADMIN_TOKEN)" -H 'Content-Type: application/json' \
		-d '{"count":$(N),"script":"$(SCRIPT)","mode":"$(MODE)"}'

reset:
	curl -s -X POST http://$(HOST)/api/v1/admin/reset -H "X-Admin-Token: $(ADMIN_TOKEN)"

clean:
	rm -rf server/state web/dist
