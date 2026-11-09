export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatNumber(value?: number | string | null): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isNaN(number) ? String(value) : number.toLocaleString('zh-CN')
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
