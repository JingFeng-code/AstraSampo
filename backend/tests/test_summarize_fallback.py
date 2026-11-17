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


# ── 全部段落失敗時，不能用保底卡蓋掉真正的錯誤 ──────────────────────────────

def _failing_segment(message="model down"):
    def fake(req, content, chunk, index, multi, on_status=None):
        raise Exception(message)  # noqa: BLE001 - 模擬模型呼叫失敗
    return fake


def test_plain_summary_all_failed_raises_instead_of_fallback():
    calls = []
    with patch.object(summarize, "route_content", return_value=_content()),             patch.object(summarize, "chunk_content", return_value=[TEXT]),             patch.object(summarize, "_run_segment", side_effect=_failing_segment()),             patch.object(summarize.llm_router, "generate", side_effect=lambda *a, **k: calls.append(a)):
        try:
            summarize.summarize(_req())
            assert False, "全部失敗必須回錯誤，不能回保底卡"
        except summarize.HTTPException as exc:
            assert exc.status_code == 500
            assert exc.detail == summarize.messages.t("summarize.all_segments_failed")
    assert calls == [], "全部失敗時不該再呼叫模型做整體總結"


def test_plain_summary_partial_failure_keeps_model_cards():
    card = {"heading": "成功的一張", "summary": "內容", "content_type": "study"}

    def fake(req, content, chunk, index, multi, on_status=None):
        if index == 1:
            raise Exception("second segment down")  # noqa: BLE001
        return {"title": "T", "cards": [card], "content_type": "study"}, MODEL

    with patch.object(summarize, "route_content", return_value=_content()),             patch.object(summarize, "chunk_content", return_value=[TEXT, TEXT]),             patch.object(summarize, "_run_segment", side_effect=fake),             patch.object(summarize.llm_router, "generate", return_value=('{"summary":"", "points":[]}', MODEL)):
        result = summarize.summarize(_req())
    assert [c["heading"] for c in result["cards"]] == ["成功的一張"]
    assert result["failed_segments"] == 1


def test_stream_all_failed_emits_no_fallback_and_no_overview():
    calls = []
    with patch.object(summarize, "route_content", return_value=_content()),             patch.object(summarize, "chunk_content", return_value=[TEXT]),             patch.object(summarize, "_run_segment", side_effect=_failing_segment()),             patch.object(summarize.llm_router, "generate", side_effect=lambda *a, **k: calls.append(a)):
        raw = b"".join(_drain(summarize.summarize_stream(_req()))).decode("utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert any('"seg_error"' in line for line in lines), raw
    assert not any('"fallback"' in line for line in lines), "全部失敗不該補保底卡"
    assert not any('"overview"' in line for line in lines), "全部失敗不該呼叫整體總結"
    assert calls == [], "全部失敗時不該再呼叫模型做整體總結"
    done = [line for line in lines if '"done"' in line]
    assert done and '"total_cards": 0' in done[-1], done


def test_stream_partial_failure_keeps_cards_but_marks_failed():
    card = {"heading": "第一段", "summary": "內容"}

    def fake(req, content, chunk, index, multi, on_status=None):
        if index == 1:
            raise Exception("second segment down")  # noqa: BLE001
        return {"title": "T", "cards": [card], "content_type": "study"}, MODEL

    with patch.object(summarize, "route_content", return_value=_content()),             patch.object(summarize, "chunk_content", return_value=[TEXT, TEXT]),             patch.object(summarize, "_run_segment", side_effect=fake),             patch.object(summarize.llm_router, "generate", return_value=('{"summary":"", "points":[]}', MODEL)):
        raw = b"".join(_drain(summarize.summarize_stream(_req()))).decode("utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert any('"first"' not in line and '"第一段"' in line for line in lines), raw
    assert any('"seg_error"' in line and '"seg": 1' in line for line in lines), raw
    done = [line for line in lines if '"done"' in line][-1]
    assert '"failed_segments": 1' in done and '"total_cards": 1' in done, done


def test_overview_is_not_requested_for_fallback_only_cards():
    calls = []
    with patch.object(summarize, "route_content", return_value=_content()),             patch.object(summarize, "chunk_content", return_value=[TEXT]),             patch.object(summarize, "_run_segment", return_value=(EMPTY, MODEL)),             patch.object(summarize.llm_router, "generate", side_effect=lambda *a, **k: calls.append(a)):
        result = summarize.summarize(_req())
    assert result["cards"][0]["fallback"] is True
    assert result["overview"] == {"summary": "", "points": []}
    assert calls == [], "只有保底卡時不該再花一次模型呼叫做總結"

    calls.clear()
    with patch.object(summarize, "route_content", return_value=_content()),             patch.object(summarize, "chunk_content", return_value=[TEXT]),             patch.object(summarize, "_run_segment", return_value=(EMPTY, MODEL)),             patch.object(summarize.llm_router, "generate", side_effect=lambda *a, **k: calls.append(a)):
        raw = b"".join(_drain(summarize.summarize_stream(_req()))).decode("utf-8")
    assert '"fallback"' in raw, "沒有失敗、只是沒有卡片時仍要產保底卡"
    assert '"overview"' not in raw, "只有保底卡時串流也不該送 overview"
    assert calls == []


if __name__ == "__main__":
    test_fallback_card_is_built_from_transcript()
    test_plain_summary_falls_back_when_model_returns_no_cards()
    test_overview_uses_model_output()
    test_overview_falls_back_to_card_headings()
    test_stream_emits_fallback_cards_event()
    test_plain_summary_all_failed_raises_instead_of_fallback()
    test_plain_summary_partial_failure_keeps_model_cards()
    test_stream_all_failed_emits_no_fallback_and_no_overview()
    test_stream_partial_failure_keeps_cards_but_marks_failed()
    test_overview_is_not_requested_for_fallback_only_cards()
    print("Summarize fallback tests passed")
