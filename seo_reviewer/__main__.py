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
    crawl.set_defaults(model=None)
    args = parser.parse_args(argv)
    try:
        config = Config.from_env(site_url=args.site_url, data_dir=args.data_dir, model=args.model)
    except (ValidationError, ValueError):
        # Validation errors can include inputs. Do not echo configuration secrets.
        parser.error("Invalid configuration; check the origin, request interval, and paths")
    if args.command == "run":
        from seo_reviewer.crawl import run_crawl
        try:
            result = run_crawl(config)
        except (OSError, ValueError) as exc:
            print(f"Collection stopped ({type(exc).__name__}): {exc}", file=sys.stderr)
            return 1
        print(f"{result['status']}: {result['coverage']}")
        for url in result['deferred_urls']:
            print(f"Deferred: {url}")
        for error in result['errors']:
            print(f"Collection error: {error}")
        print(f"Evidence: {config.data_dir / 'runs' / result['run_id'] / 'collection.json'}")
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
