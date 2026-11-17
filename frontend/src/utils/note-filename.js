// 筆記檔名的狀態機：新影片要換成新標題，同一支影片則保留使用者手動改過的值。
// 抽成純函式，三種情況（新影片、同影片手改、同影片未改）才能被直接測試。
export function noteVideoKey(result, url = '') {
  if (!result) return url || ''
  if (result.local_video_id) return 'local:' + result.local_video_id
  if (result.youtube_video_id) return 'youtube:' + result.youtube_video_id
  if (result.bilibili_video_id) return 'bilibili:' + result.bilibili_video_id + ':' + (result.bilibili_page || 1)
  return result.source_url || url || ''
}

// previous: 目前欄位的狀態（{ filename, videoKey, edited }）
// video:    這次的影片（{ title, key }）
export function resolveNoteFilename(previous = {}, video = {}) {
  const title = String(video.title || '').trim()
  const key = video.key || ''
  const sameVideo = !!previous.videoKey && previous.videoKey === key
  if (sameVideo && previous.edited) {
    // 使用者自己取的名字比自動標題重要，同一支影片內不再覆蓋
    return { filename: previous.filename || '', videoKey: key, edited: true }
  }
  return { filename: title || (sameVideo ? previous.filename || '' : ''), videoKey: key, edited: false }
}
