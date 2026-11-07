"""Command-line entrypoint for the initial integration milestone."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from seo_reviewer.config import Config
from seo_reviewer.preflight import run_preflight
from seo_reviewer.storage import RunStore, publish_probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily SEO Reviewer")
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("preflight", help="Verify site and model access before implementing the crawler")
    probe.add_argument("--site-url", help="Exact site origin (default: https://www.djangoproject.com)")
    probe.add_argument("--data-dir", type=Path)
    probe.add_argument("--model", help="Override OPENAI_MODEL")
    probe.add_argument("--skip-model", action="store_true", help="Collect site evidence without a model call; exits 2 for incomplete gate")
    probe.add_argument("--publish-dir", type=Path, help="Export a JSON-only Pages smoke artifact")
    crawl = commands.add_parser("run", help="Collect the fixed cohort and new sitemap URLs")
    crawl.add_argument("--site-url")
    crawl.add_argument("--data-dir", type=Path)
    crawl.add_argument("--model")
    crawl.add_argument("--run-id-file", type=Path, help="Write current run identity for publication")
    crawl.add_argument("--review", action="store_true", help="Also generate an immutable review")
    crawl.add_argument("--skip-ai", action="store_true", help="Use deterministic fallback when generating a review")
    review = commands.add_parser("review", help="Create a bounded AI/deterministic review from saved evidence")
    review.add_argument("--run-id", required=True)
    review.add_argument("--data-dir", type=Path)
    review.add_argument("--model")
    review.add_argument("--skip-ai", action="store_true")
    review.add_argument("--refresh-ai", action="store_true", help="Save a new analysis revision from immutable evidence")
    review.set_defaults(site_url=None)
    args = parser.parse_args(argv)
    try:
        config = Config.from_env(site_url=args.site_url, data_dir=args.data_dir, model=args.model)
    except (ValidationError, ValueError):
        # Validation errors can include inputs. Do not echo configuration secrets.
        parser.error("Invalid configuration; check the origin, request interval, and paths")
    if args.command == "review":
        from seo_reviewer.review import generate_review
        try:
            if args.refresh_ai:
                if args.skip_ai:
                    raise ValueError('Cannot refresh AI with skip-ai')
                from seo_reviewer.review import reanalyse_review
                result, revision_path = reanalyse_review(config, args.run_id)
                print(f"Analysis revision: {revision_path}")
            else:
                result = generate_review(config, args.run_id, skip_ai=args.skip_ai)
        except (OSError, ValueError) as exc:
            print(f"Review failed ({type(exc).__name__})", file=sys.stderr)
            return 1
        print(f"SEO status: {result.alert_status}; narrative: {result.narrative_source}")
        print(f"Review: {config.data_dir / 'reviews' / (result.run_id + '.json')}")
        return 0
    if args.command == "run":
        from seo_reviewer.crawl import run_crawl
        try:
            result = run_crawl(config)
            if args.run_id_file:
                import json
                args.run_id_file.write_text(json.dumps({"run_id": result["run_id"]}) + "\n")
        except (OSError, ValueError) as exc:
            print(f"Collection stopped ({type(exc).__name__}): {exc}", file=sys.stderr)
            return 1
        print(f"{result['status']}: {result['coverage']}")
        print(f"SEO status: {result['detection']['alert_status']}; findings: {len(result['detection']['findings'])}")
        for url in result['deferred_urls']:
            print(f"Deferred: {url}")
        for error in result['errors']:
            print(f"Collection error: {error}")
        print(f"Evidence: {config.data_dir / 'runs' / result['run_id'] / 'collection.json'}")
        if args.review:
            from seo_reviewer.review import generate_review
            try:
                review = generate_review(config, result['run_id'], skip_ai=args.skip_ai)
            except (OSError, ValueError) as exc:
                print(f"Review persistence failed ({type(exc).__name__})", file=sys.stderr)
                return 1
            print(f"Review narrative: {review.narrative_source}; generation: {review.generation.reason}")
        return 0 if result['status'] == 'collected' else 1
    try:
        store = RunStore(config.data_dir)
        result = run_preflight(config, store, skip_model=args.skip_model)
        if args.publish_dir:
            publish_probe(result, args.publish_dir)
    except OSError as exc:
        print(f"Unable to write evidence ({type(exc).__name__})", file=sys.stderr)
        return 1
    for check in result.checks:
        print(f"{check.status.upper():7} {check.name}: {check.detail}")
    print(f"Evidence: {store.path / 'preflight.json'}")
    if any(check.status == "failed" for check in result.checks):
        return 1
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
