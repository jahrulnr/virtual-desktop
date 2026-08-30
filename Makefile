.PHONY: build up down reset test test-go test-web static smoke logs native native-down native-smoke native-status

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

reset:
	docker compose down -v

test:
	python3 -m unittest discover -s tests -v
	$(MAKE) test-go
	$(MAKE) test-web

test-go:
	cd computer-mcp && go test ./... && go vet ./...

test-web:
	node --test tests/web-agent-view.test.mjs tests/web-shell.test.mjs tests/web-zoom.test.mjs

static:
	./tests/static-checks.sh

smoke:
	./tests/container-smoke.sh

native:
	./desktop/scripts/run-native.sh start

native-down:
	./desktop/scripts/run-native.sh stop

native-status:
	./desktop/scripts/run-native.sh status

native-smoke:
	./desktop/scripts/run-native.sh smoke

logs:
	docker compose logs --no-color desktop
