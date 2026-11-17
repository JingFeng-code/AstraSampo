// 重點區的「重點／總結」分頁：狀態要跨重新整理保留，換一支影片則回到重點。
// 抽成純函式，讓 node:test 能不用 DOM 就驗證行為（含 localStorage 壞掉的情況）。
export const DECK_TAB_KEY = 'ycr-deck-tab'

// 沒有總結內容就不該出現「總結」分頁
export function hasOverview(overview) {
  if (!overview) return false
  return !!overview.summary || (overview.points || []).length > 0
}

export function readDeckTab(storage) {
  try {
    return storage?.getItem(DECK_TAB_KEY) === 'overview' ? 'overview' : 'cards'
  } catch {
    return 'cards'
  }
}

export function writeDeckTab(storage, tab) {
  try {
    storage?.setItem(DECK_TAB_KEY, tab === 'overview' ? 'overview' : 'cards')
  } catch {
    /* 無痕模式或配額用盡時只是不記得，不該讓重點區掛掉 */
  }
}

// 換一支影片就回到重點：舊分頁是上一支影片的選擇，不能沿用
// （同一個 result 物件＝重新整理或換卡，保留使用者當下的選擇）
export function resolveDeckTab(previousResult, nextResult, tab) {
  return previousResult === nextResult ? tab : 'cards'
}

// 總結的條列能不能對到某張卡：只接受正規化後完全相同，對不上就維持純文字
export function matchOverviewPoint(point, cards = []) {
  const key = normalize(point)
  if (!key) return -1
  const index = cards.findIndex(card => normalize(card?.heading) === key)
  return index
}

function normalize(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
}
