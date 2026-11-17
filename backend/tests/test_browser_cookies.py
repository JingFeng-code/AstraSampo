"""瀏覽器 cookie 讀取：不碰真實瀏覽器資料，全部用假的 cookie jar 驗證分類與訊息。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import settings as api_settings
from app.main import app
from app.transcript import browser_cookies

LOCAL = "http://127.0.0.1:8420"
CLEAN_ENV = {"ASTRA_DESKTOP_TOKEN": "", "CODESPACE_NAME": "", "ASTRA_DESKTOP_DATA_DIR": "",
             "ASTRA_ALLOWED_ORIGINS": "", "ASTRA_ALLOWED_HOSTS": ""}


def local_client() -> TestClient:
    """端點現在會檢查 request.client，測試要走真正的 HTTP 層（不能用假 request）。"""
    return TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000))


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
    with patch.dict(os.environ, CLEAN_ENV), \
         patch.object(browser_cookies, "_extract",
                      return_value=_jar(FakeCookie("SESSDATA", ".bilibili.com", "tok123"))), \
         patch.object(api_settings.config, "save", side_effect=lambda updates: saved.update(updates)), \
         patch.object(api_settings, "_public_state", return_value={"ok": True}):
        res = local_client().post("/settings/bilibili-cookie", json={"browser": "firefox"})
    assert res.status_code == 200, res.text
    assert saved == {"BILIBILI_SESSDATA": "tok123"}
    assert res.json() == {"ok": True}


def test_import_endpoint_explains_locked_browser():
    with patch.dict(os.environ, CLEAN_ENV), \
         patch.object(browser_cookies, "_extract", side_effect=RuntimeError("Failed to decrypt with DPAPI")):
        res = local_client().post("/settings/bilibili-cookie", json={"browser": "edge"})
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "加密" in detail or "App-Bound" in detail


def test_import_endpoint_rejects_remote_requests():
    with patch.dict(os.environ, CLEAN_ENV), \
         patch.object(browser_cookies, "_extract") as extract:
        remote = TestClient(app, base_url=LOCAL, client=("192.168.1.20", 50000))
        assert remote.post("/settings/bilibili-cookie", json={"browser": "firefox"}).status_code == 403
        assert remote.get("/settings/bilibili-browsers").status_code == 403
    assert extract.call_count == 0


if __name__ == "__main__":
    test_reads_bilibili_sessdata()
    test_other_sites_sessdata_is_ignored()
    test_missing_locked_and_no_session_are_classified()
    test_probe_reports_a_state_for_every_browser()
    test_import_endpoint_saves_sessdata()
    test_import_endpoint_explains_locked_browser()
    test_import_endpoint_rejects_remote_requests()
    print("Browser cookie tests passed")
