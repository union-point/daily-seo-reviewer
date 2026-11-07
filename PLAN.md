# One-day implementation plan: Daily SEO Reviewer

## Implementation status — 7 November 2026

- Initial integration slice implemented: `preflight` CLI, locked dependencies, robots/origin-aware HTTP access, immutable evidence, schema/reference-validated model probe, tests, manual Pages/Issue smoke workflow, and setup documentation.
- A real local site-only probe passed robots, sitemap, weblog, and one article; evidence is retained under `data/runs/20261107T135530.817108Z-c5636a91/`. OpenAI was explicitly skipped. This is not an SEO baseline or proof of GitHub-runner access.
- A subsequent local preflight in `data/runs/20261107T140017.433642Z-a9112e38/` passed all site checks and the schema/reference-validated model probe. Hosted-runner access, Pages deployment, and Issue delivery still require the manual workflow.
- Repository setup verified: the `OPENAI_API_KEY` Actions secret and `OPENAI_MODEL` repository variable exist, and Pages uses GitHub Actions as its source. Local `.env` configuration can be loaded using `uv run --env-file .env`.
- **Hour 1 gate passed:** hosted run [42382361069](https://github.com/union-point/daily-seo-reviewer/actions/runs/42382361069) verified runner/model access, Pages deployment, and Issue delivery.
- Hours 2–3 implemented locally: `run` CLI, fixed 50-URL cohort, bounded new-URL queue, typed SEO observations, immutable collection snapshots, atomic latest-successful comparison state, rolling coverage history, and manual collection/persistence workflow. Two real local runs each collected all 50 pages; the second preserved the cohort and recorded all 50 previous successful observations. Hosted collection validation follows after publishing this milestone.
- Next: deterministic findings and lifecycles (hour 4); current collection statuses do not claim SEO health or regressions.

## 1. Outcome and defaults

Build a Python agent that reviews **djangoproject.com** every morning, publishes an evidence-backed report on GitHub Pages, and adds a daily summary to one GitHub Issue.

- **Repository:** New public repository named `daily-seo-reviewer`.
- **Schedule:** Daily at **09:17 Asia/Yerevan**, using `17 5 * * *` UTC; also support manual runs.
- **Model:** Default `gpt-6.1-terra`; switch to `gpt-6.1-sol` through `OPENAI_MODEL`. Use low reasoning effort initially. These identifiers are documented in [OpenAI’s model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6.1-sol).
- **Scope:** Technical SEO health and regressions. Search traffic, rankings, and conversions require Search Console or analytics and are excluded.
- **Day-one exclusions:** Playwright, model tool calls, full-site link checking, and PageSpeed integration. Add one mobile PageSpeed check only if the core submission is complete.

## 2. Implementation sequence

### Hour 1 — Prove the integrations

- Create the repository, Python project, and manually triggered Actions workflow.
- Install `requests`, `lxml`, `pydantic`, `openai`, `jinja2`, and `pytest`; pin the tested dependency versions.
- Configure `OPENAI_API_KEY` as an Actions secret.
- From a GitHub-hosted runner, fetch robots.txt, sitemap.xml, the weblog, and an article using a descriptive User-Agent.
- Verify HTTP responses contain expected content rather than a challenge page. If blocked, stop site-specific development and select another site; do not add bypasses.
- Make one schema-validated API call using the selected model. Verify GitHub Pages deployment and Issue write permissions.

**Completion gate:** Runner access, model access, deployment, and delivery permissions work before expanding the crawler.

### Hours 2–3 — Collect and persist evidence

Implement one command, `python -m seo_reviewer run`, with configuration for site URL, model, request limits, and output locations.

- Fetch and respect robots.txt before crawling; default to one request per second per host.
- Parse sitemap XML and sitemap indexes. Keep crawling on the configured origin.
- Establish a fixed cohort of **50 URLs**: homepage, weblog index, and 48 recent dated weblog articles. Persist the cohort.
- Each subsequent run checks the cohort and up to 50 newly discovered sitemap URLs, capped at **100 pages**. Display any deferred URLs.
- Capture status, redirect chain, final URL, title, description, H1s, canonical, robots meta, `X-Robots-Tag`, JSON-LD presence/parse errors, response duration, and timestamp.
- Use bounded timeouts and retries; respect `Retry-After`. Recognize blocking and collection errors separately from missing SEO fields.
- Store parsed observations and robots/sitemap evidence in immutable, timestamped run snapshots. Maintain separate latest-successful observations and rolling aggregate history.
- Record schema/configuration versions, coverage, request errors, and run ID. Never overwrite a successful page observation with a failed attempt.

**Completion gate:** A real runner crawl produces downloadable JSON and a reproducible baseline.

### Hour 4 — Detect issues and changes

Use deterministic code for findings, severity, confidence, and overall status.

- Normalize whitespace and resolve relative URLs before comparing; preserve meaningful case and URL differences.
- Detect confirmed non-success responses, newly introduced indexing restrictions, missing/duplicate titles, missing descriptions/H1s, canonical changes, and malformed JSON-LD.
- Treat title changes, multiple H1s, redirects, and absent structured data as context-dependent observations rather than automatic critical errors.
- Compare sitemap membership and robots rules. Sitemap removal alone does not prove a page was deleted.
- Give findings stable IDs and track **new, ongoing, worsened, resolved**, or **unverified** states.
- Recheck potentially critical regressions within the same run. Flag changes affecting over 25% of comparable pages for investigation without suppressing genuine site-wide problems.
- First run reports existing issues and establishes the baseline; it does not claim regressions or trends. Failed checks cannot resolve previous findings.

**Completion gate:** Saved fixtures demonstrate regression, persistence, recovery, and collection failure.

### Hour 5 — Add bounded AI triage

Use the OpenAI Responses API with Pydantic-backed Structured Outputs. The SDK supports typed parsing, but factual correctness still requires application validation. [OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs)

**Input:** Deterministic findings, evidence IDs, comparable metrics, coverage, and URL-pattern groups.

**Output:** Headline, concise summary, up to five prioritized issues with finding IDs and recommended actions, plus a verification bucket.

- Keep alert status, observed values, counts, and affected URLs authoritative in code.
- Require valid finding references; render factual evidence directly from stored observations.
- Treat crawled text as untrusted data, never instructions.
- Bound input size, output tokens, and call timeout. Allow one retry.
- On refusal, invalid references, timeout, or API failure, publish a deterministic review labeled “AI summary unavailable.”
- Save model ID, prompt version, token usage, and generation outcome with each review.

**Completion gate:** Both AI success and AI failure produce usable reports.

### Hour 6 — Publish and notify

Generate static HTML with Jinja and a single shared stylesheet; no JavaScript framework.

**Report template checklist:** Title/date → status and freshness → crawl coverage → summary → prioritized issues with evidence/actions → resolved and verification items → history table → archive/data links → limitations.

- Reuse the template for latest and archived reviews; add a small archive index.
- Show baseline-only, healthy, partial-crawl, collection-failed, and AI-fallback states explicitly.
- Escape external content, use semantic headings/tables, and ensure links work under the repository’s GitHub Pages base path.
- Maintain one GitHub Issue titled **Daily SEO reviews**. Add a daily comment containing status, coverage, top actions, report link, and workflow-run link.
- Use a run-ID marker to prevent duplicate comments when retrying notification delivery. Explain in the README that team members must subscribe to the Issue for notifications.

**Completion gate:** A real Actions run publishes a report and delivers its Issue comment.

### Hours 7–8 — Harden and prepare the submission

- Add the daily schedule and workflow concurrency control.
- Commit collected data before deploying the generated Pages artifact; deploy explicitly in the same workflow.
- Grant only required permissions: contents and issues writes, plus Pages deployment permissions.
- Keep notification failures visible and retryable without rerunning the crawl. On pipeline failure, attempt a separate Issue comment with the workflow link.
- Review report rendering on desktop/mobile and independently check latest/archive consistency.
- Write the README and record the demonstration.

## 3. Data and interfaces

Keep the implementation as small Python modules for collection, storage, detection, triage, rendering, and notification.

Use versioned Pydantic types:

- **Page observation:** Requested/final URL, timestamp, collection outcome, extracted SEO fields, response metadata.
- **Finding:** Stable ID, rule, affected URLs, evidence, severity, confidence, lifecycle state.
- **Review:** Run metadata, authoritative status/coverage, findings, AI explanations, model outcome.

Persist run evidence under `data/runs/<run-id>/`, reviews under `data/reviews/<run-id>.json`, and a latest-state index for comparisons. Retain all evidence for the assignment; never fabricate historical runs.

## 4. Verification and submission

Test the consequential behaviors:

- Robots exclusion, redirects, relative canonicals, indexing headers, malformed HTML/JSON-LD, timeouts, and challenge responses.
- Stable cohort selection and sitemap additions/removals.
- First-run baseline, confirmed regression, recovery, widespread changes, and preservation of successful observations.
- Invalid AI references and API failure falling back correctly.
- HTML escaping, archive links, and notification deduplication.

Deliver:

1. Repository and README explaining architecture, configuration, rules, limitations, and data provenance.
2. Real collected JSON snapshots, findings, and at least one delivered review.
3. Working GitHub Pages report and daily-review Issue.
4. A recording of approximately **7–9 minutes**: show a live manual run, its delivered review, the pipeline/code/data, a clearly labeled regression fixture, and future improvements.

**Success criterion:** The workflow runs unattended, produces traceable findings, publishes the review, and delivers a daily summary—even when the model fails or no new SEO issues appear.
