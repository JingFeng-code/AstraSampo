import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { applyPartialSettings } from '../src/utils/settings-partial.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('部分更新只通知父層更新設定，不會呼叫會關閉視窗的 onSaved', () => {
  const calls = []
  const messages = []
  const errors = []
  const next = { bilibili_sessdata_set: false }
  const message = applyPartialSettings({
    next,
    message: '已移除儲存的 SESSDATA',
    onChanged: value => calls.push(value),
    setMessage: value => messages.push(value),
    setError: value => errors.push(value),
  })
  assert.deepEqual(calls, [next], '父層設定要更新，畫面才反映已移除')
  assert.equal(message, '已移除儲存的 SESSDATA')
  assert.deepEqual(messages, ['已移除儲存的 SESSDATA'], '提示要真的寫進畫面狀態')
  assert.deepEqual(errors, [''])
})

test('兩個部分更新動作都走 applyPartialSettings，不再呼叫 onSaved', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  const importFn = modal.slice(modal.indexOf('async function importCookie'),
                               modal.indexOf('async function removeSessdata'))
  const removeFn = modal.slice(modal.indexOf('async function removeSessdata'),
                              modal.indexOf('async function handleSave'))
  assert.match(importFn, /applyPartialSettings\(/)
  assert.match(removeFn, /applyPartialSettings\(/)
  assert.doesNotMatch(importFn, /onSaved\?\./, '匯入不該關閉視窗')
  assert.doesNotMatch(removeFn, /onSaved\?\./, '移除不該關閉視窗')
  assert.match(modal, /onChanged: onSettingsChanged/)
  // 提示訊息有實際渲染在畫面上
  assert.match(modal, /\{cookieMsg &&/)
})

test('App 傳入的 onSettingsChanged 只更新 settings，不關閉視窗', () => {
  const app = read('../src/App.jsx')
  const line = app.split('\n').find(row => row.includes('<SettingsModal '))
  assert.ok(line, '找不到 SettingsModal')
  assert.match(line, /onSettingsChanged=\{next=>setSettings\(next\)\}/)
  assert.match(line, /onSaved=\{handleSettingsSaved\}/)
  // 只有一般「儲存」走 handleSettingsSaved，它才會關閉視窗
  assert.match(app, /function handleSettingsSaved\(next\)\{[\s\S]*?setShowSettings\(false\)/)
})
