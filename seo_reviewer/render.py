"""Render saved reviews as safe, portable static HTML; never execute crawled content."""

import argparse
import hashlib
import json
import math
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from seo_reviewer.detection import RANK
from seo_reviewer.report_content import issue_presentation, report_presentation
from seo_reviewer.review_models import Review

TEMPLATES = Path(__file__).with_name('rendering')


def safe_url(value: str | None) -> str | None:
    if not value or any(ord(char) < 33 for char in value) or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        parsed.port
        return value
    except ValueError:
        return None


def base_path(value: str) -> str:
    if value in {'', '/'}:
        return ''
    if not re.fullmatch(r'/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?', value):
        raise ValueError('Base path must contain safe path segments, starting with /')
    return value.rstrip('/')


def display_time(value: str | datetime) -> str:
    date = datetime.fromisoformat(value) if isinstance(value, str) else value
    if date.tzinfo is None:
        raise ValueError('Report timestamps must include a timezone')
    return date.astimezone(ZoneInfo('Asia/Yerevan')).strftime('%d %b %Y, %H:%M Asia/Yerevan')


def load_reviews(data_dir: Path) -> list[tuple[Review, dict, bytes]]:
    rows = []
    for path in (data_dir / 'reviews').glob('*.json'):
        review = Review.model_validate_json(path.read_text())
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', review.run_id) or path.stem != review.run_id:
            raise ValueError('Invalid review filename/run ID')
        expected = f'runs/{review.run_id}/collection.json'
        if review.collection_path != expected:
            raise ValueError('Unexpected collection evidence path')
        raw = (data_dir / expected).read_bytes()
        if hashlib.sha256(raw).hexdigest() != review.collection_sha256:
            raise ValueError('Collection evidence digest mismatch')
        collection = json.loads(raw)
        if collection['run_id'] != review.run_id:
            raise ValueError('Collection/run identity mismatch')
        rows.append((review, collection, raw))
    return sorted(rows, key=lambda row: (datetime.fromisoformat(row[1]['completed_at']), row[0].run_id), reverse=True)


def render_site(data_dir: Path, output_dir: Path, *, base: str = '', now: datetime | None = None, repository_url: str = 'https://github.com/union-point/daily-seo-reviewer', workflow_url: str | None = None, require_run_id: str | None = None) -> dict:
    base = base_path(base)
    now = now or datetime.now(UTC)
    # Generated output must never replace evidence, source, or arbitrary existing directories.
    destination = output_dir.resolve()
    evidence = data_dir.resolve()
    if destination == evidence or destination in evidence.parents or evidence in destination.parents:
        raise ValueError('Output directory must be separate from evidence')
    legacy_smoke = (
        output_dir.is_dir()
        and {item.name for item in output_dir.iterdir()} <= {'preflight.json', 'index.txt', '.nojekyll'}
        and (output_dir / 'index.txt').is_file()
        and (output_dir / 'index.txt').read_text().startswith('Daily SEO Reviewer integration preflight.')
    )
    if output_dir.exists() and any(output_dir.iterdir()) and not (output_dir / '.seo-site').exists() and not legacy_smoke:
        raise ValueError('Refusing to replace an output directory not owned by this renderer')
    rows = load_reviews(data_dir)
    if require_run_id is not None and require_run_id not in {row[0].run_id for row in rows}:
        raise ValueError('Current collection has no saved review; refusing stale publication')
    def link(path: str) -> str:
        return base + '/' + path
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(['html']), undefined=StrictUndefined)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Clean only files from a previously generated tree, leaving source/evidence untouched.
    if (output_dir / '.seo-site').exists():
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    (output_dir / '.seo-site').touch()
    (output_dir / '.nojekyll').touch()
    (output_dir / 'assets').mkdir()
    shutil.copyfile(TEMPLATES / 'styles.css', output_dir / 'assets/styles.css')
    (output_dir / 'reviews').mkdir()
    (output_dir / 'archive').mkdir()
    history = [
        {'date': display_time(collection['completed_at']),
         'status_label': presentation['status_label'], 'status_tone': presentation['status_tone'],
         'coverage': presentation['coverage_text'], 'href': link(f'reviews/{review.run_id}.html')}
        for review, collection, _ in rows
        for presentation in [report_presentation(review, collection)]
    ]
    for review, collection, raw in rows:
        report_dir = output_dir / 'data/reviews'
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / f'{review.run_id}.json').write_text(review.model_dump_json(indent=2) + '\n')
        collection_dir = output_dir / 'data/runs' / review.run_id
        collection_dir.mkdir(parents=True, exist_ok=True)
        (collection_dir / 'collection.json').write_bytes(raw)
        prose = {item.finding_id: item for item in [*review.narrative.prioritized_issues, *review.narrative.verification_items]}
        ranking = {item.finding_id: index for index, item in enumerate(review.narrative.prioritized_issues)}
        sections = []
        for title, allowed in [('Priority issues', {'new', 'ongoing', 'worsened'}), ('Needs verification', {'unverified'}), ('Resolved issues', {'resolved'})]:
            findings = sorted((finding for finding in review.findings if finding.state in allowed), key=lambda finding: (ranking.get(finding.id, 99), -RANK[finding.severity], finding.rule, finding.id))
            items = []
            for finding in findings:
                explanation = prose.get(finding.id) if review.narrative_source == 'ai' else None
                refs = []
                for record in finding.evidence:
                    run_id = record.get('run_id', '')
                    href = None
                    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id):
                        # Every run pointer opens its JSON record, never a raw HTML response.
                        if (data_dir / 'runs' / run_id / 'collection.json').is_file():
                            target = output_dir / 'data/runs' / run_id
                            target.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(data_dir / 'runs' / run_id / 'collection.json', target / 'collection.json')
                            href = link(f'data/runs/{run_id}/collection.json')
                    refs.append({'label': 'Saved page check' if len(finding.evidence) == 1 else f'Saved page check {len(refs) + 1}', 'href': href})
                item = {
                    **issue_presentation(finding), 'finding': finding,
                    'explanation': explanation.explanation if explanation and finding.state not in {'resolved', 'unverified'} else '',
                    'evidence': refs,
                    'urls': [{'label': url, 'href': safe_url(url)} for url in dict.fromkeys([*finding.urls, *finding.related_urls])],
                    'raw_before': json.dumps(finding.before, ensure_ascii=False), 'raw_observed': json.dumps(finding.observed, ensure_ascii=False),
                }
                if explanation and finding.state not in {'resolved', 'unverified'}:
                    item['action'] = explanation.recommended_action
                items.append(item)
            sections.append({'title': title, 'items': items})
        collected = datetime.fromisoformat(collection['completed_at'])
        freshness = 'Check is over 36 hours old. Run a new check before relying on this report.' if now - collected > timedelta(hours=36) else 'Check was less than 36 hours old when published.'
        context = {
            'page_title': 'Daily SEO review', 'base': base, 'report': review, 'collection': collection,
            'collected_at': display_time(collected), 'published_at': display_time(now), 'freshness': freshness,
            'baseline': review.baseline_only, 'sections': sections, 'history': history[:5],
            'presentation': report_presentation(review, collection),
            'action_plan': [
                {**item, 'anchor': f'issue-{section_index}-{item_index}'}
                for section_index, section in enumerate(sections, 1)
                if section['title'] != 'Resolved issues'
                for item_index, item in enumerate(section['items'], 1)
            ],
            'archive_href': link('archive/index.html'), 'review_json_href': link(f'data/reviews/{review.run_id}.json'),
            'collection_json_href': link(f'data/runs/{review.run_id}/collection.json'),
            'workflow_href': safe_url(workflow_url) if require_run_id == review.run_id else None,
            'repository_href': safe_url(repository_url),
        }
        rendered = env.get_template('report.html').render(**context)
        (output_dir / 'reviews' / f'{review.run_id}.html').write_text(rendered, encoding='utf-8')
        if review == rows[0][0]:
            (output_dir / 'index.html').write_text(rendered, encoding='utf-8')
    page_count = max(1, math.ceil(len(history) / 30))
    for page in range(1, page_count + 1):
        def archive_link(number: int) -> str:
            return link('archive/index.html' if number == 1 else f'archive/page-{number}.html')
        rendered = env.get_template('archive.html').render(
            page_title='Review archive', base=base, archive_href=link('archive/index.html'),
            entries=history[(page - 1) * 30:page * 30], page_number=page, page_count=page_count,
            previous_href=archive_link(page - 1) if page > 1 else None,
            next_href=archive_link(page + 1) if page < page_count else None, total_reviews=len(history),
        )
        (output_dir / 'archive' / ('index.html' if page == 1 else f'page-{page}.html')).write_text(rendered, encoding='utf-8')
        if not rows:
            (output_dir / 'index.html').write_text(rendered, encoding='utf-8')
    return {'review_count': len(rows), 'latest_run_id': rows[0][0].run_id if rows else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build static HTML reviews from saved evidence')
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--output-dir', type=Path, default=Path('site'))
    parser.add_argument('--base-path', default='')
    parser.add_argument('--run-id-file', type=Path)
    parser.add_argument('--delivery-dir', type=Path)
    parser.add_argument('--workflow-url')
    args = parser.parse_args(argv)
    try:
        run_id = json.loads(args.run_id_file.read_text())['run_id'] if args.run_id_file else None
        result = render_site(args.data_dir, args.output_dir, base=args.base_path, workflow_url=args.workflow_url, require_run_id=run_id)
        if args.delivery_dir:
            if not run_id:
                raise ValueError('Delivery requires the current run manifest')
            args.delivery_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.data_dir / 'reviews' / f'{run_id}.json', args.delivery_dir / 'review.json')
        print(f"Rendered {result['review_count']} reviews; latest: {result['latest_run_id']}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'Report build failed ({type(exc).__name__}): {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
