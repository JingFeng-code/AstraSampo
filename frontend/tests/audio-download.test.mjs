import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { canOfferAudioDownload } from '../src/utils/source-info.js'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('只有 Bilibili 的「沒有字幕／需要登入」才提供下載音訊', () => {
  const noSubtitle = '這支 Bilibili 影片沒有可公開取得的字幕。如果你有，可以匯入 SRT／VTT 後再分析。'
  const login = '這支 Bilibili 影片的字幕需要登入才能讀取。如果你有字幕檔，也可以匯入 SRT／VTT。'
  assert.equal(canOfferAudioDownload('bilibili', noSubtitle), true)
  assert.equal(canOfferAudioDownload('bilibili', login), true)
  // 其他來源、其他錯誤（網路、分 P、SESSDATA 格式）都不能出現下載選項
  assert.equal(canOfferAudioDownload('youtube', noSubtitle), false)
  assert.equal(canOfferAudioDownload('bilibili', 'Bilibili 字幕下載失敗或遭到限制。'), false)
  assert.equal(canOfferAudioDownload('bilibili', ''), false)
})

test('下載音訊要按兩次確認，沒確認不會送出 allow_audio_download', () => {
  const prompt = read('../src/components/AudioDownloadPrompt.jsx')
  assert.match(prompt, /useState\(false\)/)
  assert.match(prompt, /onClick=\{\(\) => setConfirm\(true\)\}/)
  assert.match(prompt, /onClick=\{\(\) => \{ setConfirm\(false\); onConfirm\(\) \}\}/)
  assert.match(prompt, /role="alert"/)

  const app = read('../src/App.jsx')
  assert.match(app, /async function startAnalysis\(useVisual,allowAudio=false\)/)
  assert.match(app, /canOfferAudioDownload\(source,stream\.error\)/)
  assert.match(app, /onConfirm=\{\(\)=>startAnalysis\(false,true\)\}/)
  assert.match(app, /stream\.summarize\(isLocalMode\?localUrl:url,activeProvider,useVisual,isLocalMode\?localVideo\?\.name:null,allowAudio\)/)
})

test('串流請求會帶 allow_audio_download，預設是 false', () => {
  const api = read('../src/api.js')
  assert.match(api, /export const summarizeStream = \(url, provider, deep_visual=false, onEvent, signal, allow_audio_download=false\)/)
  assert.match(api, /\{url, provider, deep_visual, allow_audio_download\}/)
  const hook = read('../src/hooks/useSummarizeStream.js')
  assert.match(hook, /\}, controller\.signal, allowAudioDownload\)/)
})

test('風險說明兩種語言都要講清楚：暫存、刪除、條款限制', () => {
  for (const lang of Object.keys(STRINGS)) {
    const table = STRINGS[lang]
    for (const key of ['audio.risk', 'audio.action', 'audio.busy', 'audio.confirm', 'audio.confirmYes', 'audio.confirmNo']) {
      assert.ok(table[key], `${lang} 缺少 ${key}`)
    }
    assert.match(table['audio.risk'], /yt-dlp/, lang)
    assert.match(table['audio.confirmYes'], /./, lang)
  }
  assert.match(STRINGS.zh['audio.risk'], /暫存/)
  assert.match(STRINGS.zh['audio.risk'], /(刪除|刪掉)/)
  assert.match(STRINGS.zh['audio.risk'], /條款/)
  assert.match(STRINGS.en['audio.risk'], /(temporary|temp)/)
  assert.match(STRINGS.en['audio.risk'], /delete/)
  assert.match(STRINGS.en['audio.risk'], /terms/)
})
