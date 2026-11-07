# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.13+ scaffold for Daily SEO Reviewer. `main.py` currently prints a greeting; `pyproject.toml` defines project metadata with no dependencies. `.python-version` selects Python 3.13, `README.md` is empty, and `PLAN.md` describes the intended implementation.

As implementation proceeds, organize `seo_reviewer/` into small modules for collection, storage, detection, AI triage, rendering, and notification. Add tests under `tests/` and report templates and a shared stylesheet alongside rendering code. Planned evidence paths are `data/runs/<run-id>/` and `data/reviews/<run-id>.json`; preserve immutable run snapshots.

## Build, Test, and Development Commands

- `uv sync` — create `.venv` and install project dependencies.
- `uv run python --version` — confirm the project uses Python 3.13 or newer.
- `uv run main.py` — run the current scaffold.
- `uv add <package>` — add a runtime dependency.
- `uv add --dev pytest` — add the planned test runner as a development dependency.
- `uv run python -m seo_reviewer run` — intended CLI from `PLAN.md`; unavailable until the package is implemented.
- `uv run pytest` — run tests once pytest and the test suite are added.

Use `uv` for environment and dependency management; manual environment activation is unnecessary with `uv run`. Commit `uv.lock` when generated for reproducible installs. No build pipeline, test runner dependency, formatter, or linter is configured yet. Document development tooling when introduced.

## Coding Style & Naming Conventions

Use four-space indentation, standard Python import grouping, `snake_case` functions and modules, and `PascalCase` classes. Add type annotations to public interfaces. Keep collection, deterministic findings, and AI explanations separate; observed values and alert status must remain authoritative in code.

## Testing Guidelines

Use the planned pytest framework with `tests/test_<module>.py` files and `test_<behavior>` functions. Prefer saved fixtures and mocked HTTP/API responses. Cover robots exclusions, collection failures, baseline/regression/recovery behavior, invalid AI references, HTML escaping, and notification deduplication. No coverage threshold is configured; prioritize these consequential behaviors.

## Commit & Pull Request Guidelines

History contains only `Initial commit`, so no established message convention exists. Use concise, imperative subjects describing one cohesive change. PRs should explain behavior changes, reference relevant plan items or issues, and include validation commands and results. Include screenshots when changing generated reports.

## Security & Configuration

Keep API keys in environment variables or GitHub Actions secrets. Respect robots.txt, request limits, and the configured origin. Treat crawled content as untrusted input, escape report output, and retain deterministic reporting when AI triage fails.
