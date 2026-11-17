import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { sourceProgressLabel } from '../src/utils/progress-label.js'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const t = (key, ...args) => {
  const value = STRINGS.zh[key]
  return typeof value === 'function' ? value(...args) : value
}

test('來源階段：下載與轉錄有專屬標籤，不會退回預設的整理重點', () => {
  assert.equal(sourceProgressLabel({ stage: 'source', state: 'download', percent: 42 }, t), '正在下載音訊… 42%')
  assert.equal(sourceProgressLabel({ stage: 'source', state: 'download' }, t), '正在下載音訊…')
  assert.equal(sourceProgressLabel({ stage: 'source', state: 'transcribe' }, t), '正在用本機模型把音訊轉成文字…（可按「停止」取消）')
  assert.equal(sourceProgressLabel({ stage: 'source' }, t), '讀取來源')
  // 產生階段不走這個函式
  assert.equal(sourceProgressLabel({ stage: 'generate', state: 'request' }, t), null)
  assert.equal(sourceProgressLabel(null, t), null)
  // 舊的錯誤事件形狀（stage 被蓋成 download）不該被當成來源階段
  assert.equal(sourceProgressLabel({ stage: 'download', percent: 42 }, t), null)
})

test('事件契約：stage="source" 搭配 state，不是把 stage 換成 download', () => {
  // 後端必須送 {"stage":"source","state":"download"}；
  // 這裡用同一份契約驗證前端標籤，兩邊才不會各說各話。
  assert.equal(sourceProgressLabel({ stage: 'source', state: 'download', percent: 7 }, t), '正在下載音訊… 7%')
  assert.equal(sourceProgressLabel({ stage: 'source', state: 'transcribe' }, t), '正在用本機模型把音訊轉成文字…（可按「停止」取消）')
  assert.equal(sourceProgressLabel({ stage: 'source', state: null }, t), '讀取來源')
})

test('GenerationProgress 用 sourceProgressLabel，不再自己判斷', () => {
  const app = read('../src/App.jsx')
  assert.match(app, /sourceProgressLabel\(progress,t\)/)
  assert.match(app, /let label=sourceLabel\|\|t\('progress\.generate'\)/)
  assert.doesNotMatch(app, /progress\.stage==='source'&&progress\.state==='download'/)
})
