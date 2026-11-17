"""Whisper 備援路徑也要能中途停止：逐段解碼時檢查取消旗標。"""
import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.transcript import whisper_local
from app.transcript.cancel import TranscriptionCancelled


class FakeSegment:
    def __init__(self, index):
        self.start = float(index)
        self.text = f"第 {index} 句"


def test_whisper_stops_decoding_when_cancelled():
    produced = []

    def fake_transcribe(path, vad_filter=True, beam_size=1, condition_on_previous_text=False):
        def segments():
            for index in range(5):
                produced.append(index)
                yield FakeSegment(index)

        return segments(), types.SimpleNamespace(language="zh")

    model = types.SimpleNamespace(transcribe=fake_transcribe)
    with patch.object(whisper_local, "_get_model", return_value=model):
        try:
            whisper_local.transcribe_file("audio.webm", cancelled=lambda: len(produced) >= 2)
            assert False, "取消後要丟 TranscriptionCancelled"
        except TranscriptionCancelled:
            pass
    assert produced == [0, 1], "第二段之後就要停，不能把整段解碼完"


def test_whisper_still_works_without_cancellation():
    def fake_transcribe(path, vad_filter=True, beam_size=1, condition_on_previous_text=False):
        return iter([FakeSegment(0), FakeSegment(1)]), types.SimpleNamespace(language="zh")

    with patch.object(whisper_local, "_get_model",
                      return_value=types.SimpleNamespace(transcribe=fake_transcribe)):
        text, is_chinese = whisper_local.transcribe_file("audio.webm")
    assert "[0] 第 0 句" in text and "[1] 第 1 句" in text
    assert is_chinese is True


if __name__ == "__main__":
    test_whisper_stops_decoding_when_cancelled()
    test_whisper_still_works_without_cancellation()
    print("Whisper cancel tests passed")
