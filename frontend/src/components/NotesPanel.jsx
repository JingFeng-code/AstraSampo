import { useState } from 'react'
import { fmtTime } from '../utils.js'
import { useI18n } from '../i18n/index.jsx'

export default function NotesPanel({ vault, clips, cardCount = 0, onClipNoteChange, onRemoveClip, freeNote, setFreeNote, filename, setFilename, onSave, onExport, onExportAll, onClipAll, onCopy, onClear, lastSaved, saving, folders, noteFiles, saveOpts, onSaveOptsChange }) {
  const { t } = useI18n()
  // 清空會丟掉已收的重點與隨手筆記，要再確認一次（不用 window.confirm）
  const [confirmClear, setConfirmClear] = useState(false)
  const vs=!vault.configured?{cls:'warn',text:t('vault.notConfigured')}:!vault.exists?{cls:'warn',text:t('vault.missing')}:{cls:'ok',text:t('vault.connected')}
  const isAppend=saveOpts.mode==='append'
  const hasContent=clips.length>0||!!freeNote.trim()
  const canSave=!saving&&hasContent&&(!isAppend||saveOpts.targetFile)
  // 主要按鈕只留一個：有 Obsidian 時是存入 Obsidian，沒有的時候是下載 Markdown
  const primary='btn-save', secondary='btn-paper notes-action'
  return (
    <aside className="notes">
      <div className="notes-head"><h3>{t('notes.title')}</h3><span className="count">{t('notes.count',clips.length)}</span></div>
      {cardCount>0&&<button className={secondary} onClick={onClipAll} disabled={clips.length>=cardCount}>{t('notes.clipAll')}</button>}
      <div className="clip-list">
        {clips.length===0?<p className="empty-clip">{t('notes.empty')}</p>
          :clips.map(c=>(
            <div className="clip-item" key={c.id}>
              <div className="clip-head">{c.ts!=null&&<span className="ts">{fmtTime(c.ts)}</span>}<strong>{c.heading}</strong><button className="rm" onClick={()=>onRemoveClip(c.id)} aria-label={t('notes.remove')}>×</button></div>
              <textarea placeholder={t('notes.thought')} value={c.note} onChange={e=>onClipNoteChange(c.id,e.target.value)}/>
            </div>
          ))
        }
      </div>
      <textarea className="free-note" placeholder={t('notes.free')} value={freeNote} onChange={e=>setFreeNote(e.target.value)}/>


      {!vault.configured&&<label className="cfg-row notes-filename">
        <span className="cfg-label">{t('notes.filenameLabel')}</span>
        <input className="fname" type="text" placeholder={t('notes.filename')} value={filename} onChange={e=>setFilename(e.target.value)}/>
      </label>}
      {vault.configured&&(
        <div className="save-config">
          <label className="cfg-row">
            <span className="cfg-label">{t('notes.folder')}</span>
            <select value={saveOpts.folder} onChange={e=>onSaveOptsChange({folder:e.target.value})}>
              {folders.length===0&&<option value="">{t('notes.folderDefault')}</option>}
              {folders.map(f=><option key={f} value={f}>{f===''?t('notes.vaultRoot'):f}</option>)}
            </select>
          </label>
          <div className="mode-toggle">
            <button className={!isAppend?'on':''} onClick={()=>onSaveOptsChange({mode:'new'})}>{t('notes.modeNew')}</button>
            <button className={isAppend?'on':''} onClick={()=>onSaveOptsChange({mode:'append'})}>{t('notes.modeAppend')}</button>
          </div>
          {isAppend?(
            <label className="cfg-row">
              <span className="cfg-label">{t('notes.pick')}</span>
              <select value={saveOpts.targetFile} onChange={e=>onSaveOptsChange({targetFile:e.target.value})}>
                <option value="">{t('notes.pickPlaceholder')}</option>
                {noteFiles.map(f=><option key={f} value={f}>{f.replace(/\.md$/,'')}</option>)}
              </select>
            </label>
          ):(
            <label className="cfg-row notes-filename">
              <span className="cfg-label">{t('notes.filenameLabel')}</span>
              <input className="fname" type="text" placeholder={t('notes.filename')} value={filename} onChange={e=>setFilename(e.target.value)}/>
            </label>
          )}
          {isAppend&&noteFiles.length===0&&<p className="cfg-note">{t('notes.emptyFolder')}</p>}
        </div>
      )}

      {/* 動作列黏在面板底部：收了 31 則之後不必捲過整份清單才找得到下載與清空 */}
      <div className="notes-actions">
        {vault.configured&&<button className={primary} onClick={onSave} disabled={!canSave}>{saving?t('notes.saving'):isAppend?t('notes.append'):t('notes.save')}</button>}
        <button className={vault.configured?secondary:primary} onClick={onExport} disabled={!hasContent}>{t('notes.downloadMarkdown')}</button>
        {/* 不必先收進筆記：直接匯出「總結＋全部卡片＋隨手筆記」 */}
        <button className={secondary} onClick={onExportAll} disabled={!(cardCount>0||hasContent)}>{t('notes.exportAll')}</button>
        {/* 存檔失敗（例如「下載」資料夾不能寫）時的退路：至少能把 Markdown 複製走 */}
        <button className={secondary} onClick={onCopy} disabled={!hasContent}>{t('notes.copyMarkdown')}</button>
        {confirmClear?
          <span className="notes-clear-confirm" role="alert">
            {t('notes.clearConfirm')}
            <button type="button" className="btn-paper danger" onClick={()=>{setConfirmClear(false);onClear()}}>{t('notes.clearYes')}</button>
            <button type="button" className="btn-paper" onClick={()=>setConfirmClear(false)}>{t('notes.clearNo')}</button>
          </span>:
          <button type="button" className={secondary} onClick={()=>setConfirmClear(true)} disabled={!hasContent}>{t('notes.clear')}</button>}
        {/* 存檔成功後留在畫面上，文字可選取；下次存檔或收合面板才清掉 */}
        {lastSaved&&<p className="notes-last-saved"><span className="cfg-label">{t('notes.lastSaved')}</span><span className="path">{lastSaved}</span></p>}
        {vault.configured&&<p className="save-hint"><span className={`vault-chip ${vs.cls}`} style={{marginLeft:0}}><span className="dot"/> {vs.text}</span><br/>{vault.configured?`vault：${vault.path?.replace(/[/\\][^/\\]*$/,'')||vault.path}`:t('notes.vaultHint')}</p>}
      </div>
    </aside>
  )
}
