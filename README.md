# Daily SEO Reviewer

An evidence-backed technical SEO reviewer for `www.djangoproject.com`, implemented incrementally through the milestones described below.

## Current milestone: HTML reports and daily delivery

The first slice verifies site access and a schema-validated OpenAI Responses API call before expanding the crawler. A manually triggered workflow also tests Pages deployment and delivery to one GitHub Issue named **Daily SEO reviews**. Preflight results are connectivity evidence, **not SEO findings, a baseline, or a delivered daily review**.

Implemented:

- Python 3.13 CLI, validated configuration, exact dependency versions, and `uv.lock`.
- Robots-first fetching with wildcard/Allow precedence using Protego, at least one second between requests, origin checks on every redirect, bounded response sizes, connect/read timeouts, one retry, and `Retry-After` handling.
- Sitemap XML/index validation, a small bounded sitemap traversal, weblog validation, and one dated article check. Challenges stop further site checks; no bypasses are attempted.
- Immutable per-run evidence with response bodies, SHA-256 hashes, timestamps, request metadata, errors, schema/config versions, and local/runner provenance.
- A bounded Structured Outputs model probe, including refusal/incomplete-output handling and application validation of evidence references. The preflight probe sends no crawled text; review triage uses the bounded projection documented below.
- Automated tests, a JSON-only Pages smoke artifact, and retryable Issue delivery with run-ID deduplication.

The fixed cohort, detailed SEO extraction, persistent comparison state, and manual collection workflow are now implemented. Deterministic SEO findings/lifecycles and bounded AI review summaries are implemented. HTML reports, archives, daily Pages publication, and Issue delivery are implemented. The remaining submission work is hosted end-to-end validation, final hardening, and the demonstration recording.

## Collect observations

```sh
uv run python -m seo_reviewer run
```

This command makes no model calls and requires no API key. On the first successful discovery it fixes exactly 50 URLs: homepage, weblog index, and the 48 most recent dated articles in the sitemap (date order, with URL as a stable tie-breaker). It refuses to establish a smaller cohort. Each subsequent run retains those URLs, including URLs removed from the sitemap, and checks up to 50 newly discovered URLs. The initial sitemap inventory does not cause old pages outside the cohort to be crawled on the second run. Failed/deferred additions stay queued, and successful additions leave the queue. Complete sitemap removal drops a queued addition; it does not prove deletion of a cohort page.

Each page observation records requested/final URL, redirect chain, status, timestamps, total elapsed and network response durations, title, description, H1s, resolved canonicals, robots meta, X-Robots-Tag, and JSON-LD block/error counts. Whitespace is normalized while meaningful case and URL differences remain intact. Missing fields on otherwise collected HTML remain distinct from HTTP, robots, timeout, challenge, content-type, and parsing failures.

`data/runs/<run-id>/collection.json` is immutable and contains config/provenance, current observations, prior successful observations for attempted URLs, coverage, the cohort, sitemap membership/deltas, errors, and deferred URLs. Raw robots, sitemap, and page responses remain alongside it. The first usable collection is baseline-only. Incomplete sitemap discovery cannot establish the cohort or claim membership removals; an existing cohort can still be checked. Challenges stop further page requests.

`data/state.json` is a versioned, atomically replaced index: fixed cohort, per-URL latest-successful observations, last complete sitemap inventory, pending additions, latest run ID, and a rolling 90-run aggregate history. All original snapshots are retained. Failed attempts never replace successful observations. A process lock serializes local runs; a schema/origin mismatch fails before collection. Use a separate `--data-dir` for another origin. A crash after snapshot finalization but before index publication can leave an unindexed snapshot; the previous state remains usable.

The command exits `0` for a complete collection, `1` for partial/failed collection or state errors, and `2` for invalid arguments/configuration. Deferred page URLs and collection errors are printed explicitly. Collection status is not an SEO alert status.

After pushing, run the **Collect SEO observations** workflow (`gh workflow run collect.yml --ref main`). It runs tests, collects from the default branch, commits evidence and state back to that branch, and uploads a downloadable artifact even when collection is partial. It needs repository contents write permission and permission to push to the default branch; branch protection or a concurrent external push can reject persistence, leaving the artifact available for recovery. The workflow then renders and deploys Pages and delivers a daily Issue comment. Publication shares the existing concurrency group and runs daily at 09:17 Asia/Yerevan.

## PageSpeed Insights and Lighthouse

Normal collection optionally calls the official [PageSpeed Insights API v5](https://developers.google.com/speed/docs/insights/rest/v5/pagespeedapi/runpagespeed) for **Performance and SEO** categories. It uses the existing HTTP dependency and adds no crawler, CrUX API client, or model calls. By default, up to **3 successfully collected pages** are audited with **mobile and desktop** strategies: at most 6 initial requests. Selection is deterministic from collected final URLs: homepage first when available, then distinct path depths/families to favor an index and a detail page. Redirect aliases are deduplicated; failed, robots-excluded and off-origin pages are ineligible. URL shape is a heuristic for page type, not content classification; no domain-specific paths are used by this integration.

Configuration follows the existing environment-variable conventions, not a new YAML loader. Copy [`.env.example`](.env.example) to `.env`, fill only the credentials you use, then run:

```sh
uv run --env-file .env python -m seo_reviewer run --review
# Disable only PageSpeed; the existing SEO checks still run:
PAGESPEED_ENABLED=false uv run python -m seo_reviewer run --review
```

`.env` is ignored and loaded only when explicitly passed to `uv`. In code, the equivalent defaults are `Config(pagespeed={"enabled": True, "strategies": ["mobile", "desktop"], "max_pages": 3})`.

| Variable | Default / bounds |
| --- | --- |
| `PAGESPEED_ENABLED` | `true` |
| `PAGESPEED_STRATEGIES` | `mobile,desktop`; either or both, without duplicates |
| `PAGESPEED_MAX_PAGES` | `3`; 1–10 pages, independently of the crawl budget |
| `PAGESPEED_API_KEY` | Optional, unset; read only when making PSI requests |
| `PAGESPEED_READ_TIMEOUT` | `60` seconds per attempt; greater than 0, at most 120 |
| `PAGESPEED_RETRIES` | `1`; 0–2 transient retries per measurement |
| `PAGESPEED_POOR_SCORE` | `50` out of 100; greater than 0, at most 100 |

Google's [getting-started guide](https://developers.google.com/speed/docs/insights/v5/get-started) permits requests without an API key and recommends a key for automation. To obtain one, create/select a Google Cloud project, enable **PageSpeed Insights API**, create an API key under **APIs & Services → Credentials**, and restrict the key to that API. Set `PAGESPEED_API_KEY` locally or add it as an optional Actions repository secret (`gh secret set PAGESPEED_API_KEY`, entering it at the prompt). The collection workflow passes that secret and the optional repository variables `PAGESPEED_ENABLED`, `PAGESPEED_STRATEGIES`, and `PAGESPEED_MAX_PAGES`. Preflight remains the existing site/model integration gate and makes no PSI requests. No key is saved in configuration, evidence, logs, or published reports.

**Lab versus field:** Performance/SEO scores (0–100), Largest Contentful Paint (LCP), Cumulative Layout Shift (CLS), First Contentful Paint (FCP), Total Blocking Time (TBT), and Speed Index come from **Lighthouse laboratory measurements**. Times are stored in milliseconds, CLS is unitless; the report formats times in seconds. These are synthetic measurements, not actual visitor traffic. Lighthouse SEO score describes its technical checks; it is not an overall search-ranking or organic-traffic metric. Actionable failed audits retain IDs, titles, descriptions, scores, and available numeric/display observations.

When PSI returns CrUX `loadingExperience` or `originLoadingExperience`, these **field data** remain separate, including explicit page/origin-fallback scope, original percentile units and distributions. They are never substituted for lab measurements. Missing CrUX is explicitly unavailable and does not make otherwise complete Lighthouse data fail. Google [plans to discontinue field data in PSI](https://developers.google.com/speed/docs/insights/v5/get-started); this integration deliberately makes no separate CrUX API requests and continues to work without it.

**Deterministic checks:** A warning requires a Performance score below the configured threshold **and** at least one poor lab value: LCP > 4,000 ms, CLS > 0.25, or TBT > 600 ms. These are conservative investigation thresholds, not a field Core Web Vitals pass/fail assessment. Each explicitly failed, scored Lighthouse SEO audit produces a warning. Manual, not-applicable, informative and errored audits never become confirmed failures. Available partial evidence can support a finding; missing measurements cannot prove recovery.

Comparisons use the same exact URL and strategy, with matching Lighthouse version and final URL for historical claims. A new performance regression also requires a previously non-problematic, complete core measurement and a core metric crossing its poor boundary with an increase of at least **30% and 1,000 ms LCP / 0.1 CLS / 300 ms TBT**, respectively. Score fluctuations alone do not create regressions. A new SEO regression requires that exact audit previously passed. First observations remain baseline issues; active issues remain ongoing until a usable check no longer meets the rule, or that SEO audit explicitly passes. Missing, failed, deferred or omitted measurements leave previous findings unverified. Lab regressions are investigation signals, not proof of real-user or business impact.

Snapshots store normalized observations under `pagespeed`, with URL, strategy, collection time, status (`success`, `incomplete`, `unavailable`), missing fields, metrics and audit evidence. `pagespeed/*.json` files retain compact diagnostic projections with SHA-256 digests; screenshots, DOM tables, resource waterfalls and full Lighthouse reports are omitted to bound evidence growth. Only fully successful measurements replace `state.json` comparison entries. Snapshots without PageSpeed fields remain valid and show an explicit older-report state. Saved review generation, AI reanalysis and rendering use only immutable saved evidence and never request PageSpeed again; existing review hashes and narrative-reference validation still apply. The same bounded triage call can explain PageSpeed findings and supplied failed audits, with deterministic fallback when AI is unavailable.

The **Performance & Lighthouse** report section shows audited URLs/strategies, scores, available metrics, factual comparable score deltas and explicit unavailable states. Failed-audit descriptions and page/origin CrUX availability live in a native expandable technical disclosure. Priority findings use the existing report issue list. All untrusted text is escaped; no raw Lighthouse JSON is printed in the primary report.

**Reliability and limits:** Requests run serially with the configured site request interval (minimum one second), a connect timeout and separate PSI read timeout, no HTTP redirects, at most 8 MB per response, and bounded retries for timeouts/connection failures, HTTP 429 and transient 5xx errors. `Retry-After` is honored up to 60 seconds; longer delays are deferred. An exhausted 429 or 403 defers remaining PSI requests for the run. Service failures do not change crawl success/exit status or stop review/publication; missing Lighthouse data can set `verification_required` while keeping measured SEO findings authoritative. They never become confirmed website performance problems or zero scores.

Google Cloud project quotas, shared unauthenticated limits, API latency, inaccessible pages and run-to-run variation apply. Check the PageSpeed API quota dashboard for your project's current limits rather than assuming a universal allowance. Default retries permit up to 12 total requests; repeated timeouts can add several minutes to collection. Raising page/retry/timeout limits can exceed the existing 20-minute workflow budget; keep scheduled settings conservative. There is no persistent API cache beyond saved run evidence: a fresh collection deliberately measures again, while review retries reuse snapshots. History begins with the first successful comparable PageSpeed measurement; old reports are never backfilled.

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

## Bounded AI triage

Generate a review alongside a new collection, or from an existing collection without crawling again:

```sh
uv run --env-file .env python -m seo_reviewer run --review
uv run --env-file .env python -m seo_reviewer review --run-id <run-id>
```

For an explicitly deterministic review, use `--skip-ai` with either command. Plain `run` still makes no model call. The collection workflow now uses `run --review` with the Actions API-key secret and model repository variable, then commits and uploads `data/reviews/*.json` with the collection data. The same workflow now also publishes HTML reports and delivers the saved review.

Reviews are immutable versioned JSON at `data/reviews/<run-id>.json`. They contain the source snapshot path and SHA-256 digest, authoritative status/coverage/findings, deterministic summary, separately labeled AI or deterministic narrative, and generation metadata. Existing reviews are reused without another paid call, even when the requested model or `--skip-ai` changes. Changing a source snapshot is rejected. A local lock and atomic exclusive publication prevent partial review files and duplicate concurrent model calls. A failed write remains visible as a command failure; rerun the review command using the same evidence.

The model receives only a bounded projection of deterministic findings, evidence references, comparable metrics, coverage, and URL-pattern groups. Raw response bodies and API keys are never included. Before/observed excerpts are untrusted crawled data; instructions explicitly prohibit following embedded commands. Input is capped at 32,000 UTF-8 bytes and 50 active findings, with omitted counts recorded. Deterministic findings remain complete in the review. Excerpts/URL samples can be truncated; full authoritative values remain in the source and stored findings.

The Pydantic Structured Outputs contract contains a headline, concise summary, up to five priorities, and up to five verification items. Each item must name a supplied finding and its matching `<finding-id>:finding` evidence reference, which refers to that finding record and its stored body evidence. Application validation rejects invented, omitted, duplicate, cross-finding, or wrongly categorized references. Unverified findings belong only in verification items. The output schema contains no authoritative status, severity, count, URL, or observation fields. AI prose remains advisory: schema/reference validation cannot establish that every sentence is factually correct. Future reports must render factual evidence from the stored code-controlled values and escape all prose.

Triage uses low reasoning effort, a 2,048-token output cap, a 30-second SDK request timeout, no tools, and `store=False`. The application permits at most two API attempts total; SDK retries are disabled to avoid multiplying the budget. Invalid schemas/references, incomplete output, and API errors can use the one retry; refusal/empty output immediately falls back. Missing keys, explicit opt-out, or an oversized metadata envelope also fall back without calling the model. Timeout settings apply to network operations rather than guaranteeing a strict wall-clock deadline.

Every failure produces a usable deterministic narrative headed **AI summary unavailable**, with rule-specific actions and a verification bucket. Model failure alone does not change collection status or cause a nonzero exit. Authoritative fields stay intact. Each review records requested/returned model, prompt version, payload digest/size, included/omitted findings, per-attempt outcome, response ID, and token usage when available. Raw API errors and rejected output are not persisted. `Config` exposes validated limits (`ai_max_input_bytes`, `ai_max_findings`, `ai_max_output_tokens`, `ai_timeout`) for programmatic use; model selection remains `OPENAI_MODEL` / `--model`.

The real review `data/reviews/20261107T155148.935096Z-6285c5ed.json` was generated from the successful hosted collection run: the AI call succeeded in one attempt while preserving warning status and 50/50 coverage. Saved synthetic tests exercise failures without fabricating collected regressions. API behavior follows the [official Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

## HTML reports and daily delivery

Build the latest review and the complete saved-review archive without crawling or calling the model:

```sh
uv run python -m seo_reviewer.render --base-path /daily-seo-reviewer
python3 -m http.server 8000 --directory site
```

For local preview, use `--base-path ''` (or serve the generated tree under a matching `/daily-seo-reviewer/` parent). `--output-dir` selects a different generated directory. The renderer refuses to replace unrelated nonempty directories or evidence paths; it can upgrade the old preflight smoke directory. `site/` is generated and ignored. `DESIGN.md` and `UX-CONTRACT.md` document the shared presentation contract; [desktop](docs/screenshots/report-desktop.jpg) and [mobile](docs/screenshots/report-mobile.jpg) previews show real saved evidence.

The shared Jinja report template renders `/index.html` and `/reviews/<run-id>.html`. The archive starts at `/archive/index.html`, with static pages of 30 reviews and a five-report recent-history table linked by check date. Latest means newest collection time, independent of AI generation time. All report/data/CSS links honor the repository Pages base path. Evidence digests are verified before rendering. Only saved review JSON and collection JSON are copied into the Pages artifact; raw crawled response bodies remain in repository evidence and workflow artifacts. The main report uses plain-language statuses, concise coverage, changes, and issue impact/actions. Incomplete checks and unverified issues remain prominent. Specialist disclosures and raw technical links are omitted from report pages; identifiers, rule codes, confidence values, and digests stay out of report text. The saved evidence retains paths and digests for reproducibility.

Report order: check date → overall status, coverage, and check limitations → summary and changes → priority issues with impact, actions, and useful before/after comparisons → issues needing verification → resolved issues → recent reports → report scope and optional specialist details. First-report, no-issues-found, incomplete, failed, unverified, empty-archive, and unavailable-AI states are explicit. Freshness is measured **at publication**, with a 36-hour stale threshold; static pages do not update after deployment. Report dates use Asia/Yerevan. HTML output autoescapes all crawled/model content, accepts only HTTP(S) external links, and includes a restrictive content security policy. No JavaScript framework, remote fonts, or executable crawled HTML is published.

The collection workflow runs daily at **09:17 Asia/Yerevan** (`17 5 * * *` UTC), and supports manual runs. GitHub may delay scheduled execution. Jobs are serialized and scoped to the default branch. Data is committed before building/deploying the Pages artifact. Permissions are per job: contents write for persisted evidence, Pages/OIDC writes for deployment, and Issue write plus Actions/repository read for delivery. Configure Pages to use GitHub Actions and allow the default branch in the `github-pages` environment.

One Issue named **Daily SEO reviews** receives status, coverage, code-derived top actions, a link to the exact archived report, and the workflow-run link. Subscribe to that Issue for notifications. An AI failure still delivers a deterministic review; no new findings still produces a daily summary. Collection failures/partial crawls can publish their saved reviews and remain visible as workflow failures. If review creation/build/deployment fails, notification attempts a clearly labeled pipeline/publication failure message instead of claiming that an older report is current.

Notification downloads the **exact artifact ID output by its collection job**, so retrying only `notify` reuses the saved current review without recrawling or calling the model. A rerun-all whose new collection fails cannot silently reuse an earlier attempt's review. Existing run-ID comment markers prevent duplicates across uncertain POSTs; when deployment later succeeds, retry delivery updates the existing comment with its report link. If only notification fails, rerun that job. If deployment fails, rerun the failed deployment and notification jobs. Full reruns collect new immutable evidence. Build/deployment/notification failures remain in Actions, and artifacts remain available for 90 days; committed evidence has durable history. Repository branch protection or an external concurrent push can reject evidence persistence, preventing deployment and triggering a failure notification attempt.

The old integration preflight now checks site/model access without publishing by default. Its `publish_smoke` input explicitly enables the initial smoke deployment and Issue probe; that option replaces the Pages site and is intended only for initial setup. Use the collection workflow for daily reports.

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
4. For initial setup only, run **Integration preflight** with `publish_smoke` enabled to test Pages/Issue delivery. Later preflight runs leave publication disabled by default.
5. Inspect the downloadable `preflight-evidence-<attempt>` artifact, deployed `/preflight.json`, and the **Daily SEO reviews** Issue. Subscribe to that Issue to receive notifications.

The preflight workflow runs tests and uploads network/model evidence. When `publish_smoke` is enabled it also deploys a JSON smoke artifact and posts the gate outcome. It fails if site/model checks or deployment fail, or if delivery fails. A successful local probe does not prove GitHub-runner access. Full gate success requires the runner checks, Pages deployment, **and** successful Issue delivery in the same workflow.

Permissions are scoped by job: repository read for collection, Pages/OIDC writes for deployment, and Issue write plus Actions/repository read for notification. Publication is serialized. The collection/review workflow now has the `17 5 * * *` UTC schedule (09:17 Asia/Yerevan).

If only notification fails, rerun the failed notification job. It downloads the saved preflight artifact and checks all comment pages for the run marker before posting. It updates an existing result when deployment status changes. An uncertain POST can therefore be retried without another crawl. For key/site fixes, run the whole preflight again. Preflight test/setup failures remain visible in Actions. The daily collection workflow also attempts a failure Issue comment when no current review artifact exists.

The preflight workflow retains evidence only in artifacts; the collection workflow commits its snapshots and state. Runner artifacts expire after 90 days. The Pages smoke artifact is replaced on each deployment and is not an archive.

## Evidence and provenance

```text
seo_reviewer/
  config.py          # validated, non-secret configuration
  collection.py      # rate-limited, robots-aware HTTP client
  models.py          # versioned fetch/integration evidence types
  observations.py    # typed SEO field extraction
  pagespeed.py       # bounded PSI collection and typed lab/field observations
  pagespeed_detection.py # conservative URL/strategy-specific Lighthouse checks
  crawl.py           # cohort selection, discovery, collection orchestration
  state.py           # typed comparison index and active findings
  detection.py       # deterministic rules, confirmation decisions, and lifecycles
  preflight.py       # site checks and gate orchestration
  triage.py          # bounded model probe and validated AI triage
  review.py          # immutable reviews and deterministic fallback
  review_models.py   # versioned narrative and generation contracts
  storage.py         # immutable run snapshots and JSON export
  notification.py    # shared Issue client and integration delivery
  daily_delivery.py  # retryable daily-review/failure comments
  render.py          # safe static site build and data projection
  rendering/         # shared Jinja templates and stylesheet
data/runs/<run-id>/
  preflight.json     # integration runs only
  collection.json    # collection runs only: observations and previous evidence
  fetches.jsonl      # request evidence, including redirect responses
  responses/*.body   # bounded raw response bytes (untrusted content)
  pagespeed/*.json    # compact Lighthouse diagnostic evidence with snapshot digests
```

Snapshots use unique timestamp/UUID run IDs and refuse existing run directories or finalized-run writes. Preflight snapshots never update comparison state; collection runs publish state only after finalizing their snapshot. A response body is diagnostic input, not executable or trusted HTML; the smoke deployment contains JSON only. HTTP headers persisted are limited to content type, redirect location, retry timing, and indexing headers. API exception messages and tokens are not persisted.

The included local snapshot `data/runs/20261107T135530.817108Z-c5636a91/` records a real **7 November 2026** site-only probe: robots, 1,021 same-origin sitemap URLs, weblog, and one article passed; OpenAI was explicitly skipped. It establishes neither SEO health nor runner access. Test fixtures are synthetic and are kept under `tests/`, separate from collected evidence.

The subsequent local snapshot `data/runs/20261107T140017.433642Z-a9112e38/` passed the site checks and schema/reference-validated model probe. This verifies local model access. The hosted integration gate subsequently passed in [run 42382361069](https://github.com/union-point/daily-seo-reviewer/actions/runs/42382361069), including Pages and Issue delivery.

## Validation and next milestone

Run `uv run pytest` for mocked robots, origin/redirect, timeout, challenge, retry, XML, immutable storage, model-reference, CLI, and notification-deduplication cases. Tests do not require a network connection or API key. CI uses the locked environment. No formatter, linter, or coverage threshold is configured.

Two real local collection snapshots from 7 November 2026 (`20261107T144408.785631Z-a1373579` and `20261107T144617.966697Z-2f55601a`) each collected 50/50 pages. The second preserved the cohort and records 50 previous successful observations. Neither run fabricates historical SEO regressions.

Next: run the complete hosted workflow to verify report deployment and daily Issue delivery, then review remaining hardening and prepare the 7–9 minute demonstration. The workflow schedule activates after this change reaches the default branch.

API implementation references: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI Python parsing helpers](https://github.com/openai/openai-python/blob/main/helpers.md), [Protego](https://github.com/scrapy/protego), and [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

The report leads with the saved assessment and its headline, followed by one ordered priority list combining reasoning, affected pages, next actions, and completion checks. Individual explanations have no “AI note” labels. For issues with saved analysis, show that explanation and recommendation without repeating stock condition or impact paragraphs; omit standard verification boilerplate. Issues without an explanation retain plain-language fallback context. Completion checks are standard workflow guidance; recommendations and ordering reuse saved analysis where available. No suggested owners are displayed. Coverage and confirmed changes remain code-derived and visible. No saved reviews are rewritten or extra model calls made to render the report.

To reanalyse an existing collection with the latest prompt without recrawling or replacing its original review:

```sh
uv run --env-file .env python -m seo_reviewer review --run-id <run-id> --refresh-ai
uv run python -m seo_reviewer.render --base-path ''
```

Successful reanalyses are immutable files under `data/review_revisions/<run-id>/`. Rendering selects the newest analysis for the same collection, checks that all authoritative facts match the original review, and validates finding/evidence references. A failed reanalysis leaves earlier results intact. Ordinary review retries remain idempotent. Prompt v4 retains grouped prevalence and lifecycle counts before bounded detail truncation; asks for concise significance, caveats, related issues and a justified order of fixes; and forbids invented traffic or ranking effects. It also distinguishes Lighthouse lab measurements from field data and grounds performance advice in supplied failed audits. The snippet guidance follows [Google Search Central](https://developers.google.com/search/docs/appearance/snippet): Google primarily builds snippets from page content and may use the meta description.

## Narrative ownership

New successful AI reviews use a strict response schema requiring an issue title, explanation, recommendation and completion criterion. All issue narrative and executive-summary text is saved in the immutable review artifact before rendering. Missing/blank required fields trigger the existing retry and whole-review fallback policy. The renderer does not supplement AI issues with stock recommendations or titles. Statuses, URLs, observations and evidence references remain code-owned.

The bounded AI response can select up to five priorities and five verification items. Findings outside that selection, including resolved findings, remain available as factual records in a disclosure. They do not receive synthetic narrative cards. Historical AI artifacts without newer fields display their saved text and a static label; they are not rewritten. Deterministic narrative templates are isolated behind fallback generation, and new fallback text is likewise stored before rendering. Only historical fallback artifacts require the explicit legacy rendering adapter. Daily delivery recommendations also reuse saved actions.

Live verification on 8 November 2026 generated a new AI analysis revision from existing collection evidence and a separate AI-disabled review. Neither verification recollected pages or replaced an original review. The local latest report uses the new analysis revision.
