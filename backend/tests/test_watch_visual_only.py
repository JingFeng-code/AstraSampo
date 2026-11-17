"""陪看：沒有語音（純音樂）時，畫面筆記仍然要能被保存。"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.transcript import imported_subtitles, watch_along


def test_has_content_accepts_visuals_only():
    assert watch_along.has_content([], []) is False
    assert watch_along.has_content([], [{"t": 3.0, "text": "畫面是簡報"}]) is True
    assert watch_along.has_content([{"start": 1, "end": 2, "text": "hi"}], []) is True


def test_visual_only_subtitles_are_chinese():
    """沒有語音時，語言判斷要用畫面筆記的內容，不能因為 cues 空就當成外文。"""
    tmp = Path(tempfile.mkdtemp())
    with patch.object(imported_subtitles, "CACHE_DIR", tmp):
        imported_subtitles.save_cues("bilibili", "BV1B7411m7LV", 1, "watch", [],
                                     visuals=[{"t": 4.0, "text": "投影片寫著系統架構"}])
        stored = imported_subtitles.load("bilibili", "BV1B7411m7LV", 1)
    assert stored["cues"] == []
    assert stored["is_chinese"] is True
    assert stored["visuals"][0]["text"] == "投影片寫著系統架構"


def test_transcript_from_visuals_keeps_screen_lines():
    text = imported_subtitles.transcript_from_cues([], [{"t": 65.0, "text": "畫面是終端機"}])
    assert text == "【畫面 1:05】畫面是終端機"


def test_status_reports_capture_counters():
    session = watch_along.Session(platform="bilibili", video_id="BV1B7411m7LV", page=1,
                                  region={"x": 0, "y": 0, "w": 10, "h": 10},
                                  vision_model="ornith-1.5:9b")
    session.frame_count = 7
    session.vision_tries = 5
    session.vision_empty = 3
    status = session.status()
    assert status["frame_count"] == 7
    assert status["vision_tries"] == 5
    assert status["vision_empty"] == 3


if __name__ == "__main__":
    test_has_content_accepts_visuals_only()
    test_visual_only_subtitles_are_chinese()
    test_transcript_from_visuals_keeps_screen_lines()
    test_status_reports_capture_counters()
    print("Watch visual-only tests passed")
