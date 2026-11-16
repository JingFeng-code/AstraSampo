"""Ollama Cloud 供應商：用 Ollama 官方雲端 API（需要 API Key）。

跟本機 `ollama.py` 的差別只有兩個：位址固定是 https://ollama.com，而且要帶
`Authorization: Bearer <key>`。請求格式（/api/chat、/api/tags）與本機版相同，
所以解析邏輯沿用同一套，避免兩份實作漂移。

金鑰只存在本機 settings.json；這條路徑會把逐字稿送到 Ollama 雲端，設定頁要講清楚。
"""
from __future__ import annotations

import json
import re

import httpx

from app.core import config, messages
from app.llm import ollama
from app.llm.base import ProviderError, TruncatedOutputError

BASE_URL = "https://ollama.com"
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)


def api_key() -> str:
    return (config.get("OLLAMA_CLOUD_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def _headers(key: str | None = None) -> dict[str, str]:
    token = (key or api_key()).strip()
    if not token:
        raise ProviderError(messages.t("provider.ollama_cloud_no_key"))
    return {"Authorization": f"Bearer {token}"}


def _verify_key(key: str) -> None:
    """用需要授權的端點確認這把金鑰真的有效。

    `/api/tags` 是公開端點：不帶金鑰或隨便一把無效金鑰都會回 200，所以拿它當
    「檢查連線」等於沒有檢查。`POST /api/me` 對無效金鑰回 401 invalid credentials。
    """
    with httpx.Client(timeout=httpx.Timeout(8.0), trust_env=False, follow_redirects=False) as client:
        response = client.post(BASE_URL + "/api/me", headers=_headers(key))
        if response.status_code in (401, 403):
            raise ProviderError(messages.t("provider.ollama_cloud_bad_key"))
        response.raise_for_status()


def list_models(key: str | None = None) -> list[str]:
    """列出這把金鑰真的看得到的雲端模型；格式與本機 /api/tags 相同。"""
    _verify_key(key)
    with httpx.Client(timeout=httpx.Timeout(8.0), trust_env=False, follow_redirects=False) as client:
        response = client.get(BASE_URL + "/api/tags", headers=_headers(key))
        if response.status_code == 401:
            raise ProviderError(messages.t("provider.ollama_cloud_bad_key"))
        response.raise_for_status()
        data = response.json()
    rows = data.get("models", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        raise ProviderError("Ollama Cloud 模型清單格式不正確。")
    names = []
    for item in rows:
        name = item.get("name") or item.get("model") if isinstance(item, dict) else None
        if isinstance(name, str) and _MODEL.fullmatch(name) and name not in names:
            names.append(name)
    return names


def connection_status(key: str | None = None) -> dict:
    try:
        models = list_models(key)
        return {"connected": True, "models": models,
                "message": messages.t("provider.ollama_cloud_connected", count=len(models))}
    except (httpx.HTTPError, ProviderError, ValueError, OSError) as exc:
        return {"connected": False, "models": [], "message": str(exc)}


def _check_truncated(done_reason: object, content: str, name: str) -> None:
    if done_reason != "length":
        return
    message = messages.t("provider.truncated", vendor="Ollama Cloud")
    if not content:
        raise ProviderError(message)
    raise TruncatedOutputError(message, partial=content, label=f"Ollama Cloud/{name}")


def generate_messages(messages_list: list[dict], system: str = "", model: str = "",
                      tries: int = 1, on_status=None) -> tuple[str, str]:
    name = (model or "").strip()
    if not name or not _MODEL.fullmatch(name):
        raise ProviderError(messages.t("provider.ollama_cloud_no_model"))
    payload_messages = ([{"role": "system", "content": system}] if system else []) + list(messages_list)
    payload = {"model": name, "messages": payload_messages, "stream": True,
               "think": False,
               "options": {"num_ctx": ollama.context_size(payload_messages)}}
    parts: list[str] = []
    finished = False
    done_reason = None
    try:
        with httpx.Client(timeout=_TIMEOUT, trust_env=False, follow_redirects=False) as client:
            with client.stream("POST", BASE_URL + "/api/chat", json=payload,
                               headers=_headers()) as response:
                if response.status_code == 401:
                    raise ProviderError(messages.t("provider.ollama_cloud_bad_key"))
                if response.status_code == 429:
                    raise ProviderError(messages.t("provider.ollama_cloud_rate_limited"))
                if response.status_code == 404:
                    raise ProviderError(messages.t("provider.ollama_cloud_model_missing", model=name))
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if not isinstance(chunk, dict):
                        raise ValueError("unexpected chunk")
                    if chunk.get("error"):
                        raise ProviderError(str(chunk["error"])[:200])
                    piece = (chunk.get("message") or {}).get("content", "")
                    if isinstance(piece, str):
                        parts.append(piece)
                    if chunk.get("done"):
                        finished = True
                        done_reason = chunk.get("done_reason")
                        break
    except ProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise ProviderError(messages.t("provider.ollama_cloud_timeout")) from exc
    except httpx.HTTPStatusError as exc:
        raise ProviderError(messages.t("provider.http_error", vendor="Ollama Cloud",
                                       status=exc.response.status_code)) from exc
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ProviderError(messages.t("provider.ollama_cloud_bad_response")) from exc
    if not finished:
        raise ProviderError(messages.t("provider.ollama_cloud_interrupted"))
    content = "".join(parts).strip()
    _check_truncated(done_reason, content, name)
    if not content:
        raise ProviderError(messages.t("provider.empty_answer", vendor="Ollama Cloud"))
    return content, f"Ollama Cloud/{name}"


def generate(prompt: str, system: str = "", model: str = "", seg: int = 0,
             on_status=None) -> tuple[str, str]:
    return generate_messages([{"role": "user", "content": prompt}], system, model,
                             on_status=on_status)
