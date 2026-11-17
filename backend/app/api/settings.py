"""/settings：讀取與更新使用者設定（金鑰只回遮罩預覽，不外洩完整內容）。"""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.api.local_video import on_this_computer
from app.core import config, languages, messages
from app.llm import ollama
from app.models.schemas import BrowserCookieRequest, SettingsUpdate
from app.transcript import browser_cookies

router = APIRouter(prefix="/settings", tags=["settings"])

_DEFAULT_FOLDER = "Youtube Card Reader"

# 設定畫面上的金鑰欄位：(API 欄位名, config 欄位名)
_KEY_FIELDS = (
    ("gemini_api_key", "GEMINI_API_KEY"),
    ("opencode_api_key", "OPENCODE_API_KEY"),
    ("deepseek_api_key", "DEEPSEEK_API_KEY"),
    ("openai_api_key", "OPENAI_API_KEY"),
    ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    ("openrouter_api_key", "OPENROUTER_API_KEY"),
    ("groq_api_key", "GROQ_API_KEY"),
    ("mistral_api_key", "MISTRAL_API_KEY"),
    ("together_api_key", "TOGETHER_API_KEY"),
    ("ollama_cloud_api_key", "OLLAMA_CLOUD_API_KEY"),
)


def _mask(key: str) -> str:
    """回傳遮罩後的金鑰預覽。"""
    key = key or ""
    if not key:
        return ""
    if len(key) <= 8:
        return "••••"
    return f"{key[:4]}••••{key[-4:]}"


def _public_state() -> dict:
    """對前端公開的設定狀態（不含完整金鑰）。"""
    g = config.get("GEMINI_API_KEY")
    g_keys = [k for k in re.split(r"[,\s]+", (g or "").strip()) if k]
    vault = config.get("OBSIDIAN_VAULT_PATH")
    folder = config.get("OBSIDIAN_NOTES_FOLDER") or _DEFAULT_FOLDER

    state: dict = {
        # Gemini 支援多把金鑰，預覽文字要反映把數
        "gemini_key_count": len(g_keys),
        # Obsidian 路徑非機密，完整回傳以便設定畫面預填
        "obsidian_vault_path": vault,
        "obsidian_notes_folder": folder,
        "obsidian_set": bool(vault),
        "obsidian_exists": bool(vault) and Path(vault).expanduser().exists(),
        "output_language": config.get("OUTPUT_LANGUAGE") or languages.DEFAULT,
        "ui_language": config.get("UI_LANGUAGE") or "zh-Hant",
        "ollama_base_url": config.get("OLLAMA_BASE_URL") or ollama.DEFAULT_BASE_URL,
        "ollama_model": config.get("OLLAMA_MODEL") or "",
        "languages": languages.codes(),
    }
    for api_field, cfg_field in _KEY_FIELDS:
        name = api_field.removesuffix("_api_key")
        raw = config.get(cfg_field)
        state[f"{name}_set"] = bool(raw)
        state[f"{name}_preview"] = (messages.t("settings.key_count", count=len(g_keys))
                                    if name == "gemini" and len(g_keys) > 1 else _mask(raw))
    # 回傳金鑰是否已設定（不代表驗證通過）；無金鑰仍可使用本機 Ollama。
    state["configured"] = any(state[f"{f.removesuffix('_api_key')}_set"] for f, _ in _KEY_FIELDS)
    # B 站 cookie 不是 AI 金鑰：有自己的欄位，也不影響上面的 `configured`。
    sessdata = config.get("BILIBILI_SESSDATA")
    state["bilibili_sessdata_set"] = bool(sessdata)
    state["bilibili_sessdata_preview"] = _mask(sessdata)
    return state


def _require_this_computer(request: Request) -> None:
    """讀取瀏覽器 cookie 只在這台電腦上有意義；遠端請求一律拒絕。"""
    client = request.client.host if request.client else None
    if not on_this_computer(client, request.headers.get("origin")):
        raise HTTPException(403, messages.t("settings.local_only"))


@router.get("/bilibili-browsers")
def get_bilibili_browsers(request: Request) -> dict:
    """列出這台機器上讀得到／讀不到 B 站登入狀態的瀏覽器。"""
    _require_this_computer(request)
    return {"browsers": browser_cookies.probe()}


@router.post("/bilibili-cookie")
def import_bilibili_cookie(req: BrowserCookieRequest, request: Request) -> dict:
    """從使用者自己的瀏覽器讀出 SESSDATA 並存到本機設定（不代替使用者登入）。"""
    _require_this_computer(request)
    name = browser_cookies.label(req.browser)
    try:
        value = browser_cookies.read_sessdata(req.browser)
    except ValueError as exc:
        code = str(exc)
        key = {
            "missing": "settings.cookie_missing",
            "locked": "settings.cookie_locked",
            "no_session": "settings.cookie_no_session",
        }.get(code, "settings.cookie_error")
        raise HTTPException(400, messages.t(key, browser=name, error=code)) from exc
    if (len(value) > 512 or any(ord(ch) < 32 for ch in value)
            or ";" in value or "," in value):
        raise HTTPException(400, messages.t("settings.bilibili_sessdata_invalid"))
    config.save({"BILIBILI_SESSDATA": value})
    return _public_state()


@router.get("")
def get_settings() -> dict:
    return _public_state()


@router.post("")
def update_settings(req: SettingsUpdate) -> dict:
    """只更新有提供的欄位；金鑰缺席代表維持原值。"""
    updates: dict[str, str] = {}
    for api_field, cfg_field in _KEY_FIELDS:
        value = getattr(req, api_field, None)
        if value is not None:
            updates[cfg_field] = value.strip()
    if req.ollama_base_url is not None:
        try:
            updates["OLLAMA_BASE_URL"] = ollama.validate_base_url(req.ollama_base_url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if req.ollama_model is not None:
        try:
            updates["OLLAMA_MODEL"] = (ollama.validate_model(req.ollama_model)
                                       if req.ollama_model.strip() else "")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if req.obsidian_vault_path is not None:
        updates["OBSIDIAN_VAULT_PATH"] = req.obsidian_vault_path.strip()
    if req.obsidian_notes_folder is not None:
        updates["OBSIDIAN_NOTES_FOLDER"] = req.obsidian_notes_folder.strip()
    if req.output_language is not None:
        # 不認得的語言代碼一律回退預設，避免前端送錯值就讓 prompt 壞掉
        updates["OUTPUT_LANGUAGE"] = languages.get(req.output_language).code
    if req.bilibili_sessdata is not None:
        # 只留 cookie 值本身；換行／分號／逗號都視為貼錯（整段 Cookie 標頭會被拒絕）
        value = req.bilibili_sessdata.strip()
        if (len(value) > 512 or any(ord(ch) < 32 for ch in value)
                or ";" in value or "," in value):
            raise HTTPException(400, messages.t("settings.bilibili_sessdata_invalid"))
        updates["BILIBILI_SESSDATA"] = value
    if req.ui_language is not None:
        # 介面語言只有兩種；認不出來就當繁中，config 那層也會再擋一次
        updates["UI_LANGUAGE"] = req.ui_language if req.ui_language in ("zh-Hant", "en") else "zh-Hant"
    try:
        config.save(updates)
    except RuntimeError as e:
        raise HTTPException(500, messages.t("settings.save_failed", error=e))
    return _public_state()
