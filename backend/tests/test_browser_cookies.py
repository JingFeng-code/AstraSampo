"""瀏覽器 cookie 讀取：不碰真實瀏覽器資料，全部用假的 cookie jar 驗證分類與訊息。"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import settings as api_settings
from app.models.schemas import BrowserCookieRequest
from app.transcript import browser_cookies


class FakeCookie:
    def __init__(self, name, domain, value="abc"):
        self.name = name
        self.domain = domain
        self.value = value


def _jar(*cookies):
    return list(cookies)


def test_reads_bilibili_sessdata():
    jar = _jar(FakeCookie("buvid3", ".bilibili.com"), FakeCookie("SESSDATA", ".bilibili.com", "s3cr3t"))
    with patch.object(browser_cookies, "_extract", return_value=jar):
        assert browser_cookies.read_sessdata("firefox") == "s3cr3t"


def test_other_sites_sessdata_is_ignored():
    jar = _jar(FakeCookie("SESSDATA", ".example.com", "nope"))
    with patch.object(browser_cookies, "_extract", return_value=jar):
        try:
            browser_cookies.read_sessdata("firefox")
            assert False, "cookies from other domains must not be used"
        except ValueError as exc:
            assert str(exc) == "no_session"


def test_missing_locked_and_no_session_are_classified():
    cases = [
        (FileNotFoundError("could not find chrome cookies database"), "missing"),
        (RuntimeError("Failed to decrypt with DPAPI"), "locked"),
        (RuntimeError("something odd"), "error"),
    ]
    for error, expected in cases:
        with patch.object(browser_cookies, "_extract", side_effect=error):
            try:
                browser_cookies.read_sessdata("chrome")
                assert False, "must raise"
            except ValueError as exc:
                assert str(exc) == expected, (error, str(exc))


def test_probe_reports_a_state_for_every_browser():
    def fake_extract(browser):
        if browser == "firefox":
            return _jar(FakeCookie("SESSDATA", ".bilibili.com", "v"))
        if browser == "chrome":
            raise FileNotFoundError("could not find chrome cookies database")
        if browser == "edge":
            raise RuntimeError("Failed to decrypt with DPAPI")
        return _jar(FakeCookie("buvid3", ".bilibili.com"))

    with patch.object(browser_cookies, "_extract", side_effect=fake_extract):
        states = {row["browser"]: row["state"] for row in browser_cookies.probe()}
    assert states["firefox"] == "ready"
    assert states["chrome"] == "missing"
    assert states["edge"] == "locked"
    assert states["brave"] == "no_session"


def test_import_endpoint_saves_sessdata():
    saved = {}
    with patch.object(browser_cookies, "_extract",
                      return_value=_jar(FakeCookie("SESSDATA", ".bilibili.com", "tok123"))), \
         patch.object(api_settings.config, "save", side_effect=lambda updates: saved.update(updates)), \
         patch.object(api_settings.config, "get", return_value=""), \
         patch.object(api_settings, "_public_state", return_value={"ok": True}):
        state = api_settings.import_bilibili_cookie(BrowserCookieRequest(browser="firefox"))
    assert saved == {"BILIBILI_SESSDATA": "tok123"}
    assert state == {"ok": True}


def test_import_endpoint_explains_locked_browser():
    with patch.object(browser_cookies, "_extract", side_effect=RuntimeError("Failed to decrypt with DPAPI")):
        try:
            api_settings.import_bilibili_cookie(BrowserCookieRequest(browser="edge"))
            assert False, "locked browser must fail with a readable message"
        except Exception as exc:  # HTTPException
            detail = str(getattr(exc, "detail", exc))
            assert "加密" in detail or "App-Bound" in detail


if __name__ == "__main__":
    test_reads_bilibili_sessdata()
    test_other_sites_sessdata_is_ignored()
    test_missing_locked_and_no_session_are_classified()
    test_probe_reports_a_state_for_every_browser()
    test_import_endpoint_saves_sessdata()
    test_import_endpoint_explains_locked_browser()
    print("Browser cookie tests passed")
