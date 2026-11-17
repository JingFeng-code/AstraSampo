# 第二次退回：PR #60、#61、#64 的 Codex 審查意見

> 給原作者（實作的 AI Agent）。接續 `docs/WORK_ORDER_UX_NOTES_REVIEW.zh-TW.md`。
> 日期：2026-11-17。對象：PR #60（`ux/w1-notes-export`）、#61（`ux/w2-deck-tabs`）、#64（`ux/w5-deck-header`）。
> #62（W3）與 #63（W4）沒有新意見，但因為疊在 #60 上，**必須跟著 rebase**（見第 4 節）。
> 規則同前：不要 force push 到別人的分支以外的地方；不要自動合併；不要開新 PR；回報照原格式，結尾寫「自動化測試通過，實機未驗收」。

## 0. 先讀

- 五個 PR 的 CI 都已通過，但 Codex 留了 4 則 P2，**合併前必須處理**。審查留言原文在各 PR 的 Files changed 頁。
- 每個修正都要附「**修改前會失敗**」的測試，並在回報寫出你怎麼確認它修改前會失敗。
- 這次 Codex 抓到的問題，有些是我們前兩輪審核漏掉或低估的，不是你一個人的疏漏；但還是要修。

---

## 1. PR #60（W1）：兩則

### 1-a　同名檔案同時匯出會互相覆蓋（成立，必修）

**問題**：`_unique_path()` 先檢查檔案是否存在，再由 `_write_export()` 用 `write_text()` 寫入。兩個請求幾乎同時進來（下載按鈕在請求期間仍可按，FastAPI 同步端點在執行緒池跑），會挑到同一個路徑，後寫的把先寫的截斷，兩邊都回成功，只剩一份。這違反動工文件「不覆蓋既有檔案」。

**做法**：
- 改成**以排他方式建立檔案**（`open(path, "x", encoding="utf-8")`），遇到 `FileExistsError` 就換下一個後綴（` (2)`、` (3)`…）重試，直到成功。
- 保留既有的 `_ensure_within()` 檢查，每次重試都要做。
- 重試要有上限（例如 1000 次），超過回 500 與清楚訊息，不要無限迴圈。
- 內容只在檔案建立成功後才寫入；寫到一半失敗時不要留下空檔（失敗就刪掉自己剛建立的那個檔）。

**測試（修改前必須失敗）**：
- 用兩個執行緒同時對同一個檔名匯出，並用 `threading.Barrier` 讓兩邊都在「挑完路徑、還沒寫入」時同步（可以 patch 掉挑路徑與寫入之間的步驟，或在測試裡替換 `_unique_path` 讓它回傳同一個路徑再驗證排他開檔會迫使第二個換名）。斷言：產生兩個不同的檔案，兩份內容都在。
- 撞名超過上限時回明確錯誤。
- 既有的「同名不覆蓋」測試維持通過。

### 1-b　Windows 保留裝置名稱（建議，應修）

**問題**：`CON`、`PRN`、`AUX`、`NUL`、`COM1`–`COM9`、`LPT1`–`LPT9`（不分大小寫，連帶 `CON.md` 這種帶副檔名的）是 Windows 的裝置名稱。審核時我在 Windows 11 實測，`con.md`、`nul.md` 都能寫成一般檔案，但：
- 舊版 Windows（例如 Windows 10）的行為我沒有驗證；
- CI 跑在 Linux，這類檔名的測試只驗了 POSIX 行為，現有的敵意檔名清單裡把 `con` 當成「應該成功」並不能證明 Windows 上也是。

**做法**：`_export_name()` 在清理後，如果基本名稱（不含副檔名、不分大小寫）是上述保留名稱之一，在前面加上底線（`_con`）。不要在整個檔名後面加東西，也不要拒絕請求。

**測試**：
- 直接斷言 `_export_name("con") == "_con"`、`"NUL"`、`"com1"`、`"LPT9"`、`"Con"`；一般名稱（`"console"`、`"connect"`、`"com10"`）**不被改動**。
- HTTP 層：匯出 `con` 回 200，且實際檔名是 `_con.md`。
- 因為 CI 在 Linux，這些斷言要寫成**不依賴作業系統**的純字串檢查。

---

## 2. PR #61（W2）：一則

### 2-a　`localStorage` 屬性本身可能丟例外（成立，必修）

**問題**：`CardDeck.jsx` 第 17 行附近：

```
const storage=typeof localStorage==='undefined'?null:localStorage
```

瀏覽器政策停用儲存時，**讀取全域的 `localStorage` 屬性本身就會丟 `SecurityError`**，連 `typeof` 都可能丟。這發生在 `readDeckTab()`／`writeDeckTab()` 的 try/catch **之前**，所以 `CardDeck` 會直接當掉，使用者分析完影片卻看到錯誤畫面。動工文件要求「讀寫都包 try/catch」，取得 `localStorage` 這件事本身也要包。

**做法**：
- 在 `utils/deck-tabs.js` 新增一個取得儲存物件的函式（例如 `getDeckStorage(win = globalThis)`），整個放進 try/catch，失敗回 `null`；`CardDeck` 用它，不要在元件裡直接寫 `typeof localStorage`。
- 其餘 `readDeckTab(null)`、`writeDeckTab(null, …)` 本來就能處理 `null`，保持。
- 順便檢查你這次所有新增的程式（W1–W5）是否還有其他「直接讀 `localStorage`」的地方，一併改掉；**不要改既有、不是你新增的程式**。

**測試（修改前必須失敗）**：
- 用 `Object.defineProperty(globalThis, 'localStorage', { get() { throw new DOMException('denied', 'SecurityError') }, configurable: true })` 模擬，斷言 `getDeckStorage()` 回 `null` 而不是丟例外；測完還原。
- 斷言 `CardDeck.jsx` 不再含 `typeof localStorage`（原始碼比對即可，專案慣例）。

---

## 3. PR #64（W5）：一則

### 3-a　窄版英文介面標題列會橫向溢出（看起來成立，必修；修完要實測）

**問題**：`.deck-meta` 設了 `flex-wrap:nowrap`，只有模型名稱會收縮，來源標籤、「Advanced tools」、張數都是 `flex-shrink:0`。375 寬度、**英文介面**、來源是像「Deep visual + captions」這種長標籤時，扣掉面板內距後約 317px，放不下，整列溢出，把張數擠到可視範圍外。修改前這幾個項目各自可以換行，這次反而退步。

你之前的截圖都是繁中介面，英文沒有驗證過。

**做法**：
- 窄版（例如 `max-width: 480px`）讓 `.deck-meta` 允許換行（`flex-wrap: wrap`），來源標籤與進階工具仍不縮、不被截斷；寬版維持現在一行的行為。
- 不要因此讓模型名稱在寬版失去省略號行為。

**驗證（必做，貼在回報裡）**：
- 把介面切到英文，來源用最長的情況（深視覺＋字幕），在 **375、414、768** 寬度各量一次：`.deck-meta` 的 `scrollWidth <= clientWidth`、張數在可視範圍內、沒有橫向捲軸。附數字與截圖。
- 繁中也各量一次，確認沒有退步。

**測試**：CSS 規則比對（窄版有 `flex-wrap: wrap`，且寬版規則不變）；版面行為以量測為準，這點照舊在 PR 說明寫清楚。

---

## 4. 修完之後的 rebase 與 push（很重要）

#62 疊在 #60 上，#63 疊在 #62 上，所以 #60 一改，後面兩個分支要重新對齊，否則 PR 的差異會夾帶舊提交：

1. 先在 `ux/w1-notes-export` 上修 1-a、1-b（各自一個 commit，訊息寫清楚對應哪則意見）。
2. 把 `ux/w3-all-notes` rebase 到新的 `ux/w1-notes-export`，再把 `ux/w4-note-filename` rebase 到新的 `ux/w3-all-notes`。若有衝突自己解，**解完要重跑完整測試**，並再確認 `App.jsx` 的 `<NotesPanel …>` 那一行仍同時有 `setFilename={changeFilename}`、`onExportAll=`、`onClipAll=`、`onClear=`、`lastSaved=`（W4 的守住測試會抓這個）。
3. 修 2-a 在 `ux/w2-deck-tabs`、3-a 在 `ux/w5-deck-header`，這兩個沒有被別的分支依賴。
4. 重新 push 被 rebase 的分支需要 `--force-with-lease`：**只允許對 `ux/w3-all-notes` 與 `ux/w4-note-filename` 這兩個你自己的分支使用**，其他分支一律一般 push；不要對 `main` 或 `feat/ollama-cloud-and-ux` 做任何強制推送。
5. 五個分支依 W1 → W2 → W3 → W4 → W5 的順序合併到一個臨時分支，確認無衝突、前端與後端測試通過、`npm run build` 通過，再刪掉臨時分支。

## 5. 不要動的事

與第一份退回清單相同：摘要提示詞、陪看、Bilibili 登入與下載、Ollama Cloud、設定頁；切換卡片一律暫停的行為維持。**不要順手處理 #59 的任何問題。**

## 6. 回報格式

每則意見一段：

```
## <PR 編號>-<項目>
### 修了什麼
### 修改前會失敗的證據（怎麼讓它失敗、失敗訊息）
### 沒做的項目與原因
### 親自確認的 vs 依程式推測的
```

最後附上整體 `git log --oneline` 與各分支 push 後的 commit。結尾寫：**自動化測試通過，實機未驗收。**
