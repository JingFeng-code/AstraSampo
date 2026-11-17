// 「部分更新」的收尾：移除 SESSDATA、從瀏覽器匯入，都只改一個欄位。
// App 傳進來的 onSaved 會關閉設定視窗（handleSettingsSaved → setShowSettings(false)），
// 所以這兩個動作只能呼叫 onSettingsChanged：視窗留著，其他還沒儲存的欄位才不會消失。
export function applyPartialSettings({ next, message, onChanged, setMessage, setError }) {
  onChanged?.(next)
  setMessage?.(message)
  setError?.('')
  return message
}
