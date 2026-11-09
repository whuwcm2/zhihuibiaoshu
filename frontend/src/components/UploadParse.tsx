import { useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { api } from '../api'
import type { ParseJobStatus } from '../types'
import { errorText, formatNumber } from '../utils'
import { StatusPill } from './StatusPill'

const STAGE_LABELS: Record<string, string> = {
  parsing: '解析 PDF',
  extracting: '结构化抽取',
  embedding: '向量入库',
}

export function UploadParse({
  onGoWrite,
}: {
  onGoWrite: (docId: string) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [parser, setParser] = useState('auto')
  const [extract, setExtract] = useState(false)
  const [ingest, setIngest] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [job, setJob] = useState<ParseJobStatus | null>(null)
  const [startedOptions, setStartedOptions] = useState({ extract: false, ingest: false })
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const jobId = job?.job_id
  const jobStatus = job?.status

  useEffect(() => {
    if (!jobId || jobStatus === 'succeeded' || jobStatus === 'failed') return
    const timer = window.setInterval(() => {
      api
        .getParseJob(jobId)
        .then(setJob)
        .catch((reason: unknown) => setError(errorText(reason)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [jobId, jobStatus])

  const pickFiles = (files: FileList | null) => {
    const picked = files?.[0]
    if (!picked) return
    if (!picked.name.toLowerCase().endsWith('.pdf')) {
      setError('只支持 PDF 文件')
      return
    }
    setError('')
    setJob(null)
    setFile(picked)
  }

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    setDragOver(false)
    pickFiles(event.dataTransfer.files)
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) {
      setError('请先选择招标文件 PDF')
      return
    }
    setSubmitting(true)
    setError('')
    setJob(null)
    setStartedOptions({ extract, ingest })
    const form = new FormData()
    form.append('file', file)
    form.append('parser', parser)
    form.append('extract', String(extract))
    form.append('ingest', String(ingest))
    try {
      const created = await api.parsePdf(form)
      setJob({
        job_id: created.job_id,
        filename: created.filename,
        status: 'pending',
        created_at: new Date().toISOString(),
      })
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setSubmitting(false)
    }
  }

  const stageList = [
    'parsing',
    ...(startedOptions.extract ? ['extracting'] : []),
    ...(startedOptions.ingest ? ['embedding'] : []),
  ]
  const currentStageIndex = job?.stage ? stageList.indexOf(job.stage) : -1
  const progress =
    job?.status === 'succeeded'
      ? 100
      : job?.stage
        ? Math.min(92, Math.max(15, ((currentStageIndex + 1) / stageList.length) * 100))
        : 5
  const result = job?.result

  return (
    <div className="grid gap-6 xl:grid-cols-[1.25fr_1fr]">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5">
          <h2 className="text-lg font-semibold text-slate-900">上传招标文件</h2>
          <p className="mt-1 text-sm text-slate-500">
            支持拖拽 PDF，解析结果会进入“已解析文档库”，可直接发起投标编写。
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          <label
            onDragOver={(event) => {
              event.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition ${
              dragOver
                ? 'border-indigo-400 bg-indigo-50'
                : 'border-slate-300 bg-slate-50 hover:border-indigo-300 hover:bg-indigo-50/40'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={(event) => pickFiles(event.target.files)}
            />
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-xl text-indigo-600">
              ↑
            </div>
            <p className="mt-4 text-sm font-medium text-slate-700">
              {file ? file.name : '拖拽 PDF 到此处，或点击选择文件'}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {file
                ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
                : '单个文件不超过 200MB'}
            </p>
            {file && (
              <button
                type="button"
                className="mt-3 text-xs text-indigo-600 hover:underline"
                onClick={(event) => {
                  event.stopPropagation()
                  setFile(null)
                  if (inputRef.current) inputRef.current.value = ''
                }}
              >
                重新选择
              </button>
            )}
          </label>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">
                解析方式
              </span>
              <select
                value={parser}
                onChange={(event) => setParser(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              >
                <option value="auto">自动（MinerU 优先，失败回退 PyMuPDF）</option>
                <option value="mineru">MinerU 云端精准解析</option>
                <option value="pymupdf">PyMuPDF（快速，扫描件效果差）</option>
              </select>
            </label>

            <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <label className="flex items-start gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={extract}
                  onChange={(event) => setExtract(event.target.checked)}
                  className="mt-0.5 accent-indigo-600"
                />
                <span>
                  结构化抽取
                  <span className="block text-xs text-slate-500">
                    DeepSeek 抽取评标办法/资格/格式，耗时较长
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={ingest}
                  onChange={(event) => setIngest(event.target.checked)}
                  className="mt-0.5 accent-indigo-600"
                />
                <span>
                  向量入库
                  <span className="block text-xs text-slate-500">
                    智谱 embedding-3 写入 Chroma，供后续检索
                  </span>
                </span>
              </label>
            </div>
          </div>

          {error && (
            <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !file}
            className="mt-5 inline-flex w-full items-center justify-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {submitting ? '正在上传…' : '上传并开始解析'}
          </button>
        </form>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">解析进度</h2>
            <p className="mt-1 text-sm text-slate-500">任务在 Celery worker 中执行</p>
          </div>
          {job && <StatusPill status={job.status} />}
        </div>

        {!job && (
          <div className="flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-center">
            <p className="text-sm font-medium text-slate-600">尚未开始解析</p>
            <p className="mt-1 max-w-xs text-xs text-slate-500">
              上传 PDF 后，这里会实时显示解析、抽取和入库阶段。
            </p>
          </div>
        )}

        {job && (
          <div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span className="truncate font-mono">{job.job_id}</span>
                <span>{progress.toFixed(0)}%</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="mt-4 space-y-2">
                {stageList.map((stage, index) => {
                  const done =
                    job.status === 'succeeded' ||
                    (currentStageIndex >= 0 && index < currentStageIndex)
                  const active = job.stage === stage && job.status === 'running'
                  return (
                    <div key={stage} className="flex items-center gap-2 text-sm">
                      <span
                        className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${
                          done
                            ? 'bg-emerald-100 text-emerald-700'
                            : active
                              ? 'bg-indigo-600 text-white'
                              : 'bg-slate-200 text-slate-500'
                        }`}
                      >
                        {done ? '✓' : index + 1}
                      </span>
                      <span
                        className={
                          active ? 'font-medium text-indigo-700' : 'text-slate-600'
                        }
                      >
                        {STAGE_LABELS[stage] ?? stage}
                        {active ? '…' : ''}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            {job.error && (
              <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {job.error}
              </div>
            )}

            {result && (
              <div className="mt-5">
                <div className="grid grid-cols-2 gap-3">
                  {[
                    ['页数', formatNumber(result.page_count)],
                    ['解析器', result.parser],
                    ['内容块', formatNumber(result.block_count)],
                    ['片段数', formatNumber(result.chunk_count)],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="rounded-lg border border-slate-200 bg-white p-3"
                    >
                      <p className="text-xs text-slate-500">{label}</p>
                      <p className="mt-1 text-lg font-semibold text-slate-900">
                        {value}
                      </p>
                    </div>
                  ))}
                </div>

                {result.extraction_summary && (
                  <div className="mt-3 rounded-lg border border-indigo-100 bg-indigo-50/60 p-3 text-sm text-indigo-900">
                    <p className="font-medium">
                      {result.extraction_summary.project_name || '结构化抽取完成'}
                    </p>
                    <p className="mt-1 text-xs text-indigo-700">
                      目录 {formatNumber(result.extraction_summary.toc_count)} 条 ·
                      评分因素{' '}
                      {formatNumber(result.extraction_summary.scoring_factor_count)} 项
                      {result.ingested ? ' · 已写入向量库' : ''}
                    </p>
                  </div>
                )}

                {result.chunks_preview.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 text-sm font-medium text-slate-700">
                      片段预览
                    </p>
                    <div className="space-y-2">
                      {result.chunks_preview.map((chunk) => (
                        <div
                          key={chunk.index}
                          className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                        >
                          <p className="text-xs font-medium text-slate-500">
                            PDF p.{chunk.page_start}–{chunk.page_end} ·{' '}
                            {chunk.heading || '无章节'}
                          </p>
                          <p className="mt-1 line-clamp-3 text-sm text-slate-700">
                            {chunk.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => onGoWrite(result.doc_id)}
                  className="mt-5 w-full rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-medium text-indigo-700 transition hover:bg-indigo-100"
                >
                  用该文档编写投标文件 →
                </button>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
