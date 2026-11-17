// 來源階段（讀字幕／下載音訊／本機轉錄）的說明文字。
// 後端的事件契約是 stage="source"、state="download"|"transcribe"、percent；
// 抽成純函式才測得到「不會退回預設的整理重點」。
export function sourceProgressLabel(progress, t) {
  if (!progress || progress.stage !== 'source') return null
  if (progress.state === 'download') {
    return progress.percent != null ? t('progress.download', progress.percent) : t('progress.downloadUnknown')
  }
  if (progress.state === 'transcribe') return t('progress.transcribe')
  return t('progress.source')
}
