import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { hasOverview, matchOverviewPoint, readDeckTab, resolveDeckTab, writeDeckTab } from '../src/utils/deck-tabs.js'
import { STRINGS } from '../src/i18n/strings.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

function memoryStorage(initial) {
  const data = { ...initial }
  return {
    getItem: key => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value) },
    data,
  }
}

test('沒有總結內容就不顯示「總結」分頁', () => {
  assert.equal(hasOverview(null), false)
  assert.equal(hasOverview(undefined), false)
  assert.equal(hasOverview({}), false)
  assert.equal(hasOverview({ summary: '', points: [] }), false)
  assert.equal(hasOverview({ summary: null, points: null }), false)
  assert.equal(hasOverview({ summary: '整支影片的結論' }), true)
  assert.equal(hasOverview({ points: ['第一條'] }), true)
})

test('預設是重點分頁，並記得上次的選擇', () => {
  assert.equal(readDeckTab(null), 'cards')
  assert.equal(readDeckTab(memoryStorage({})), 'cards')
  assert.equal(readDeckTab(memoryStorage({ 'ycr-deck-tab': 'overview' })), 'overview')
  // 壞掉的值或不認識的值一律回到重點
  assert.equal(readDeckTab(memoryStorage({ 'ycr-deck-tab': 'nonsense' })), 'cards')

  const storage = memoryStorage({})
  writeDeckTab(storage, 'overview')
  assert.equal(storage.data['ycr-deck-tab'], 'overview')
  assert.equal(readDeckTab(storage), 'overview')
  writeDeckTab(storage, 'cards')
  assert.equal(readDeckTab(storage), 'cards')
})

test('localStorage 不能寫時不拋錯（無痕模式、配額用盡）', () => {
  const broken = {
    getItem: () => { throw new Error('SecurityError') },
    setItem: () => { throw new Error('QuotaExceededError') },
  }
  assert.equal(readDeckTab(broken), 'cards')
  assert.doesNotThrow(() => writeDeckTab(broken, 'overview'))
})

test('換一支影片回到重點，同一支影片保留使用者的選擇', () => {
  const videoA = { title: 'A' }
  const videoB = { title: 'B' }
  assert.equal(resolveDeckTab(videoA, videoA, 'overview'), 'overview', '重新整理或換卡不該跳走')
  assert.equal(resolveDeckTab(videoA, videoB, 'overview'), 'cards', '新影片要回到重點')
  assert.equal(resolveDeckTab(null, videoB, 'overview'), 'cards', '第一次分析也要回到重點')
})

test('總結條列只對得上完全相同的卡片標題', () => {
  const cards = [{ heading: '第一張卡' }, { heading: '第二張\n卡' }]
  assert.equal(matchOverviewPoint('第一張卡', cards), 0)
  assert.equal(matchOverviewPoint('  第二張  卡 ', cards), 1, '空白差異視為同一張')
  assert.equal(matchOverviewPoint('第一張', cards), -1, '不做模糊比對')
  assert.equal(matchOverviewPoint('', cards), -1)
  assert.equal(matchOverviewPoint('第一張卡', []), -1)
  assert.equal(matchOverviewPoint('第一張卡', [{ heading: '其他' }]), -1)
})

test('CardDeck 用分頁呈現，重點分頁不再渲染總結', () => {
  const deck = read('../src/components/CardDeck.jsx')
  assert.match(deck, /role="tablist"/)
  assert.match(deck, /role="tab"/)
  assert.match(deck, /aria-selected=\{tab==='cards'\}/)
  assert.match(deck, /aria-selected=\{tab==='overview'\}/)
  assert.match(deck, /showTabs&&tab==='overview'\?overviewPanel/)
  // 分頁不搶左右方向鍵：卡片切換仍由全頁鍵盤處理
  assert.doesNotMatch(deck, /onKeyDown/)
  // 0 張卡時維持原本的總結畫面
  assert.match(deck, /deck-empty[\s\S]*?deck-overview/)
})

test('分頁文字兩種語言都有', () => {
  for (const [lang, table] of Object.entries(STRINGS)) {
    for (const key of ['deck.tabs', 'deck.tabCards', 'deck.tabOverview']) {
      assert.ok(table[key], `${lang} 缺少 ${key}`)
    }
  }
})
