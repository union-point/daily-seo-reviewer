# Daily SEO Reviewer

An evidence-backed technical SEO reviewer for `www.djangoproject.com`, implemented incrementally from [PLAN.md](PLAN.md).

## Current milestone: integration preflight

The first slice verifies site access and a schema-validated OpenAI Responses API call before expanding the crawler. A manually triggered workflow also tests Pages deployment and delivery to one GitHub Issue named **Daily SEO reviews**. Preflight results are connectivity evidence, **not SEO findings, a baseline, or a delivered daily review**.

Implemented:

- Python 3.13 CLI, validated configuration, exact dependency versions, and `uv.lock`.
- Robots-first fetching with wildcard/Allow precedence using Protego, at least one second between requests, origin checks on every redirect, bounded response sizes, connect/read timeouts, one retry, and `Retry-After` handling.
- Sitemap XML/index validation, a small bounded sitemap traversal, weblog validation, and one dated article check. Challenges stop further site checks; no bypasses are attempted.
- Immutable per-run evidence with response bodies, SHA-256 hashes, timestamps, request metadata, errors, schema/config versions, and local/runner provenance.
- A bounded Structured Outputs model probe, including refusal/incomplete-output handling and application validation of evidence references. No crawled text is sent to the model at this stage.
- Automated tests, a JSON-only Pages smoke artifact, and retryable Issue delivery with run-ID deduplication.

Not implemented yet: the `run` command, fixed 50-page cohort, incremental 100-page collection, SEO extraction/detection, comparison state/history, AI review summaries, HTML reports, persistent published archives, daily scheduling, or the final submission recording. Those follow the integration gate in `PLAN.md`.

## Local development

Install [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --locked
uv run python --version
uv run pytest
uv run python -m seo_reviewer --help
uv run python -m seo_reviewer preflight --skip-model
```

`main.py` delegates to the same CLI: `uv run main.py preflight --skip-model`.

To include a real model call, set `OPENAI_API_KEY` in your shell and run:

```sh
uv run python -m seo_reviewer preflight --publish-dir site
```

If your key and model are in a local `.env` file, explicitly load it with uv:

```sh
uv run --env-file .env python -m seo_reviewer preflight --publish-dir site
```

The key is read by the OpenAI SDK; it is never stored in configuration or evidence. `.env` files are ignored by Git but are not automatically loaded without `--env-file`. Never commit API keys. A real probe uses API quota and may incur a small charge.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | All local/runner collection and model checks passed; Pages and Issue delivery are checked separately by the workflow. |
| `1` | A collection/model check failed, or evidence could not be written. |
| `2` | Incomplete gate (model skipped/missing key), or invalid CLI/configuration. |

A missing key is a skipped check, never a successful integration test. A failed check still produces a preflight result and collected evidence. Connection/read timeouts apply to each HTTP attempt. Responses are capped at 4 MB after decompression; redirects are capped at five; retry and robots delays above 60 seconds defer the request rather than violate the requested delay. Sitemap traversal is limited to six documents by default, and reports deferred documents. Requests stay on the configured origin, including sitemap and redirect targets.

## Configuration

| Environment variable | Default | CLI override |
| --- | --- | --- |
| `SITE_URL` | `https://www.djangoproject.com` | `--site-url` |
| `OPENAI_MODEL` | `gpt-6.1-terra` | `--model` |
| `OPENAI_API_KEY` | unset | none |
| `SEO_USER_AGENT` | `DailySEOReviewer/0.1 (+https://github.com/union-point/daily-seo-reviewer)` | none |
| `SEO_REQUEST_INTERVAL` | `1` second, minimum `1` | none |
| `SEO_DATA_DIR` | `data` | `--data-dir` |

Use the canonical `www` origin explicitly. An origin has no path, credentials, query, or fragment. Cross-origin redirects are refused, including redirects from the bare domain to `www`. The preflight currently expects the Django-style `/weblog/` and dated article paths; changing the origin alone does not make it a generic-site crawler. `OPENAI_MODEL=gpt-6.1-sol` selects the alternative from the plan. The model probe uses low reasoning effort, at most 512 output tokens, a 30-second SDK timeout per attempt, and at most one SDK retry.

## GitHub integration gate

After the code is on the default branch:

1. Add an Actions repository secret named `OPENAI_API_KEY` (for example, `gh secret set OPENAI_API_KEY`). Enter the key through the secret prompt, not a committed file. Optionally set the Actions repository variable `OPENAI_MODEL`; the workflow uses it unless you supply a manual model override, falling back to `gpt-6.1-terra` when neither is set.
2. In repository **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source.
3. Ensure Issues are enabled and the `github-pages` environment permits deployments from the default branch.
4. Run **Actions → Integration preflight → Run workflow** from the default branch, or `gh workflow run preflight.yml`.
5. Inspect the downloadable `preflight-evidence-<attempt>` artifact, deployed `/preflight.json`, and the **Daily SEO reviews** Issue. Subscribe to that Issue to receive notifications.

The workflow runs tests before network checks, uploads failure evidence, deploys a JSON smoke artifact, and posts the gate outcome. It fails if site/model checks or deployment fail, or if delivery fails. A successful local probe does not prove GitHub-runner access. Full gate success requires the runner checks, Pages deployment, **and** successful Issue delivery in the same workflow.

Permissions are scoped by job: repository read for collection, Pages/OIDC writes for deployment, and Issue write plus Actions/repository read for notification. Publication is serialized. There is no schedule yet; the planned `17 5 * * *` UTC schedule (09:17 Asia/Yerevan) comes after complete daily-review behavior exists.

If only notification fails, rerun the failed notification job. It downloads the saved preflight artifact and checks all comment pages for the run marker before posting. It updates an existing result when deployment status changes. An uncertain POST can therefore be retried without another crawl. For key/site fixes, run the whole preflight again. Test/setup failures that occur before a result exists remain visible in Actions; a separate pipeline-failure Issue notification is deferred to the hardening milestone.

The workflow does not commit data yet. Runner artifacts expire after 90 days; download and retain evidence until durable data persistence is implemented. The Pages smoke artifact is replaced on each deployment and is not an archive.

## Evidence and provenance

```text
seo_reviewer/
  config.py          # validated, non-secret configuration
  collection.py      # rate-limited, robots-aware HTTP client
  models.py          # versioned integration evidence types
  preflight.py       # site checks and gate orchestration
  triage.py          # bounded structured model connectivity probe
  storage.py         # immutable run snapshots and JSON export
  notification.py    # saved-result Issue delivery
data/runs/<run-id>/
  preflight.json     # checks, config, provenance, and model outcome
  fetches.jsonl      # request evidence, including redirect responses
  responses/*.body   # bounded raw response bytes (untrusted content)
```

Snapshots use unique timestamp/UUID run IDs and refuse existing run directories or finalized-run writes. They never update comparison/baseline state. A response body is diagnostic input, not executable or trusted HTML; the smoke deployment contains JSON only. HTTP headers persisted are limited to content type, redirect location, retry timing, and indexing headers. API exception messages and tokens are not persisted.

The included local snapshot `data/runs/20261107T135530.817108Z-c5636a91/` records a real **7 November 2026** site-only probe: robots, 1,021 same-origin sitemap URLs, weblog, and one article passed; OpenAI was explicitly skipped. It establishes neither SEO health nor runner access. Test fixtures are synthetic and are kept under `tests/`, separate from collected evidence.

The subsequent local snapshot `data/runs/20261107T140017.433642Z-a9112e38/` passed the site checks and schema/reference-validated model probe. This verifies local model access; the hosted integration gate remains pending.

## Validation and next milestone

Run `uv run pytest` for mocked robots, origin/redirect, timeout, challenge, retry, XML, immutable storage, model-reference, CLI, and notification-deduplication cases. Tests do not require a network connection or API key. CI uses the locked environment. No formatter, linter, or coverage threshold is configured.

Once the real integration gate passes, implement the persistent fixed cohort, detailed page observations, latest-successful state, and coverage reporting described in hours 2–3 of the plan. Subsequent milestones add deterministic findings/lifecycles, bounded AI triage with deterministic fallback, escaped Jinja reports, daily delivery, and durable history.

API implementation references: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI Python parsing helpers](https://github.com/openai/openai-python/blob/main/helpers.md), [Protego](https://github.com/scrapy/protego), and [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
