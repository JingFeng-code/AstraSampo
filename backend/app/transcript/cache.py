"""逐字稿快取：key → .cache/transcripts/<sha1>.json，跨重啟保留。

key 請自帶版本前綴（例如 "deepsrt_v1:<video_id>"），避免不同轉錄來源互相污染。
"""
import hashlib
import os
import json
from pathlib import Path
from typing import Optional, Tuple

CACHE_DIR = (Path(os.environ["ASTRA_DESKTOP_DATA_DIR"]) if os.environ.get("ASTRA_DESKTOP_DATA_DIR") else Path(__file__).resolve().parents[3]) / ".cache" / "transcripts"


def _path(key: str) -> Path:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.json"


def get(key: str) -> Optional[Tuple[str, bool]]:
    """命中回傳 (逐字稿, is_chinese)，沒有或壞掉回傳 None。"""
    p = _path(key)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d["text"], bool(d.get("is_chinese", False))
    except Exception:
        return None


def get_obj(key: str) -> Optional[dict]:
    """命中回傳完整的 JSON 物件，沒有或壞掉回傳 None。

    給需要附帶欄位（例如字幕語言、是否 AI 生成）的來源用；`get()` 只回
    (text, is_chinese)，那些來源若硬塞進同一份快取就會掉資料。
    """
    p = _path(key)
    if not p.exists():
        return None
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def put_obj(key: str, value: dict) -> None:
    """寫入完整 JSON 物件；失敗不影響主流程。"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def put(key: str, text: str, is_chinese: bool) -> None:
    """寫入快取；失敗不影響主流程。"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(
            json.dumps({"text": text, "is_chinese": is_chinese}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
