.PHONY: build up down reset test test-go static smoke logs

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

test-go:
	cd computer-mcp && go test ./... && go vet ./...

static:
	./tests/static-checks.sh

smoke:
	./tests/container-smoke.sh

logs:
	docker compose logs --no-color desktop computer-mcp coddy
