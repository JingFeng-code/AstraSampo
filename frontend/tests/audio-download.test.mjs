import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { canOfferAudioDownload } from '../src/utils/source-info.js'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('只有 Bilibili 的「沒有字幕／需要登入」code 才提供下載音訊', () => {
  assert.equal(canOfferAudioDownload('bilibili', 'bilibili_no_subtitle'), true)
  assert.equal(canOfferAudioDownload('bilibili', 'bilibili_login_required'), true)
  // 其他來源、其他錯誤（網路、分 P、SESSDATA 格式）都沒有 code，不能出現下載選項
  assert.equal(canOfferAudioDownload('youtube', 'bilibili_no_subtitle'), false)
  assert.equal(canOfferAudioDownload('bilibili', ''), false)
  assert.equal(canOfferAudioDownload('bilibili', 'bilibili_network_error'), false)
  // 不再靠錯誤文字判斷：只有文字、沒有 code 就不顯示（登入過期那句不含 SRT）
  assert.equal(canOfferAudioDownload('bilibili', '這支影片沒有可公開取得的字幕，可以匯入 SRT／VTT。'), false)
})

test('fatal 事件的 code 會被保留下來，前端不靠翻譯文字判斷', () => {
  const hook = read('../src/hooks/useSummarizeStream.js')
  assert.match(hook, /const \[errorCode, setErrorCode\] = useState\(''\)/)
  assert.match(hook, /fatalCode = ev\.code \|\| ''/)
  assert.match(hook, /setErrorCode\(fatalCode\)/)
  const app = read('../src/App.jsx')
  assert.match(app, /canOfferAudioDownload\(source,stream\.errorCode\)/)
})

test('下載音訊要按兩次確認，沒確認不會送出 allow_audio_download', () => {
  const prompt = read('../src/components/AudioDownloadPrompt.jsx')
  assert.match(prompt, /useState\(false\)/)
  assert.match(prompt, /onClick=\{\(\) => setConfirm\(true\)\}/)
  assert.match(prompt, /onClick=\{\(\) => \{ setConfirm\(false\); onConfirm\(\) \}\}/)
  assert.match(prompt, /role="alert"/)

  const app = read('../src/App.jsx')
  assert.match(app, /async function startAnalysis\(useVisual,allowAudio=false\)/)
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
