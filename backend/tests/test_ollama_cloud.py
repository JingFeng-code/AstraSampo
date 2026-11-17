"""Ollama Cloud：路由分派與沒有金鑰時的錯誤訊息。"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import ollama_cloud, router
from app.llm.base import ProviderError


def test_router_dispatches_ollama_cloud_model():
    with patch.object(router.ollama_cloud, "generate", return_value=("答案", "Ollama Cloud/kimi-k3")) as gen:
        text, label = router.generate("ollama-cloud:kimi-k3", "問題", "系統")
    assert text == "答案"
    assert label == "Ollama Cloud/kimi-k3"
    gen.assert_called_once()


def test_missing_key_is_reported():
    with patch.object(ollama_cloud, "api_key", return_value=""):
        try:
            ollama_cloud.generate_messages([{"role": "user", "content": "hi"}], "sys", "kimi-k3")
            assert False, "missing key must fail"
        except ProviderError as exc:
            assert "Ollama Cloud" in str(exc)


def test_model_list_parses_tags_shape():
    class Resp:
        status_code = 200
        def raise_for_status(self): return None
        def json(self):
            return {"models": [{"name": "kimi-k3:cloud"}, {"name": "gpt-oss:120b"}]}

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None):
            # 金鑰驗證一定要打需要授權的端點（GET /api/tags 對任何金鑰都回 200）
            assert url == "https://ollama.com/api/me", url
            assert headers and headers["Authorization"].startswith("Bearer ")
            return Resp()
        def get(self, url, headers=None):
            assert headers and headers["Authorization"].startswith("Bearer ")
            return Resp()

    with patch.object(ollama_cloud.httpx, "Client", Client):
        models = ollama_cloud.list_models("key123")
    assert models == ["kimi-k3:cloud", "gpt-oss:120b"]


def test_invalid_key_fails_connection_check():
    """錯的金鑰必須讓「檢查連線」失敗，不能因為 /api/tags 是公開端點就放行。"""
    class Resp401:
        status_code = 401
        def raise_for_status(self):
            raise AssertionError("401 要在呼叫 raise_for_status 之前就處理掉")
        def json(self):
            return {"error": "invalid credentials"}

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None):
            return Resp401()
        def get(self, url, headers=None):
            raise AssertionError("金鑰無效時不該再去抓模型清單")

    with patch.object(ollama_cloud.httpx, "Client", Client):
        status = ollama_cloud.connection_status("definitely-not-a-key")
    assert status["connected"] is False, status


if __name__ == "__main__":
    test_router_dispatches_ollama_cloud_model()
    test_missing_key_is_reported()
    test_model_list_parses_tags_shape()
    test_invalid_key_fails_connection_check()
    print("Ollama Cloud tests passed")
