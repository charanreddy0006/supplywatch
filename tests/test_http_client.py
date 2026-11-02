from unittest.mock import Mock
import requests
import pytest
from ingestion.clients.http_client import HttpClient, HttpRequestError


def response(status=200, value=None):
    r = Mock()
    r.status_code, r.url, r.headers = status, "https://example.test", {}
    r.json.return_value = value if value is not None else {"ok": True}
    r.raise_for_status.side_effect = requests.HTTPError(f"{status}") if status >= 400 else None
    return r


def test_success_and_server_retry(monkeypatch):
    client = HttpClient(max_retries=1)
    client.session.get = Mock(side_effect=[response(500), response()])
    monkeypatch.setattr("ingestion.clients.http_client.time.sleep", lambda _: None)
    assert client.get_json("https://example.test") == {"ok": True}
    assert client.session.get.call_count == 2


@pytest.mark.parametrize("error", [requests.ConnectionError("offline"), requests.Timeout("slow")])
def test_connection_and_timeout_exhaustion(monkeypatch, error):
    client = HttpClient(max_retries=1)
    client.session.get = Mock(side_effect=error)
    monkeypatch.setattr("ingestion.clients.http_client.time.sleep", lambda _: None)
    with pytest.raises(HttpRequestError):
        client.get_json("https://example.test")
    assert client.session.get.call_count == 2


@pytest.mark.parametrize("status", [429, 500])
def test_retryable_status_exhaustion(monkeypatch, status):
    client = HttpClient(max_retries=1)
    client.session.get = Mock(return_value=response(status))
    monkeypatch.setattr("ingestion.clients.http_client.time.sleep", lambda _: None)
    with pytest.raises(HttpRequestError):
        client.get_json("https://example.test")
    assert client.session.get.call_count == 2


def test_permanent_error_not_retried():
    client = HttpClient(max_retries=3)
    client.session.get = Mock(return_value=response(404))
    with pytest.raises(HttpRequestError):
        client.get_json("https://example.test")
    assert client.session.get.call_count == 1
