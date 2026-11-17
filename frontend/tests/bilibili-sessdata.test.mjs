import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('SESSDATA 有明確的移除按鈕，且只在已儲存時出現', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  assert.match(modal, /async function removeSessdata\(\)/)
  // 只有按下按鈕才送空字串，後端才知道要清掉
  assert.match(modal, /api\.saveSettings\(\{ bilibili_sessdata: '' \}\)/)
  assert.match(modal, /state\?\.bilibili_sessdata_set &&/)
  assert.match(modal, /t\('settings\.bilibiliRemove'\)/)
})

test('一般儲存欄位空白時不送 bilibili_sessdata，不會誤刪', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  assert.match(modal, /\.\.\.\(sessdata\.trim\(\) \? \{ bilibili_sessdata: sessdata\.trim\(\) \} : \{\}\)/)
})

test('移除成功／失敗都有回饋，說明文字和實際行為一致', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  // 成功訊息改由 applyPartialSettings 寫進 setCookieMsg（不關閉視窗）
  assert.match(modal, /message: t\('settings\.bilibiliRemoveDone'\)/)
  assert.match(modal, /setCookieErr\(t\('settings\.bilibiliRemoveFailed', e\.message\)\)/)
  for (const [lang, table] of Object.entries(STRINGS)) {
    for (const key of ['settings.bilibiliRemove', 'settings.bilibiliRemoving', 'settings.bilibiliRemoveDone']) {
      assert.ok(table[key], `${lang} 缺少 ${key}`)
    }
    assert.match(table['settings.bilibiliRemoveFailed']('x'), /x/, lang)
    // 不能再暗示「清空欄位即刪除」——那正是這次的 bug
    const hint = table['settings.bilibiliSessdataHint']
    assert.ok(!hint.includes('清空欄位即刪除'), lang)
    assert.ok(!hint.includes('cleared by emptying'), lang)
  }
})
