.PHONY: build up down reset test static smoke logs

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

static:
	./tests/static-checks.sh

smoke:
	./tests/container-smoke.sh

logs:
	docker compose logs --no-color desktop
