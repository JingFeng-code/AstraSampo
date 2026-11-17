import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { applyPartialSettings } from '../src/utils/settings-partial.js'
import { connectionCheckKey } from '../src/utils/provider-check.js'

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


test('匯入成功會清掉手動貼上的 SESSDATA 草稿，其他欄位不動', () => {
  const others = { outputLanguage: 'en', vault: '/notes', typedKey: 'sk-typed' }
  const fields = { ...others, sessdata: 'manually-pasted-before-import' }
  let draft = fields.sessdata
  const next = { bilibili_sessdata_set: true }
  applyPartialSettings({
    next,
    message: '已從 Firefox 讀取登入狀態',
    onChanged: () => {},
    setMessage: () => {},
    setError: () => {},
    resetDraft: () => { draft = '' },
  })
  assert.equal(draft, '', '匯入後不能再留著舊草稿，否則一般儲存會蓋掉新 cookie')
  assert.deepEqual({ ...fields, sessdata: draft }, { ...others, sessdata: '' }, '其他未儲存欄位不能被動到')
})

test('匯入的程式碼真的把草稿清空（resetDraft: setSessdata）', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  const importFn = modal.slice(modal.indexOf('async function importCookie'),
                               modal.indexOf('async function removeSessdata'))
  assert.match(importFn, /resetDraft: \(\) => setSessdata\(''\)/)
})

test('只有連線相關設定會改變檢查鍵（SESSDATA 等變動不重跑驗證）', () => {
  const base = { engine: 'gemini', keySet: true, ollamaUrl: 'http://127.0.0.1:11434' }
  assert.equal(
    connectionCheckKey(base),
    connectionCheckKey({ ...base, sessdataSet: true, vault: '/x', outputLanguage: 'en', folder: 'f' }),
    'SESSDATA／vault／語言變動不該讓進行中的驗證被作廢',
  )
  assert.notEqual(connectionCheckKey(base), connectionCheckKey({ ...base, keySet: false }))
  assert.notEqual(connectionCheckKey(base), connectionCheckKey({ ...base, ollamaUrl: 'http://127.0.0.1:11435' }))
  assert.notEqual(connectionCheckKey(base), connectionCheckKey({ ...base, engine: 'openai' }))
})

test('連線檢查的 effect 只看 checkKey，作廢時把 checking 收掉', () => {
  const modal = read('../src/components/SettingsModal.jsx')
  assert.match(modal, /const checkKey = connectionCheckKey\(/)
  assert.match(modal, /\}, \[checkKey\]\)/)
  assert.doesNotMatch(modal, /\}, \[engine, state\]\)/, '不能整個 state 當依賴')
  assert.match(modal, /return \(\) => \{ \+\+checkVersion\.current; setChecking\(false\) \}/)
})
