"""摘要保底：模型沒有給卡片時，至少要用逐字稿產出一張卡（短片最常遇到）。"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import summarize
from app.models.schemas import SummarizeRequest

TEXT = "\n".join(f"[{i * 5}] 第 {i} 句內容" for i in range(1, 9))
EMPTY = {"title": "短片", "cards": [], "content_type": "other"}
MODEL = "Ollama/mimo-v2.6:latest"


def _content():
    return {"type": "bilibili", "video_id": "BV1B7411m7LV", "title": None, "text": TEXT,
            "is_chinese": True, "has_timestamps": True, "bilibili_page": 1,
            "transcript_source": "local_speech"}


def _req():
    return SummarizeRequest(url="https://www.bilibili.com/video/BV1B7411m7LV/",
                            provider="ollama:mimo-v2.6:latest")


def _patches():
    return (
        patch.object(summarize, "route_content", return_value=_content()),
        patch.object(summarize, "chunk_content", return_value=[TEXT]),
        patch.object(summarize, "_run_segment", return_value=(EMPTY, MODEL)),
    )


def _drain(response):
    """把 StreamingResponse 的 generator 跑完（測試不經過 ASGI）。"""
    async def collect():
        out = []
        async for chunk in response.body_iterator:
            out.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
        return out

    return asyncio.run(collect())


def test_fallback_card_is_built_from_transcript():
    card = summarize._fallback_card(TEXT, "zh-Hant")
    assert card["heading"]
    assert "第 1 句內容" in card["summary"]
    assert card["fallback"] is True
    assert card["actionable"] is False


def test_plain_summary_falls_back_when_model_returns_no_cards():
    route, chunk, segment = _patches()
    with route, chunk, segment:
        result = summarize.summarize(_req())
    assert len(result["cards"]) == 1
    assert result["cards"][0]["fallback"] is True
    assert "第 1 句內容" in result["cards"][0]["summary"]


def test_overview_uses_model_output():
    raw = '{"summary": "這支影片談 AI 程式碼審核。", "points": ["PR 前先確保可執行", "CI 自動檢查"]}'
    with patch.object(summarize.llm_router, "generate", return_value=(raw, "Ollama/test")):
        view = summarize._build_overview([{"heading": "測試", "summary": "內容"}], "標題", "zh-Hant", "ollama:test")
    assert view["summary"] == "這支影片談 AI 程式碼審核。"
    assert view["points"] == ["PR 前先確保可執行", "CI 自動檢查"]


def test_overview_falls_back_to_card_headings():
    with patch.object(summarize.llm_router, "generate", side_effect=RuntimeError("model down")):
        view = summarize._build_overview([{"heading": "一", "summary": ""}, {"heading": "二", "summary": ""}],
                                         None, "zh-Hant", "ollama:test")
    assert view["points"] == ["一", "二"]
    assert view["summary"] == ""


def test_stream_emits_fallback_cards_event():
    route, chunk, segment = _patches()
    with route, chunk, segment:
        raw = b"".join(_drain(summarize.summarize_stream(_req())))
    events = [line for line in raw.decode("utf-8").splitlines() if '"cards"' in line]
    assert events, raw.decode("utf-8")
    assert "fallback" in events[-1], events[-1]


if __name__ == "__main__":
    test_fallback_card_is_built_from_transcript()
    test_plain_summary_falls_back_when_model_returns_no_cards()
    test_overview_uses_model_output()
    test_overview_falls_back_to_card_headings()
    test_stream_emits_fallback_cards_event()
    print("Summarize fallback tests passed")
