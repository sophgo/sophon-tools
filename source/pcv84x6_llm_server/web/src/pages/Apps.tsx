import { useEffect, useState } from 'react'
import { api, type Model } from '../api'
import KbApp from './apps/KbApp'
import AsrApp from './apps/AsrApp'
import OcrApp from './apps/OcrApp'
import { readyOf } from './apps/common'

/* 应用演示: the auxiliary models put to work the way a customer would use them,
   rather than one endpoint at a time (that is what 对话测试 is for). Each tab
   reads the live model list, so loading a model on the 模型 page changes what
   the app can do without a reload. */

type Tab = 'kb' | 'asr' | 'ocr'

const TABS: { id: Tab; label: string; sub: string; needs: Model['kind'][] }[] = [
  { id: 'kb', label: '知识库问答', needs: ['embedding', 'rerank', 'ocr'],
    sub: '上传文档建一个本地知识库，用关键词 + 向量混合检索、Reranker 精排找到答案；扫描件和图片先 OCR。' },
  { id: 'asr', label: '语音转写', needs: ['asr'],
    sub: '离线语音转文字：边转边出稿，点时间跳到对应位置播放，可导出 TXT / SRT。' },
  { id: 'ocr', label: '文档识别', needs: ['ocr'],
    sub: '批量识别图片中的文字，图上标出每一行的位置，结果可复制或保存。' },
]

export default function Apps() {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('apps.tab') as Tab) || 'kb')
  const [models, setModels] = useState<Model[]>([])

  useEffect(() => {
    let alive = true
    const tick = () => api.models().then((r) => { if (alive) setModels(r.models) }).catch(() => undefined)
    void tick()
    const t = setInterval(tick, 4000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const pick = (t: Tab) => { setTab(t); localStorage.setItem('apps.tab', t) }
  const cur = TABS.find((t) => t.id === tab) ?? TABS[0]

  return (
    <>
      <h1>应用演示</h1>
      <p className="sub" data-testid="apps-sub">{cur.sub}</p>
      <div className="tabs" role="tablist" aria-label="演示应用" data-testid="apps-tabs">
        {TABS.map((t) => {
          const ok = t.needs.filter((k) => k && readyOf(models, k)).length
          return (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'active' : ''}
                    data-testid={`apps-tab-${t.id}`} onClick={() => pick(t.id)}
                    title={`所需模型已加载 ${ok} / ${t.needs.length}`}>
              {t.label}
              <span className={`tab-badge${ok === t.needs.length ? '' : ' off'}`}>
                <span className="dot" />{ok}/{t.needs.length}
              </span>
            </button>
          )
        })}
      </div>
      {tab === 'kb' && <KbApp models={models} />}
      {tab === 'asr' && <AsrApp models={models} />}
      {tab === 'ocr' && <OcrApp models={models} />}
    </>
  )
}
