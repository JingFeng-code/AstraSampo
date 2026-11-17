"""讀取瀏覽器登入狀態只接受這台電腦上的請求。

/settings/bilibili-browsers 與 /settings/bilibili-cookie 會打開本機瀏覽器的
cookie 資料庫；遠端環境（Codespaces）或其他機器不能觸發。
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api import settings as settings_api
from app.main import app

LOCAL = "http://127.0.0.1:8420"
CLEAN_ENV = {"ASTRA_DESKTOP_TOKEN": "", "CODESPACE_NAME": "", "ASTRA_DESKTOP_DATA_DIR": "",
             "ASTRA_ALLOWED_ORIGINS": "", "ASTRA_ALLOWED_HOSTS": ""}


def client(host: str = "127.0.0.1") -> TestClient:
    return TestClient(app, base_url=LOCAL, client=(host, 50000))


def test_remote_host_cannot_probe_or_import_cookies():
    saved = []
    with patch.dict(os.environ, CLEAN_ENV), \
            patch.object(settings_api.browser_cookies, "probe", return_value=[]), \
            patch.object(settings_api.browser_cookies, "read_sessdata", return_value="x" * 16) as read, \
            patch.object(settings_api.config, "save", lambda updates: saved.append(updates)):
        remote = client("192.168.1.20")
        assert remote.get("/settings/bilibili-browsers").status_code == 403
        assert remote.post("/settings/bilibili-cookie", json={"browser": "firefox"}).status_code == 403
        assert read.call_count == 0, "遠端請求不能讀本機 cookie"
        assert saved == [], "遠端請求不能寫入設定"

        # 本機請求行為不變
        local = client()
        assert local.get("/settings/bilibili-browsers").status_code == 200
        assert local.post("/settings/bilibili-cookie", json={"browser": "firefox"}).status_code == 200
        assert saved and saved[-1]["BILIBILI_SESSDATA"] == "x" * 16


def test_codespaces_is_treated_as_remote():
    with patch.dict(os.environ, {**CLEAN_ENV, "CODESPACE_NAME": "codespaces-abc"}), \
            patch.object(settings_api.browser_cookies, "probe", return_value=[]) as probe:
        assert client().get("/settings/bilibili-browsers").status_code == 403
        assert client().post("/settings/bilibili-cookie", json={"browser": "firefox"}).status_code == 403
    assert probe.call_count == 0


if __name__ == "__main__":
    test_remote_host_cannot_probe_or_import_cookies()
    test_codespaces_is_treated_as_remote()
    print("Bilibili cookie access tests passed")
