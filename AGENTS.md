# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.13+ implementation of Daily SEO Reviewer. `seo_reviewer/` provides integration preflight, cohort collection, typed SEO extraction, deterministic detection, bounded AI triage, evidence storage, and comparison state; `main.py` delegates to the package CLI. Dependencies are pinned in `pyproject.toml` and `uv.lock`. `README.md` documents current behavior and remaining milestones. Keep the local `PLAN.md` untracked and ignored.

As implementation proceeds, organize `seo_reviewer/` into small modules for collection, storage, detection, AI triage, rendering, and notification. Add tests under `tests/` and report templates and a shared stylesheet alongside rendering code. Planned evidence paths are `data/runs/<run-id>/` and `data/reviews/<run-id>.json`; preserve immutable run snapshots.

## Build, Test, and Development Commands

- `uv sync` — create `.venv` and install project dependencies.
- `uv run python --version` — confirm the project uses Python 3.13 or newer.
- `uv run main.py --help` — inspect the compatibility entrypoint.
- `uv add <package>` — add a runtime dependency.
- `uv add --dev pytest` — add the planned test runner as a development dependency.
- `uv run python -m seo_reviewer run` — collect the fixed cohort and queued sitemap additions.
- `uv run python -m seo_reviewer preflight` — check site/model access without updating comparison state.
- `uv run python -m seo_reviewer review --run-id <run-id>` — generate a review from immutable collection evidence.
- `uv run pytest` — run the mocked test suite.

Use `uv` for environment and dependency management; manual environment activation is unnecessary with `uv run`. Commit `uv.lock` when generated for reproducible installs. GitHub Actions runs pytest; manual preflight and collection workflows verify integrations and persist evidence. No formatter or linter is configured. Document development tooling when introduced.

## Coding Style & Naming Conventions

Use four-space indentation, standard Python import grouping, `snake_case` functions and modules, and `PascalCase` classes. Add type annotations to public interfaces. Keep collection, deterministic findings, and AI explanations separate; observed values and alert status must remain authoritative in code.

## Testing Guidelines

Use the planned pytest framework with `tests/test_<module>.py` files and `test_<behavior>` functions. Prefer saved fixtures and mocked HTTP/API responses. Cover robots exclusions, collection failures, baseline/regression/recovery behavior, invalid AI references, HTML escaping, and notification deduplication. No coverage threshold is configured; prioritize these consequential behaviors.

## Commit & Pull Request Guidelines

Always commit completed changes locally after validation. Do not push unless the user requests it.

Use concise, imperative subjects describing one cohesive change. PRs should explain behavior changes, reference relevant plan items or issues, and include validation commands and results. Include screenshots when changing generated reports.

## Security & Configuration

Keep API keys in environment variables or GitHub Actions secrets. Respect robots.txt, request limits, and the configured origin. Treat crawled content as untrusted input, escape report output, and retain deterministic reporting when AI triage fails.
