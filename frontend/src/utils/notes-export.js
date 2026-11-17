// 沒有 Obsidian 的一般使用者，也能把已整理的重點留在自己的電腦。
function oneLine(value) {
  return String(value || '').replace(/[\r\n]+/g, ' ').trim()
}

export function markdownFilename(title) {
  const base = oneLine(title).replace(/[\\/:*?"<>|\x00-\x1f]/g, '-').replace(/\.+$/g, '').slice(0, 90).trim()
  return (base || 'AstraTube-notes') + '.md'
}

export function createNoteMarkdown({title, sourceUrl, clips = [], freeNote = ''}) {
  const lines = ['# ' + (oneLine(title) || 'AstraTube 筆記'), '']
  if (sourceUrl) {
    // 不將任意輸入插入 Markdown link 語法，避免影片網址中含特殊括號。
    lines.push('來源：' + oneLine(sourceUrl), '')
  }
  if (clips.length) {
    lines.push('## 學習重點', '')
    for (const clip of clips) {
      lines.push('### ' + (oneLine(clip.heading) || '重點'))
      if (clip.ts != null && Number.isFinite(Number(clip.ts))) {
        const secs = Math.max(0, Math.floor(Number(clip.ts)))
        lines.push('時間：' + Math.floor(secs / 60) + ':' + String(secs % 60).padStart(2, '0'))
      }
      if (clip.summary) lines.push('', String(clip.summary).trim())
      if (clip.transcript) lines.push('', '**原文**', '', '> ' + String(clip.transcript).trim().replace(/\n/g, '\n> '))
      if (clip.translation) lines.push('', '**翻譯**', '', String(clip.translation).trim())
      if (clip.visual) lines.push('', '**畫面重點**', '', String(clip.visual).trim())
      if (clip.note) lines.push('', '**我的註記**', '', String(clip.note).trim())
      lines.push('')
    }
  }
  if (freeNote.trim()) lines.push('## 隨手筆記', '', freeNote.trim(), '')
  return lines.join('\n').trimEnd() + '\n'
}

// 一般瀏覽器：Blob + <a download>。桌面版（Tauri／WebView2）沒有下載管理員，這條路按了不會有檔案。
export function downloadMarkdown(markdown, filename) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const href = URL.createObjectURL(blob)
  const element = document.createElement('a')
  element.href = href
  element.download = filename
  document.body.appendChild(element)
  element.click()
  element.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

// 桌面版改由後端寫檔（存到使用者的下載資料夾）。兩條路都要回一句話給使用者，
// 成功、退回程式資料夾、失敗都不能靜悄悄——原本按了沒反應就是這個問題。
export async function saveNoteMarkdown({ markdown, filename, isDesktop, saveToBackend, downloadInBrowser, t }) {
  if (isDesktop) {
    try {
      const res = await saveToBackend(filename, markdown)
      const savedTo = res?.saved_to || ''
      const message = res?.fallback ? t('toast.savedToFallback', savedTo) : t('toast.savedTo', savedTo)
      return { ok: true, message }
    } catch (e) {
      return { ok: false, message: t('toast.exportFailed', e?.message || String(e)) }
    }
  }
  try {
    downloadInBrowser(markdown, filename)
    return { ok: true, message: t('toast.downloaded', filename) }
  } catch (e) {
    return { ok: false, message: t('toast.exportFailed', e?.message || String(e)) }
  }
}
