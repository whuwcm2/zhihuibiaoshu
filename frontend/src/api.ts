import type {
  BidHistoryItem,
  BidJobCreated,
  BidJobStatus,
  BidderProfile,
  DocumentItem,
  ParseJobCreated,
  ParseJobStatus,
} from './types'

const API_BASE = (
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8001'
).replace(/\/+$/, '')

async function errorMessage(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown }
    if (typeof data.detail === 'string') return data.detail
    return JSON.stringify(data.detail ?? data)
  } catch {
    return `${response.status} ${response.statusText}`
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as T
}

export const api = {
  health: () =>
    request<{ status: string; service: string; redis: boolean }>('/api/health'),

  parsePdf: (form: FormData) =>
    request<ParseJobCreated>('/api/parse', { method: 'POST', body: form }),

  getParseJob: (jobId: string) =>
    request<ParseJobStatus>(`/api/parse/${jobId}`),

  writeBid: (payload: {
    doc_id: string
    profile: BidderProfile
    export_docx: boolean
  }) =>
    request<BidJobCreated>('/api/bids', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  getBidJob: (jobId: string) => request<BidJobStatus>(`/api/bids/${jobId}`),

  listDocuments: () => request<DocumentItem[]>('/api/documents'),

  listBids: () => request<BidHistoryItem[]>('/api/bids'),

  async previewMarkdown(docId: string): Promise<string> {
    const response = await fetch(
      `${API_BASE}/api/bids/${encodeURIComponent(docId)}/files/bid.md?download=false`,
    )
    if (!response.ok) throw new Error(await errorMessage(response))
    return response.text()
  },

  fileUrl: (docId: string, filename: string, download = true) =>
    `${API_BASE}/api/bids/${encodeURIComponent(docId)}/files/${filename}` +
    (download ? '?download=true' : '?download=false'),
}

export { API_BASE }
