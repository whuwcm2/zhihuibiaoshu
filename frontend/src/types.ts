export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface ChunkPreview {
  index: number
  page_start: number
  page_end: number
  heading: string
  text: string
}

export interface ParseResult {
  doc_id: string
  filename: string
  page_count: number
  parser: string
  block_count: number
  chunk_count: number
  markdown_path: string
  chunks_path: string
  chunks_preview: ChunkPreview[]
  extraction_path?: string | null
  extraction_summary?: {
    project_name?: string | null
    toc_count?: number
    scoring_factor_count?: number
  } | null
  ingested?: boolean
}

export interface ParseJobCreated {
  job_id: string
  status: string
  filename: string
  status_url: string
}

export interface ParseJobStatus {
  job_id: string
  filename: string
  status: JobStatus
  stage?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  result?: ParseResult | null
  error?: string | null
}

export interface BidJobCreated {
  job_id: string
  status: string
  doc_id: string
  status_url: string
}

export interface ScoringReportItem {
  category?: string
  item?: string
  sub_item?: string | null
  points?: number | string | null
  covered: boolean
}

export interface ScoringReport {
  items?: ScoringReportItem[]
  total_points?: number
  covered_points?: number
  coverage_rate?: number
}

export interface ReviewIssue {
  section?: string
  issue?: string
  severity?: string
  suggestion?: string
}

export interface BidReview {
  issues?: ReviewIssue[]
  placeholder_count?: number
  fabrication_risk?: boolean
  summary?: string
}

export interface BidResult {
  job_id?: string
  doc_id: string
  output_dir: string
  markdown_path: string
  docx_path?: string | null
  agent_dir: string
  placeholder_count: number
  review?: BidReview
  scoring_report?: ScoringReport
  started_at?: string | null
  finished_at?: string | null
}

export interface BidJobStatus {
  job_id: string
  doc_id?: string | null
  status: JobStatus
  stage?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  result?: BidResult | null
  error?: string | null
}

export interface DocumentItem {
  doc_id: string
  project_name?: string | null
  source?: string | null
  page_count: number
  parser?: string | null
  created_at?: string | null
  chunk_count: number
  has_extraction: boolean
  root: string
}

export interface BidHistoryItem {
  doc_id: string
  project_name?: string | null
  company_name?: string | null
  generated_at?: string | null
  placeholder_count: number
  review_summary: string
  has_docx: boolean
  output_dir: string
  markdown_path: string
  docx_path?: string | null
}

export interface BidderProfile {
  company_name?: string
  legal_representative?: string
  registered_address?: string
  contact_person?: string
  contact_phone?: string
  email?: string
  business_license_no?: string
  registered_capital?: string
  established_date?: string
  qualification?: Record<string, string>
  safety_license?: Record<string, string>
  similar_projects?: Array<Record<string, unknown>>
  personnel?: Record<string, Record<string, string>>
  financial?: Record<string, unknown>
  credit?: Record<string, unknown>
  management_systems?: string[]
  bid_bond?: Record<string, string>
  other?: Record<string, unknown>
  [key: string]: unknown
}
