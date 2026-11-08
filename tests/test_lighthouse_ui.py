"""Compact report comparisons use saved values, not generated sample measurements."""

from lxml import html

from seo_reviewer.render import pagespeed_presentation, render_site
from test_render import pagespeed_observation, save_review


def report(tmp_path, observations):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': observations}})
    render_site(data, output)
    return html.fromstring((output / 'index.html').read_text()).xpath('//section[@aria-labelledby="performance-heading"]')[0]


def test_metric_matrix_formats_saved_lab_values_with_adjacent_strategies(tmp_path):
    section = report(tmp_path, [pagespeed_observation(metrics={'lcp_ms': 3172.8, 'cls': 0.001898, 'fcp_ms': 1654, 'tbt_ms': 0, 'speed_index_ms': 1654}, performance_score=93.2),
        pagespeed_observation(strategy='desktop', metrics={'lcp_ms': 685.7, 'cls': 0.001769, 'fcp_ms': 443.7, 'tbt_ms': 0, 'speed_index_ms': 443.7}, performance_score=99.8)])
    table = section.xpath('.//table')[0]
    assert table.xpath('.//thead/tr/th/text()') == ['Metric', 'Mobile', 'Desktop']
    rows = {row.xpath('./th')[0].text: row.xpath('./td/text()') for row in table.xpath('./tbody/tr')}
    assert rows['Performance'] == ['93 / 100', '100 / 100']
    assert rows['LCP'] == ['3.17 s', '0.69 s']
    assert rows['CLS'] == ['0.002', '0.002']
    assert rows['TBT'] == ['0 ms', '0 ms']
    assert len(table.xpath('.//tr[@class="pagespeed-score"]')) == 2
    link = section.xpath('./div[@class="check-results"]/h3/a')[0]
    assert link.text == 'Homepage — /' and link.get('href') == 'https://example.com/'
    assert section.xpath('./details')


def test_partial_strategy_labels_missing_data_once_and_omits_empty_metric_rows(tmp_path):
    section = report(tmp_path, [pagespeed_observation(metrics={'lcp_ms': 2100}),
        pagespeed_observation(strategy='desktop', status='unavailable', error='Timeout')])
    table = section.xpath('.//table')[0]
    assert table.xpath('.//thead/tr/th[3]/span/text()') == ['Not measured']
    assert table.xpath('.//tbody/tr/th/text()') == ['Performance', 'SEO', 'LCP']
    assert table.xpath('.//tbody/tr/td[2]/text()') == ['—', '—', '—']
    assert '— means not recorded' in table.text_content()
    assert 'Unavailable' not in table.text_content()
    assert len(section.xpath('./p[contains(@class,"notice")]')) == 1


def test_short_path_label_retains_full_url_in_details_and_safe_link(tmp_path):
    url = 'https://example.com/' + 'segment/' * 8 + 'specific-article/'
    section = report(tmp_path, [pagespeed_observation(url=url)])
    link = section.xpath('./div[@class="check-results"]/h3/a')[0]
    assert len(link.text) <= 64 and link.get('href') == url
    assert url in section.xpath('./details')[0].text_content()


def test_all_failed_has_no_metric_matrix_or_empty_comparison(tmp_path):
    section = report(tmp_path, [pagespeed_observation(status='unavailable', error='http_429', http_status=429), pagespeed_observation(strategy='desktop', status='unavailable', error='quota_deferred')])
    assert not section.xpath('.//table')
    assert '0 of 2' in section.text_content() and 'HTTP 429' in section.text_content()
    assert 'No comparable' not in section.text_content() and 'LCP' not in section.text_content()


def test_zero_values_remain_measurements_and_single_configured_strategy_is_not_fabricated():
    data = {'pagespeed': {'enabled': True, 'observations': [pagespeed_observation(performance_score=0, seo_score=0, metrics={'cls': 0, 'tbt_ms': 0})]}}
    page = pagespeed_presentation(data)['pages'][0]
    assert [column['strategy'] for column in page['columns']] == ['Mobile']
    values = {metric['label']: metric['values'] for metric in page['measurements']}
    assert values == {'Performance': ['0 / 100'], 'SEO': ['0 / 100'], 'CLS': ['0.000'], 'TBT': ['0 ms']}
