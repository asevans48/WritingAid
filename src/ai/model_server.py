"""Your own model server: a machine on your network (or this one) that
serves a model over the OpenAI-compatible HTTP API.

llama.cpp (``llama-server``), vLLM, Ollama, LM Studio, text-generation-
webui, LocalAI and most other self-hosted servers speak this API, so one
connector covers them all. Settings hold the server's address, the model
name and an optional API key; the app then treats the server like any
other model (``default_llm = "server"`` or ``cloud:server`` for a task).

Plain ``urllib`` — no SDK — so nothing extra needs installing and the
reply can be read however the server shapes it.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Long: a 120B model on a small machine can take minutes for a long reply.
DEFAULT_TIMEOUT = 900
# Sent when no key is set: most self-hosted servers ignore the header, and
# callers that check "is there a key?" before building a client pass.
NO_KEY = "no-key-needed"

_THINK_RX = re.compile(r"<think>.*?</think>\s*", re.S | re.I)


class ServerError(RuntimeError):
    pass


def normalize_url(url: str) -> str:
    """``192.168.1.50:8080`` → ``http://192.168.1.50:8080/v1``."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    for suffix in ("/chat/completions", "/completions", "/models"):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
    if not re.search(r"/v\d+$", url):
        url += "/v1"
    return url


def _request(url: str, api_key: str = "", payload: Optional[Dict[str, Any]] = None,
             timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if api_key and api_key != NO_KEY:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code in (401, 403):
            raise ServerError("The server refused the API key.") from e
        if e.code == 404:
            raise ServerError(f"Nothing at {url} — check the address (it usually ends "
                              f"in /v1).") from e
        raise ServerError(f"Server error {e.code}: {body or e.reason}") from e
    except urllib.error.URLError as e:
        raise ServerError(f"Couldn't reach the server at {url}: {e.reason}") from e
    except TimeoutError as e:
        raise ServerError(f"The server didn't answer within {int(timeout)} seconds.") from e
    except json.JSONDecodeError as e:
        raise ServerError("The server's reply wasn't JSON — is this an OpenAI-compatible "
                          "endpoint?") from e


def list_models(url: str, api_key: str = "", timeout: float = 10) -> List[str]:
    """Model names the server offers (``GET /v1/models``)."""
    data = _request(normalize_url(url) + "/models", api_key, timeout=timeout)
    items = data.get("data") or data.get("models") or []
    out = []
    for m in items:
        name = m.get("id") or m.get("name") or m.get("model") if isinstance(m, dict) else m
        if name and name not in out:
            out.append(str(name))
    return out


def reply_text(data: Dict[str, Any]) -> str:
    """The answer from a chat-completions reply. Reasoning models' thinking
    (``reasoning_content`` or ``<think>`` blocks) is left out."""
    choices = data.get("choices") or []
    if not choices:
        raise ServerError("The server's reply had no answer in it.")
    first = choices[0] or {}
    msg = first.get("message") or {}
    text = msg.get("content")
    if isinstance(text, list):                      # content parts
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if text is None:
        text = first.get("text") or ""
    return _THINK_RX.sub("", text or "").strip()


def chat(url: str, model: str, messages: List[Dict[str, str]], *, api_key: str = "",
         max_tokens: int = 2048, temperature: float = 0.7,
         timeout: float = DEFAULT_TIMEOUT) -> str:
    payload: Dict[str, Any] = {"messages": messages, "max_tokens": max_tokens,
                               "temperature": temperature, "stream": False}
    if model:
        payload["model"] = model
    return reply_text(_request(normalize_url(url) + "/chat/completions", api_key, payload,
                               timeout=timeout))


def test_connection(url: str, api_key: str = "", model: str = "") -> Tuple[bool, str, List[str]]:
    """(ok, message, models). Lists the models, then asks the chosen one
    for a one-word reply."""
    if not (url or "").strip():
        return False, "Enter the server's address first.", []
    try:
        models = list_models(url, api_key)
    except ServerError as e:
        return False, str(e), []
    use = model or (models[0] if models else "")
    try:
        answer = chat(url, use, [{"role": "user", "content": "Reply with the word: ready"}],
                      api_key=api_key, max_tokens=16, temperature=0, timeout=120)
    except ServerError as e:
        return False, f"Found the server, but the model didn't answer: {e}", models
    shown = ", ".join(models[:5]) + ("…" if len(models) > 5 else "")
    return True, (f"Connected to {normalize_url(url)}. Model “{use or 'server default'}” "
                  f"answered: “{answer[:40]}”." + (f" Models: {shown}" if models else "")), models


def settings() -> Dict[str, str]:
    """url / model / api_key from AI Settings."""
    try:
        from src.config.ai_config import get_ai_config
        s = get_ai_config().get_settings()
    except Exception:
        s = {}
    return {"url": s.get("server_url", "") or "", "model": s.get("server_model", "") or "",
            "api_key": s.get("server_api_key", "") or ""}
