import json

from conftest import FakeSession, response
from seo_reviewer.__main__ import main
from test_preflight import ARTICLE, BLOG, HTML_HEADERS, SITEMAP


def test_complete_site_probe_persists_evidence_without_claiming_complete_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    session = FakeSession([
        response(404), response(body=SITEMAP),
        response(body=BLOG, **HTML_HEADERS), response(body=ARTICLE, **HTML_HEADERS),
    ])
    monkeypatch.setattr("seo_reviewer.collection.requests.Session", lambda: session)
    monkeypatch.setattr("seo_reviewer.collection.time.sleep", lambda _: None)
    code = main([
        "preflight", "--site-url", "https://example.com", "--data-dir", str(tmp_path / "data"),
        "--publish-dir", str(tmp_path / "site"),
    ])
    assert code == 2
    paths = list((tmp_path / "data/runs").glob("*/preflight.json"))
    assert len(paths) == 1
    result = json.loads(paths[0].read_text())
    assert result["kind"] == "integration-preflight"
    assert result["model"]["status"] == "skipped"
    assert len(result["fetches"]) == 4
    assert (tmp_path / "site/preflight.json").read_text() == paths[0].read_text()
    assert not (tmp_path / "data/latest.json").exists()


def test_collection_failure_is_written_and_returns_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    session = FakeSession([response(403)])
    monkeypatch.setattr("seo_reviewer.collection.requests.Session", lambda: session)
    assert main(["preflight", "--data-dir", str(tmp_path), "--skip-model"]) == 1
    result = json.loads(next(tmp_path.glob("runs/*/preflight.json")).read_text())
    assert result["checks"][0]["status"] == "failed"
