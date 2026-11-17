"""打包後的桌面版沒有 Whisper／yt-dlp，不得用 sys.executable 重複啟動後端。"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.transcript import whisper_local


def test_frozen_desktop_gives_clear_message_without_spawning():
    with patch.object(whisper_local.sys, "frozen", True, create=True), \
         patch.object(whisper_local.cache, "get", return_value=None), \
         patch.object(whisper_local.subprocess, "run") as run:
        try:
            whisper_local.transcribe_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ")
            assert False, "必須回報清楚的錯誤"
        except ValueError as exc:
            assert "SRT" in str(exc)
    run.assert_not_called()


def test_cached_transcript_still_works_on_desktop():
    with patch.object(whisper_local.sys, "frozen", True, create=True), \
         patch.object(whisper_local.cache, "get", return_value=("[0] 已快取", False)):
        assert whisper_local.transcribe_url("https://example.invalid", "key")[0] == "[0] 已快取"


def test_cached_audio_transcript_keeps_engine():
    """ASR 快取要回三個值；舊版只存兩項，第二次分析會 unpack 失敗。"""
    from app.transcript import audio_transcript

    with patch.object(audio_transcript.cache, "get_obj",
                      return_value={"text": "[0] 已快取", "is_chinese": True,
                                    "engine": "local_speech"}):
        got = audio_transcript.transcribe("https://example.invalid/watch", "BV1TEST")
    assert got == ("[0] 已快取", True, "local_speech"), got


if __name__ == "__main__":
    test_frozen_desktop_gives_clear_message_without_spawning()
    test_cached_transcript_still_works_on_desktop()
    test_cached_audio_transcript_keeps_engine()
    print("Desktop transcription fallback tests passed")
