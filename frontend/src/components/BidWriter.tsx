import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BidJobStatus, BidderProfile, DocumentItem } from '../types'
import { EMPTY_PROFILE, getByPath, setByPath } from '../profileTemplate'
import { errorText, formatDate, formatNumber } from '../utils'
import { MarkdownPreview } from './MarkdownPreview'
import { StatusPill } from './StatusPill'

const STAGES = [
  'planner',
  'technical_writer',
  'commercial_writer',
  'format_writer',
  'reviewer',
  'assembler',
]

const STAGE_LABELS: Record<string, string> = {
  planner: '规划章节',
  technical_writer: '编写技术标',
  commercial_writer: '编写商务标',
  format_writer: '编写格式文件',
  reviewer: '合规审查',
  assembler: '合并产物',
}

const BASIC_FIELDS = [
  { path: 'company_name', label: '公司名称', placeholder: '须与营业执照一致' },
  { path: 'legal_representative', label: '法定代表人', placeholder: '' },
  { path: 'registered_address', label: '注册地址', placeholder: '' },
  { path: 'contact_person', label: '联系人', placeholder: '' },
  { path: 'contact_phone', label: '联系电话', placeholder: '' },
  { path: 'email', label: '电子邮箱', placeholder: '' },
  { path: 'business_license_no', label: '营业执照号', placeholder: '' },
  { path: 'registered_capital', label: '注册资本', placeholder: '' },
  { path: 'established_date', label: '成立日期', placeholder: 'YYYY-MM-DD' },
]

const QUALIFICATION_FIELDS = [
  { path: 'qualification.name', label: '资质名称', placeholder: '如：水利水电工程施工总承包' },
  { path: 'qualification.grade', label: '资质等级', placeholder: '如：三级' },
  { path: 'qualification.certificate_no', label: '资质证书编号', placeholder: '' },
  { path: 'qualification.valid_until', label: '资质有效期', placeholder: '' },
  { path: 'safety_license.certificate_no', label: '安全生产许可证号', placeholder: '' },
  { path: 'safety_license.valid_until', label: '安许证有效期', placeholder: '' },
]

const SEVERITY_STYLES: Record<string, string> = {
  high: 'border-rose-200 bg-rose-50 text-rose-800',
  medium: 'border-amber-200 bg-amber-50 text-amber-800',
  low: 'border-slate-200 bg-slate-50 text-slate-700',
}

function loadStoredProfile(): BidderProfile {
  try {
    const raw = localStorage.getItem('zhibiao_profile')
    if (raw) {
      const parsed = JSON.parse(raw) as unknown
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as BidderProfile
      }
    }
  } catch {
    // ignore invalid local draft
  }
  return EMPTY_PROFILE
}

export function BidWriter({
  selectedDocId,
  onSelectDoc,
}: {
  selectedDocId: string
  onSelectDoc: (docId: string) => void
}) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [docId, setDocId] = useState(selectedDocId)
  const [profile, setProfile] = useState<BidderProfile>(loadStoredProfile)
  const [jsonText, setJsonText] = useState(() =>
    JSON.stringify(loadStoredProfile(), null, 2),
  )
  const [jsonError, setJsonError] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [exportDocx, setExportDocx] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [job, setJob] = useState<BidJobStatus | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [preview, setPreview] = useState<{ title: string; content: string } | null>(
    null,
  )

  useEffect(() => {
    api
      .listDocuments()
      .then((items) => {
        setDocuments(items)
        if (!selectedDocId && items.length > 0) {
          setDocId(items[0].doc_id)
          onSelectDoc(items[0].doc_id)
        }
      })
      .catch((reason: unknown) => setError(errorText(reason)))
  }, [])

  useEffect(() => {
    if (selectedDocId) setDocId(selectedDocId)
  }, [selectedDocId])

  const jobId = job?.job_id
  const jobStatus = job?.status

  useEffect(() => {
    if (!jobId || jobStatus === 'succeeded' || jobStatus === 'failed') return
    const timer = window.setInterval(() => {
      api
        .getBidJob(jobId)
        .then(setJob)
        .catch((reason: unknown) => setError(errorText(reason)))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [jobId, jobStatus])

  const updateProfile = (next: BidderProfile) => {
    setProfile(next)
    setJsonText(JSON.stringify(next, null, 2))
    localStorage.setItem('zhibiao_profile', JSON.stringify(next))
  }

  const updateField = (path: string, value: string) => {
    updateProfile(setByPath(profile, path, value))
  }

  const handleJsonChange = (value: string) => {
    setJsonText(value)
    setJsonError('')
    try {
      const parsed = JSON.parse(value) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('顶层必须是 JSON 对象')
      }
      setProfile(parsed as BidderProfile)
      localStorage.setItem('zhibiao_profile', JSON.stringify(parsed))
    } catch (reason) {
      setJsonError(errorText(reason))
    }
  }

  const handleSubmit = async () => {
    if (!docId) {
      setError('请选择已解析文档')
      return
    }
    if (jsonError) {
      setError('高级 JSON 当前不合法，请先修正')
      return
    }
    setSubmitting(true)
    setError('')
    setNotice('')
    setJob(null)
    try {
      const created = await api.writeBid({
        doc_id: docId,
        profile,
        export_docx: exportDocx,
      })
      setJob({
        job_id: created.job_id,
        doc_id: docId,
        status: 'pending',
        created_at: new Date().toISOString(),
      })
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setSubmitting(false)
    }
  }

  const showPreview = async (targetDocId: string) => {
    try {
      const content = await api.previewMarkdown(targetDocId)
      setPreview({ title: `${targetDocId} · bid.md`, content })
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

  const result = job?.result
  const stageIndex = job?.stage ? STAGES.indexOf(job.stage) : -1
  const progress =
    job?.status === 'succeeded'
      ? 100
      : stageIndex >= 0
        ? Math.min(92, ((stageIndex + 1) / STAGES.length) * 100)
        : 5
  const report = result?.scoring_report
  const review = result?.review
  const coverage = report?.coverage_rate
    ? Math.round(report.coverage_rate * 100)
    : 0

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">
              1. 选择招标文档与编写参数
            </h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">
                  已解析文档
                </span>
                {documents.length > 0 ? (
                  <select
                    value={docId}
                    onChange={(event) => {
                      setDocId(event.target.value)
                      onSelectDoc(event.target.value)
                    }}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  >
                    {documents.map((document) => (
                      <option key={document.doc_id} value={document.doc_id}>
                        {document.project_name || document.doc_id} · {document.doc_id}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={docId}
                    onChange={(event) => setDocId(event.target.value)}
                    placeholder="输入 doc_id，或先上传解析 PDF"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  />
                )}
              </label>
              <label className="flex items-center gap-2 self-end rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={exportDocx}
                  onChange={(event) => setExportDocx(event.target.checked)}
                  className="accent-indigo-600"
                />
                同步导出 Word（.docx）
              </label>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              投标人资料缺失字段会由后端统一生成【待填写】占位符，不会编造事实。
            </p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  2. 投标人资料
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  常用字段用表单填写，复杂结构在高级 JSON 中维护，两种视图实时同步。
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAdvancedOpen((open) => !open)}
                className="shrink-0 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
              >
                {advancedOpen ? '收起高级 JSON' : '展开高级 JSON'}
              </button>
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              {BASIC_FIELDS.map((field) => (
                <label key={field.path} className="block">
                  <span className="mb-1.5 block text-sm font-medium text-slate-700">
                    {field.label}
                  </span>
                  <input
                    value={getByPath(profile, field.path)}
                    onChange={(event) => updateField(field.path, event.target.value)}
                    placeholder={field.placeholder}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  />
                </label>
              ))}
            </div>

            <h3 className="mt-6 text-sm font-semibold text-slate-800">资质与安许</h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {QUALIFICATION_FIELDS.map((field) => (
                <label key={field.path} className="block">
                  <span className="mb-1.5 block text-sm font-medium text-slate-700">
                    {field.label}
                  </span>
                  <input
                    value={getByPath(profile, field.path)}
                    onChange={(event) => updateField(field.path, event.target.value)}
                    placeholder={field.placeholder}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  />
                </label>
              ))}
            </div>

            {advancedOpen && (
              <div className="mt-6">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-700">
                    高级 JSON（类似业绩、人员、财务等）
                  </span>
                  <span className="text-xs text-slate-500">
                    {jsonError ? '格式有误' : '表单与 JSON 同步'}
                  </span>
                </div>
                <textarea
                  value={jsonText}
                  onChange={(event) => handleJsonChange(event.target.value)}
                  spellCheck={false}
                  rows={18}
                  className={`w-full rounded-xl border bg-slate-950 px-4 py-3 font-mono text-xs leading-5 text-slate-100 outline-none ${
                    jsonError
                      ? 'border-rose-400 ring-2 ring-rose-200'
                      : 'border-slate-700 focus:border-indigo-500'
                  }`}
                />
                {jsonError && (
                  <p className="mt-2 text-xs text-rose-600">JSON 错误：{jsonError}</p>
                )}
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting || !docId}
            className="w-full rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {submitting ? '正在提交编写任务…' : '发起多 Agent 编写任务'}
          </button>
        </section>

        <section className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">编写进度</h2>
                <p className="mt-1 text-sm text-slate-500">
                  LangGraph 多 Agent 串行执行
                </p>
              </div>
              {job && <StatusPill status={job.status} />}
            </div>

            {!job ? (
              <div className="mt-5 flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-center">
                <p className="text-sm font-medium text-slate-600">尚未发起编写</p>
                <p className="mt-1 max-w-xs text-xs text-slate-500">
                  提交后这里会显示规划、技术标、商务标、格式文件、审查、合并阶段。
                </p>
              </div>
            ) : (
              <div className="mt-5">
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
                  {STAGES.map((stage, index) => {
                    const done =
                      job.status === 'succeeded' ||
                      (stageIndex >= 0 && index < stageIndex)
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
                          {STAGE_LABELS[stage]}
                          {active ? '…' : ''}
                        </span>
                      </div>
                    )
                  })}
                </div>
                {job.error && (
                  <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                    {job.error}
                  </div>
                )}
              </div>
            )}
          </div>

          {notice && (
            <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
              {notice}
            </div>
          )}

          {result && (
            <div className="space-y-4">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-slate-900">评分覆盖报告</h2>
                <p className="mt-1 text-xs text-slate-500">
                  按技术标评分因素检查是否出现在生成内容中，不代表评委实际打分。
                </p>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs text-slate-500">覆盖分值</p>
                    <p className="mt-1 text-xl font-semibold text-slate-900">
                      {formatNumber(report?.covered_points)} /{' '}
                      {formatNumber(report?.total_points)}
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs text-slate-500">覆盖率</p>
                    <p className="mt-1 text-xl font-semibold text-slate-900">
                      {coverage}%
                    </p>
                  </div>
                </div>
                <div className="mt-4 space-y-2">
                  {(report?.items ?? []).map((item, index) => (
                    <div
                      key={`${item.item}-${index}`}
                      className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 px-3 py-2 text-sm"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-800">
                          {item.item}
                        </p>
                        <p className="text-xs text-slate-500">
                          {item.category}
                          {item.sub_item ? ` · 子项 ${item.sub_item}` : ''}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="text-xs text-slate-500">
                          {formatNumber(item.points)} 分
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            item.covered
                              ? 'bg-emerald-50 text-emerald-700'
                              : 'bg-rose-50 text-rose-700'
                          }`}
                        >
                          {item.covered ? '已覆盖' : '未覆盖'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900">审查意见</h2>
                  <span className="text-xs text-slate-500">
                    {formatNumber(result.placeholder_count)} 处【待填写】
                  </span>
                </div>
                {review?.fabrication_risk ? (
                  <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                    检测到潜在编造风险，请核对生成内容。
                  </p>
                ) : (
                  <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                    规则审计未发现编造风险；仍需人工核对全部占位符。
                  </p>
                )}
                <p className="mt-3 text-sm text-slate-600">
                  {review?.summary || '暂无审查摘要'}
                </p>
                <div className="mt-4 space-y-2">
                  {(review?.issues ?? []).map((issue, index) => (
                    <div
                      key={index}
                      className={`rounded-lg border px-3 py-2 text-sm ${
                        SEVERITY_STYLES[issue.severity ?? 'low'] ??
                        SEVERITY_STYLES.low
                      }`}
                    >
                      <p className="font-medium">
                        [{issue.severity || 'low'}] {issue.section || '全文'}
                      </p>
                      <p className="mt-1">{issue.issue}</p>
                      {issue.suggestion && (
                        <p className="mt-1 text-xs opacity-80">
                          建议：{issue.suggestion}
                        </p>
                      )}
                    </div>
                  ))}
                  {(review?.issues ?? []).length === 0 && (
                    <p className="text-sm text-slate-500">审查未提出具体问题。</p>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-slate-900">产物</h2>
                <p className="mt-1 truncate text-xs text-slate-500">
                  {result.output_dir}
                </p>
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => void showPreview(result.doc_id)}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    预览 Markdown
                  </button>
                  <button
                    type="button"
                    onClick={() => void openFolder(result.markdown_path)}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    打开所在文件夹
                  </button>
                  <a
                    href={api.fileUrl(result.doc_id, 'bid.md')}
                    className="rounded-lg bg-slate-900 px-3 py-2 text-center text-sm text-white hover:bg-slate-800"
                  >
                    下载 Markdown
                  </a>
                  {result.docx_path ? (
                    <a
                      href={api.fileUrl(result.doc_id, 'bid.docx')}
                      className="rounded-lg bg-indigo-600 px-3 py-2 text-center text-sm text-white hover:bg-indigo-700"
                    >
                      下载 Word
                    </a>
                  ) : (
                    <span className="rounded-lg bg-slate-100 px-3 py-2 text-center text-sm text-slate-400">
                      未生成 Word
                    </span>
                  )}
                </div>
                <p className="mt-3 text-xs text-slate-500">
                  生成完成：{formatDate(result.finished_at)}
                </p>
              </div>
            </div>
          )}
        </section>
      </div>

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
