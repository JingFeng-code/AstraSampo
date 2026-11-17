import { useState } from 'react'
import * as api from '../api.js'
import { pickField, youtubeLink, TRANSCRIPT_KEYS, TRANSLATION_KEYS } from '../utils.js'
import { mergeClips, newClipId } from '../utils/clips.js'

// 卡片瀏覽／摘進筆記／Deep Dive 狀態，圍繞目前的摘要結果 (result) 運作
export default function useCards(result, provider, initial = {}) {
  const cards = result?.cards || []
  const [index, setIndexRaw] = useState(initial.index || 0)
  const [startAt, setStartAt] = useState({ t: 0, auto: false, key: 0 })
  const [deepdives, setDeepdives] = useState(initial.deepdives || {})
  const [ddLoading, setDdLoading] = useState(null)
  const [clips, setClips] = useState(initial.clips || [])
  const clippedIds = new Set(clips.map(c => c.cardIndex))

  // play=false 時只跳到該秒數、不自動播放（切換卡片時的行為）
  function jumpToCard(i, play = false) {
    setIndexRaw(i)
    const t = cards[i]?.timestamp_seconds
    if (t != null) setStartAt(s => ({ t: Math.floor(t), auto: !!play, key: s.key + 1 }))
  }

  function buildClip(i, id) {
    const c = cards[i]
    if (!c) return null
    return {
      id, cardIndex: i, heading: c.heading, summary: c.summary,
      transcript: pickField(c, TRANSCRIPT_KEYS), translation: pickField(c, TRANSLATION_KEYS),
      visual: c.visual || null,
      ts: c.timestamp_seconds ?? null,
      link: result?.source_type === 'local' ? null : result?.youtube_video_id != null ? youtubeLink(result.youtube_video_id, c.timestamp_seconds) : result?.bilibili_video_id ? `https://www.bilibili.com/video/${result.bilibili_video_id}/?p=${result.bilibili_page||1}&t=${Math.max(0,Math.floor(c.timestamp_seconds||0))}` : result?.source_url || null,
      note: '',
    }
  }

  function clipCard(i) {
    const c = cards[i]
    if (!c || clippedIds.has(i)) return null
    setClips(prev => mergeClips(prev, [buildClip(i, newClipId(i))]))
    return c
  }

  // 一次收進所有還沒收的卡；回傳這次實際新增幾則，讓呼叫端能回報
  function clipAll() {
    const missing = cards.map((_, i) => i).filter(i => !clippedIds.has(i))
    if (!missing.length) return 0
    setClips(prev => mergeClips(prev, missing.map(i => buildClip(i, newClipId(i)))))
    return missing.length
  }

  // 匯出「全部重點」用：不寫進筆記狀態，所以不需要先收卡
  function allClips() {
    return cards.map((_, i) => buildClip(i, newClipId(i))).filter(Boolean)
  }
  function removeClip(id) { setClips(prev => prev.filter(c => c.id !== id)) }
  function updateClipNote(id, note) { setClips(prev => prev.map(c => c.id === id ? { ...c, note } : c)) }

  async function handleDeepDive(i) {
    const c = cards[i]
    if (!c || deepdives[i] || ddLoading != null) return
    setDdLoading(i)
    try {
      const data = await api.deepdive(provider, result.title, { heading: c.heading, summary: c.summary, timestamp_seconds: c.timestamp_seconds ?? null })
      const text = typeof data === 'string' ? data : (data.content || JSON.stringify(data))
      setDeepdives(prev => ({ ...prev, [i]: { text, model: (data && data.model_used) || '' } }))
    } finally {
      setDdLoading(null)
    }
  }

  function resetForNewResult() {
    setIndexRaw(0); setDeepdives({}); setClips([]); setStartAt({ t: 0, auto: false, key: 0 })
  }

  return {
    index, setIndex: i => jumpToCard(i, false), jumpToCard, startAt,
    clips, setClips, clippedIds, clipCard, clipAll, allClips, removeClip, updateClipNote,
    deepdives, ddLoading, handleDeepDive, resetForNewResult,
  }
}
