.PHONY: format test install

install:
	cd apalache-rpc-client && poetry install

format:
	cd apalache-rpc-client && poetry run black src/ tests/ && poetry run isort src/ tests/

test:
	cd apalache-rpc-client && poetry run pytest tests/ -v
