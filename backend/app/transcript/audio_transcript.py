"""沒有字幕的影片：yt-dlp 抓音訊 → 本機語音辨識（SenseVoice 優先，Whisper 次之）。

呼叫端（router）負責決定要不要走這條路：只有使用者明確按下「下載音訊並在本機轉錄」
才會呼叫這裡。下載有長度與大小上限、可中途取消，暫存資料夾一律在結束後刪除。

為什麼不沿用 `whisper_local.transcribe_url`：
  1. 打包版用 `sys.executable -m yt_dlp` 會重新啟動後端本身（onefile 的 executable
     不是 python），所以下載一律走 yt-dlp 的函式庫模式。
  2. 桌面版內建的是 sherpa-onnx（SenseVoice），不是 faster-whisper；先問 SenseVoice
     才不會在打包版白跑一趟。
"""
from __future__ import annotations

import glob
import os
import shutil
import tempfile
from typing import Callable, Optional

from app.core import messages
from app.transcript import cache, imported_subtitles
from app.transcript.cancel import TranscriptionCancelled

# 上限刻意寫死在程式裡：不提供放寬的設定，避免「下載更多影片」變成預設行為
MAX_MINUTES = 90
MAX_BYTES = 500 * 1024 * 1024
_SOCKET_TIMEOUT = 20


# 向後相容的別名：舊程式與測試用 AudioCancelled 這個名字
AudioCancelled = TranscriptionCancelled


def _yt_dlp():
    try:
        import yt_dlp
    except ModuleNotFoundError as exc:  # 桌面版若沒打包 yt-dlp 會走到這裡
        raise ValueError(messages.t("whisper.downloader_missing")) from exc
    return yt_dlp


def _metadata(url: str) -> dict:
    """只取中繼資料（不下載），用來在花時間下載前先擋掉太長的影片。"""
    yt_dlp = _yt_dlp()
    options = {"quiet": True, "no_warnings": True, "noplaylist": True,
               "socket_timeout": _SOCKET_TIMEOUT}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 - yt-dlp 的錯誤型別很多，一律轉成使用者訊息
        print(f"[asr] 取得影片資訊失敗：{str(exc)[:300]!a}", flush=True)
        raise ValueError(messages.t("whisper.download_failed")) from exc
    return info if isinstance(info, dict) else {}


def _guard_limits(info: dict) -> None:
    """長度與檔案大小先擋：下載前就能確定不行，就不要下載。"""
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > MAX_MINUTES * 60:
        raise ValueError(messages.t("whisper.too_long", minutes=MAX_MINUTES))
    size = info.get("filesize") or info.get("filesize_approx")
    if isinstance(size, (int, float)) and size > MAX_BYTES:
        raise ValueError(messages.t("whisper.too_large", mb=MAX_BYTES // (1024 * 1024)))


def _download(url: str, tmpdir: str, cancelled: Optional[Callable[[], bool]] = None,
              on_progress: Optional[Callable[[dict], None]] = None) -> str:
    """用 yt-dlp 下載純音訊串流，回傳檔案路徑（影片與音訊都不留在專案目錄）。"""
    yt_dlp = _yt_dlp()
    info = _metadata(url)
    _guard_limits(info)

    def hook(status: dict) -> None:
        if cancelled and cancelled():
            raise AudioCancelled()
        if on_progress and status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            percent = int(done * 100 / total) if total else None
            on_progress({"stage": "download", "percent": percent})

    options = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 2,
        "socket_timeout": _SOCKET_TIMEOUT,
        # 超過上限就讓 yt-dlp 自己停下來，不要先下載完才發現太大
        "max_filesize": MAX_BYTES,
        "progress_hooks": [hook],
        "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.extract_info(url, download=True)
    except AudioCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        if cancelled and cancelled():
            raise AudioCancelled() from exc
        print(f"[asr] 音訊下載失敗：{str(exc)[:300]!a}", flush=True)
        raise ValueError(messages.t("whisper.download_failed")) from exc

    if cancelled and cancelled():
        raise AudioCancelled()
    files = sorted(glob.glob(os.path.join(tmpdir, "audio.*")))
    if not files:
        # yt-dlp 的 max_filesize 超過時只會「跳過下載」、不丟例外；用中繼資料判斷
        # 是不是大小問題，才不會把使用者導向泛用的「下載失敗」。
        detail = result if isinstance(result, dict) else info
        size = detail.get("filesize") or detail.get("filesize_approx")
        if isinstance(size, (int, float)) and size > MAX_BYTES:
            raise ValueError(messages.t("whisper.too_large", mb=MAX_BYTES // (1024 * 1024)))
        raise ValueError(messages.t("whisper.download_failed"))
    return files[0]


def _sensevoice(path: str, cancelled: Optional[Callable[[], bool]] = None) -> Optional[tuple[str, bool]]:
    """桌面版的主力引擎；模型還沒下載或引擎缺少時回 None，交給下一個引擎。"""
    from app.transcript import local_speech

    if not local_speech.engine_available() or not local_speech.model_ready():
        return None
    cues = local_speech.transcribe_file(path, lambda _p: None,
                                        cancelled or (lambda: False))
    if not cues:
        return None
    return imported_subtitles.transcript_from_cues(cues), True


def _whisper(path: str, cancelled: Optional[Callable[[], bool]] = None) -> Optional[tuple[str, bool]]:
    try:
        from app.transcript import whisper_local

        # 備援引擎也要能中途停止：逐段解碼時檢查旗標，取消就往上拋（finally 會刪暫存）
        return whisper_local.transcribe_file(path, cancelled)
    except (ImportError, ValueError):
        return None


def transcribe(url: str, cache_key: Optional[str] = None, *,
               cancelled: Optional[Callable[[], bool]] = None,
               on_progress: Optional[Callable[[dict], None]] = None) -> tuple[str, bool, str]:
    """回傳 (帶時間戳逐字稿, 是否中文, 實際使用的引擎)。

    同一支影片第二次直接命中快取；cache_key 由呼叫端組（Bilibili 要綁 cid，
    不同分 P 不能共用）。使用者取消時丟 AudioCancelled，暫存檔一定會被刪掉。
    """
    # asr_v3：快取鍵改由呼叫端帶 cid；舊版前綴不讀，避免拿到不同分 P 的內容
    key = f"asr_v3:{cache_key or url}"
    hit = cache.get_obj(key)
    if isinstance(hit, dict) and isinstance(hit.get("text"), str):
        return hit["text"], bool(hit.get("is_chinese", False)), str(hit.get("engine") or "cache")

    tmpdir = tempfile.mkdtemp(prefix="astratube_audio_")
    try:
        audio = _download(url, tmpdir, cancelled, on_progress)
        if cancelled and cancelled():
            raise AudioCancelled()
        if on_progress:
            on_progress({"stage": "transcribe"})
        heard = _sensevoice(audio, cancelled)
        if heard:
            result = (heard[0], heard[1], "local_speech")
        else:
            heard = _whisper(audio, cancelled)
            result = (heard[0], heard[1], "whisper") if heard else None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if cancelled and cancelled():
        raise AudioCancelled()
    if result is None:
        raise ValueError(messages.t("whisper.engine_missing"))
    cache.put_obj(key, {"text": result[0], "is_chinese": result[1], "engine": result[2]})
    return result
