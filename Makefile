.PHONY: install check container-check
install:
	uv sync --frozen --all-groups
check:
	uv run python manage.py check
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy formreview accounts documents extraction reviews evaluation
	uv run pytest -m "not integration and not e2e"
container-check:
	docker compose config --quiet
	docker build -t formreview:local .
	uv run python scripts/check_container.py

.PHONY: integration
integration:
	uv run python manage.py migrate
	uv run python manage.py makemigrations --check --dry-run
	uv run pytest -m integration
	uv run python manage.py process_jobs --help

.PHONY: e2e
e2e:
	uv run pytest -m e2e
	uv run python scripts/demo_smoke.py
