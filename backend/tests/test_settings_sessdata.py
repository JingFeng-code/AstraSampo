"""SESSDATA 的清除與保存。

使用者必須能明確刪掉登入憑證；一般儲存（欄位空白、payload 不帶這個欄位）不能誤刪。
"""
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import config
from app.main import app
from app.transcript import bilibili

LOCAL = "http://127.0.0.1:8420"
CLEAN_ENV = {"ASTRA_DESKTOP_TOKEN": "", "CODESPACE_NAME": "", "ASTRA_DESKTOP_DATA_DIR": "",
             "ASTRA_ALLOWED_ORIGINS": "", "ASTRA_ALLOWED_HOSTS": ""}
SESSDATA = "abc123def456"


def client() -> TestClient:
    return TestClient(app, base_url=LOCAL)


def test_clearing_sessdata_needs_an_explicit_empty_string():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        path = Path(tmp) / "settings.json"
        with patch.object(config, "_SETTINGS_PATH", path), \
                patch.dict(config._cache, config.all_settings(), clear=True):
            c = client()
            assert c.post("/settings", json={"bilibili_sessdata": SESSDATA}).status_code == 200
            assert c.get("/settings").json()["bilibili_sessdata_set"] is True
            assert json.loads(path.read_text(encoding="utf-8"))["BILIBILI_SESSDATA"] == SESSDATA

            cleared = c.post("/settings", json={"bilibili_sessdata": ""})
            assert cleared.status_code == 200, cleared.text
            state = c.get("/settings").json()
            assert state["bilibili_sessdata_set"] is False
            assert config.get("BILIBILI_SESSDATA") == ""
            saved = json.loads(path.read_text(encoding="utf-8"))
            # 空字串要留在 settings.json：它負責蓋掉 .env 裡的舊值，但已不含任何憑證
            assert saved.get("BILIBILI_SESSDATA") == ""
            assert SESSDATA not in path.read_text(encoding="utf-8")


def test_saving_without_the_field_keeps_the_saved_sessdata():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        path = Path(tmp) / "settings.json"
        with patch.object(config, "_SETTINGS_PATH", path), \
                patch.dict(config._cache, config.all_settings(), clear=True):
            c = client()
            c.post("/settings", json={"bilibili_sessdata": SESSDATA})
            # 一般儲存：payload 根本沒帶這個欄位（欄位空白時的現行行為）
            assert c.post("/settings", json={"ui_language": "en"}).status_code == 200
            assert c.post("/settings", json={"bilibili_sessdata": None}).status_code == 200
            assert c.get("/settings").json()["bilibili_sessdata_set"] is True
            assert config.get("BILIBILI_SESSDATA") == SESSDATA


def test_cleared_sessdata_is_not_sent_to_bilibili():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        path = Path(tmp) / "settings.json"
        with patch.object(config, "_SETTINGS_PATH", path), \
                patch.dict(config._cache, config.all_settings(), clear=True):
            c = client()
            captured = []

            def fake_api_json(path_, params, referer, cookie=None):
                captured.append(cookie)
                if path_.endswith("/x/web-interface/view"):
                    return {"pages": [{"cid": 123, "page": 1, "part": "P1"}]}
                return {"subtitle": {"subtitles": []}}

            with patch.object(bilibili, "_api_json", fake_api_json):
                c.post("/settings", json={"bilibili_sessdata": SESSDATA})
                try:
                    bilibili.fetch_transcript_detail("BV1jhns6DEzi", 1, config.get("BILIBILI_SESSDATA"))
                except ValueError:
                    pass
                assert captured and all(cookie == {"Cookie": f"SESSDATA={SESSDATA}"} for cookie in captured)

                c.post("/settings", json={"bilibili_sessdata": ""})
                captured.clear()
                try:
                    bilibili.fetch_transcript_detail("BV1jhns6DEzi", 1, config.get("BILIBILI_SESSDATA"))
                except ValueError:
                    pass
            assert captured, "至少要問過 API"
            assert all(cookie == {} for cookie in captured), "清除後不得再帶 Cookie 標頭"


if __name__ == "__main__":
    test_clearing_sessdata_needs_an_explicit_empty_string()
    test_saving_without_the_field_keeps_the_saved_sessdata()
    test_cleared_sessdata_is_not_sent_to_bilibili()
    print("Settings SESSDATA tests passed")
