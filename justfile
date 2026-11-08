lint:
    uv run --group dev ruff check .

fmt:
    uv run --group dev ruff format .

fmt-check:
    uv run --group dev ruff format --check .

typecheck:
    uv run --group dev ty check .

test:
    uv run python -m unittest discover tests

check: lint fmt-check typecheck test
