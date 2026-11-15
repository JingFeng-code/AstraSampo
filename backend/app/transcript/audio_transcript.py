"""沒有字幕的影片：yt-dlp 抓音訊 → 本機語音辨識（SenseVoice 優先，Whisper 次之）。

為什麼不沿用 `whisper_local.transcribe_url`：
  1. 打包版用 `sys.executable -m yt_dlp` 會重新啟動後端本身（onefile 的 executable
     不是 python），所以下載一律走 yt-dlp 的函式庫模式。
  2. 桌面版內建的是 sherpa-onnx（SenseVoice），不是 faster-whisper；先問 SenseVoice
     才不會在打包版白跑一趟。

呼叫端（router）負責決定要不要走這條路：有字幕就用字幕，這裡只在「完全沒有字幕」
時才被用到。
"""
from __future__ import annotations

import glob
import os
import shutil
import tempfile
from typing import Optional

from app.core import messages
from app.transcript import cache, imported_subtitles


def _download(url: str, tmpdir: str) -> str:
    """用 yt-dlp 下載純音訊串流，回傳檔案路徑（影片與音訊都不留在專案目錄）。"""
    try:
        import yt_dlp
    except ModuleNotFoundError as exc:  # 桌面版若沒打包 yt-dlp 會走到這裡
        raise ValueError(messages.t("whisper.downloader_missing")) from exc

    options = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 2,
        "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001 - yt-dlp 的錯誤型別很多，一律轉成使用者訊息
        print(f"[asr] 音訊下載失敗：{str(exc)[:300]!a}", flush=True)
        raise ValueError(messages.t("whisper.download_failed")) from exc

    files = sorted(glob.glob(os.path.join(tmpdir, "audio.*")))
    if not files:
        raise ValueError(messages.t("whisper.download_failed"))
    return files[0]


def _sensevoice(path: str) -> Optional[tuple[str, bool]]:
    """桌面版的主力引擎；模型還沒下載或引擎缺少時回 None，交給下一個引擎。"""
    from app.transcript import local_speech

    if not local_speech.engine_available() or not local_speech.model_ready():
        return None
    cues = local_speech.transcribe_file(path, lambda _p: None, lambda: False)
    if not cues:
        return None
    return imported_subtitles.transcript_from_cues(cues), True


def _whisper(path: str) -> Optional[tuple[str, bool]]:
    try:
        from app.transcript import whisper_local

        return whisper_local.transcribe_file(path)
    except (ImportError, ValueError):
        return None


def transcribe(url: str, cache_key: Optional[str] = None) -> tuple[str, bool, str]:
    """回傳 (帶時間戳逐字稿, 是否中文, 實際使用的引擎)。同一支影片第二次直接命中快取。"""
    key = f"asr_v1:{cache_key or url}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    tmpdir = tempfile.mkdtemp(prefix="astratube_audio_")
    try:
        audio = _download(url, tmpdir)
        heard = _sensevoice(audio)
        if heard:
            result = (heard[0], heard[1], "local_speech")
        else:
            heard = _whisper(audio)
            result = (heard[0], heard[1], "whisper") if heard else None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if result is None:
        raise ValueError(messages.t("whisper.engine_missing"))
    cache.put(key, result[0], result[1])
    return result
