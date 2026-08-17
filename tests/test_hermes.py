from adags.hermes_backend import DEFAULT_MODEL, hermes_mode, proxy_listening, resolve_model


def test_adags_pins_nemotron_not_hermes_yaml(monkeypatch):
    monkeypatch.delenv("ADAGS_MODEL", raising=False)
    assert resolve_model() == DEFAULT_MODEL
    assert "nemotron" in DEFAULT_MODEL
    monkeypatch.setenv("ADAGS_MODEL", "nvidia/nemotron-3-ultra")
    assert resolve_model() == "nvidia/nemotron-3-ultra"


def test_hermes_mode_defaults_proxy(monkeypatch):
    monkeypatch.delenv("ADAGS_HERMES_MODE", raising=False)
    assert hermes_mode() == "proxy"


def test_proxy_listening_closed_port():
    assert proxy_listening("127.0.0.1", 1) is False
