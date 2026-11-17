"""/notes：列出 Obsidian vault 內的資料夾與筆記，並把摘要存成 .md。"""
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.api.local_video import on_this_computer
from app.core import config, messages
from app.models.schemas import ExportNoteRequest, SaveNoteRequest

router = APIRouter(prefix="/notes", tags=["notes"])

# 略過的系統/隱藏資料夾
_SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules"}


def _notes_folder() -> str:
    return config.get("OBSIDIAN_NOTES_FOLDER") or "Youtube Card Reader"


def _vault_root():
    p = config.get("OBSIDIAN_VAULT_PATH")
    if not p:
        return None
    return Path(p)


def _safe_relpath(rel: str) -> Path:
    """把使用者給的相對資料夾路徑清乾淨，移除 .. 與非法字元，避免跳出 vault。"""
    rel = (rel or "").replace("\\", "/")
    parts = []
    for seg in rel.split("/"):
        seg = re.sub(r'[:*?"<>|]', "", seg).strip().strip(".")
        if seg and seg not in ("", ".", ".."):
            parts.append(seg)
    return Path(*parts) if parts else Path()


def _safe_name(name: str) -> str:
    """新筆記檔名（不含副檔名）。"""
    name = re.sub(r'[\\/:*?"<>|]', "", name or "").strip()
    return name[:120] or datetime.now().strftime(messages.t("notes.default_filename"))


def _safe_filename(name: str) -> str:
    """現有筆記檔名（保留 .md），只取最後一段，防止路徑跳脫。"""
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r'[:*?"<>|]', "", name).strip()
    if not name.lower().endswith(".md"):
        name += ".md"
    return name


# 匯出上限：整份筆記是模型輸出，正常只有幾十 KB；2 MB 足夠，也避免被拿來寫大檔
_EXPORT_LIMIT = 2 * 1024 * 1024
_EXPORT_FOLDER = "AstraTube"


# Windows 的「下載」可能被搬到別的磁碟或 OneDrive，寫死 ~/Downloads 會在使用者目錄
# 另外生出一個資料夾，使用者反而在檔案總管的「下載」找不到檔案。
_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"


def _windows_downloads_folder():
    """用 Known Folder API 問 Windows「下載」的真實位置；拿不到就回 None。"""
    try:
        import ctypes
        from ctypes import wintypes
        from uuid import UUID
    except Exception:  # 非 Windows 或精簡版 Python
        return None

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    folder = UUID(_FOLDERID_DOWNLOADS)
    folder_id = GUID(folder.fields[0], folder.fields[1], folder.fields[2],
                     (ctypes.c_ubyte * 8)(*folder.bytes[8:]))
    path_ptr = ctypes.c_wchar_p()
    try:
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr))
    except Exception:
        return None
    if result != 0:
        return None
    try:
        return Path(path_ptr.value) if path_ptr.value else None
    finally:
        try:
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
        except Exception:
            pass


def _downloads_root() -> Path:
    if os.name == "nt":
        folder = _windows_downloads_folder()
        if folder is not None:
            return folder
    return Path.home() / "Downloads"


def _exports_root() -> Path:
    """「下載」不能寫時的退路：程式自己的資料夾（桌面版會指向使用者資料目錄）。"""
    data = os.environ.get("ASTRA_DESKTOP_DATA_DIR")
    return (Path(data) if data else Path(__file__).resolve().parents[3]) / "exports"


# 控制字元（含 NUL、換行、Tab）會讓部分平台的開檔直接失敗；它們不是檔名的一部分
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

def _export_name(name: str) -> str:
    """匯出檔名：只取名稱本身（不含路徑與副檔名），長度留給「 (2)」這種後綴。"""
    base = _safe_name(_CONTROL_CHARS.sub("", name or "").replace(os.sep, " ").replace("/", " "))
    if base.lower().endswith(".md"):
        base = base[:-3]
    # Windows 不接受結尾的點與空白，清掉以免寫檔直接失敗
    base = base.strip().rstrip(". ")
    return base[:110] or "AstraTube-notes"


# 同名上限：正常情況不會撞這麼多；上限只是避免無限重試
_EXPORT_RETRIES = 1000


def _candidate_path(folder: Path, base: str, attempt: int) -> Path:
    """第 attempt 個候選路徑（1 是原名，之後依序加 (2)、(3)…），一律確認在目標資料夾內。"""
    name = f"{base}.md" if attempt == 1 else f"{base} ({attempt}).md"
    return _ensure_within(folder, folder / name)


def _write_export(folder: Path, base: str, text: str) -> Path:
    """以排他模式建立檔案。

    先「檢查有沒有同名、再寫檔」會有時間差：兩個匯出幾乎同時進來時會挑到同一個路徑，
    後寫的把先寫的截斷。改用 open(..., "x") 讓作業系統保證只有一個成功，撞到就換下一個後綴。
    """
    folder.mkdir(parents=True, exist_ok=True)
    payload = text if text.endswith("\n") else text + "\n"
    for attempt in range(1, _EXPORT_RETRIES + 1):
        path = _candidate_path(folder, base, attempt)
        try:
            handle = open(path, "x", encoding="utf-8", newline="")
        except FileExistsError:
            continue
        try:
            with handle:
                handle.write(payload)
        except BaseException:
            # 寫到一半失敗：把自己剛建立的空檔／半檔刪掉，不要留下壞檔案
            try:
                path.unlink()
            except OSError:
                pass
            raise
        return path
    raise HTTPException(500, messages.t("notes.export_too_many"))


def _ensure_within(root: Path, target: Path) -> Path:
    """確認 target 確實在 vault 內，否則拒絕。"""
    root_r = root.resolve()
    target_r = target.resolve()
    if target_r != root_r and root_r not in target_r.parents:
        raise HTTPException(400, messages.t("notes.path_outside_vault"))
    return target_r


@router.get("/status")
def status():
    folder = _notes_folder()
    root = _vault_root()
    if root is None:
        return {"configured": False, "path": None, "exists": False, "default_folder": folder}
    note_dir = root / _safe_relpath(folder)
    return {
        "configured": True,
        "path": str(note_dir),
        "exists": root.exists(),
        "default_folder": folder,
    }


@router.get("/folders")
def folders():
    """列出 vault 內所有可用資料夾（相對路徑，"" 代表 vault 根目錄）。"""
    root = _vault_root()
    if root is None or not root.exists():
        return {"folders": [], "default": _notes_folder()}
    result = []
    for dirpath, dirnames, _ in os.walk(root):
        # 原地修改 dirnames 以剪枝，跳過隱藏與系統資料夾
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        result.append("" if rel == "." else rel.replace("\\", "/"))
    # 確保預設資料夾一定在清單中
    default_rel = str(_safe_relpath(_notes_folder())).replace("\\", "/")
    if default_rel and default_rel not in result:
        result.append(default_rel)
    return {"folders": sorted(set(result), key=lambda s: (s != default_rel, s.lower())), "default": default_rel}


@router.get("/files")
def files(folder: str = ""):
    """列出指定資料夾內的 .md 筆記檔名。"""
    root = _vault_root()
    if root is None or not root.exists():
        return {"files": []}
    d = root / _safe_relpath(folder)  # folder="" 代表 vault 根目錄
    if not d.exists() or not d.is_dir():
        return {"files": []}
    fs = sorted(
        (p.name for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".md"),
        key=str.lower,
    )
    return {"files": fs}


@router.post("/export")
def export_note(req: ExportNoteRequest, request: Request) -> dict:
    """把 Markdown 存進使用者的下載資料夾。

    桌面版（Tauri／WebView2）沒有瀏覽器的下載管理員，前端用 <a download> 按了不會有檔案，
    所以寫檔這件事必須由後端做；也只接受這台電腦上的請求，不讓遠端服務寫入本機檔案。
    """
    client = request.client.host if request.client else None
    if not on_this_computer(client, request.headers.get("origin")):
        raise HTTPException(403, messages.t("notes.export_local_only"))
    text = req.markdown or ""
    if len(text.encode("utf-8")) > _EXPORT_LIMIT:
        raise HTTPException(413, messages.t("notes.export_too_large"))
    base = _export_name(req.filename)
    try:
        path = _write_export(_downloads_root() / _EXPORT_FOLDER, base, text)
        return {"saved_to": str(path), "fallback": False}
    except (OSError, ValueError):
        # 免安裝版或受控環境可能不能寫「下載」資料夾：改存程式資料夾並在畫面說明
        try:
            path = _write_export(_exports_root(), base, text)
            return {"saved_to": str(path), "fallback": True}
        except (OSError, ValueError) as exc:
            raise HTTPException(500, messages.t("notes.export_failed", error=str(exc))) from exc


@router.post("/save")
def save(req: SaveNoteRequest):
    root = _vault_root()
    if root is None:
        raise HTTPException(400, messages.t("notes.vault_not_set"))
    if not root.exists():
        raise HTTPException(400, messages.t("notes.vault_missing"))

    folder_dir = root / _safe_relpath(req.folder)  # folder="" 代表 vault 根目錄
    _ensure_within(root, folder_dir)

    if req.mode == "append" and req.target_file:
        path = folder_dir / _safe_filename(req.target_file)
        _ensure_within(root, path)
        if not path.exists():
            raise HTTPException(400, messages.t("notes.target_missing"))
        with path.open("a", encoding="utf-8") as f:
            f.write("\n\n" + req.content.rstrip() + "\n")
        return {"ok": True, "saved_to": str(path), "mode": "append"}

    # 新增筆記（自動避開同名檔）
    folder_dir.mkdir(parents=True, exist_ok=True)
    base = _safe_name(req.filename)
    path = folder_dir / f"{base}.md"
    _ensure_within(root, path)
    i = 2
    while path.exists():
        path = folder_dir / f"{base} {i}.md"
        i += 1
    path.write_text(req.content.rstrip() + "\n", encoding="utf-8")
    return {"ok": True, "saved_to": str(path), "mode": "new"}
