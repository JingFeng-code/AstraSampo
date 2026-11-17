"""使用者按下停止時用來中止轉錄的例外。

放在獨立模組：audio_transcript（SenseVoice）與 whisper_local（Whisper 備援）
都要用同一個型別，才不會互相匯入造成循環。
"""


class TranscriptionCancelled(Exception):
    """使用者按下停止：轉寫／下載要立刻中止，暫存檔由呼叫端的 finally 清掉。"""
