import urllib.error

from dpp import sync
from dpp.sync import Server


def _server_whose_uploads(monkeypatch, outcomes):
    """A Server whose upload requests raise or succeed according to outcomes, without waiting between retries."""
    monkeypatch.setattr(sync, "RETRY_SECONDS", 0.01)
    server = Server("http://unused.invalid", "test")
    statuses = []

    def request(method, path, body=None):
        statuses.append(server.sync_status)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return b"{}"

    monkeypatch.setattr(server, "_request", request)
    return server, statuses


def test_unreachable_server_is_retried_until_the_upload_gets_through(monkeypatch):
    unavailable = urllib.error.HTTPError("http://unused.invalid", 503, "Service Unavailable", None, None)
    server, statuses = _server_whose_uploads(monkeypatch, [ConnectionRefusedError(), unavailable, None])
    server.upload("1" * 32, {"frame": 1}, b"state")
    assert server.flush(5)
    assert statuses == ["ok", "retrying", "retrying"]
    assert server.sync_status == "ok"


def test_refused_upload_stops_syncing(monkeypatch):
    forbidden = urllib.error.HTTPError("http://unused.invalid", 403, "Forbidden", None, None)
    server, statuses = _server_whose_uploads(monkeypatch, [forbidden])
    server.upload("1" * 32, {"frame": 1}, b"state")
    server.upload("2" * 32, {"frame": 2}, b"state")
    assert not server.flush(5)
    assert server.sync_status == "refused"
    assert len(statuses) == 1, "nothing is sent after a refusal"
