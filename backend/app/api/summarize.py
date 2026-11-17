"""摘要相關端點：/summarize（一次回全部）、/summarize_stream（NDJSON 串流）、/deepdive。"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from typing import Any, Callable, Iterator, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from json_repair import repair_json

from app.core import config, messages
from app.core.zh import to_traditional
from app.llm import router as llm_router
from app.llm.base import TruncatedOutputError
from app.llm.budget import summary_budget
from app.llm.util import user_error
from app.models.schemas import DeepDiveRequest, SummarizeRequest
from app.prompts.summarize import (deepdive_prompt, deepdive_system,
                                   summarize_prompt, summarize_system,
                                   budget_summarize_prompt, budget_summarize_system,
                                   overview_prompt, overview_system)
from app.services.chunker import MAX_CHUNKS, chunk_content
from app.api.local_video import on_this_computer
from app.transcript.router import Content, route_content

router = APIRouter(tags=["summarize"])


# 模型自己寫的中文欄位要正規化成繁體；transcript_highlight 是逐字引用，保留原文才忠實
_ZH_FIELDS = ("heading", "summary", "visual", "translation", "action_hint")

# 影片類型代碼。決定「下一步」走哪一條 track，前端據此換按鈕文案與 brief 模板
CONTENT_TYPES = ("tutorial", "concept", "interview", "review", "news", "other")

# 模型不一定聽話輸出英文代碼；中文說法映射回代碼，比直接退回 other 更保住資訊
_CT_ALIASES = {
    "教學操作": "tutorial", "教學": "tutorial", "操作": "tutorial", "howto": "tutorial",
    "how-to": "tutorial", "教程": "tutorial",
    "觀念分析": "concept", "觀念": "concept", "分析": "concept", "概念": "concept",
    "訪談對談": "interview", "訪談": "interview", "對談": "interview", "podcast": "interview",
    "評測比較": "review", "評測": "review", "比較": "review", "comparison": "review",
    "新聞資訊": "news", "新聞": "news", "資訊": "news",
}

_TRUTHY = {"true", "yes", "1", "是", "真"}


def _norm_content_type(value: Any) -> str:
    """把模型輸出的類型正規化成固定代碼；認不出來一律 other（絕不讓它擋住解析）。"""
    if not isinstance(value, str):
        return "other"
    v = value.strip()
    if v.lower() in CONTENT_TYPES:
        return v.lower()
    return _CT_ALIASES.get(v, _CT_ALIASES.get(v.lower(), "other"))


def _norm_bool(value: Any) -> bool:
    """模型常把布林寫成字串（"true"／"是"）；一律收斂成真布林，認不出來當 False。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return value == 1


def _pick_content_type(values: list[str]) -> str:
    """多段影片各段可能判成不同類型：取多數決（忽略 other），平手取最先出現的。"""
    votes = [v for v in values if v and v != "other"]
    if not votes:
        return "other"
    return max(dict.fromkeys(votes), key=lambda v: (votes.count(v), -votes.index(v)))


def _parse_cards(raw: str, language: str) -> dict:
    """把模型輸出（可能包 markdown 代碼框、可能有小瑕疵）解析成卡片 JSON。

    輸出語言是繁體中文時順手做簡繁正規化（中國廠商的模型常無視 prompt 吐簡體）；
    其他語言不套這層轉換。content_type／actionable 是後加的欄位，模型漏填是常態，
    一律走正規化補預設值，絕不因為缺欄位就讓整份摘要失敗。
    """
    raw = (raw or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(repair_json(raw)) if raw else None
    except (TypeError, ValueError):
        data = None
    if isinstance(data, list):
        # 有些模型直接回傳卡片陣列，少了外層物件；內容仍可用
        data = {"cards": data}
    # 只輸出思考過程、被截斷到無法修復、或回成其他結構時，要明確告訴使用者，
    # 不能讓後續程式丟出「'list' object has no attribute 'get'」這種看不懂的錯誤。
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        raise ValueError(messages.t("summarize.model_output_invalid"))
    data["cards"] = [card for card in data["cards"] if isinstance(card, dict)]
    if isinstance(data, dict):
        data["title"] = to_traditional(data.get("title"), language)
        data["content_type"] = _norm_content_type(data.get("content_type"))
        for card in data.get("cards") or []:
            for field in _ZH_FIELDS:
                if card.get(field):
                    card[field] = to_traditional(card[field], language)
            card["actionable"] = _norm_bool(card.get("actionable"))
    return data


def _allows_cloud_transcription(provider: str | None) -> bool:
    """只有自動模式或明確選 Gemini 時，字幕失敗才可自動改用 Gemini 雲端轉錄。

    選擇 Ollama 或其他指定模型時，都不能因為設定裡剛好有
    Gemini 金鑰，就默默把影片交給雲端並消耗額度。
    """
    kind, _ = llm_router.parse(provider)
    return kind in (llm_router.AUTO, llm_router.GEMINI)


def _split(content: Content, provider: str | None) -> Tuple[list[str], int]:
    """切段，回傳 (要處理的片段, 超出上限而略過的段數)。

    有額度預算的模型每段都很小，超過段數上限時只處理前段並如實回報，
    不能把多出來的內容塞進最後一段（那一段會大到必定失敗）。
    """
    has_ts = bool(content.get("has_timestamps") or content["type"] == "youtube")
    profile = summary_budget(provider)
    if not profile:
        return chunk_content(content["text"], has_ts), 0
    chunks = chunk_content(content["text"], has_ts, chunk_chars=profile.chunk_chars,
                           merge_overflow=False)
    return chunks[:MAX_CHUNKS], max(0, len(chunks) - MAX_CHUNKS)


def _require_local_audio(req: SummarizeRequest, request: Request | None) -> None:
    """下載影片音訊只在真正跑在這台電腦上的 AstraTube 才接受。"""
    if not req.allow_audio_download:
        return
    client = request.client.host if request and request.client else None
    origin = request.headers.get("origin") if request is not None else None
    if not on_this_computer(client, origin):
        raise HTTPException(403, messages.t("summarize.audio_local_only"))


def _prepare(req: SummarizeRequest) -> Tuple[Content, list[str], bool, int]:
    """擷取內容並切段，回傳 (內容, 片段列表, 是否多段, 略過的段數)。"""
    if not llm_router.is_explicit(req.provider):
        raise HTTPException(400, messages.t("llm.no_provider"))
    try:
        content = route_content(req.url, deep_visual=req.deep_visual,
                                    allow_cloud_fallback=_allows_cloud_transcription(req.provider),
                                    allow_audio_download=req.allow_audio_download)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        # 例外內容可能含本機路徑或上游回應，只留在後端紀錄
        print(f"[summarize] 內容擷取失敗：{e!a}", flush=True)
        raise HTTPException(500, messages.t("summarize.fetch_failed"))

    chunks, skipped = _split(content, req.provider)
    return content, chunks, len(chunks) > 1, skipped


_TS_LINE = re.compile(r"^\[(\d+)\]", re.M)
_VISUAL_LINE = re.compile(r"^【畫面 (\d+):(\d{2})】")


def _last_ts(text: str) -> int:
    """素材中最後（最大）的口說時間戳秒數；沒有時間戳回 0。"""
    ts = _TS_LINE.findall(text)
    return max(map(int, ts)) if ts else 0


def _text_after(text: str, sec: int) -> str:
    """取素材中時間戳 >= sec 之後的行（含其間的【畫面】筆記行）。"""
    out: list[str] = []
    cur = -1
    for line in text.splitlines():
        m = _TS_LINE.match(line)
        if m:
            cur = int(m.group(1))
        else:
            v = _VISUAL_LINE.match(line)
            if v:
                cur = int(v.group(1)) * 60 + int(v.group(2))
        if cur >= sec:
            out.append(line)
    return "\n".join(out)


def _audit_coverage(req: SummarizeRequest, content: Content, chunk: str,
                    index: int, data: dict, model_used: str, language: str,
                    on_status: Callable[[dict[str, Any]], None] | None = None) -> Tuple[dict, str]:
    """覆蓋率稽核：卡片沒蓋到素材尾端就對缺的後段補做（最多 2 輪）。

    防兩種病：模型只整理前半就自報完成（偷懶）、輸出被截斷後 json_repair 靜默閉合。
    """
    cards = data.get("cards") or []
    target = _last_ts(chunk)
    if not target or not cards:
        return data, model_used

    # 只在「明顯偷懶」時補做：容忍尾端 90 秒（最後一張卡的時間戳是起點，本來就不會貼齊尾端），
    # 短段落改用比例容忍。補做一輪就好——每輪都是一次完整的 LLM 呼叫，會直接翻倍等待時間。
    threshold = max(target - 90, target * 0.75)
    labels = [model_used]
    for _ in range(1):
        covered = max((c.get("timestamp_seconds") or 0) for c in cards)
        if covered >= threshold:
            break
        remaining = _text_after(chunk, covered + 1)
        if len(remaining) < 200:
            break
        print(f"[summarize] 覆蓋率不足（卡片到 {covered}s／素材到 {target}s），補做後段…", flush=True)
        if on_status:
            on_status({"state": "coverage"})
        seg: dict[str, Any] = {**content, "text": remaining,
                               "is_segment": True, "is_continuation": True}
        try:
            def report(event: dict[str, Any]) -> None:
                if on_status:
                    on_status({**event, "phase": "coverage"})

            try:
                raw, label = llm_router.generate(req.provider, summarize_prompt(seg, language),
                                                 summarize_system(language), seg=index,
                                                 on_status=report)
            except TruncatedOutputError as e:
                # 補做同樣可能撞到輸出上限：留下修得回來的卡片，並告知這段不完整
                raw, label, data["truncated"] = e.partial, e.label, True
            more = _parse_cards(raw, language)
        except Exception as e:  # noqa: BLE001
            print(f"[summarize] 補做失敗，保留現有卡片：{e}", flush=True)
            break
        new_cards = more.get("cards") or []
        if not new_cards:
            break
        cards = cards + new_cards
        if label and label not in labels:
            labels.append(label)

    data["cards"] = cards
    return data, "、".join(labels)



def _fallback_card(text: str, language: str) -> dict:
    """模型沒有給出任何卡片時，至少把逐字稿本身整理成一張卡。

    短片（例如 1 分鐘的示範）常常被模型判定「沒有可整理的內容」而回空陣列；
    使用者要的是「看得到東西」，而不是一個空白畫面或錯誤。這張卡只做抽取式摘要，
    不冒充 AI 分析，標題會寫明是自動整理。
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    picked = lines[:12]
    body = chr(10).join(picked)[:1500]
    return {"heading": messages.t("summarize.fallback_heading"),
            "summary": body,
            "transcript_highlight": picked[0][:200] if picked else "",
            "actionable": False,
            "fallback": True}


def _build_overview(cards: list[dict], title: str | None, language: str, provider: str | None) -> dict:
    """把一堆卡片收斂成一段整體總結（模型失敗時退回卡片標題，至少不是空的）。"""
    if not cards:
        return {"summary": "", "points": []}
    fallback = {"summary": "",
                "points": [str(c.get("heading") or "").strip() for c in cards[:6] if c.get("heading")]}
    try:
        raw, _model = llm_router.generate(provider, overview_prompt(cards, title, language),
                                          overview_system(language), seg=len(cards) + 1)
        data = json.loads(repair_json(raw)) if raw else None
    except Exception as exc:  # noqa: BLE001
        print(f"[summarize] 總結失敗：{exc}", flush=True)
        return fallback
    if not isinstance(data, dict):
        return fallback
    summary = str(data.get("summary") or "").strip()
    points = [str(point).strip() for point in (data.get("points") or [])
              if str(point).strip()][:6]
    if not summary and not points:
        return fallback
    return {"summary": summary, "points": points}

def _run_segment(req: SummarizeRequest, content: Content, chunk: str,
                 index: int, multi: bool,
                 on_status: Callable[[dict[str, Any]], None] | None = None) -> Tuple[dict, str]:
    """對單一片段做摘要（含覆蓋率稽核），回傳 (卡片 JSON, 模型標籤)。"""
    t0 = time.time()
    language = config.get("OUTPUT_LANGUAGE")
    seg: dict[str, Any] = {**content, "text": chunk, "is_segment": multi}
    profile = summary_budget(req.provider)
    prompt = budget_summarize_prompt(seg, language) if profile else summarize_prompt(seg, language)
    system = budget_summarize_system(language) if profile else summarize_system(language)
    # 輸出上限只屬於摘要的預算，不影響問答、翻譯與實作
    limit = {"max_completion_tokens": profile.max_completion_tokens} if profile else {}
    truncated = False
    try:
        raw, model_used = llm_router.generate(req.provider, prompt, system, seg=index,
                                              on_status=on_status, **limit)
    except TruncatedOutputError as e:
        # 半份 JSON 通常還能修復出前面的卡片；留下卡片並告知使用者這段不完整
        raw, model_used, truncated = e.partial, e.label, True
    t_gen = time.time() - t0
    data = _parse_cards(raw, language)
    if truncated:
        data["truncated"] = True
    # 低額度方案每段已縮短；避免覆蓋率稽核又暗中送出一份大請求。
    if profile:
        label = model_used
    else:
        data, label = _audit_coverage(req, content, chunk, index, data,
                                      model_used, language, on_status=on_status)
    print(f"[summarize] 片段 {index + 1} 完成：{len(data.get('cards') or [])} 張卡，"
          f"生成 {t_gen:.1f}s／總計 {time.time() - t0:.1f}s（{label}）", flush=True)
    return data, label


@router.post("/summarize")
def summarize(req: SummarizeRequest, request: Request = None) -> dict:
    """一次回傳全部卡片（不串流）。單一片段失敗會跳過，全部失敗才報錯。"""
    _require_local_audio(req, request)
    content, chunks, multi, skipped = _prepare(req)

    all_cards: list[dict] = []
    title: str | None = None
    models_used: list[str] = []
    content_types: list[str] = []
    failed = truncated = 0

    for i, chunk in enumerate(chunks):
        try:
            data, model_used = _run_segment(req, content, chunk, i, multi)
        except RuntimeError as e:  # 金鑰未設定等致命錯誤
            raise HTTPException(400, str(e))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[summarize] 片段 {i + 1}/{len(chunks)} 失敗，已跳過：{e}", flush=True)
            continue
        truncated += bool(data.get("truncated"))
        if title is None:
            title = data.get("title")
        all_cards.extend(data.get("cards", []))
        content_types.append(data.get("content_type") or "other")
        if model_used and model_used not in models_used:
            models_used.append(model_used)

    if not all_cards:
        if (content.get("text") or "").strip():
            all_cards = [_fallback_card(content["text"], config.get("OUTPUT_LANGUAGE"))]
        else:
            raise HTTPException(500, messages.t("summarize.all_segments_failed"))

    return {"title": title or messages.t("summarize.untitled"),
            "overview": _build_overview(all_cards, title, config.get("OUTPUT_LANGUAGE"), req.provider),
            "source_type": content["type"],
            "source_url": req.url, "youtube_video_id": content.get("video_id") if content["type"] == "youtube" else None,
            "bilibili_video_id": content.get("video_id") if content["type"] == "bilibili" else None,
            "local_video_id": content.get("video_id") if content["type"] == "local" else None,
            "bilibili_page": content.get("bilibili_page"),
            "transcript_source": content.get("transcript_source"),
            "content_type": _pick_content_type(content_types),
            "cards": all_cards, "model_used": "、".join(models_used),
            "segments": len(chunks), "failed_segments": failed,
            "truncated_segments": truncated, "skipped_segments": skipped}


@router.post("/summarize_stream")
def summarize_stream(req: SummarizeRequest, request: Request = None) -> StreamingResponse:
    """串流版摘要（NDJSON，每行一個事件）。

    事件：progress → meta → title → cards（每段一批）→ done；單段失敗發
    seg_error 但不中斷，致命錯誤發 fatal 後結束。內容擷取移入 generator，
    讓前端能在字幕與文章擷取開始時立即顯示真實工作階段。
    """
    _require_local_audio(req, request)
    stream = _stream_events(req)

    async def body():
        try:
            async for chunk in iterate_in_threadpool(stream):
                yield chunk
        finally:
            # 使用者按「停止」時連線中斷，伺服器會取消這裡；要主動關閉 generator，
            # 它才會取消排隊中的段落。光是不再讀取，背景排好的段落仍會一段段呼叫模型。
            try:
                stream.close()
            except ValueError:
                pass  # 正在背景執行緒裡跑；心跳讓它最多 0.5 秒就回來，之後不會再被呼叫

    return StreamingResponse(body(), media_type="application/x-ndjson")


def _stream_events(req: SummarizeRequest) -> Iterator[str]:
    """產生串流事件。使用者按「停止」時前端會中斷連線，伺服器隨即關閉這個 generator。"""
    def line(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    def gen() -> Iterator[str]:
        yield line({"type": "progress", "stage": "source", "completed": 0, "total": 0})
        # 必須在擷取內容之前檢查：沒選 AI 時不能連影片都先交給 Gemini 轉錄
        if not llm_router.is_explicit(req.provider):
            yield line({"type": "fatal", "error": messages.t("llm.no_provider")})
            return
        # 內容擷取（含下載音訊、本機轉錄）可能在背景跑好幾分鐘：
        # 放進執行緒，外層每 0.5 秒送心跳，連線中斷時才能立刻設定取消旗標。
        cancel = threading.Event()
        progress: Queue = Queue()
        holder: dict[str, Any] = {}

        def fetch() -> None:
            try:
                holder["content"] = route_content(
                    req.url, deep_visual=req.deep_visual,
                    allow_cloud_fallback=_allows_cloud_transcription(req.provider),
                    allow_audio_download=req.allow_audio_download,
                    cancelled=cancel.is_set,
                    on_progress=progress.put)
            except BaseException as exc:  # noqa: BLE001
                holder["error"] = exc

        worker = threading.Thread(target=fetch, daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                worker.join(timeout=0.5)
                forwarded = False
                while True:
                    try:
                        info = progress.get_nowait()
                    except Empty:
                        break
                    forwarded = True
                    yield line({"type": "progress", "stage": "source", **info})
                if not forwarded:
                    # 心跳：讓伺服器每 0.5 秒有機會發現使用者已經按了停止
                    yield ""
            while True:  # 收尾：把最後一批進度送完
                try:
                    info = progress.get_nowait()
                except Empty:
                    break
                yield line({"type": "progress", "stage": "source", **info})
        finally:
            if worker.is_alive():
                # 使用者按停止或連線中斷：通知下載／轉寫中止（暫存檔由 audio_transcript 清掉）
                cancel.set()

        error = holder.get("error")
        if isinstance(error, ValueError):
            yield line({"type": "fatal", "error": str(error)})
            return
        if error is not None:
            print(f"[summarize] 內容擷取失敗：{error!a}", flush=True)
            yield line({"type": "fatal", "error": messages.t("summarize.fetch_failed")})
            return
        content = holder["content"]
        profile = summary_budget(req.provider)
        chunks, skipped = _split(content, req.provider)

        multi = len(chunks) > 1
        workers = profile.workers if profile else llm_router.parallel_workers(req.provider, len(chunks))
        yield line({"type": "meta", "source_type": content["type"], "source_url": req.url,
                    "youtube_video_id": content.get("video_id") if content["type"] == "youtube" else None,
            "bilibili_video_id": content.get("video_id") if content["type"] == "bilibili" else None,
            "local_video_id": content.get("video_id") if content["type"] == "local" else None,
            "bilibili_page": content.get("bilibili_page"),
                    "transcript_source": content.get("transcript_source"),
                    "segments": len(chunks), "workers": workers})
        if skipped:
            yield line({"type": "coverage_limited", "skipped": skipped,
                        "covered_until": _last_ts(chunks[-1])})
        title: str | None = None
        models_used: list[str] = []
        content_types: list[str] = []   # 依段落順序 append（emit 是嚴格時間序），供多數決
        failed = total = 0
        collected: list[dict] = []
        status_events = [Queue() for _ in chunks]
        fatal_error: str | None = None

        def report(i: int):
            def put(event: dict[str, Any]) -> None:
                status_events[i].put({"type": "segment_status", "seg": i, **event})
            return put

        def wait_and_emit(i: int, future) -> Iterator[str]:
            nonlocal title, failed, total, fatal_error
            events = status_events[i]
            # API 等待期間持續把 worker 的「請求／重試／換模型」狀態送到前端。
            while not future.done():
                try:
                    yield line(events.get(timeout=0.5))
                except Empty:
                    # 心跳（空字串，前端會略過）：讓伺服器每 0.5 秒有機會發現使用者已經按了停止
                    yield ""
            while True:
                try:
                    yield line(events.get_nowait())
                except Empty:
                    break
            try:
                data, model_used = future.result()
            except RuntimeError as e:
                fatal_error = str(e)
                yield line({"type": "fatal", "error": fatal_error})
                return
            except Exception as e:  # noqa: BLE001
                failed += 1
                yield line({"type": "seg_error", "seg": i, "error": user_error(e, req.provider)})
                return
            if title is None and data.get("title"):
                title = data.get("title")
                yield line({"type": "title", "title": title})
            cards = data.get("cards", [])
            total += len(cards)
            collected.extend(cards)
            if model_used and model_used not in models_used:
                models_used.append(model_used)
            ctype = data.get("content_type") or "other"
            content_types.append(ctype)
            # 每段都帶：前端第一段就能顯示「下一步」入口，done 事件再用多數決校正
            event = {"type": "cards", "seg": i, "cards": cards, "model": model_used,
                     "content_type": ctype}
            if data.get("truncated"):
                event["truncated"] = True
            yield line(event)

        ex = ThreadPoolExecutor(max_workers=workers)
        try:
            # 第一段優先：不和後段搶免費 API；完成並送到前端後，才平行跑剩餘段落。
            first = ex.submit(_run_segment, req, content, chunks[0], 0, multi, report(0))
            yield from wait_and_emit(0, first)
            if fatal_error:
                return

            futs = [ex.submit(_run_segment, req, content, c, i, multi, report(i))
                    for i, c in enumerate(chunks[1:], start=1)]
            for i, f in enumerate(futs, start=1):  # 嚴格依影片時間順序輸出
                yield from wait_and_emit(i, f)
                if fatal_error:
                    return
        finally:
            # 使用者按「停止」（連線中斷、generator 被關閉）或發生致命錯誤時：
            # 取消還在排隊的段落，不再呼叫模型；已經在跑的那段無法中斷，會在背景做完。
            # 不等待（wait=False），以免關閉 generator 時卡住伺服器。
            ex.shutdown(wait=False, cancel_futures=True)
        if total == 0 and (content.get("text") or "").strip():
            # 模型整段都沒給卡片（短片最常見）：補一張抽取式摘要，讓畫面有內容
            fallback = _fallback_card(content["text"], config.get("OUTPUT_LANGUAGE"))
            total += 1
            collected.append(fallback)
            yield line({"type": "cards", "seg": len(chunks), "cards": [fallback],
                        "model": messages.t("summarize.fallback_model"), "content_type": "other"})
        if collected:
            # 前端在 done 之後會把 overview 放在卡片上方；模型失敗時退回卡片標題
            yield line({"type": "overview", **_build_overview(
                collected, title, config.get("OUTPUT_LANGUAGE"), req.provider)})
        yield line({"type": "done", "title": title or messages.t("summarize.untitled"),
                    "model_used": "、".join(models_used), "segments": len(chunks),
                    "content_type": _pick_content_type(content_types),
                    "failed_segments": failed, "total_cards": total,
                    "skipped_segments": skipped})

    return gen()


@router.post("/deepdive")
def deepdive(req: DeepDiveRequest) -> dict:
    """對單一張卡片做深度解析。"""
    language = config.get("OUTPUT_LANGUAGE")
    try:
        text, model_used = llm_router.generate(
            req.provider,
            deepdive_prompt(req.source_title, req.card.model_dump(), language),
            deepdive_system(language))
        return {"content": to_traditional(text, language), "model_used": model_used}
    except TruncatedOutputError as e:
        return {"content": f"{to_traditional(e.partial, language)}\n\n{messages.t('summarize.deepdive_truncated')}",
                "model_used": e.label}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, messages.t("summarize.deepdive_failed",
                                            error=user_error(e, req.provider)))
