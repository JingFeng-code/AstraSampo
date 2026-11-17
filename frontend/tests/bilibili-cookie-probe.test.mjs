import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('展開進階設定不會自動偵測瀏覽器', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  // 不能再有「advancedOpen 一變就呼叫 getBilibiliBrowsers」的 effect
  assert.doesNotMatch(modal, /if \(!advancedOpen\) return[\s\S]{0,200}getBilibiliBrowsers/)
  assert.doesNotMatch(modal, /\}, \[advancedOpen\]\)/)
})

test('只有按下「偵測可匯入的瀏覽器」才會讀取本機 cookie', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  assert.match(modal, /async function probeBrowsers\(\)/)
  assert.match(modal, /await api\.getBilibiliBrowsers\(\)/)
  assert.match(modal, /onClick=\{probeBrowsers\}/)
  assert.match(modal, /t\('settings\.bilibiliProbe'\)/)
  // 偵測結果不跨次使用：probed 只在這次開啟設定頁有效
  assert.match(modal, /setProbed\(true\)/)
})

test('偵測中的狀態與失敗訊息兩種語言都有', () => {
  for (const [lang, table] of Object.entries(STRINGS)) {
    for (const key of ['settings.bilibiliProbe', 'settings.bilibiliProbeBusy', 'settings.bilibiliProbeHint']) {
      assert.ok(table[key], `${lang} 缺少 ${key}`)
    }
    assert.match(table['settings.bilibiliProbeFailed']('x'), /x/, lang)
    // 說明文字要講清楚是「按了才讀」、只取 SESSDATA
    assert.match(table['settings.bilibiliProbeHint'], /SESSDATA/, lang)
  }
})
