import { useEffect, useState } from 'react'
import { API_BASE, api } from './api'
import { BidHistory } from './components/BidHistory'
import { BidWriter } from './components/BidWriter'
import { DocumentLibrary } from './components/DocumentLibrary'
import { UploadParse } from './components/UploadParse'

const STEPS = [
  {
    id: 1,
    label: '上传与解析',
    hint: '拖拽 PDF，设置解析方式与抽取入库选项',
  },
  {
    id: 2,
    label: '投标文件编写',
    hint: '填写投标人资料，发起多 Agent 编写并查看评分覆盖',
  },
  {
    id: 3,
    label: '已解析文档库',
    hint: '直接选择已解析文档，无需重新上传',
  },
  {
    id: 4,
    label: '历史投标产物',
    hint: '预览、下载 Markdown/Word，并在资源管理器中打开',
  },
] as const

function App() {
  const [step, setStep] = useState<number>(1)
  const [selectedDocId, setSelectedDocId] = useState('')
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>(
    'checking',
  )

  useEffect(() => {
    let alive = true
    const check = () => {
      api
        .health()
        .then(() => alive && setApiStatus('online'))
        .catch(() => alive && setApiStatus('offline'))
    }
    void check()
    const timer = window.setInterval(check, 30000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  const current = STEPS.find((item) => item.id === step) ?? STEPS[0]

  const handleSelectDoc = (docId: string) => {
    setSelectedDocId(docId)
    setStep(2)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-900">
      <aside className="flex w-64 shrink-0 flex-col bg-slate-950 text-slate-100">
        <div className="border-b border-white/10 px-5 py-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500 text-sm font-bold">
              标
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-wide">zhibiao</h1>
              <p className="text-[11px] text-slate-400">标书智能工作台</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-5">
          {STEPS.map((item) => {
            const active = item.id === step
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setStep(item.id)}
                className={`flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition ${
                  active
                    ? 'bg-indigo-500/15 text-white ring-1 ring-inset ring-indigo-400/40'
                    : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                }`}
              >
                <span
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                    active
                      ? 'bg-indigo-500 text-white'
                      : 'bg-white/10 text-slate-400'
                  }`}
                >
                  {item.id}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{item.label}</span>
                  <span className="mt-0.5 block text-[11px] leading-4 text-slate-500">
                    {item.hint}
                  </span>
                </span>
              </button>
            )
          })}
        </nav>

        <div className="border-t border-white/10 px-5 py-4 text-[11px] text-slate-500">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                apiStatus === 'online'
                  ? 'bg-emerald-400'
                  : apiStatus === 'offline'
                    ? 'bg-rose-400'
                    : 'bg-amber-400'
              }`}
            />
            <span>
              {apiStatus === 'online'
                ? '后端在线'
                : apiStatus === 'offline'
                  ? '后端离线'
                  : '检测中…'}
            </span>
          </div>
          <p className="mt-2 truncate font-mono" title={API_BASE}>
            {API_BASE}
          </p>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-slate-200 bg-white px-8 py-5">
          <p className="text-xs font-medium uppercase tracking-wider text-indigo-600">
            STEP {current.id} / {STEPS.length}
          </p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">
            {current.label}
          </h2>
          <p className="mt-1 text-sm text-slate-500">{current.hint}</p>
        </header>

        <div className="flex-1 overflow-y-auto p-6 lg:p-8">
          {apiStatus === 'offline' && (
            <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              后端 API 未连接。请先启动 FastAPI 和 Celery worker：
              <code className="ml-1 rounded bg-white/70 px-1.5 py-0.5 text-xs">
                uv run uvicorn api.main:app --port 8001
              </code>
            </div>
          )}

          {step === 1 && <UploadParse onGoWrite={handleSelectDoc} />}
          {step === 2 && (
            <BidWriter
              selectedDocId={selectedDocId}
              onSelectDoc={setSelectedDocId}
            />
          )}
          {step === 3 && <DocumentLibrary onSelect={handleSelectDoc} />}
          {step === 4 && <BidHistory />}
        </div>
      </main>
    </div>
  )
}

export default App
