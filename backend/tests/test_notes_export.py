"""桌面版匯出 Markdown：檔案只能落在目標資料夾、不覆蓋既有檔、只接受本機請求。

測試一律用暫存資料夾假裝「下載」與程式資料夾，不碰使用者真正的下載夾。
"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api import notes
from app.main import app

LOCAL = "http://127.0.0.1:8420"
# 遠端環境與桌面資料夾的變數要清掉，否則本機判斷會受執行測試的機器影響
CLEAN_ENV = {"ASTRA_DESKTOP_TOKEN": "", "CODESPACE_NAME": "", "ASTRA_DESKTOP_DATA_DIR": "",
             "ASTRA_ALLOWED_ORIGINS": "", "ASTRA_ALLOWED_HOSTS": ""}


def client(host: str = "127.0.0.1") -> TestClient:
    # 後端用 request.client.host 判斷是否本機，TestClient 預設不是回環位址
    return TestClient(app, base_url=LOCAL, client=(host, 50000))


def make_roots(base: Path):
    """回傳會把下載資料夾／退路資料夾指到暫存目錄的 patch 們。"""
    return patch.multiple(notes,
                          _downloads_root=lambda: base / "Downloads",
                          _exports_root=lambda: base / "program" / "exports")


def post_export(c: TestClient, filename: str, markdown: str):
    return c.post("/notes/export", json={"filename": filename, "markdown": markdown})


def test_normal_export_writes_utf8_file_in_downloads():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        with make_roots(base):
            res = post_export(client(), "我的筆記", "# 標題\n\n中文內容不會亂碼")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["fallback"] is False
        saved = Path(body["saved_to"])
        assert saved == base / "Downloads" / "AstraTube" / "我的筆記.md"
        assert saved.read_text(encoding="utf-8") == "# 標題\n\n中文內容不會亂碼\n"


def test_same_name_does_not_overwrite():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        with make_roots(base):
            c = client()
            first = post_export(c, "重點整理", "第一次")
            second = post_export(c, "重點整理", "第二次")
            third = post_export(c, "重點整理", "第三次")
        assert first.status_code == second.status_code == third.status_code == 200
        paths = [Path(r.json()["saved_to"]) for r in (first, second, third)]
        assert len(set(paths)) == 3
        assert paths[1].name == "重點整理 (2).md"
        assert paths[2].name == "重點整理 (3).md"
        assert paths[0].read_text(encoding="utf-8") == "第一次\n", "既有檔案不得被覆蓋"


def test_hostile_filenames_stay_inside_target_folder():
    names = ["..\\..\\evil", "../../evil", "C:\\Windows\\evil", "a:b*c?d|e", "..", "   ",
             "x" * 400, "con", "note.md", "note.MD",
             # 控制字元不是檔名的一部分；開檔會失敗，後端要自己清掉（不是靠前端）
             "a\x00b", "line1\nline2", "\x1f\x07bell", "\x7fdel"]
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        folder = base / "Downloads" / "AstraTube"
        with make_roots(base):
            c = client()
            saved = []
            for name in names:
                res = post_export(c, name, "內容")
                assert res.status_code == 200, (name, res.text)
                path = Path(res.json()["saved_to"])
                assert path.parent == folder, (name, path)
                assert path.name.endswith(".md") and path.name.count(".md") == 1, path.name
                assert "/" not in path.name and "\\" not in path.name and ":" not in path.name
                assert not any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in path.name), repr(path.name)
                assert len(path.name) <= 120, (name, len(path.name))
                saved.append(path)
        assert len(set(saved)) == len(names), "同名清理後也不能互相覆蓋"
        assert all(p.read_text(encoding="utf-8") == "內容\n" for p in saved)


def test_oversized_markdown_is_rejected():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        with make_roots(base):
            res = post_export(client(), "太大", "a" * (2 * 1024 * 1024 + 1))
        assert res.status_code == 413
        assert not (base / "Downloads").exists(), "被拒絕的請求不應該留下任何檔案"


def test_only_requests_from_this_computer_are_accepted():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        with make_roots(base):
            remote = client("192.168.1.20")
            assert post_export(remote, "note", "內容").status_code == 403
            assert post_export(client(), "note", "內容").status_code == 200
        with patch.dict(os.environ, {**CLEAN_ENV, "CODESPACE_NAME": "codespaces-abc"}):
            assert post_export(client(), "note", "內容").status_code == 403
        assert not (base / "program" / "exports").exists()


def test_downloads_folder_uses_windows_known_folder_when_available():
    """Windows 的「下載」可能不在 ~/Downloads；使用者搬過資料夾時要跟著搬。"""
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        real = base / "OneDrive" / "下載"
        with patch.object(notes.os, "name", "nt"), patch.object(notes, "_windows_downloads_folder", lambda: real):
            assert notes._downloads_root() == real
        # 取不到（舊版 Windows／API 失敗）才退回 ~/Downloads
        with patch.object(notes.os, "name", "nt"), \
                patch.object(notes, "_windows_downloads_folder", lambda: None), \
                patch.object(Path, "home", classmethod(lambda cls: base)):
            assert notes._downloads_root() == base / "Downloads"
        # 非 Windows 一律用 ~/Downloads（CI 就是這條路）
        with patch.object(notes.os, "name", "posix"), \
                patch.object(Path, "home", classmethod(lambda cls: base)):
            assert notes._downloads_root() == base / "Downloads"


def test_unwritable_downloads_falls_back_to_program_folder():
    with TemporaryDirectory() as tmp, patch.dict(os.environ, CLEAN_ENV):
        base = Path(tmp)
        blocked = base / "blocked"
        blocked.write_text("這是一個檔案，不能當資料夾", encoding="utf-8")
        with patch.multiple(notes,
                            _downloads_root=lambda: blocked,
                            _exports_root=lambda: base / "program" / "exports"):
            res = post_export(client(), "筆記", "退路")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["fallback"] is True
        saved = Path(body["saved_to"])
        assert saved == base / "program" / "exports" / "筆記.md"
        assert saved.read_text(encoding="utf-8") == "退路\n"


if __name__ == "__main__":
    test_normal_export_writes_utf8_file_in_downloads()
    test_same_name_does_not_overwrite()
    test_hostile_filenames_stay_inside_target_folder()
    test_downloads_folder_uses_windows_known_folder_when_available()
    test_oversized_markdown_is_rejected()
    test_only_requests_from_this_computer_are_accepted()
    test_unwritable_downloads_falls_back_to_program_folder()
    print("Notes export tests passed")
