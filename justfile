lint:
    uv run --group dev ruff check .

fmt:
    uv run --group dev ruff format .

fmt-check:
    uv run --group dev ruff format --check .

typecheck:
    uv run --group dev ty check .

check: lint fmt-check typecheck
