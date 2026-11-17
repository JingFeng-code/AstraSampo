"""Bilibili 沒有字幕時的本機音訊轉錄：只用在使用者明確同意之後，且有上限、可取消。

不碰網路、不呼叫真的 yt-dlp 或語音引擎：全部用假的模組與函式。
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api import summarize
from app.main import app
from app.models.schemas import SummarizeRequest
from app.transcript import audio_transcript, bilibili, cache
from app.transcript import router as transcript_router
from app.transcript.router import Content

LOCAL = "http://127.0.0.1:8420"
CLEAN_ENV = {"ASTRA_DESKTOP_TOKEN": "", "CODESPACE_NAME": "", "ASTRA_DESKTOP_DATA_DIR": "",
             "ASTRA_ALLOWED_ORIGINS": "", "ASTRA_ALLOWED_HOSTS": ""}
URL = "https://www.bilibili.com/video/BV1jhns6DEzi/"
SESS = "ollama:qwen3:4b"


class FakeYoutubeDL:
    """假的 yt-dlp：記錄有沒有真的被要求下載，必要時呼叫進度 hook。"""

    info: dict = {}
    download_asked: list[bool] = []
    on_hook = None

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        FakeYoutubeDL.download_asked.append(download)
        if not download:
            return dict(FakeYoutubeDL.info)
        if FakeYoutubeDL.on_hook:
            # 測試自己的回呼先跑（例如把取消旗標設起來），再跑 yt-dlp 的進度 hook
            FakeYoutubeDL.on_hook({"status": "downloading"})
            for hook in self.options.get("progress_hooks") or []:
                hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})
        outtmpl = str(self.options["outtmpl"]).replace("%(ext)s", "webm")
        with open(outtmpl, "wb") as handle:
            handle.write(b"fake audio")
        return dict(FakeYoutubeDL.info)


def fake_ytdlp(info=None, on_hook=None):
    FakeYoutubeDL.info = info or {"duration": 120, "filesize": 1024}
    FakeYoutubeDL.download_asked = []
    FakeYoutubeDL.on_hook = on_hook
    return patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)})


def no_subtitle(cid=456):
    error = bilibili.NoSubtitleError("這支 Bilibili 影片沒有可公開取得的字幕。")
    error.cid = cid
    return error


def test_download_only_after_explicit_consent():
    calls = []
    with patch.object(bilibili, "fetch_transcript_detail", side_effect=no_subtitle()), \
            patch.object(transcript_router.audio_transcript, "transcribe",
                         side_effect=lambda *a, **k: calls.append(k) or ("逐字稿", True, "local_speech")):
        try:
            transcript_router.route_content(URL, allow_audio_download=False)
            assert False, "沒有同意不可以下載"
        except bilibili.NoSubtitleError:
            pass
        assert calls == [], "allow_audio_download=False 時不能呼叫下載"

        content = transcript_router.route_content(URL, allow_audio_download=True)
    assert content["text"] == "逐字稿"
    assert len(calls) == 1
    assert calls[0]["cache_key"] == "bilibili:BV1jhns6DEzi:456", "快取鍵要綁 cid"


def test_generic_caption_errors_never_download_even_with_consent():
    for message in ["Bilibili 字幕下載失敗或遭到限制。",
                    "Bilibili 影片沒有第 2 個分 P，請確認連結。",
                    "Bilibili SESSDATA 格式不正確（不可含換行、分號或逗號，最長 512 字元）。"]:
        calls = []
        with patch.object(bilibili, "fetch_transcript_detail", side_effect=ValueError(message)), \
                patch.object(transcript_router.audio_transcript, "transcribe",
                             side_effect=lambda *a, **k: calls.append(k) or ("x", True, "local_speech")):
            try:
                transcript_router.route_content(URL, allow_audio_download=True)
                assert False, message
            except ValueError:
                pass
        assert calls == [], f"一般錯誤不該觸發下載：{message}"


def test_long_video_is_refused_before_downloading():
    with fake_ytdlp(info={"duration": audio_transcript.MAX_MINUTES * 60 + 60}):
        try:
            audio_transcript.transcribe(URL, cache_key="bilibili:BV1:x")
            assert False, "超過上限必須拒絕"
        except ValueError as exc:
            assert str(audio_transcript.MAX_MINUTES) in str(exc)
    assert FakeYoutubeDL.download_asked == [False], "只查中繼資料，不能真的下載"


def test_large_audio_is_refused_before_downloading():
    with fake_ytdlp(info={"duration": 60, "filesize": audio_transcript.MAX_BYTES + 1}):
        try:
            audio_transcript.transcribe(URL, cache_key="bilibili:BV1:x")
            assert False, "超過大小上限必須拒絕"
        except ValueError as exc:
            assert str(audio_transcript.MAX_BYTES // (1024 * 1024)) in str(exc)
    assert FakeYoutubeDL.download_asked == [False]


def test_cancel_during_download_stops_and_removes_temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp) / "audio"
        tmpdir.mkdir()
        flag = {"cancel": False}

        def hook(status):
            # 收到第一個進度就當成使用者按了停止
            flag["cancel"] = True

        with fake_ytdlp(on_hook=hook), \
                patch.object(audio_transcript.tempfile, "mkdtemp", return_value=str(tmpdir)):
            try:
                audio_transcript.transcribe(URL, cache_key="bilibili:BV1:x",
                                            cancelled=lambda: flag["cancel"])
                assert False, "取消後必須丟 AudioCancelled"
            except audio_transcript.AudioCancelled:
                pass
        assert not tmpdir.exists(), "取消後暫存資料夾要刪掉"


def test_cancel_during_transcription_stops_and_removes_temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp) / "audio"
        tmpdir.mkdir()
        with fake_ytdlp(), \
                patch.object(audio_transcript, "_sensevoice",
                             side_effect=audio_transcript.AudioCancelled()), \
                patch.object(audio_transcript.tempfile, "mkdtemp", return_value=str(tmpdir)):
            try:
                audio_transcript.transcribe(URL, cache_key="bilibili:BV1:x", cancelled=lambda: True)
                assert False, "轉錄中取消也要中止"
            except audio_transcript.AudioCancelled:
                pass
        assert not tmpdir.exists()


def test_cache_key_includes_cid():
    keys = {111: [], 222: []}
    with fake_ytdlp(), \
            patch.object(audio_transcript, "_sensevoice", return_value=("文字", True)), \
            patch.object(cache, "get_obj", return_value=None), \
            patch.object(cache, "put_obj", side_effect=lambda key, value: keys[current[0]].append(key)):
        for cid in (111, 222):
            current = [cid]
            error = bilibili.NoSubtitleError("沒有字幕")
            error.cid = cid
            with patch.object(bilibili, "fetch_transcript_detail", side_effect=error):
                transcript_router.route_content(URL, allow_audio_download=True)
    assert keys[111] == ["asr_v3:bilibili:BV1jhns6DEzi:111"]
    assert keys[222] == ["asr_v3:bilibili:BV1jhns6DEzi:222"]


def test_remote_request_cannot_ask_for_audio_download():
    payload = {"url": URL, "provider": SESS, "allow_audio_download": True}
    content = Content(type="article", video_id=None, title="t", text="內容",
                      is_chinese=False, has_timestamps=False, transcript_source=None)
    with patch.dict(os.environ, CLEAN_ENV),             patch.object(summarize, "route_content", return_value=content) as route:
        remote = TestClient(app, base_url=LOCAL, client=("192.168.1.20", 50000))
        assert remote.post("/summarize_stream", json=payload).status_code == 403
        assert remote.post("/summarize", json=payload).status_code == 403
        assert route.call_count == 0, "被拒絕的請求不能開始擷取內容"
        local = TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000))
        ok = local.post("/summarize_stream", json={**payload, "allow_audio_download": False})
        assert ok.status_code == 200
    assert route.call_count == 1


def _drain(response):
    async def collect():
        out = []
        async for chunk in response.body_iterator:
            out.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
        return out

    return asyncio.run(collect())


def _stream_events(req, route):
    """跑完一次串流並回傳解析後的事件（模型段落用假的、不會碰網路）。"""
    empty = {"title": "t", "cards": [], "content_type": "other"}
    with patch.object(summarize, "route_content", side_effect=route),             patch.object(summarize, "_run_segment", return_value=(empty, "model")),             patch.object(summarize.llm_router, "generate",
                         return_value=('{"summary": "", "points": []}', "model")):
        raw = b"".join(_drain(summarize.summarize_stream(req))).decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def _content():
    return Content(type="bilibili", video_id="BV1jhns6DEzi", title=None, text="內容",
                   is_chinese=True, has_timestamps=True, transcript_source="local_speech")


def test_download_and_transcribe_progress_keep_stage_source():
    """事件契約：進度事件固定是 stage="source"，下載／轉錄放在 state。"""
    def route(url, **kwargs):
        on_progress = kwargs["on_progress"]
        on_progress({"stage": "download", "percent": 42})
        on_progress({"stage": "transcribe"})
        return _content()

    events = _stream_events(SummarizeRequest(url=URL, provider=SESS), route)
    progress = [event for event in events if event.get("type") == "progress"]
    download = [event for event in progress if event.get("state") == "download"]
    assert download, progress
    assert download[0]["stage"] == "source", "stage 不能變成 download"
    assert download[0]["percent"] == 42
    transcribe = [event for event in progress if event.get("state") == "transcribe"]
    assert transcribe and transcribe[0]["stage"] == "source"
    assert "percent" in transcribe[0]


def test_fatal_events_carry_a_code_for_bilibili_caption_errors():
    for error, expected in [(no_subtitle(), "bilibili_no_subtitle"),
                            (bilibili.LoginRequiredError("這支影片的字幕需要登入，且 SESSDATA 已失效。"),
                             "bilibili_login_required")]:
        def route(url, _error=error, **kwargs):
            raise _error

        fatal = [event for event in _stream_events(SummarizeRequest(url=URL, provider=SESS), route)
                 if event.get("type") == "fatal"]
        assert fatal, "要送出 fatal"
        assert fatal[0].get("code") == expected, fatal[0]
        assert fatal[0]["error"]


def test_fatal_events_have_no_code_for_other_errors():
    for message in ["Bilibili 字幕下載失敗或遭到限制。", "Bilibili 影片沒有第 2 個分 P，請確認連結。"]:
        def route(url, _message=message, **kwargs):
            raise ValueError(_message)

        fatal = [event for event in _stream_events(SummarizeRequest(url=URL, provider=SESS), route)
                 if event.get("type") == "fatal"]
        assert fatal and "code" not in fatal[0], fatal[0]


def test_cancel_during_whisper_fallback_stops_and_removes_temp_dir():
    """SenseVoice 不可用時的 Whisper 備援也要能取消。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp) / "audio"
        tmpdir.mkdir()
        seen = {}
        state = {"cancel": False}

        def fake_sensevoice(path, cancelled=None):
            state["cancel"] = True   # 模擬使用者在 SenseVoice 階段按下停止
            return None

        def fake_whisper(path, cancelled=None):
            seen["cancelled"] = cancelled
            assert cancelled is not None, "取消旗標要傳進 Whisper 備援"
            assert cancelled() is True
            raise audio_transcript.AudioCancelled()

        with fake_ytdlp(),                 patch.object(audio_transcript, "_sensevoice", side_effect=fake_sensevoice),                 patch.object(audio_transcript, "_whisper", side_effect=fake_whisper),                 patch.object(audio_transcript.tempfile, "mkdtemp", return_value=str(tmpdir)):
            try:
                audio_transcript.transcribe(URL, cache_key="bilibili:BV1:x",
                                            cancelled=lambda: state["cancel"])
                assert False, "Whisper 備援取消也要中止"
            except audio_transcript.AudioCancelled:
                pass
        assert "cancelled" in seen
        assert not tmpdir.exists()


def test_size_limit_hit_only_during_download_reports_too_large():
    """yt-dlp 的 max_filesize 超過時只跳過、不丟例外；要回「超過大小」而不是泛用失敗。"""

    class OversizeYDL(FakeYoutubeDL):
        def extract_info(self, url, download=False):
            if not download:
                return {"duration": 60, "filesize": 1024}   # 中繼資料看起來沒超過
            return {"duration": 60, "filesize": audio_transcript.MAX_BYTES + 1}

    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=OversizeYDL)}),                 patch.object(audio_transcript.tempfile, "mkdtemp", return_value=str(Path(tmp) / "audio")):
            (Path(tmp) / "audio").mkdir()
            try:
                audio_transcript.transcribe(URL, cache_key="bilibili:BV1:x")
                assert False, "超過大小要拒絕"
            except ValueError as exc:
                assert str(audio_transcript.MAX_BYTES // (1024 * 1024)) in str(exc), str(exc)


def test_closing_the_stream_stops_the_background_fetch():
    started = threading.Event()
    stopped = threading.Event()

    def slow_route(url, **kwargs):
        started.set()
        cancelled = kwargs.get("cancelled") or (lambda: False)
        while not cancelled():
            time.sleep(0.05)
        stopped.set()
        raise ValueError("cancelled")

    with patch.object(summarize, "route_content", side_effect=slow_route):
        stream = summarize._stream_events(SummarizeRequest(url=URL, provider=SESS,
                                                           allow_audio_download=True))
        next(stream)   # 第一個 progress 事件
        next(stream)   # 進入擷取階段：背景執行緒開始、外層先送心跳
        assert started.wait(5), "擷取應該在背景執行"
        stream.close()  # 使用者按停止（連線中斷）
        assert stopped.wait(5), "關閉串流後要設定取消旗標，背景作業才會停"


if __name__ == "__main__":
    test_download_only_after_explicit_consent()
    test_generic_caption_errors_never_download_even_with_consent()
    test_long_video_is_refused_before_downloading()
    test_large_audio_is_refused_before_downloading()
    test_cancel_during_download_stops_and_removes_temp_dir()
    test_cancel_during_transcription_stops_and_removes_temp_dir()
    test_cache_key_includes_cid()
    test_remote_request_cannot_ask_for_audio_download()
    test_cancel_during_whisper_fallback_stops_and_removes_temp_dir()
    test_size_limit_hit_only_during_download_reports_too_large()
    test_download_and_transcribe_progress_keep_stage_source()
    test_fatal_events_carry_a_code_for_bilibili_caption_errors()
    test_fatal_events_have_no_code_for_other_errors()
    test_closing_the_stream_stops_the_background_fetch()
    print("Audio download tests passed")
