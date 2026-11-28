"""Deterministic probe tests: no network, DNS, broker, or database required."""
from unittest.mock import patch

import httpx
import pytest

from main import probe

URL = "https://example.com/health"
REAL_CLIENT = httpx.Client


@pytest.mark.parametrize(
    "outcomes,retries,status,error,attempts",
    [
        ([200], 2, 200, None, 1),
        ([204], 0, 204, None, 1),
        ([500], 0, 500, "Unexpected HTTP status", 1),
        ([302], 0, 302, "Unexpected HTTP status", 1),
        (["timeout"], 0, None, "ReadTimeout", 1),
        (["connect"], 0, None, "ConnectError", 1),
        ([503, 200], 2, 200, None, 2),
        (["timeout", 200], 1, 200, None, 2),
        ([500, 503, 502], 2, 502, "Unexpected HTTP status", 3),
        ([500, "timeout"], 1, None, "ReadTimeout", 2),
    ],
)
def test_probe_outcomes(outcomes, retries, status, error, attempts):
    requests = []

    def handler(request):
        requests.append(request)
        outcome = outcomes[len(requests) - 1]
        if outcome == "timeout":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        if outcome == "connect":
            raise httpx.ConnectError("simulated failure", request=request)
        return httpx.Response(outcome, headers={"Location": URL})

    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    with (
        patch("main.validate_target") as validate,
        patch("main.httpx.Client", side_effect=client_factory),
        patch("main.time.sleep") as sleep,
    ):
        result = probe(URL, retries)

    assert result["status"] == status
    assert result["error"] == error
    assert result["latency_ms"] >= 0
    assert len(requests) == attempts
    assert validate.call_count == attempts
    assert sleep.call_count == attempts - 1
    assert all(r.method == "GET" and str(r.url) == URL for r in requests)


def test_rejected_target_never_opens_http_client():
    with (
        patch("main.validate_target", side_effect=ValueError),
        patch("main.httpx.Client") as client,
    ):
        result = probe(URL, 0)
    client.assert_not_called()
    assert result["status"] is None
    assert result["error"] == "ValueError"
