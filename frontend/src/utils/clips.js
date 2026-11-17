// 筆記項目（clip）的合併與排序。
// 抽出來的理由：一次加入多張卡時最容易出錯的就是重複與順序，這兩件事要能單獨測。
let seq = 0

// id 只用來當 React key 與刪除識別；同一次操作加入多張卡時不能撞號
export function newClipId(cardIndex) {
  seq += 1
  return `${Date.now()}-${cardIndex}-${seq}`
}

// 同一張卡只留一份：連按兩次「全部收進筆記」不能變成兩份
export function mergeClips(existing = [], incoming = []) {
  const next = [...existing]
  const seenCards = new Set(next.map(clip => clip.cardIndex))
  const seenIds = new Set(next.map(clip => clip.id))
  for (const clip of incoming) {
    if (!clip || seenCards.has(clip.cardIndex) || seenIds.has(clip.id)) continue
    seenCards.add(clip.cardIndex)
    seenIds.add(clip.id)
    next.push(clip)
  }
  return next
}

// 匯出時照影片時間排；沒有時間的排最後，並維持原本的相對順序
export function sortClipsByTime(clips = []) {
  const time = clip => {
    const value = clip?.ts
    return value == null || !Number.isFinite(Number(value)) ? null : Number(value)
  }
  return clips
    .map((clip, order) => ({ clip, order, t: time(clip) }))
    .sort((a, b) => {
      if (a.t != null && b.t != null) return a.t - b.t || a.order - b.order
      if (a.t != null) return -1
      if (b.t != null) return 1
      return a.order - b.order
    })
    .map(item => item.clip)
}
