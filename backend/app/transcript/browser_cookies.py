"""從使用者「已經登入 B 站」的瀏覽器讀取登入狀態（只取 SESSDATA），
不代替使用者登入、不保存整份 cookie jar。

為什麼需要這個模組：
  SESSDATA 是 HttpOnly cookie，網頁腳本與書籤都讀不到，只有擴充套件或本機程式
  能拿。我們選本機程式：使用者按一次按鈕，程式從他自己的瀏覽器設定檔讀出
  SESSDATA，存進本機 settings.json。

已知限制（要在 UI 說清楚，不要讓使用者以為壞掉）：
  Windows 上 Chrome／Edge 127 以後的 cookie 改用 App-Bound Encryption，
  yt-dlp 目前解不開（yt-dlp issue #10927）。Firefox 與舊版 Chrome 可以。
"""
from __future__ import annotations

import os
from typing import Iterable

# yt-dlp 認得的瀏覽器代號；只列出這個平台真的可能存在的。
SUPPORTED = ("firefox", "chrome", "edge", "brave", "opera", "vivaldi")

_MISSING = "missing"          # 找不到瀏覽器設定檔
_LOCKED = "locked"            # 找得到但解不開（DPAPI／App-Bound Encryption）
_ERROR = "error"              # 其他錯誤
_READY = "ready"              # 讀得到，而且有 B 站登入狀態
_NO_SESSION = "no_session"    # 讀得到，但沒有登入 B 站
_LABELS = {
    "firefox": "Firefox",
    "chrome": "Chrome",
    "edge": "Edge",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
}


def _extract(browser: str):
    """把 yt-dlp 的 cookie 讀取包起來，方便測試替換（也會延遲匯入）。"""
    from yt_dlp.cookies import extract_cookies_from_browser

    return extract_cookies_from_browser(browser)


def _classify(error: Exception) -> str:
    text = str(error).lower()
    if isinstance(error, FileNotFoundError):
        return _MISSING
    if "decrypt" in text or "dpapi" in text or "app-bound" in text:
        return _LOCKED
    if "could not find" in text or "no such file" in text:
        return _MISSING
    return _ERROR


def _sessdata(jar: Iterable) -> str:
    """從 jar 裡挑出 bilibili 網域的 SESSDATA；沒有就回空字串。"""
    for cookie in jar:
        if getattr(cookie, "name", "") == "SESSDATA" and "bilibili" in getattr(cookie, "domain", ""):
            return str(getattr(cookie, "value", "") or "")
    return ""


def probe() -> list[dict]:
    """回報每個瀏覽器的狀態，讓設定頁只列出真的能用的那幾個。

    state：ready / no_session / locked / missing / error
    """
    result = []
    for browser in SUPPORTED:
        try:
            jar = _extract(browser)
        except Exception as exc:  # noqa: BLE001 - 任何失敗都只是一種狀態
            result.append({"browser": browser, "label": _LABELS[browser], "state": _classify(exc)})
            continue
        has = bool(_sessdata(jar))
        result.append({"browser": browser, "label": _LABELS[browser],
                       "state": _READY if has else _NO_SESSION})
    return result


def read_sessdata(browser: str) -> str:
    """讀出指定瀏覽器的 B 站 SESSDATA；失敗時丟 ValueError（訊息給使用者看）。"""
    if browser not in SUPPORTED:
        raise ValueError("browser_unsupported")
    try:
        jar = _extract(browser)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(_classify(exc)) from exc
    value = _sessdata(jar)
    if not value:
        raise ValueError(_NO_SESSION)
    return value


def is_supported(browser: str) -> bool:
    return browser in SUPPORTED


def label(browser: str) -> str:
    return _LABELS.get(browser, browser)
