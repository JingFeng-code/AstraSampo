"""Bilibili 公開字幕：不對外發送網路請求的固定資料測試。"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.transcript import bilibili
from app.transcript import router
from app.transcript.router import route_content
from app.api import summarize as api_summarize
from app.api import ask as api_ask
from app.models.schemas import SummarizeRequest


BVID = "BV1B7411m7LV"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.content = json.dumps(payload).encode("utf-8")
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


def test_video_url():
    assert bilibili.parse_video_url(f"https://www.bilibili.com/video/{BVID}") == (BVID, 1)
    assert bilibili.parse_video_url(f"https://m.bilibili.com/video/{BVID}?p=2") == (BVID, 2)
    assert bilibili.parse_video_url(f"https://evil-bilibili.com/video/{BVID}") is None
    assert bilibili.parse_video_url(f"http://www.bilibili.com/video/{BVID}") is None
    try:
        bilibili.parse_video_url(f"https://www.bilibili.com/video/{BVID}?p=-1")
        assert False, "Invalid page must fail"
    except ValueError:
        pass


def test_allowed_subtitle_domains():
    assert bilibili._subtitle_url("//aisubtitle.hdslb.com/abc.json").startswith("https:")
    for url in ("http://aisubtitle.hdslb.com/a", "https://hdslb.com.evil.com/a",
                "http://127.0.0.1/", "file:///etc/passwd", "https://localhost/a"):
        try:
            bilibili._subtitle_url(url)
            assert False, "Unexpected allowed domain: " + url
        except ValueError:
            pass


def test_fetch_public_subtitle_and_cache():
    calls = []
    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/x/web-interface/view"):
            return FakeResponse({"code": 0, "data": {"pages": [
                {"cid": 123, "page": 1}, {"cid": 456, "page": 2}
            ]}})
        if url.endswith("/x/player/v2"):
            assert kwargs["params"]["cid"] == 456
            return FakeResponse({"code": 0, "data": {"subtitle": {"subtitles": [
                {"lan": "en", "subtitle_url": "//aisubtitle.hdslb.com/en.json", "ai_type": 1},
                {"lan": "zh-Hans", "subtitle_url": "//aisubtitle.hdslb.com/zh.json", "ai_type": 0}
            ]}}})
        assert url == "https://aisubtitle.hdslb.com/zh.json"
        return FakeResponse({"body": [{"from": 1.8, "to": 4.2, "content": "你好 &amp; 世界"}]})
    stored = {}
    with patch.object(bilibili.requests, "get", side_effect=fake_get), \
         patch.object(bilibili.cache, "get", side_effect=lambda key: stored.get(key)), \
         patch.object(bilibili.cache, "put", side_effect=lambda key, text, chinese: stored.__setitem__(key, (text, chinese))):
        assert bilibili.fetch_transcript(BVID, 2) == ("[1] 你好 & 世界", True)
        calls.clear()
        # 第二次仍會問一次 view（拿 cid 驗證快取），但不能再抓字幕檔
        assert bilibili.fetch_transcript(BVID, 2) == ("[1] 你好 & 世界", True)
        assert calls == ["https://api.bilibili.com/x/web-interface/view"], calls


def test_cached_transcript_from_another_video_is_ignored():
    """快取綁 cid：舊的／別的影片的快取不能拿來當這支片的字幕。"""
    poisoned = {"text": "[1] 別的影片", "is_chinese": True, "lang": "ai-zh", "is_ai": True, "cid": 999}
    def fake_get(url, **kwargs):
        if url.endswith("/x/web-interface/view"):
            return FakeResponse({"code": 0, "data": {"pages": [{"cid": 123}]}})
        if url.endswith("/x/player/v2"):
            return FakeResponse({"code": 0, "data": {"subtitle": {"subtitles": [
                {"lan": "zh-Hans", "subtitle_url": "//aisubtitle.hdslb.com/ok.json", "ai_type": 0}]}}})
        return FakeResponse({"body": [{"from": 1, "content": "這支影片"}]})
    with patch.object(bilibili.requests, "get", side_effect=fake_get),          patch.object(bilibili.cache, "get_obj", return_value=poisoned),          patch.object(bilibili.cache, "put_obj"):
        text, _cn, _lang, _ai = bilibili.fetch_transcript_detail(BVID, 1)
    assert text == "[1] 這支影片", text


def test_missing_public_subtitle():
    def fake_get(url, **kwargs):
        if url.endswith("/x/web-interface/view"):
            return FakeResponse({"code": 0, "data": {"pages": [{"cid": 123}]}})
        return FakeResponse({"code": 0, "data": {"subtitle": {"subtitles": []}, "need_login_subtitle": True}})
    with patch.object(bilibili.requests, "get", side_effect=fake_get), \
         patch.object(bilibili.cache, "get", return_value=None):
        try:
            bilibili.fetch_transcript(BVID)
            assert False, "Login-only captions must fail"
        except ValueError as exc:
            assert "需要登入" in str(exc)


def test_sessdata_is_sent_to_api_only_and_ai_subtitles_are_labelled():
    seen = []

    def fake_get(url, **kwargs):
        seen.append((url, kwargs.get("headers", {}).get("Cookie")))
        if url.endswith("/x/web-interface/view"):
            return FakeResponse({"code": 0, "data": {"pages": [{"cid": 123}]}})
        if url.endswith("/x/player/v2"):
            return FakeResponse({"code": 0, "data": {"subtitle": {"subtitles": [
                {"lan": "ai-zh", "subtitle_url": "//aisubtitle.hdslb.com/ai.json", "ai_type": 1}
            ]}}})
        return FakeResponse({"body": [{"from": 2, "content": "自動字幕"}]})

    with patch.object(bilibili.requests, "get", side_effect=fake_get),          patch.object(bilibili.cache, "get_obj", return_value=None),          patch.object(bilibili.cache, "put_obj"):
        text, is_chinese, lang, is_ai = bilibili.fetch_transcript_detail(BVID, 1, "abc123")
    assert text == "[2] 自動字幕" and is_chinese and is_ai and lang == "ai-zh"
    # 登入狀態只給 api.bilibili.com；字幕 CDN 是另一個網域，不該拿到 SESSDATA
    api_cookies = [c for u, c in seen if u.startswith("https://api.bilibili.com/")]
    cdn_cookies = [c for u, c in seen if u.startswith("https://aisubtitle.hdslb.com/")]
    assert api_cookies and all(c == "SESSDATA=abc123" for c in api_cookies), seen
    assert cdn_cookies and all(c is None for c in cdn_cookies), seen

    seen.clear()
    with patch.object(bilibili.requests, "get", side_effect=fake_get),          patch.object(bilibili.cache, "get_obj", return_value=None),          patch.object(bilibili.cache, "put_obj"):
        bilibili.fetch_transcript_detail(BVID, 1)
    assert all(c is None for _u, c in seen), "沒有 SESSDATA 時不該送出 Cookie"


def test_bad_sessdata_is_rejected():
    for bad in ("a;b", "a,b", "line" + chr(10) + "break", "x" * 513):
        try:
            bilibili._cookie_header(bad)
            assert False, "Invalid SESSDATA must be rejected: " + bad
        except ValueError:
            pass


def test_router_falls_back_to_local_transcription():
    with patch.object(bilibili, "fetch_transcript_detail",
                      side_effect=ValueError("這支影片的字幕需要登入才能讀取。")),          patch.object(router.audio_transcript, "transcribe",
                      return_value=("[0] 本機轉錄", True, "local_speech")) as transcribe:
        content = route_content(f"https://www.bilibili.com/video/{BVID}/")
    assert content["type"] == "bilibili"
    assert content["transcript_source"] == "local_speech"
    assert content["text"] == "[0] 本機轉錄"
    transcribe.assert_called_once()


def test_router_keeps_both_reasons_when_transcription_is_unavailable():
    with patch.object(bilibili, "fetch_transcript_detail",
                      side_effect=ValueError("字幕需要登入。")),          patch.object(router.audio_transcript, "transcribe",
                      side_effect=ValueError("桌面版沒有內建語音轉錄。")):
        try:
            route_content(f"https://www.bilibili.com/video/{BVID}/")
            assert False, "Must fail when nothing can fetch the transcript"
        except ValueError as exc:
            assert "字幕需要登入" in str(exc) and "沒有內建語音轉錄" in str(exc)


def test_router_and_ask_use_bilibili_cache():
    with patch.object(bilibili, "fetch_transcript_detail",
                      return_value=("[15] 測試逐字稿", True, "zh-hans", False)):
        content = route_content(f"https://www.bilibili.com/video/{BVID}/?p=3")
        assert content["type"] == "bilibili"
        assert content["bilibili_page"] == 3
        assert content["video_id"] == BVID
        assert content["has_timestamps"]
    with patch.object(api_ask.cache, "get", return_value=("[15] 測試逐字稿", True)):
        assert api_ask._load_transcript(f"bilibili:{BVID}:p3") == "[15] 測試逐字稿"


async def _events(response):
    result = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        result.extend(json.loads(line) for line in text.splitlines() if line.strip())
    return result


def test_summary_stream_has_bilibili_metadata():
    content = {"type": "bilibili", "video_id": BVID, "bilibili_page": 2,
               "title": None, "text": "[0] 測試", "is_chinese": True,
               "has_timestamps": True, "transcript_source": "bilibili_captions"}
    with patch.object(api_summarize, "route_content", return_value=content), \
         patch.object(api_summarize, "chunk_content", return_value=["[0] 測試"]), \
         patch.object(api_summarize, "_run_segment", return_value=(
             {"title": "範例", "cards": [{"heading": "重點", "summary": "內容"}], "content_type": "tutorial"}, "fake-model"
         )), \
         patch.object(api_summarize.llm_router, "parallel_workers", return_value=1):
        response = api_summarize.summarize_stream(SummarizeRequest(url=f"https://www.bilibili.com/video/{BVID}/?p=2", provider="auto"))
        events = asyncio.run(_events(response))
        meta = next(e for e in events if e["type"] == "meta")
        assert meta["youtube_video_id"] is None
        assert meta["bilibili_video_id"] == BVID
        assert meta["bilibili_page"] == 2
        assert any(e["type"] == "cards" for e in events)


if __name__ == "__main__":
    test_video_url()
    test_allowed_subtitle_domains()
    test_fetch_public_subtitle_and_cache()
    test_cached_transcript_from_another_video_is_ignored()
    test_missing_public_subtitle()
    test_sessdata_is_sent_to_api_only_and_ai_subtitles_are_labelled()
    test_bad_sessdata_is_rejected()
    test_router_falls_back_to_local_transcription()
    test_router_keeps_both_reasons_when_transcription_is_unavailable()
    test_router_and_ask_use_bilibili_cache()
    test_summary_stream_has_bilibili_metadata()
    print("Bilibili 公開字幕測試通過。")
