import { useEffect, useRef, useState } from 'react'
import { fmtTime, pickField, summaryLines, TRANSCRIPT_KEYS, TRANSLATION_KEYS, TRANSCRIPT_SOURCE_KEYS } from '../utils.js'
import { defaultTrack, hasCode } from '../hooks/useImplement.js'
import { getDeckStorage, hasOverview, matchOverviewPoint, readDeckTab, resolveDeckTab, writeDeckTab } from '../utils/deck-tabs.js'
import { useI18n } from '../i18n/index.jsx'

// 重點數量多時把導覽縮小排密，避免撐破標題列
const COMPACT_FROM = 24

export default function CardDeck({ result, index, setIndex, clippedIds, onClip, onJumpVideo, deepdives, onDeepDive, deepdiveLoading, onImplement, fullWidth, onTabChange }) {
  const { t } = useI18n()
  const cards=result.cards||[], card=cards[index]
  const dotsRef=useRef(null), deckRef=useRef(null)
  // 總結是參考資料，不該擋在每次切換的重點上方；記住使用者上次停在哪個分頁
  const overview=result.overview
  const showTabs=cards.length>0&&hasOverview(overview)
  const storage=getDeckStorage()
  const [tab,setTab]=useState(()=>readDeckTab(storage))
  const firstResult=useRef(result)
  // 分析另一支影片時回到重點；重新整理頁面（同一個 result 首次掛載）則保留上次的選擇
  useEffect(()=>{
    const next=resolveDeckTab(firstResult.current,result,tab)
    firstResult.current=result
    if(next!==tab)setTab(next)
  },[result])
  useEffect(()=>{writeDeckTab(storage,tab);onTabChange?.(tab)},[tab])
  // 圓點列可橫向捲動，切換卡片時把目前的圓點帶進視野
  useEffect(()=>{
    const el=dotsRef.current?.children[index]
    el?.scrollIntoView({block:'nearest',inline:'nearest'})
  },[index])
  // 重點欄會自己捲動，換一張卡或切回重點時要從頭開始看（最上方就是卡片本身）
  useEffect(()=>{ if(deckRef.current) deckRef.current.scrollTop=0 },[index,tab])
  // 從總結點進某一條：行為要和切換卡片一致（只跳過去，不自動播放）
  function openCard(i){ setTab('cards'); setIndex(i) }
  // 模型這次沒有回傳任何卡片（短片、辨識不到內容、或輸出被截斷）：
  // 以前這裡會直接讀 card.heading 而讓整個畫面變成空白，現在改成看得到的說明。
  if(!cards.length) return (
    <section className="deck deck-empty">
      {overview&&(overview.summary||overview.points?.length)&&<div className="deck-overview">
        <h3 className="deck-overview-title">{t('deck.overview')}</h3>
        {overview.summary&&<p>{overview.summary}</p>}
        {(overview.points||[]).length>0&&<ul className="summary-list">{overview.points.map((p,i)=><li key={i}>{p}</li>)}</ul>}
      </div>}
      <p className="deck-empty-title">{t('deck.empty')}</p>
      <p className="deck-empty-hint">{t('deck.emptyHint')}</p>
      {result.transcript_source&&<p className="deck-empty-hint">{t('deck.emptySource',t(TRANSCRIPT_SOURCE_KEYS[result.transcript_source]||result.transcript_source))}</p>}
    </section>
  )
  if (!card) return null
  const transcript=pickField(card,TRANSCRIPT_KEYS), translation=pickField(card,TRANSLATION_KEYS)
  const points=summaryLines(card.summary)
  const isClipped=clippedIds.has(index), dive=deepdives[index], isYT=['youtube','bilibili','local'].includes(result.source_type)
  // 舊的工作階段（localStorage）沒有 content_type，defaultTrack 會退回 study
  const suggestedTrack=defaultTrack(result.content_type,hasCode(cards))
  const sourceKey=result.transcript_source&&TRANSCRIPT_SOURCE_KEYS[result.transcript_source]
  const [kbdL,kbdR,kbdMid,kbdN,kbdTail]=t('deck.kbdHint','←','→','N')
  const overviewPoints=overview?.points||[]
  const overviewPanel=(
    <div className="deck-overview" id="deck-panel-overview" role="tabpanel" aria-labelledby="deck-tab-overview">
      {overview?.summary&&<p>{overview.summary}</p>}
      {overviewPoints.length>0&&<ul className="summary-list">{overviewPoints.map((p,i)=>{
        const target=matchOverviewPoint(p,cards)
        return <li key={i}>{target>=0?<button type="button" className="overview-link" onClick={()=>openCard(target)} title={t('deck.goto',target+1)}>{p}</button>:p}</li>
      })}</ul>}
    </div>
  )
  return (
    <section className={`deck ${fullWidth?'deck-full':''}`} ref={deckRef}>
      <div className="deck-head">
        <h2 className="deck-title" title={result.title}>{result.title}</h2>
        <div className="deck-meta">
          {/* 只有模型名稱會在最擠的時候被省略；滑鼠移上去可看全文，
              鍵盤聚焦目前看不到（瀏覽器不會在聚焦時顯示 title 提示） */}
          {result.model_used&&<span className="model-badge" title={`${t('deck.modelTitle')}：${result.model_used}${result.segments>1?t('deck.segments',result.segments):''}`}>{result.model_used}{result.segments>1?t('deck.segments',result.segments):''}</span>}
          {/* 來源標籤字數少，不該跟著模型名稱一起被截斷 */}
          {sourceKey&&<span className="model-badge deck-source" title={t('deck.sourceTitle')}>{t(sourceKey)}</span>}
          <span className="deck-count">{t('deck.count',index+1,cards.length)}</span>
          {/* 實作的對象是整支影片，不是單張卡——所以按鈕在標題列，不在卡片上 */}
          <details className="deck-advanced"><summary>{t('ai.advancedTools')}</summary><button className="btn-implement" onClick={onImplement} title={t('implement.ctaTitle')}>{t(`implement.cta.${suggestedTrack}`)}</button></details>
        </div>
      </div>
      {showTabs&&<div className="deck-tabs" role="tablist" aria-label={t('deck.tabs')}>
        <button type="button" role="tab" id="deck-tab-cards" className="deck-tab" aria-selected={tab==='cards'} aria-controls="deck-panel-cards" onClick={()=>setTab('cards')}>{t('deck.tabCards')}</button>
        <button type="button" role="tab" id="deck-tab-overview" className="deck-tab" aria-selected={tab==='overview'} aria-controls="deck-panel-overview" onClick={()=>setTab('overview')}>{t('deck.tabOverview')}</button>
      </div>}
      {showTabs&&tab==='overview'?overviewPanel:<div role={showTabs?'tabpanel':undefined} id={showTabs?'deck-panel-cards':undefined} aria-labelledby={showTabs?'deck-tab-cards':undefined}>
      {/* 重點導覽常駐頂部，不必捲到底才能切換 */}
      <div className="deck-nav deck-nav-top">
        <button className="nav-arrow" onClick={()=>setIndex(index-1)} disabled={index===0} aria-label={t('deck.prev')}>←</button>
        <div className={`dots ${cards.length>=COMPACT_FROM?'compact':''}`} ref={dotsRef}>{cards.map((_,i)=><button key={i} className={`dot-btn ${i===index?'on':clippedIds.has(i)?'was-clipped':''}`} onClick={()=>setIndex(i)} title={t('deck.goto',i+1)} aria-label={t('deck.goto',i+1)}/>)}</div>
        <button className="nav-arrow" onClick={()=>setIndex(index+1)} disabled={index===cards.length-1} aria-label={t('deck.next')}>→</button>
      </div>
      <article className={`card ${isClipped?'clipped':''}`} key={index}>
        <div className="card-meta">
          <span>{t('deck.card',String(index+1).padStart(2,'0'))}</span>
          {isYT&&card.timestamp_seconds!=null&&<button className="card-ts" title={t('deck.jumpPlay')} onClick={()=>onJumpVideo(index)}>▶ {fmtTime(card.timestamp_seconds)}</button>}
        </div>
        <h2>{card.heading}</h2>
        {card.fallback&&<p className="card-fallback-note">{t('deck.fallbackNote')}</p>}
        {points.length>1?<ul className="summary-list">{points.map((p,i)=><li key={i}>{p}</li>)}</ul>:<p className="summary">{card.summary}</p>}
        {transcript&&<blockquote className="transcript"><span className="label">{t('deck.transcript')}</span>{transcript}{translation&&<><br/><span style={{color:'var(--ink)'}}>{translation}</span></>}</blockquote>}
        {card.visual&&<blockquote className="transcript"><span className="label">{t('deck.visual')}</span>{card.visual}</blockquote>}
        {/* 模型認為這張卡有可動手的事時，把它明講出來 */}
        {card.actionable&&card.action_hint&&<p className="action-hint"><span className="label">{t('deck.actionHint')}</span>{card.action_hint}</p>}
        <div className="card-actions">
          <button className="btn-clip" onClick={()=>onClip(index)} disabled={isClipped}>{isClipped?t('deck.clipped'):t('deck.clip')}</button>
          <button className="btn-paper" onClick={()=>onDeepDive(index)} disabled={deepdiveLoading===index||!!dive}>{deepdiveLoading===index?t('deck.deepdiveLoading'):dive?t('deck.deepdiveDone'):t('deck.deepdive')}</button>
        </div>
        {dive&&<div className="deepdive"><span className="label">{t('deck.deepdiveLabel')}{dive.model?` / ${dive.model}`:''}</span>{dive.text}</div>}
      </article>
      <p className="kbd-hint"><kbd>{kbdL}</kbd> <kbd>{kbdR}</kbd>{kbdMid}<kbd>{kbdN}</kbd>{kbdTail}</p>
      </div>}
    </section>
  )
}
