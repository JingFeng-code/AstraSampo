import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

// 版面問題以截圖為準（PR 附 375／768／1280）；這裡只鎖住「不要又改回截斷」的規則，
// 讓之後的改動不會默默把來源標籤裁掉或把底部留白拿掉。
test('標題列：模型／來源／張數／進階工具自成一行，不會各自被切斷', () => {
  const deck = read('../src/components/CardDeck.jsx')
  assert.match(deck, /<div className="deck-meta">/)
  assert.match(deck, /deck-source/)
  // 模型名稱真的放不下時才截斷，滑鼠移上去看得到完整文字
  // （鍵盤聚焦不會顯示 title 提示，所以文件與回報不能寫成「聚焦也看得到」）
  assert.match(deck, /title=\{`\$\{t\('deck\.modelTitle'\)\}/)
  // 沒有自訂提示就不要多一個按 Tab 停下來卻什麼都看不到的焦點位置
  assert.doesNotMatch(deck, /tabIndex=/)
  // 標題本身也要有完整文字可看
  assert.match(deck, /<h2 className="deck-title" title=\{result\.title\}>/)
})

test('CSS：來源標籤不縮、模型名稱先縮，底部留白蓋不住卡片按鈕', () => {
  const css = read('../src/index.css')
  assert.match(css, /\.deck-meta \.deck-source\{flex-shrink:0[^}]*\}/)
  assert.match(css, /\.deck-meta \.model-badge\{flex:0 1 auto\}/)
  assert.match(css, /\.deck-head\{display:flex;flex-wrap:wrap/)
  // 手機寬度不再硬裁 120px
  assert.doesNotMatch(css, /\.model-badge\{max-width:120px\}/)
  // 浮動的「筆記」「問模型」約 44px 高、離底部 12–20px，留白要大於兩者相加
  assert.match(css, /\.deck\{[^}]*padding-bottom:88px/)
  assert.match(css, /\.workspace-split \.deck\{overflow-y:auto;padding-bottom:104px\}/)
})


test('窄版允許整列換行，寬版維持一行', () => {
  const css = read('../src/index.css')
  // 寬版：一行，空間不夠時只有模型名稱收窄
  assert.match(css, /\.deck-meta\{[^}]*flex-wrap:nowrap\}/)
  // 窄版：整組可以換行；英文介面的來源標籤（Deep visual + captions）比中文長
  assert.match(css, /@media\(max-width:480px\)\{\s*\.deck-meta\{flex-wrap:wrap\}/)
  assert.match(css, /\.deck-meta \.deck-source\{flex-shrink:0[^}]*\}/)
})
