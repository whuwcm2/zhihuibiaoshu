import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BidHistoryItem } from '../types'
import { errorText, formatDate, formatNumber } from '../utils'
import { MarkdownPreview } from './MarkdownPreview'

export function BidHistory() {
  const [items, setItems] = useState<BidHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [preview, setPreview] = useState<{ title: string; content: string } | null>(
    null,
  )

  const load = async () => {
    setLoading(true)
    try {
      setItems(await api.listBids())
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

  const showPreview = async (docId: string) => {
    try {
      const content = await api.previewMarkdown(docId)
      setPreview({ title: `${docId} · bid.md`, content })
    } catch (reason) {
      setError(errorText(reason))
    }
  }

  const openFolder = async (target: string) => {
    setNotice('')
    if (window.electronAPI) {
      try {
        await window.electronAPI.showItemInFolder(target)
      } catch (reason) {
        setNotice(errorText(reason))
      }
      return
    }
    try {
      await navigator.clipboard.writeText(target)
      setNotice(`文件路径已复制：${target}`)
    } catch {
      setNotice(`请手动打开：${target}`)
    }
  }

  const filtered = items.filter((item) => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return true
    return [item.doc_id, item.project_name, item.company_name]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  })

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">历史投标产物</h2>
          <p className="mt-1 text-sm text-slate-500">
            读取 data/bids（兼容 upload/bids）下已生成的 Markdown / Word / 审查结果。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索项目 / 公司 / doc_id"
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
      {notice && (
        <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
          {notice}
        </div>
      )}

      {loading ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">
          正在读取历史产物…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <p className="text-base font-medium text-slate-700">暂无历史投标产物</p>
          <p className="mt-1 text-sm text-slate-500">
            完成一次“投标文件编写”后，产物会出现在这里。
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((item) => (
            <article
              key={item.doc_id}
              className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-200 hover:shadow"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-slate-900">
                    {item.project_name || '未命名项目'}
                  </h3>
                  <p className="mt-1 text-xs text-slate-500">
                    投标人：{item.company_name || '【待填写】'} · 生成于{' '}
                    {formatDate(item.generated_at)}
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="rounded-full bg-amber-50 px-2 py-1 font-medium text-amber-700">
                    {formatNumber(item.placeholder_count)} 处待填写
                  </span>
                  <span
                    className={`rounded-full px-2 py-1 font-medium ${
                      item.has_docx
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-slate-100 text-slate-500'
                    }`}
                  >
                    {item.has_docx ? '含 Word' : '仅 Markdown'}
                  </span>
                </div>
              </div>

              <p className="mt-3 line-clamp-2 text-sm text-slate-600">
                {item.review_summary || '暂无审查摘要'}
              </p>
              <p className="mt-2 truncate font-mono text-xs text-slate-400" title={item.output_dir}>
                {item.doc_id}
              </p>

              <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={() => void showPreview(item.doc_id)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  预览 Markdown
                </button>
                <button
                  type="button"
                  onClick={() => void openFolder(item.markdown_path || item.output_dir)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  打开文件夹
                </button>
                <a
                  href={api.fileUrl(item.doc_id, 'bid.md')}
                  className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800"
                >
                  下载 Markdown
                </a>
                {item.has_docx && (
                  <a
                    href={api.fileUrl(item.doc_id, 'bid.docx')}
                    className="rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
                  >
                    下载 Word
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {preview && (
        <MarkdownPreview
          title={preview.title}
          content={preview.content}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  )
}
