# 退回清單：PR #59（`feat/ollama-cloud-and-ux`）合併前要補的事

> 給原作者（實作的 AI Agent）。審核對象：分支 `feat/ollama-cloud-and-ux`，目前最新提交 `6094efd`（已含 W1–W5 的合併）。
> 審核日期：2026-11-17。依據：直接閱讀該分支的程式與實測，不是依 PR 說明。
> 專案規則照 `AGENTS.md` 與 `docs/WORK_ORDER_UX_NOTES.zh-TW.md` 第 0 節，不在這裡重複。

## 0. 先讀

> **2026-11-17 更新**：使用者已決定 Bilibili 的 SESSDATA 與下載音訊「保留但改成手動觸發」，原本的「待使用者決定 D1」已改寫為必修的 **P59-4**（第 5 節）。工作順序建議：P59-1 → P59-2 → P59-3 → P59-4 → P59-D（文件最後）。

### 現況

- PR #59 的 CI 三項全綠，但 **Codex 只審過第一個提交 `e130751`**，後面約 19 個提交（含 W1–W5）都沒被審過，也無法重新觸發。所以「CI 綠」和「Codex 沒意見」都不能當作這個 PR 已經審完。
- 這份清單只列**審核後仍成立**的問題。已經修好並由審核者確認的項目不用再做：`/models` 回報 Ollama Cloud、語音轉錄快取存引擎（`asr_v2`）、Ollama Cloud 金鑰檢查改用 `POST /api/me`（審核者用無效金鑰實測回 401）、SESSDATA 只送 `api.bilibili.com`、新測試已加入 `ci.yml`。

### 怎麼交付

- **不要直接推 `feat/ollama-cloud-and-ux`。** 每一項各開一個分支（從 `feat/ollama-cloud-and-ux` 切出，名稱 `fix/pr59-<代號>-<簡短英文>`），各自一個 PR，目標是 `feat/ollama-cloud-and-ux`。
- 不要 force push、不要自動合併、不要碰 `main`。
- 每個修正都要附「**修改前會失敗**」的測試，並在回報寫出你怎麼確認它修改前會失敗（把修正暫時拿掉再跑，貼失敗訊息）。
- 回報要分開寫「我親自執行並確認的」和「依程式推測的」；結尾寫「自動化測試通過，實機未驗收」。
- 本文件每一項都附「審核時看到的證據」，修之前請先在自己的環境重現一次，**重現不了就回報，不要硬改**。

### 不要動

W1–W5 已合併的檔案（筆記匯出、卡片分頁、標題列）、摘要提示詞、陪看模式、Ollama Cloud 的請求格式。

---

## 1. P59-1　SESSDATA 存了就清不掉（必修，Codex P2 仍成立）

### 問題

`frontend/src/components/SettingsModal.jsx` 送出設定時：

```
...(sessdata.trim() ? { bilibili_sessdata: sessdata.trim() } : {}),
```

欄位是空的就**整個不送**。後端 `settings.py` 只有收到明確的空字串才會清除，所以使用者把欄位清空再按儲存，舊的 SESSDATA 仍留在磁碟上（`settings.json`），而且接下來的 Bilibili 請求繼續使用它。介面上的說明卻暗示清空就會刪除。這是登入憑證，使用者必須能刪掉。

### 做法

- **不要靠「欄位空白」推斷要清除**（這會讓不相干的設定儲存意外刪掉憑證）。改成**明確的動作**：在 SESSDATA 欄位旁，當 `state.bilibili_sessdata_set` 為真時顯示「移除已儲存的 SESSDATA」按鈕；按下後直接送 `{ bilibili_sessdata: '' }`，成功後更新畫面狀態（`onSaved`）並顯示提示。
- 失敗要有看得到的錯誤訊息。
- 一般的「儲存」維持現在的行為：欄位空白 = 不變。
- 修正欄位下方的說明文字，讓它和實際行為一致；繁中與英文都要改。
- 後端先確認：送空字串真的把 `BILIBILI_SESSDATA` 從 `settings.json` 清掉（不是留一個空值以外的殘留），而且 `GET /settings` 之後回報 `bilibili_sessdata_set: false`。若不是，一併修。

### 驗收

- [ ] 已儲存 SESSDATA 時看得到「移除」按鈕；沒存時不顯示。
- [ ] 按下後 `settings.json` 裡沒有 SESSDATA，`GET /settings` 回 `bilibili_sessdata_set` 為 `false`，之後的 Bilibili 請求不再帶 `Cookie` 標頭。
- [ ] 一般儲存（欄位空白）不會清掉已存的 SESSDATA。

### 測試（修改前必須失敗）

- 後端：`POST /settings` 送 `bilibili_sessdata: ""` 後，設定檔不含該值、狀態為未設定；再送 `bilibili_sessdata` 不帶（`null`）時不影響已存的值。
- 後端：清除後呼叫 Bilibili 取字幕的函式，斷言送出的標頭沒有 `Cookie`。
- 前端：`api.js` 有對應函式；`SettingsModal.jsx` 有移除按鈕且只在 `bilibili_sessdata_set` 時顯示；一般儲存的 payload 在欄位空白時**不含** `bilibili_sessdata`。

---

## 2. P59-2　模型整批失敗時，保底卡會蓋掉真正的錯誤（必修）

### 問題

`backend/app/api/summarize.py` 串流版在所有段落結束後：

```
if total == 0 and (content.get("text") or "").strip():
    # 補一張「逐字稿前 12 行」的卡
```

只看「一張卡都沒有」，沒有區分兩種完全不同的情況：
1. 模型有回應，但給了空的卡片（短片、無實質內容）：補保底卡是合理的。
2. **每一段都失敗**（例如 Ollama 沒開、金鑰錯誤、逾時）：使用者應該看到失敗原因，而不是一張看起來像成功的卡。

現在第 2 種也會出現保底卡，接著還會多呼叫一次模型做「整體總結」（同樣會失敗）。非串流的 `summarize()` 也有同樣的問題（`if not all_cards:` 之後有文字就補保底卡）。**這是依程式判斷，審核者沒有執行重現，請你先重現。**

### 做法

- 保底卡只在「**沒有任何段落失敗**，而且卡片總數為 0」時產生。只要有任何段落失敗（`failed > 0`）且沒有任何卡片，就不產生保底卡、不呼叫整體總結，並讓前端顯示失敗原因（沿用現有的 `seg_error` → 前端 `error.noCards · <原因>` 的路徑，不要另造新事件）。
- 串流與非串流兩處都要改，行為一致。
- 若部分段落成功、部分失敗：維持現狀（顯示成功的卡片，失敗的段落由既有機制通知）。
- 整體總結只在「至少有一張**模型產生的**卡片」時才呼叫；只有保底卡時不呼叫。

### 驗收

- [ ] 把模型呼叫換成一律丟例外：事件序列有 `seg_error`，**沒有**保底卡的 `cards` 事件，**沒有** `overview` 事件，且模型的 `generate` 沒有被呼叫來做總結。
- [ ] 模型回傳空卡片、沒有任何失敗：仍然產生保底卡（現有 `test_summarize_fallback.py` 的行為不退步）。
- [ ] 非串流版同樣：全部失敗回錯誤，不回保底卡。

### 測試（修改前必須失敗）

擴充 `backend/tests/test_summarize_fallback.py`：全部失敗、部分失敗、空卡片三種情境，串流與非串流各一份；用計數器斷言「總結用的模型呼叫次數」。

---

## 3. P59-3　展開「進階」就自動讀取所有瀏覽器的 cookie（必修）

### 問題

`SettingsModal.jsx` 有一個 effect：`advancedOpen` 變成真就呼叫 `getBilibiliBrowsers()`，後端 `GET /settings/bilibili-browsers` 會**逐一開啟本機每個瀏覽器的 cookie 資料庫**去偵測（程式註解自己說約 1–2 秒）。使用者只是展開一個區塊就觸發，並沒有按任何「匯入」按鈕；`browser_cookies.py` 的說明卻寫「使用者按一次按鈕」。讀取登入憑證這類動作必須是使用者明確觸發的。

另外這兩個端點（`/settings/bilibili-browsers`、`/settings/bilibili-cookie`）沒有擋非本機的請求，其他同類寫檔／讀本機資料的端點（例如 `/notes/export`、`/local-video/*`）都用 `on_this_computer()` 擋。

### 做法

- 前端：**移除**展開時自動偵測的 effect。改成一個「偵測可匯入的瀏覽器」按鈕，按了才呼叫 `getBilibiliBrowsers()`，顯示忙碌狀態；偵測完才出現瀏覽器清單與「匯入」按鈕。偵測結果不要快取到下次開啟設定頁（每次都由使用者觸發）。
- 說明文字講清楚：這會讀取你自己瀏覽器裡的 B 站登入狀態，只取 `SESSDATA`，存在本機。
- 後端：兩個端點都加 `on_this_computer()`（沿用 `app/api/local_video.py` 的函式），非本機回 403 與清楚訊息（中英都要加）。

### 驗收

- [ ] 展開、收合設定的「進階」不會對 `/settings/bilibili-browsers` 發出任何請求。
- [ ] 只有按下「偵測…」按鈕才會發出請求。
- [ ] 非本機請求兩個端點都回 403；本機請求行為不變。

### 測試（修改前必須失敗）

- 後端：兩個端點用非本機的 `client` 呼叫回 403（比照 `test_notes_export.py` 的做法）。
- 前端：原始碼比對 `SettingsModal.jsx` 不再有「依 `advancedOpen` 自動呼叫 `getBilibiliBrowsers`」的 effect，且有按鈕的點擊處理函式呼叫它。

---

## 4. P59-D　文件與錯誤訊息要和實際行為一致（必修，不需要等決定）

### 問題

- `docs/PLATFORM_TERMS_RISK.zh-TW.md` 第 20 行附近仍寫 `yt-dlp` 下載音訊（**桌面版不含**）。實際上 `requirements-desktop.txt` 與 `build-desktop.ps1` 已把 yt-dlp 打包進桌面版，Bilibili 沒有字幕時會下載音訊並做本機轉錄。這句話現在是錯的。
- `backend/app/transcript/bilibili.py` 約第 175 行的錯誤訊息仍說「**AstraTube 不會下載影音來轉錄**」；但同一個流程（`router.py` 的 `except ValueError as caption_error`）接著就會下載音訊，而且最後把兩段訊息串在一起顯示給使用者，變成同一句話裡自相矛盾。

### 做法

- 更新 `PLATFORM_TERMS_RISK`：寫明桌面版現在會下載公開 Bilibili 影片的音訊（沒有字幕時）、風險評估照實寫（不要淡化；Bilibili 用戶協議對自動化取得內容與下載的限制要保留）、使用者提供 SESSDATA 的做法與其風險（登入憑證只存本機、不代替使用者登入）。
- 把 `bilibili.py` 那句訊息改成只描述事實（例如「這支影片沒有可公開取得的字幕。」），不要再保證會不會下載；實際的下載與否由後面的說明負責。
- 全專案搜尋「不會下載」「不下載影音」「不會使用你的帳號」，**逐一檢查是否仍然屬實**（README、`docs/`、`frontend/src/i18n/strings.js`、`backend/app/core/messages.py`），不屬實的改掉，並在回報列出你檢查過的檔案與結果。
- **這一項放在 P59-4 之後做（或和 P59-4 同一個 PR）**：文字要描述 P59-4 完成後的最終行為（手動觸發、有風險說明、有上限），不是現在的自動行為。

### 驗收

- [ ] 文件與介面文字都不再出現與實際行為矛盾的保證。
- [ ] 回報附上搜尋結果與逐項判斷。

### 測試

文件修正不需要新測試；`messages` 的中英一致測試（`test_messages.py`）要維持通過。

---

## 5. P59-4　Bilibili：SESSDATA 與下載音訊改成「使用者主動觸發」（必修）

> **使用者在 2026-11-17 決定：保留這兩個功能，但改成手動觸發。** 目標：預設只走合規的兩條路（匯入字幕、陪看模式）；登入憑證與下載音訊只在使用者明確要求時才動，並在按鈕旁講清楚風險。

### 5-a　現況的問題（審核時看到的）

- `router.py` 的 `except ValueError as caption_error:` 讓**任何** `ValueError`（網路錯誤、分 P 不存在、SESSDATA 格式錯誤、被平台攔截…）都自動改去下載音訊。
- `audio_transcript.py` 沒有長度或大小上限、沒有逾時、不能中途停止；快取鍵是 `bilibili:{bvid}:{page}`，沒有綁 `cid`（字幕那邊已經綁了）。
- 使用者看不到「接下來要下載你的影片音訊」這件事，也沒有機會拒絕。

### 5-b　要做的事

**1. 只在「確定沒有字幕」且使用者按了才下載**
- 在 `bilibili.py` 新增兩個 `ValueError` 的子類別：`NoSubtitleError`（影片確實沒有可取得的字幕）與 `LoginRequiredError`（字幕需要登入、而目前沒有有效的 SESSDATA）。其他錯誤維持一般 `ValueError`。
- `SummarizeRequest` 新增欄位 `allow_audio_download: bool = False`。`route_content()` **只有在**這個欄位為真、而且字幕錯誤是上述兩個子類別之一時，才走音訊下載。網路錯誤、分 P 不存在、SESSDATA 格式錯誤、被攔截一律**不**下載，直接回原本的錯誤。
- 後端只在這台電腦的請求才接受 `allow_audio_download=true`（沿用 `on_this_computer()`），否則回 403 與清楚訊息（中英都要加）。

**2. 前端：把選擇交給使用者**
- 分析失敗且錯誤是「沒有字幕」或「字幕需要登入」（Bilibili）時，在錯誤區塊提供三個明確的選項：**匯入字幕檔**、**用陪看模式**、**下載音訊並在本機轉成文字**。
- 第三個選項是兩步確認（同一位置換成「確定？」加兩個按鈕，做法參考 `WatchAlong.jsx` 的放棄確認，不用 `window.confirm`），按鈕旁有一段風險說明：會用 yt-dlp 下載這支影片的音訊到暫存資料夾、轉完立刻刪除、只在本機處理；Bilibili 條款對自動取得內容有限制，風險由使用者自行承擔。繁中與英文都要寫，措辭要直接，不要淡化。
- 使用者確認後，以 `allow_audio_download=true` 重送同一個分析請求。
- 沒有按確認就不會下載任何東西。

**3. 上限與保護**
- 下載前先用 yt-dlp 只取中繼資料（`download=False`）：**影片長度超過上限就直接拒絕**，不下載。預設上限 90 分鐘，放成設定常數，錯誤訊息要說明上限。
- 設定檔案大小上限（預設 500 MB，用 yt-dlp 的對應選項）與連線逾時（`socket_timeout`），超過就中止並清掉暫存檔。
- 只下載純音訊、不下載播放清單（已有 `noplaylist`，保持）。

**4. 可以中途停止**（沿用 PR #57 的做法）
- 下載與轉文字要放進背景執行緒，串流的產生器在等待期間每 0.5 秒送一個空的心跳，並在被關閉（使用者按「停止」、連線中斷）時設定取消旗標。
- 下載階段：用 yt-dlp 的 `progress_hooks`，旗標一設就丟出自訂的取消例外中止下載。
- 轉文字階段：把取消旗標傳給 `local_speech.transcribe_file(..., cancelled)` 的取消參數（該函式本來就有）。
- 取消後一定要刪除暫存資料夾，不留半個音檔。
- 串流要送進度事件（下載中、轉文字中），讓畫面不是一片空白。

**5. 快取綁 `cid`**
- 先用 `/x/web-interface/view` 取得 `cid`，快取鍵改成 `asr_v3:bilibili:{bvid}:{cid}`（版本號遞增以免讀到舊格式）。不同分 P 或被換掉內容的影片不會互相混用。

**6. SESSDATA 的部分（和 P59-1、P59-3 一起完成，不需要重寫）**
- 手動觸發的部分已由 P59-3（偵測與匯入要按按鈕）與 P59-1（可明確移除）涵蓋。
- 額外：設定頁 SESSDATA 欄位旁加風險說明（登入憑證只存本機 `settings.json`、等同帳號登入狀態、遺失或共用會讓他人能操作該帳號、Bilibili 條款對自動化取得內容有限制）。
- 沒有 SESSDATA 時行為與從前相同；有 SESSDATA 時，只用於讀取需要登入的字幕，不用於下載音訊（下載音訊不要帶 cookie）。

### 5-c　驗收

- [ ] 沒有字幕的 Bilibili 影片：分析失敗並出現三個選項；**不按確認，yt-dlp 完全沒有被呼叫**。
- [ ] 確認後才下載；長度超過上限的影片在下載前就被拒絕。
- [ ] 網路錯誤、分 P 不存在、SESSDATA 格式錯誤：**不會**觸發下載，顯示原本的錯誤。
- [ ] 下載中按「停止」：下載與轉文字都中止，暫存資料夾被刪除，畫面顯示已停止。
- [ ] 同一支影片的不同分 P、不同 `cid` 不會共用轉錄快取。
- [ ] 非本機請求帶 `allow_audio_download=true` 回 403。

### 5-d　測試（修改前必須失敗）

- 後端（mock yt-dlp 與本機語音引擎，不碰網路）：
  - 字幕錯誤是 `NoSubtitleError`、`allow_audio_download=False` → `_download` 沒被呼叫；`True` → 被呼叫一次。
  - 一般 `ValueError`、網路錯誤即使 `allow_audio_download=True` 也不下載。
  - 長度超過上限 → 在 `_download` 之前拒絕。
  - 取消旗標在下載中被設定 → 丟取消例外、暫存資料夾不存在；在轉文字中設定 → 同樣被中止並清掉。
  - 快取鍵含 `cid`：同一個 `bvid` 不同 `cid` 不互相命中。
  - 非本機請求 403。
  - 沿用 PR #57 的 `test_stop_stream.py` 手法：關閉串流產生器後，背景作業不再繼續。
- 前端：錯誤區塊在「沒有字幕／需要登入」且為 Bilibili 時有三個選項；第三個要兩步確認；風險說明兩種語言都有；沒有確認不會送出 `allow_audio_download: true`（原始碼與純函式檢查，專案慣例）。

### 5-e　不要做

不要讓下載在使用者不知情下自動發生；不要把 SESSDATA 帶進下載請求；不要放寬上限來「讓更多影片能用」。

---

## 6. 待使用者決定：先不要動

### D2　整體總結每次分析多呼叫一次模型

沒有開關。雲端模型會多花額度。等使用者決定要預設開、預設關還是做開關。

---

## 7. 回報格式

每一項一段：

```
## P59-<編號>
### 重現（修改前我看到什麼）
### 修了什麼
### 修改前會失敗的證據（怎麼讓它失敗、失敗訊息）
### 沒做的項目與原因
### 親自確認的 vs 依程式推測的
```

最後附上每個分支與 PR 的清單（PR 目標必須是 `feat/ollama-cloud-and-ux`），並寫：**自動化測試通過，實機未驗收。**
