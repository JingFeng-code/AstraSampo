import { useState } from 'react'
import { useI18n } from '../i18n/index.jsx'

// Bilibili 沒有字幕時的第三條路：下載音訊到暫存資料夾、在這一台電腦轉成文字。
// 這是下載別人的影片內容，必須按兩次確認才送出；沒有確認就不會呼叫後端。
export default function AudioDownloadPrompt({ busy, onConfirm }) {
  const { t } = useI18n()
  const [confirm, setConfirm] = useState(false)
  return (
    <div className="no-caption-option audio-download">
      <span className="audio-risk">{t('audio.risk')}</span>
      {confirm ? (
        <span className="audio-confirm" role="alert">
          {t('audio.confirm')}
          <button type="button" className="btn-paper danger" disabled={busy}
            onClick={() => { setConfirm(false); onConfirm() }}>{t('audio.confirmYes')}</button>
          <button type="button" className="btn-paper" disabled={busy}
            onClick={() => setConfirm(false)}>{t('audio.confirmNo')}</button>
        </span>
      ) : (
        <button type="button" className="btn-paper" disabled={busy}
          onClick={() => setConfirm(true)}>{busy ? t('audio.busy') : t('audio.action')}</button>
      )}
    </div>
  )
}
