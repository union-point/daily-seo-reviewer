import pytest
from pydantic import ValidationError

from seo_reviewer.config import Config, origin


@pytest.mark.parametrize("value", [
    "ftp://example.com", "https://u:password@example.com", "https://example.com/path",
    "https://example.com?query=1", "https://example.com/#fragment", "https://example.com:invalid",
    "https://example.com\\@evil.com", "https://example.com/ space",
])
def test_reject_invalid_origin(value):
    with pytest.raises(ValidationError):
        Config(site_url=value)


def test_origin_normalizes_host_but_preserves_scheme_and_port():
    assert origin("https://Example.COM:443/Page") == "https://example.com"
    assert origin("http://example.com:8080/") == "http://example.com:8080"


def test_config_reads_env_and_allows_cli_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SITE_URL", "https://example.com")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("SEO_DATA_DIR", str(tmp_path))
    config = Config.from_env(model="gpt-6.1-terra")
    assert config.site_url == "https://example.com"
    assert config.model == "gpt-6.1-terra"
    assert config.data_dir == tmp_path


def test_request_rate_cannot_exceed_one_request_per_second():
    with pytest.raises(ValidationError):
        Config(request_interval=0.1)
