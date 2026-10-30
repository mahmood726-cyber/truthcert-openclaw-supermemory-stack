"""Network exposure regressions for the TruthCert API process.

The API must bind only to loopback unless its operator explicitly chooses
another interface. The tests never open a socket.
"""

import uvicorn

from certifier.constants import DEFAULT_HOST, DEFAULT_PORT, ENV_HOST, ENV_PORT
from certifier.main import run_server


def test_api_listener_defaults_to_loopback(monkeypatch):
    """No configuration means no accidental external network listener."""
    monkeypatch.delenv(ENV_HOST, raising=False)
    monkeypatch.delenv(ENV_PORT, raising=False)
    calls = []

    def capture_run(app, *, host, port):
        calls.append((app, host, port))

    monkeypatch.setattr(uvicorn, "run", capture_run)
    run_server()

    assert DEFAULT_HOST == "127.0.0.1"
    assert len(calls) == 1
    assert calls[0][1:] == ("127.0.0.1", DEFAULT_PORT)


def test_api_listener_external_binding_requires_explicit_host(monkeypatch):
    """An intentional deployment override remains possible and observable."""
    monkeypatch.setenv(ENV_HOST, "0.0.0.0")
    monkeypatch.setenv(ENV_PORT, "8765")
    calls = []

    def capture_run(app, *, host, port):
        calls.append((app, host, port))

    monkeypatch.setattr(uvicorn, "run", capture_run)
    run_server()

    assert len(calls) == 1
    assert calls[0][1:] == ("0.0.0.0", 8765)
