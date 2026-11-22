"""Your own model server (OpenAI-compatible) as a model the app can call."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.ai import model_server as ms


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        want = self.server.key
        return not want or self.headers.get("Authorization") == f"Bearer {want}"

    def do_GET(self):
        if not self._authorized():
            return self._send(401, {"error": "bad key"})
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": "gpt-oss-120b"}, {"id": "qwen3-72b"}]})
        self._send(404, {"error": "nope"})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"error": "bad key"})
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "nope"})
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        last = body["messages"][-1]["content"]
        self._send(200, {"choices": [{"message": {
            "role": "assistant", "reasoning_content": "hmm, let me think",
            "content": f"<think>planning</think>echo: {last} [{body.get('model', '')}]"}}]})


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.requests, httpd.key = [], ""
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()


def url_of(server, suffix=""):
    return f"127.0.0.1:{server.server_address[1]}{suffix}"


@pytest.mark.parametrize("given,expected", [
    ("192.168.1.50:8080", "http://192.168.1.50:8080/v1"),
    ("http://minipc.local:11434/", "http://minipc.local:11434/v1"),
    ("https://box/v1/chat/completions", "https://box/v1"),
    ("http://box:8000/v1", "http://box:8000/v1"),
    ("", ""),
])
def test_normalize_url(given, expected):
    assert ms.normalize_url(given) == expected


def test_lists_models_and_chats(server):
    assert ms.list_models(url_of(server)) == ["gpt-oss-120b", "qwen3-72b"]
    text = ms.chat(url_of(server), "gpt-oss-120b",
                   [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
                   max_tokens=50, temperature=0.2)
    assert text == "echo: hi [gpt-oss-120b]"            # thinking left out
    sent = server.requests[-1]
    assert sent["max_tokens"] == 50 and sent["temperature"] == 0.2 and not sent["stream"]


def test_api_key_is_sent_and_checked(server):
    server.key = "secret"
    with pytest.raises(ms.ServerError, match="refused the API key"):
        ms.list_models(url_of(server))
    assert ms.list_models(url_of(server), "secret")


def test_connection_test_reports_plainly(server):
    ok, msg, models = ms.test_connection(url_of(server))
    assert ok and "gpt-oss-120b" in msg and models[0] == "gpt-oss-120b"
    ok, msg, _ = ms.test_connection("127.0.0.1:1")
    assert not ok and "Couldn't reach" in msg
    assert ms.test_connection("")[0] is False


@pytest.fixture
def settings(monkeypatch, server):
    """AI Settings pointing at the fake server (never the user's real file)."""
    import src.config.ai_config as ac
    cfg = ac.AIConfig.__new__(ac.AIConfig)
    cfg.settings = dict(ac.AIConfig.DEFAULT_SETTINGS, default_llm="server",
                        server_url=url_of(server), server_model="gpt-oss-120b")
    cfg.save_settings = lambda s: True
    monkeypatch.setattr(ac, "_ai_config", cfg)
    return cfg


def test_works_as_the_default_model(settings, server):
    from src.ai.llm_client import LLMProvider
    from src.ai.task_llm import build_default_llm
    assert settings.get_api_key("server") == ms.NO_KEY     # "has a key" checks pass
    assert settings.get_model("server") == "gpt-oss-120b"
    llm = build_default_llm()
    assert llm.provider == LLMProvider.SERVER
    assert llm.generate_text("hello", "sys") == "echo: hello [gpt-oss-120b]"
    assert server.requests[-1]["messages"][0] == {"role": "system", "content": "sys"}


def test_works_as_a_task_model(settings):
    from src.ai.task_llm import build_llm_from_spec
    from src.config.creativeos_config import parse_task_model_spec, TASK_CLOUD_PROVIDERS
    assert "server" in TASK_CLOUD_PROVIDERS
    assert parse_task_model_spec("cloud:server:qwen3-72b")["provider"] == "server"
    llm = build_llm_from_spec("cloud:server:qwen3-72b")
    assert llm.generate_text("x") == "echo: x [qwen3-72b]"


def test_large_server_model_gets_full_prompts(settings):
    from src.ai.chapter_analysis_agent import is_local_llm
    from src.ai.task_llm import build_default_llm
    assert not is_local_llm(build_default_llm())


def test_no_address_means_no_server(settings):
    settings.settings["server_url"] = ""
    assert settings.get_api_key("server") == ""
    from src.ai.task_llm import build_default_llm
    assert build_default_llm() is None


def test_server_error_reaches_the_caller_as_text(settings, server):
    from src.ai.task_llm import build_default_llm
    llm = build_default_llm()
    server.shutdown()
    server.server_close()
    assert llm.generate_text("hi").startswith("Error generating text:")
