# Daily SEO Reviewer

Daily SEO Reviewer automatically checks a website every morning, collecting technical SEO and performance data and comparing it with previous observations. AI helps prioritize validated findings and turn them into actionable recommendations. The latest review and report history are published on GitHub Pages, with a daily summary delivered through a GitHub Issue.

Built as a take-home assignment for the **AI Automation Specialist** position at **Loopex Digital**.

## Live demo

- **[Latest SEO report](https://union-point.github.io/daily-seo-reviewer/)**
- [Report history](https://union-point.github.io/daily-seo-reviewer/archive/index.html)
- [Daily collection workflow and run history](https://github.com/union-point/daily-seo-reviewer/actions/workflows/collect.yml)

## What it does

- Runs scheduled daily checks while respecting robots.txt, request limits, and the configured origin.
- Analyzes public HTML for technical SEO issues, including metadata and indexing directives.
- Collects Google PageSpeed Insights / Lighthouse performance and SEO measurements for selected pages on mobile and desktop.
- Compares observations with saved history to identify new, ongoing, resolved, and unverified issues.
- Uses AI to explain findings, prioritize fixes, and suggest actions and completion checks.
- Publishes readable HTML reports, preserves report history, and posts daily Issue summaries.

## How it works

1. **Schedule:** GitHub Actions starts the daily workflow and runs the test suite.
2. **Collect:** The Python collector retrieves website HTML, sitemap information, and optional PageSpeed measurements.
3. **Detect:** Deterministic rules identify technical issues and compare them with previous successful observations.
4. **Explain:** An OpenAI model receives a bounded evidence summary and returns structured priorities, explanations, and recommendations. The application validates its finding and evidence references.
5. **Render:** Saved collection evidence and review results become a static HTML report and archive.
6. **Deliver:** GitHub Pages publishes the reports, and the workflow posts a summary to the **Daily SEO reviews** Issue.

Code owns observed values, issue detection, and alert status. The model explains the supplied evidence; it does not crawl the website or change detection results. If AI is unavailable or its response fails validation, the application saves a deterministic fallback review.

## Data sources

The demonstration monitors **`www.djangoproject.com`**, using:

- **Public website content:** HTML, metadata, HTTP responses, robots.txt, and sitemaps.
- **Google PageSpeed Insights:** Lighthouse laboratory measurements and failed audits. Any returned CrUX field data is kept separate from lab results.
- **Application history:** Immutable collection snapshots and saved reviews, with comparison state for tracking changes.

Google Search Console and private analytics data are not used. The reviewer does not measure actual search rankings or organic traffic; Lighthouse scores describe technical checks and synthetic performance measurements.

## Run locally

Requires **Python 3.13+** and **uv**. From the repository root:

```sh
uv sync --locked
cp .env.example .env
```

Edit `.env` with the credentials you want to use. It is ignored by Git and loaded only when explicitly passed with `--env-file`.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for AI explanations; collection and fallback reviews work without it. |
| `OPENAI_MODEL` | Model selection; defaults to `gpt-6.1-terra`. |
| `PAGESPEED_API_KEY` | Optional PageSpeed key; without one, requests use Google's unauthenticated access where available. |
| `PAGESPEED_ENABLED` | Defaults to `true`; set to `false` to skip performance measurements. |

The remaining defaults are in [`.env.example`](.env.example) and [`seo_reviewer/config.py`](seo_reviewer/config.py). PageSpeed checks up to three successfully collected pages on mobile and desktop by default. The crawler's initial page selection follows Django's weblog structure; changing `SITE_URL` alone does not make it suitable for any website.

Collect data and generate a review:

```sh
uv run --env-file .env python -m seo_reviewer run --review
```

The command prints the evidence path containing the run ID. To collect without AI, add `--skip-ai`. To collect first and generate a review separately:

```sh
uv run --env-file .env python -m seo_reviewer run
# Replace RUN_ID with the ID printed in the collection evidence path.
uv run --env-file .env python -m seo_reviewer review --run-id RUN_ID
```

Build and preview reports from saved reviews, without collecting again or calling the model:

```sh
uv run python -m seo_reviewer.render --base-path ''
uv run python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. Collection evidence lives in `data/runs/`, reviews in `data/reviews/`, and generated reports in `site/`. Saved reviews are reused on ordinary retries.

Run the mocked test suite with `uv run pytest`; it requires no API key or network access.

## Automation and delivery

[`.github/workflows/collect.yml`](.github/workflows/collect.yml) runs daily at **09:17 Asia/Yerevan** (`17 5 * * *` UTC) on the default branch. GitHub may delay scheduled runs. For a manual run, open **Actions → Collect SEO observations → Run workflow** and select the default branch.

The workflow commits collection evidence, reviews, and comparison state before building and deploying the GitHub Pages site. It then posts a daily summary and report link to the **Daily SEO reviews** Issue; subscribe to that Issue for notifications.

Configure deployment in repository **Settings → Pages**, using **GitHub Actions** as the source. The `github-pages` environment must permit the default branch, Issues must be enabled, and the workflow must be allowed to commit evidence to that branch.

Manage credentials under **Settings → Secrets and variables → Actions**:

- **Secrets:** `OPENAI_API_KEY` for AI reviews and optional `PAGESPEED_API_KEY`.
- **Variables:** optional `OPENAI_MODEL`, `PAGESPEED_ENABLED`, `PAGESPEED_STRATEGIES`, and `PAGESPEED_MAX_PAGES`.

## Limitations

- Coverage is a selected set of pages: a fixed initial cohort of 50, plus up to 50 newly discovered sitemap URLs per run. It is not a full-site audit.
- Lighthouse lab measurements vary between runs; changes are investigation signals rather than proof of real-user impact.
- API availability, quotas, and timeouts can leave optional performance checks unavailable. Missing checks do not prove that an issue is resolved.
- Private Search Console and analytics data are unavailable, so reports cannot establish ranking or traffic effects.
- AI explanations are grounded in collected evidence but should be reviewed before making changes.
