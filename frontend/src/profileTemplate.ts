import type { BidderProfile } from './types'

export const EMPTY_PROFILE: BidderProfile = {
  company_name: '',
  legal_representative: '',
  registered_address: '',
  contact_person: '',
  contact_phone: '',
  email: '',
  business_license_no: '',
  registered_capital: '',
  established_date: '',
  qualification: {
    name: '',
    grade: '',
    certificate_no: '',
    valid_until: '',
  },
  safety_license: {
    certificate_no: '',
    valid_until: '',
  },
  similar_projects: [],
  personnel: {
    project_manager: { name: '', certificate: '', title: '', phone: '' },
    technical_lead: { name: '', certificate: '', title: '' },
    quality_manager: { name: '', certificate: '', title: '' },
    safety_manager: { name: '', certificate: '', title: '' },
  },
  financial: {
    years: [],
    revenue: [],
    net_profit: [],
    audit_agency: '',
  },
  credit: { rating: '', certificates: [] },
  management_systems: [],
  bid_bond: { method: '', amount: '', valid_until: '' },
  other: {},
}

export function getByPath(
  source: BidderProfile,
  path: string,
): string {
  const value = path
    .split('.')
    .reduce<unknown>((current, key) => {
      if (current && typeof current === 'object') {
        return (current as Record<string, unknown>)[key]
      }
      return undefined
    }, source)
  return value === null || value === undefined ? '' : String(value)
}

export function setByPath(
  source: BidderProfile,
  path: string,
  value: unknown,
): BidderProfile {
  const clone = JSON.parse(JSON.stringify(source)) as Record<string, unknown>
  const parts = path.split('.')
  let current: Record<string, unknown> = clone
  for (const part of parts.slice(0, -1)) {
    const next = current[part]
    if (!next || typeof next !== 'object') current[part] = {}
    current = current[part] as Record<string, unknown>
  }
  current[parts[parts.length - 1]] = value
  return clone as BidderProfile
}
