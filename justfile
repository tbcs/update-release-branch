set shell := ["bash", "-cu"]

_default:
  @just --choose

# initialize the source tree for development
init: _install-git-commit-template _install-git-hooks _init-python

# instruct git to use a template for commit messages
_install-git-commit-template:
    git config --local commit.template ".gitmessage"

# install pre-commit git hooks
_install-git-hooks:
    pre-commit install --overwrite --install-hooks

# initialize the Python environment
_init-python:
    uv sync --locked --all-groups

# update pre-commit git hooks
update-git-hooks:
    pre-commit autoupdate --freeze

# lock Python dependencies
lock:
    uv lock

# run validations and linters
check:
    uv run mypy .
    uv run ruff check

# clean the source tree (build artifacts etc.)
clean:
    rm -rf .venv/
    rm -rf build/
    find . -type d -name "__pycache__" -print0 | xargs -0 rm -rf
    find . -type f -name "*.py[co]" -print0 | xargs -0 rm -rf
