import React from 'react'

/**
 * 畫面層的最後一道防線。
 *
 * 為什麼需要它：React 18 在 render 期間丟出例外時會把整棵樹卸載，使用者看到的就是
 * 一片黑（這個專案就發生過：模型回傳 0 張卡片，CardDeck 讀 card.heading 直接爆掉）。
 * 有 error boundary 至少能把錯誤訊息留在畫面上，使用者可以回報、也可以直接重載。
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // 主控台在發行版看不到，但仍留一份給開發版除錯
    console.error('[AstraTube] render error', error, info?.componentStack)
  }

  render() {
    const error = this.state.error
    if (!error) return this.props.children
    const message = String(error?.message || error)
    const zh = String(navigator.language || '').toLowerCase().startsWith('zh')
    const copy = zh
      ? { title: '畫面發生錯誤', body: '這次的操作沒有完成，但應用程式還在。重新載入後可以再試一次；如果每次都出現同樣訊息，請把下面這段文字回報給開發者。', reload: '重新載入' }
      : { title: 'Something went wrong', body: 'That action did not finish, but the app is still running. Reload and try again; if it keeps happening, please report the message below.', reload: 'Reload' }
    return (
      <main style={{ padding: 32, fontFamily: 'sans-serif', lineHeight: 1.7 }}>
        <h1>{copy.title}</h1>
        <p style={{ whiteSpace: 'pre-wrap', color: '#b3261e' }}>{message}</p>
        <p>{copy.body}</p>
        <button type="button" onClick={() => window.location.reload()}
                style={{ padding: '8px 16px', fontSize: 14, cursor: 'pointer' }}>
          {copy.reload}
        </button>
      </main>
    )
  }
}
