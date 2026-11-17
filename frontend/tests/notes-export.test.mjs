import test from 'node:test'
import assert from 'node:assert/strict'
import { createNoteMarkdown, markdownFilename, saveNoteMarkdown } from '../src/utils/notes-export.js'
import { mergeClips, newClipId } from '../src/utils/clips.js'
import { STRINGS } from '../src/i18n/strings.js'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

// 用真的字串表當 t，訊息才會跟介面一致；有函式的 key 依參數代入
const translator = lang => (key, ...args) => {
  const value = STRINGS[lang][key]
  assert.ok(value, `${lang} 缺少 ${key}`)
  return typeof value === 'function' ? value(...args) : value
}

test('匯出檔名不會帶路徑或非法字元', () => {
  assert.equal(markdownFilename('AI 代理時代的軟體工程品質'), 'AI 代理時代的軟體工程品質.md')
  assert.equal(markdownFilename('..\\..\\evil'), '..-..-evil.md')
  assert.equal(markdownFilename('/etc/passwd'), '-etc-passwd.md')
  assert.equal(markdownFilename('a:b*c?d'), 'a-b-c-d.md')
  assert.equal(markdownFilename('name...'), 'name.md')
  assert.equal(markdownFilename('   '), 'AstraTube-notes.md')
  assert.ok(markdownFilename('長'.repeat(200)).length <= 94)
})

test('Markdown 內容：模型輸出的標題換行不破壞格式', () => {
  const md = createNoteMarkdown({
    title: '第一行\n第二行',
    sourceUrl: 'https://www.youtube.com/watch?v=abcdefghijk',
    clips: [{ heading: '重點一\n續行', summary: '摘要', ts: 75, note: '我的想法' }],
    freeNote: '隨手寫',
  })
  assert.match(md, /^# 第一行 第二行/)
  assert.match(md, /### 重點一 續行/)
  assert.match(md, /時間：1:15/)
  assert.match(md, /## 隨手筆記\n\n隨手寫/)
})

test('桌面版走後端寫檔，成功後回報實際路徑', async () => {
  const calls = []
  const result = await saveNoteMarkdown({
    markdown: '# 筆記', filename: '筆記.md', isDesktop: true, t: translator('zh'),
    saveToBackend: async (filename, markdown) => { calls.push([filename, markdown]); return { saved_to: 'C:\\Users\\me\\Downloads\\AstraTube\\筆記.md', fallback: false } },
    downloadInBrowser: () => assert.fail('桌面版不應該走瀏覽器下載'),
  })
  assert.deepEqual(calls, [['筆記.md', '# 筆記']])
  assert.equal(result.ok, true)
  assert.match(result.message, /已存入：.*Downloads.*筆記\.md/)
  // 路徑要回傳給呼叫端留在面板上（toast 4 秒後就看不到）
  assert.match(result.savedTo, /Downloads.*筆記\.md$/)
})

test('桌面版遇到「下載」不能寫時，訊息要說明改存到哪裡', async () => {
  const result = await saveNoteMarkdown({
    markdown: '# 筆記', filename: '筆記.md', isDesktop: true, t: translator('zh'),
    saveToBackend: async () => ({ saved_to: 'C:\\AstraTube\\exports\\筆記.md', fallback: true }),
    downloadInBrowser: () => assert.fail('不應該走瀏覽器下載'),
  })
  assert.equal(result.ok, true)
  assert.match(result.message, /不能寫入/)
  assert.match(result.message, /exports/)
  assert.match(result.savedTo, /exports.*筆記\.md$/)
})

test('桌面版存檔失敗要顯示看得懂的原因', async () => {
  for (const lang of ['zh', 'en']) {
    const result = await saveNoteMarkdown({
      markdown: '# 筆記', filename: '筆記.md', isDesktop: true, t: translator(lang),
      saveToBackend: async () => { throw new Error('HTTP 500') },
      downloadInBrowser: () => assert.fail('不應該走瀏覽器下載'),
    })
    assert.equal(result.ok, false)
    assert.match(result.message, /HTTP 500/)
  }
})

test('一般瀏覽器維持 Blob 下載，兩種結果也都有訊息', async () => {
  const downloads = []
  const ok = await saveNoteMarkdown({
    markdown: '# 筆記', filename: '筆記.md', isDesktop: false, t: translator('zh'),
    saveToBackend: async () => assert.fail('瀏覽器不應該呼叫後端'),
    downloadInBrowser: (markdown, filename) => downloads.push([markdown, filename]),
  })
  assert.deepEqual(downloads, [['# 筆記', '筆記.md']])
  assert.equal(ok.ok, true)
  assert.match(ok.message, /已開始下載：筆記\.md/)
  // 瀏覽器下載沒有可回報的落點，不要假裝有路徑
  assert.equal(ok.savedTo, undefined)

  const failed = await saveNoteMarkdown({
    markdown: '# 筆記', filename: '筆記.md', isDesktop: false, t: translator('zh'),
    saveToBackend: async () => assert.fail('瀏覽器不應該呼叫後端'),
    downloadInBrowser: () => { throw new Error('blocked') },
  })
  assert.equal(failed.ok, false)
  assert.match(failed.message, /存檔失敗：blocked/)
})

test('存檔成功後路徑留在面板上，收合面板才清掉', () => {
  const panel = read('../src/components/NotesPanel.jsx')
  assert.match(panel, /\{lastSaved&&<p className="notes-last-saved">/)
  assert.match(panel, /t\('notes\.lastSaved'\)/)
  const app = read('../src/App.jsx')
  // 設定路徑與收合時清掉，兩邊都要接上
  assert.match(app, /if\(r\.ok&&r\.savedTo\)setLastNoteSave\(r\.savedTo\)/)
  assert.match(app, /onToggle=\{min=>\{if\(min\)setLastNoteSave\(null\)\}\}/)
  assert.match(app, /lastSaved=\{lastNoteSave\}/)
})

test('複製 Markdown 的字串兩種語言都有', () => {
  for (const lang of Object.keys(STRINGS)) {
    const t = translator(lang)
    assert.ok(t('notes.copyMarkdown'))
    assert.ok(t('notes.clipboardUnavailable'))
    assert.match(t('toast.copyFailed', 'denied'), /denied/)
  }
})

test('匯出全部重點時，總結放在最前面', () => {
  const md = createNoteMarkdown({
    title: '影片',
    clips: [{ heading: '卡片一', summary: '摘要', ts: 10 }],
    overview: { summary: '整支影片的結論', points: ['第一條\n續行', '第二條'] },
  })
  const summaryAt = md.indexOf('## 總結')
  const clipsAt = md.indexOf('## 學習重點')
  assert.ok(summaryAt >= 0 && summaryAt < clipsAt, '總結要在學習重點之前')
  assert.match(md, /## 總結\n\n整支影片的結論\n\n- 第一條 續行\n- 第二條/)
  // 沒有總結時不要長出空段落
  assert.doesNotMatch(createNoteMarkdown({ title: '影片', clips: [] }), /## 總結/)
  assert.doesNotMatch(createNoteMarkdown({ title: '影片', overview: { summary: '', points: [] } }), /## 總結/)
})

test('匯出的重點依影片時間排序，沒有時間的排最後', () => {
  const md = createNoteMarkdown({
    title: '影片',
    clips: [
      { heading: '沒有時間 A', summary: 'x' },
      { heading: '晚一點', summary: 'x', ts: 120 },
      { heading: '最早', summary: 'x', ts: 5 },
      { heading: '沒有時間 B', summary: 'x' },
      { heading: '中間', summary: 'x', ts: 60 },
    ],
  })
  const order = [...md.matchAll(/### (.+)/g)].map(m => m[1])
  assert.deepEqual(order, ['最早', '中間', '晚一點', '沒有時間 A', '沒有時間 B'])
})

test('全部收進筆記只加一次，不會重複', () => {
  const clip = (cardIndex, id) => ({ id, cardIndex, heading: `卡 ${cardIndex}` })
  const first = mergeClips([], [clip(0, 'a0'), clip(1, 'a1'), clip(2, 'a2')])
  assert.equal(first.length, 3)
  // 再按一次：同一張卡不重複（clipAll 用同一個 mergeClips）
  const again = mergeClips(first, [clip(0, 'b0'), clip(1, 'b1'), clip(2, 'b2')])
  assert.equal(again.length, 3)
  // 只有新的卡片會被加入，且保留原本的順序
  const more = mergeClips(again, [clip(3, 'c3'), clip(0, 'c0')])
  assert.deepEqual(more.map(c => c.cardIndex), [0, 1, 2, 3])
  // 產生的 id 不能撞號
  const ids = [newClipId(0), newClipId(0), newClipId(1)]
  assert.equal(new Set(ids).size, ids.length)
})

test('新增的筆記按鈕文字兩種語言都有', () => {
  for (const lang of Object.keys(STRINGS)) {
    const t = translator(lang)
    for (const key of ['notes.clipAll', 'notes.exportAll', 'notes.clear', 'notes.clearConfirm', 'notes.clearYes', 'notes.clearNo', 'toast.clippedNone', 'toast.notesCleared']) {
      assert.ok(t(key), `${lang} 缺少 ${key}`)
    }
    assert.match(t('toast.clippedAll', 31), /31/)
  }
})
