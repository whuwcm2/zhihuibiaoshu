import { useEffect, useState } from 'react'
import { api } from '../api'
import type { DocumentItem } from '../types'
import { errorText, formatDate, formatNumber } from '../utils'

export function DocumentLibrary({
  onSelect,
}: {
  onSelect: (docId: string) => void
}) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      setDocuments(await api.listDocuments())
      setError('')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const filtered = documents.filter((document) => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return true
    return [document.doc_id, document.project_name, document.source]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  })

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">已解析文档库</h2>
          <p className="mt-1 text-sm text-slate-500">
            读取 data/parsed（兼容 upload/parsed）下已有解析结果，可直接发起编写。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索项目 / 文件名 / doc_id"
            className="w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
          >
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">
          正在读取文档库…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <p className="text-base font-medium text-slate-700">暂无已解析文档</p>
          <p className="mt-1 text-sm text-slate-500">
            先在“上传与解析”中解析一份招标文件。
          </p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {filtered.map((document) => (
            <article
              key={document.doc_id}
              className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-200 hover:shadow"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-slate-900">
                    {document.project_name || '未命名项目'}
                  </h3>
                  <p className="mt-1 truncate font-mono text-xs text-slate-500">
                    {document.doc_id}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-1 text-xs font-medium ${
                    document.has_extraction
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-amber-50 text-amber-700'
                  }`}
                >
                  {document.has_extraction ? '已抽取' : '仅解析'}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2 text-sm text-slate-600 sm:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-400">页数</p>
                  <p className="font-medium">{formatNumber(document.page_count)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">片段</p>
                  <p className="font-medium">{formatNumber(document.chunk_count)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">解析器</p>
                  <p className="font-medium">{document.parser || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">创建时间</p>
                  <p className="font-medium">{formatDate(document.created_at)}</p>
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
                <p className="truncate text-xs text-slate-400" title={document.root}>
                  {document.source || document.root}
                </p>
                <button
                  type="button"
                  onClick={() => onSelect(document.doc_id)}
                  className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700"
                >
                  发起编写
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
