// 連線檢查只跟「哪個供應商、有沒有已存金鑰、Ollama 位址」有關。
// 其他設定（SESSDATA、vault、介面語言…）變動時不該重跑驗證：重跑會先作廢進行中的
// 請求，而新的 effect 若因為使用者正在輸入金鑰而提早 return，就沒有人把
// checking 收回 false，畫面會一直停在「驗證中」、儲存鈕停用。
export function connectionCheckKey({ engine, keySet, ollamaUrl }) {
  return `${engine || ''}|${keySet ? '1' : '0'}|${String(ollamaUrl || '').trim()}`
}
