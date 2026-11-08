from test_review import collection

from seo_reviewer.detection import Finding
from seo_reviewer.issue_groups import canonical_issue_id, group_issues
from seo_reviewer.config import Config
from seo_reviewer.triage import build_triage_input


def finding(rule, id, **updates):
    values = dict(id=id, rule=rule, urls=['https://example.com/'], severity='warning', first_seen_run='new', last_seen_run='new', state='new', baseline_issue=True)
    values.update(updates)
    return Finding(**values)


def test_equivalent_sources_share_identity_but_not_raw_ids():
    crawler = finding('missing_description', 'crawl', state='ongoing', first_seen_run='old')
    mobile = finding('lighthouse_seo:meta-description', 'mobile', observed={'strategy': 'mobile'})
    desktop = finding('lighthouse_seo:meta-description', 'desktop', observed={'strategy': 'desktop'})
    before = [item.model_dump() for item in [crawler, mobile, desktop]]
    groups = group_issues([crawler, mobile, desktop])
    assert len(groups) == 1 and len(groups[0].members) == 3
    assert groups[0].representative.id == 'crawl' and groups[0].history == 'previously_detected'
    assert canonical_issue_id(crawler) == canonical_issue_id(mobile)
    assert before == [item.model_dump() for item in [crawler, mobile, desktop]]


def test_distinct_issues_pages_and_performance_devices_stay_separate():
    items = [finding('missing_description','a'), finding('lighthouse_seo:link-text','b'),
        finding('pagespeed_performance','c', observed={'strategy':'mobile'}),
        finding('pagespeed_performance','d', observed={'strategy':'desktop'}),
        finding('missing_description','e', urls=['https://example.com/other'])]
    assert len(group_issues(items)) == 5


def test_first_lighthouse_measurement_history_is_unknown_not_previously_present():
    group = group_issues([finding('lighthouse_seo:link-text','mobile'), finding('lighthouse_seo:link-text','desktop')])[0]
    assert group.history == 'not_comparable' and len(group.members) == 2
    regression = group_issues([finding('lighthouse_seo:link-text','regression', regression=True)])[0]
    assert regression.history == 'confirmed_regression'
    resolved = group_issues([finding('lighthouse_seo:link-text','resolved', state='resolved')])[0]
    assert resolved.history == 'resolved'
    assert len(group_issues([finding('missing_description','a'), finding('lighthouse_seo:meta-description','b', state='resolved')])) == 2


def test_ai_receives_distinct_counts_and_explicit_history(collection):
    config, data, _ = collection
    items = [finding('missing_description','crawler', state='ongoing', first_seen_run='old'),
        finding('lighthouse_seo:meta-description','description'), finding('lighthouse_seo:link-text','link')]
    result = build_triage_input(config, data, items)
    assert result['distinct_actionable_issues'] == 2 and result['source_findings'] == 3
    assert result['historical_counts'] == {'previously_detected': 1, 'not_comparable': 1}
    assert result['new_regressions'] == 0
    assert len(next(row for row in result['findings'] if row['id'] == 'crawler')['supporting_checks']) == 2


def test_render_associates_duplicate_evidence_preserves_cards_and_counts(tmp_path):
    from test_render import save_review
    from seo_reviewer.review_models import AIItem
    from seo_reviewer.render import render_site
    from lxml import html
    crawler = finding('missing_description', 'crawler', state='ongoing')
    mobile = finding('lighthouse_seo:meta-description', 'mobile', observed={'strategy':'mobile'})
    desktop = finding('lighthouse_seo:meta-description', 'desktop', observed={'strategy':'desktop'})
    distinct = finding('lighthouse_seo:link-text', 'distinct')
    data, output = tmp_path/'data', tmp_path/'site'
    review = save_review(data, source='ai', findings=[crawler,mobile,desktop,distinct])
    review.narrative.prioritized_issues=[AIItem(finding_id='crawler', evidence_ids=['crawler:finding'], title='SENTINEL title', explanation='SENTINEL explanation', recommended_action='SENTINEL action', completion_criterion='SENTINEL done')]
    (data/'reviews/run-1.json').write_text(review.model_dump_json())
    render_site(data,output)
    tree=html.fromstring((output/'index.html').read_text())
    assert len(tree.xpath('//article'))==1
    article=tree.xpath('//article')[0]
    assert '2 supporting checks' in article.text_content()
    for value in ['SENTINEL title','SENTINEL explanation','SENTINEL action','SENTINEL done','Mobile','Desktop']:
        assert value in article.text_content()
    section=tree.xpath('//section[@aria-labelledby="additional-findings-heading"]')[0]
    assert '1 additional observation' in section.text_content()
    assert 'lighthouse_seo:link-text' in section.text_content()
    assert 'meta-description' not in section.text_content()
    assert 'no saved issue narrative' not in tree.text_content()
    assert len(review.findings)==4


def test_persistent_crawler_issue_is_not_new_when_lighthouse_adds_evidence():
    crawler=finding('missing_description','crawl',state='ongoing',first_seen_run='old')
    lighthouse=finding('lighthouse_seo:meta-description','lh',regression=True)
    group=group_issues([crawler,lighthouse])[0]
    assert group.history=='previously_detected'
    ongoing=finding('lighthouse_seo:link-text','old-regression',state='ongoing',regression=True)
    assert group_issues([ongoing])[0].history=='previously_detected'


def test_existing_device_history_anchors_first_measurement_on_another_device(collection):
    config,data,_ = collection
    mobile=finding('lighthouse_seo:link-text','mobile',observed={'strategy':'mobile'})
    desktop=finding('lighthouse_seo:link-text','desktop',state='ongoing',observed={'strategy':'desktop'})
    group=group_issues([mobile,desktop])[0]
    assert group.history=='previously_detected' and group.state=='ongoing'
    payload=build_triage_input(config,data,[mobile,desktop])
    assert payload['lifecycle_counts']=={'ongoing':1}
    assert payload['issue_groups'][0]['ongoing_issues']==1
    assert payload['findings'][0]['state']=='ongoing'
    assert payload['findings'][0]['supporting_checks'][0]['state']=='new'
    assert mobile.state=='new' and desktop.state=='ongoing'


def test_new_device_regression_does_not_make_existing_cross_device_issue_new():
    mobile=finding('lighthouse_seo:link-text','mobile',regression=True,observed={'strategy':'mobile'})
    desktop=finding('lighthouse_seo:link-text','desktop',state='ongoing',observed={'strategy':'desktop'})
    assert group_issues([mobile,desktop])[0].history=='previously_detected'
    assert group_issues([mobile,desktop])[0].state=='ongoing'
    assert mobile.regression  # original per-device regression is retained as evidence
