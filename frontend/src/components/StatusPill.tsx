import type { JobStatus } from '../types'

const styles: Record<JobStatus, string> = {
  pending: 'bg-slate-100 text-slate-600 ring-slate-200',
  running: 'bg-amber-50 text-amber-700 ring-amber-200',
  succeeded: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  failed: 'bg-rose-50 text-rose-700 ring-rose-200',
}

const labels: Record<JobStatus, string> = {
  pending: '排队中',
  running: '处理中',
  succeeded: '已完成',
  failed: '失败',
}

export function StatusPill({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${styles[status]}`}
    >
      {status === 'running' && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
      )}
      {labels[status]}
    </span>
  )
}
