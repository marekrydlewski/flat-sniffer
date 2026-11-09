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

dashboard:
    uv run render_dashboard.py

serve:
    python3 -m http.server 8000

wt-new name:
    git fetch origin main
    git worktree add "$(git rev-parse --git-common-dir)/../.worktrees/{{name}}" -b {{name}} origin/main

wt-clean:
    git worktree prune
