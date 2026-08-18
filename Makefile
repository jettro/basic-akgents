# Shortcuts for the everyday commands of this project. Everything runs through
# uv, so no virtual environment has to be activated first.
#
#   make            list the targets
#   make check      what to run before committing
#   make run CASE=case_2
#   make watch      the live event feed, in a second terminal
#
# CASE is optional: without it the demo lists the store and waits for a command
# ('help' lists them).

CASE ?=

.DEFAULT_GOAL := help
.PHONY: help sync lock upgrade run watch lint fix format format-check check clean clean-data

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

## --- Environment -----------------------------------------------------------

sync: ## Install the project and its dev tools from uv.lock
	uv sync

lock: ## Refresh uv.lock without changing the installed packages
	uv lock

upgrade: ## Update the locked dependencies to their newest allowed versions
	uv lock --upgrade
	uv sync

## --- Running ---------------------------------------------------------------

run: ## Run the sample, optionally on one case: make run CASE=case_2
	uv run src/main.py $(CASE)

watch: ## Follow the live event feed of a running session (second terminal)
	tail -f data/live-feed.log

## --- Quality ---------------------------------------------------------------

lint: ## Report lint findings (ruff check)
	uv run ruff check .

fix: ## Apply the fixes ruff can make itself
	uv run ruff check --fix .

format: ## Format the code (ruff format)
	uv run ruff format .

format-check: ## Report formatting differences without writing them
	uv run ruff format --check .

check: lint format-check ## Run every check, the pre-commit gate

## --- Housekeeping ----------------------------------------------------------

clean: ## Remove caches and compiled files
	rm -rf .ruff_cache
	find . -path ./.venv -prune -o -type d -name __pycache__ -print0 | xargs -0 rm -rf

clean-data: ## Remove the event store of past runs (data/)
	rm -rf data
