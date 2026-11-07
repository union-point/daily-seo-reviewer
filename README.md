# Daily SEO Reviewer

An evidence-backed technical SEO reviewer for `www.djangoproject.com`, implemented incrementally through the milestones described below.

## Current milestone: deterministic findings and change tracking

The first slice verifies site access and a schema-validated OpenAI Responses API call before expanding the crawler. A manually triggered workflow also tests Pages deployment and delivery to one GitHub Issue named **Daily SEO reviews**. Preflight results are connectivity evidence, **not SEO findings, a baseline, or a delivered daily review**.

Implemented:

- Python 3.13 CLI, validated configuration, exact dependency versions, and `uv.lock`.
- Robots-first fetching with wildcard/Allow precedence using Protego, at least one second between requests, origin checks on every redirect, bounded response sizes, connect/read timeouts, one retry, and `Retry-After` handling.
- Sitemap XML/index validation, a small bounded sitemap traversal, weblog validation, and one dated article check. Challenges stop further site checks; no bypasses are attempted.
- Immutable per-run evidence with response bodies, SHA-256 hashes, timestamps, request metadata, errors, schema/config versions, and local/runner provenance.
- A bounded Structured Outputs model probe, including refusal/incomplete-output handling and application validation of evidence references. No crawled text is sent to the model at this stage.
- Automated tests, a JSON-only Pages smoke artifact, and retryable Issue delivery with run-ID deduplication.

The fixed cohort, detailed SEO extraction, persistent comparison state, and manual collection workflow are now implemented. Deterministic SEO findings/lifecycles are implemented. AI review summaries, HTML reports, daily review delivery/scheduling, and the final submission recording are subsequent milestones.

## Collect observations

```sh
uv run python -m seo_reviewer run
```

This command makes no model calls and requires no API key. On the first successful discovery it fixes exactly 50 URLs: homepage, weblog index, and the 48 most recent dated articles in the sitemap (date order, with URL as a stable tie-breaker). It refuses to establish a smaller cohort. Each subsequent run retains those URLs, including URLs removed from the sitemap, and checks up to 50 newly discovered URLs. The initial sitemap inventory does not cause old pages outside the cohort to be crawled on the second run. Failed/deferred additions stay queued, and successful additions leave the queue. Complete sitemap removal drops a queued addition; it does not prove deletion of a cohort page.

Each page observation records requested/final URL, redirect chain, status, timestamps, total elapsed and network response durations, title, description, H1s, resolved canonicals, robots meta, X-Robots-Tag, and JSON-LD block/error counts. Whitespace is normalized while meaningful case and URL differences remain intact. Missing fields on otherwise collected HTML remain distinct from HTTP, robots, timeout, challenge, content-type, and parsing failures.

`data/runs/<run-id>/collection.json` is immutable and contains config/provenance, current observations, prior successful observations for attempted URLs, coverage, the cohort, sitemap membership/deltas, errors, and deferred URLs. Raw robots, sitemap, and page responses remain alongside it. The first usable collection is baseline-only. Incomplete sitemap discovery cannot establish the cohort or claim membership removals; an existing cohort can still be checked. Challenges stop further page requests.

`data/state.json` is a versioned, atomically replaced index: fixed cohort, per-URL latest-successful observations, last complete sitemap inventory, pending additions, latest run ID, and a rolling 90-run aggregate history. All original snapshots are retained. Failed attempts never replace successful observations. A process lock serializes local runs; a schema/origin mismatch fails before collection. Use a separate `--data-dir` for another origin. A crash after snapshot finalization but before index publication can leave an unindexed snapshot; the previous state remains usable.

The command exits `0` for a complete collection, `1` for partial/failed collection or state errors, and `2` for invalid arguments/configuration. Deferred page URLs and collection errors are printed explicitly. Collection status is not an SEO alert status.

After pushing, run the **Collect SEO observations** workflow (`gh workflow run collect.yml --ref main`). It runs tests, collects from the default branch, commits evidence and state back to that branch, and uploads a downloadable artifact even when collection is partial. It needs repository contents write permission and permission to push to the default branch; branch protection or a concurrent external push can reject persistence, leaving the artifact available for recovery. The workflow does not deploy or notify an SEO review yet. Publication shares the existing concurrency group; no daily schedule is enabled.

## Findings and change tracking

Each collection snapshot now includes a versioned `detection` result: authoritative `alert_status`, findings, contextual observations, comparable/changed page counts, and a `widespread_change` investigation flag. `data/state.json` persists active findings; resolved entries remain in their immutable run snapshots. Existing state files migrate by defaulting these new fields; old snapshots are never rewritten.

Rules and severity:

| Rule | Severity / handling |
| --- | --- |
| Non-success HTTP response | Critical only when a separate same-run request confirms the same status; collection/challenge errors are unverified. |
| Newly observed noindex/none restriction | Critical after confirmation; restrictions already present at baseline are warnings. Bot scopes are retained. |
| Newly introduced robots exclusion | Critical after re-fetching robots and confirming the exclusion; excluded pages are never requested. Baseline exclusions are warnings. |
| Missing title, description, or H1 | Warning on successfully parsed HTML. |
| Duplicate title | Warning within successfully collected pages; comparisons preserve title case. |
| Changed canonical | Warning compared with the original pre-change canonical; remains open until that value returns. |
| Malformed JSON-LD | Warning; more malformed blocks worsens the finding. |

Title changes, multiple H1s, redirects, absent structured data, and sitemap additions/removals are contextual observations. Robots body changes are recorded by digest and do not imply that rule semantics changed. Sitemap removal alone never proves deletion. Indexing directives follow [Google's robots meta specifications](https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag); these rules identify technical conditions, not actual ranking or traffic effects.

Finding IDs are stable hashes of rule and requested URL. Each finding records severity, confidence, first/last run, baseline/regression labels, before/observed values, and evidence paths for the original request and any confirmation. States are `new`, `ongoing`, `worsened`, `resolved`, and `unverified`. Missing/failed/deferred checks cannot resolve a previous finding. Duplicate-title recovery also requires successful checks of its previously matching peers. Additional duplicate matches or malformed JSON-LD blocks can produce `worsened`. Resolved findings can recur under the same ID as a new episode.

Critical confirmations happen after primary collection and obey the same origin, rate, timeout, and robots rules. They recheck existing URLs, so the 100-distinct-page cap remains intact; request totals can exceed 100. A robots policy is re-fetched at most once for exclusion confirmations. A contradictory or failed confirmation leaves the finding unverified and preserves the earlier successful comparison baseline. Confirmed noindex content remains an authoritative successfully collected observation.

`critical` means at least one confirmed critical finding; otherwise verified warnings produce `warning`, outstanding unverified findings/collection gaps produce `verification_required` when there are no verified warnings, and a complete check without active findings is `healthy`. Collection status/exit codes remain separate: a successful collection may still have critical SEO findings. The first baseline reports existing issues without claiming regressions. A change affecting strictly more than 25% of comparable pages flags investigation and never suppresses findings, including confirmed site-wide HTTP failures. This flag is not a trend inferred from a single run.

The synthetic scenarios in `tests/test_detection.py` and `tests/test_crawl.py` cover baseline, persistence, worsening, failed-check uncertainty, confirmation conflicts, robots enforcement, and recovery. No synthetic regressions are inserted into collected history. The included live run `20261107T151913.294864Z-c527f39c` collected 50/50 pages and recorded two warnings; that is observed evidence, not a simulated regression.

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

Preflight exit codes:

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
| `SEO_MAX_PAGES` | `100`, allowed range `50–100` | none |
| `SEO_MAX_SITEMAPS` | `6`, allowed range `1–20` | none |

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

The preflight workflow retains evidence only in artifacts; the collection workflow commits its snapshots and state. Runner artifacts expire after 90 days. The Pages smoke artifact is replaced on each deployment and is not an archive.

## Evidence and provenance

```text
seo_reviewer/
  config.py          # validated, non-secret configuration
  collection.py      # rate-limited, robots-aware HTTP client
  models.py          # versioned fetch/integration evidence types
  observations.py    # typed SEO field extraction
  crawl.py           # cohort selection, discovery, collection orchestration
  state.py           # typed comparison index and active findings
  detection.py       # deterministic rules, confirmation decisions, and lifecycles
  preflight.py       # site checks and gate orchestration
  triage.py          # bounded structured model connectivity probe
  storage.py         # immutable run snapshots and JSON export
  notification.py    # saved-result Issue delivery
data/runs/<run-id>/
  preflight.json     # integration runs only
  collection.json    # collection runs only: observations and previous evidence
  fetches.jsonl      # request evidence, including redirect responses
  responses/*.body   # bounded raw response bytes (untrusted content)
```

Snapshots use unique timestamp/UUID run IDs and refuse existing run directories or finalized-run writes. Preflight snapshots never update comparison state; collection runs publish state only after finalizing their snapshot. A response body is diagnostic input, not executable or trusted HTML; the smoke deployment contains JSON only. HTTP headers persisted are limited to content type, redirect location, retry timing, and indexing headers. API exception messages and tokens are not persisted.

The included local snapshot `data/runs/20261107T135530.817108Z-c5636a91/` records a real **7 November 2026** site-only probe: robots, 1,021 same-origin sitemap URLs, weblog, and one article passed; OpenAI was explicitly skipped. It establishes neither SEO health nor runner access. Test fixtures are synthetic and are kept under `tests/`, separate from collected evidence.

The subsequent local snapshot `data/runs/20261107T140017.433642Z-a9112e38/` passed the site checks and schema/reference-validated model probe. This verifies local model access. The hosted integration gate subsequently passed in [run 42382361069](https://github.com/union-point/daily-seo-reviewer/actions/runs/42382361069), including Pages and Issue delivery.

## Validation and next milestone

Run `uv run pytest` for mocked robots, origin/redirect, timeout, challenge, retry, XML, immutable storage, model-reference, CLI, and notification-deduplication cases. Tests do not require a network connection or API key. CI uses the locked environment. No formatter, linter, or coverage threshold is configured.

Two real local collection snapshots from 7 November 2026 (`20261107T144408.785631Z-a1373579` and `20261107T144617.966697Z-2f55601a`) each collected 50/50 pages. The second preserved the cohort and records 50 previous successful observations. Neither run fabricates historical SEO regressions.

The next milestone adds bounded AI triage with validated finding references and deterministic fallback. Later milestones add deterministic findings/lifecycles, bounded AI triage with deterministic fallback, escaped Jinja reports, daily delivery, and durable history.

API implementation references: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI Python parsing helpers](https://github.com/openai/openai-python/blob/main/helpers.md), [Protego](https://github.com/scrapy/protego), and [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
