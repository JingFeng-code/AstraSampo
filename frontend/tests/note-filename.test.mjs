import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { noteVideoKey, resolveNoteFilename } from '../src/utils/note-filename.js'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

const A = { title: 'AI 代理時代的軟體工程品質', key: 'youtube:xslkY2Voy0A' }
const B = { title: 'AI 大模型與程式設計師轉型的觀念基礎', key: 'youtube:abcdefghijk' }

test('分析出新影片時，檔名跟著換成新標題', () => {
  const previous = { filename: A.title, videoKey: A.key, edited: false }
  assert.deepEqual(resolveNoteFilename(previous, B), { filename: B.title, videoKey: B.key, edited: false })
  // 沒改過的檔名，連重新分析同一支影片也會更新成最新標題
  assert.deepEqual(resolveNoteFilename(previous, { ...A, title: '新標題' }), { filename: '新標題', videoKey: A.key, edited: false })
})

test('同一支影片手動改過檔名就保留，不被標題蓋掉', () => {
  const previous = { filename: '我的重點整理', videoKey: A.key, edited: true }
  assert.deepEqual(resolveNoteFilename(previous, A), { filename: '我的重點整理', videoKey: A.key, edited: true })
  assert.deepEqual(resolveNoteFilename(previous, { ...A, title: '重新分析後的標題' }),
    { filename: '我的重點整理', videoKey: A.key, edited: true })
  // 換到另一支影片就不再沿用
  assert.deepEqual(resolveNoteFilename(previous, B), { filename: B.title, videoKey: B.key, edited: false })
})

test('同一支影片沒改過：保留標題；沒有標題時不要清掉使用者看得到的值', () => {
  const previous = { filename: A.title, videoKey: A.key, edited: false }
  assert.equal(resolveNoteFilename(previous, { title: A.title, key: A.key }).filename, A.title)
  assert.equal(resolveNoteFilename(previous, { title: '', key: A.key }).filename, A.title)
  // 新影片但這次沒有標題：不能留著上一支的標題
  assert.equal(resolveNoteFilename(previous, { title: '', key: B.key }).filename, '')
})

test('重新整理後（狀態從 localStorage 還原）仍對應目前影片', () => {
  // 存下來的是影片 B 的狀態，重新載入時第一次計算不能又變回舊標題
  const restored = { filename: B.title, videoKey: B.key, edited: false }
  assert.equal(resolveNoteFilename(restored, B).filename, B.title)
  const edited = { filename: 'B 的自訂檔名', videoKey: B.key, edited: true }
  assert.equal(resolveNoteFilename(edited, B).filename, 'B 的自訂檔名')
  // 舊版工作階段沒有 videoKey：視為新影片，換成目前標題（修掉殘留上一支標題的問題）
  assert.equal(resolveNoteFilename({ filename: A.title }, B).filename, B.title)
})

test('影片識別碼優先用平台 ID，避免同網址不同分頁互相覆蓋', () => {
  assert.equal(noteVideoKey({ youtube_video_id: 'xslkY2Voy0A', source_url: 'https://youtu.be/x' }), 'youtube:xslkY2Voy0A')
  assert.equal(noteVideoKey({ bilibili_video_id: 'BV1jhns6DEzi', bilibili_page: 2 }), 'bilibili:BV1jhns6DEzi:2')
  assert.equal(noteVideoKey({ local_video_id: 'a'.repeat(16) }), 'local:' + 'a'.repeat(16))
  assert.equal(noteVideoKey({ source_url: 'https://example.com/article' }), 'https://example.com/article')
  assert.equal(noteVideoKey(null, 'https://example.com/typed'), 'https://example.com/typed')
})

test('檔名欄位有看得見的標籤，且兩種語言都有', () => {
  const panel = read('../src/components/NotesPanel.jsx')
  assert.match(panel, /notes-filename/)
  assert.match(panel, /t\('notes\.filenameLabel'\)/)
  for (const lang of Object.keys(STRINGS)) assert.ok(STRINGS[lang]['notes.filenameLabel'], lang)
  // App 要記住「使用者改過」，不能只靠欄位有沒有值
  const app = read('../src/App.jsx')
  assert.match(app, /resolveNoteFilename\(/)
  assert.match(app, /function changeFilename\(value\)\{setFilename\(value\);setFilenameMeta/)
})

test('合併衝突後 NotesPanel 仍同時接上 changeFilename 與全部重點的動作', () => {
  // 解衝突時只要取錯一邊，這裡就會失敗：手改的檔名會被標題蓋掉，
  // 或「下載全部重點」的按鈕消失（兩種都不會被其他測試抓到）
  const app = read('../src/App.jsx')
  const line = app.split('\n').find(row => row.includes('<NotesPanel '))
  assert.ok(line, '找不到 NotesPanel')
  assert.match(line, /setFilename=\{changeFilename\}/)
  assert.match(line, /onExportAll=\{/)
  assert.match(line, /onClipAll=\{/)
  assert.match(line, /onClear=\{/)
  assert.match(line, /lastSaved=\{/)
})
