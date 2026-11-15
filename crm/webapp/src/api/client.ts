import type { Merchant, Incident, DashboardData, ConversionRow, HourlyRow, CompareRow, CanonicalValues, FullDashboardData, FilterOptions, DashboardPeriod, WeeklyData, ChatGroup, TraderDashboardData, TraderFilterOptions, BizDevDashboardData, IncidentListResponse, IncidentDetailResponse, MerchantChatMessage, MerchantChatSummary, ScannerStatus, LiveData } from '../types'

const BASE = import.meta.env.VITE_API_URL || ''

function getInitData(): string {
  const tg = (window as any).Telegram?.WebApp
  return tg?.initData || ''
}

function getAuthHeaders(): Record<string, string> {
  const initData = getInitData()

  // If Telegram Mini App, use initData
  if (initData) {
    return { 'X-Init-Data': initData }
  }

  // If standalone PWA, use Bearer token from localStorage
  const storedAuth = localStorage.getItem('pwa_auth')
  if (storedAuth) {
    try {
      const { userId, accessKey } = JSON.parse(storedAuth)
      return { 'Authorization': `Bearer ${accessKey}:${userId}` }
    } catch {
      // Invalid stored auth, clear it
      localStorage.removeItem('pwa_auth')
    }
  }

  return {}
}

async function req<T>(path: string, opts?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), opts?.timeoutMs ?? 30000)

  try {
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        ...(opts?.headers || {}),
      },
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  } catch (e: any) {
    if (e.name === 'AbortError') throw new Error('Время ожидания истекло')
    throw e
  } finally {
    clearTimeout(timeout)
  }
}

export const api = {
  health: () => req<{ status: string }>('/api/health'),

  auth: {
    verify: () => req<{ user_id: number; username: string; first_name: string; is_admin: boolean; is_authorized: boolean }>('/api/auth/verify', { method: 'POST' }),
  },

  analytics: {
    dashboard: () => req<DashboardData>('/api/analytics/dashboard'),
    live: () => req<LiveData>('/api/analytics/live'),
    conversionToday: () => req<ConversionRow[]>('/api/analytics/conversion-today'),
    hourly: () => req<HourlyRow[]>('/api/analytics/hourly'),
    compareYesterday: () => req<CompareRow[]>('/api/analytics/compare-yesterday'),
    fullDashboard: (params: { period?: DashboardPeriod; merchant?: string; provider?: string; method?: string; bank?: string; op_type?: string } = {}) => {
      const q = new URLSearchParams()
      if (params.period) q.set('period', params.period)
      if (params.merchant) q.set('merchant', params.merchant)
      if (params.provider) q.set('provider', params.provider)
      if (params.method) q.set('method', params.method)
      if (params.bank) q.set('bank', params.bank)
      if (params.op_type) q.set('op_type', params.op_type)
      const qs = q.toString()
      return req<FullDashboardData>(`/api/analytics/full-dashboard${qs ? '?' + qs : ''}`)
    },
    filterOptions: () => req<FilterOptions>('/api/analytics/filter-options'),
    canceled: () => req<Record<string, any>[]>('/api/analytics/canceled'),
    banks: () => req<Record<string, any>[]>('/api/analytics/banks'),
    weekly: () => req<WeeklyData>('/api/analytics/weekly'),
    monthly: () => req<Record<string, any>>('/api/analytics/monthly'),
    unpaid: () => req<Record<string, any>>('/api/analytics/unpaid'),
    badClients: () => req<Record<string, any>[]>('/api/analytics/bad-clients'),
    rates: () => req<Record<string, any>[]>('/api/analytics/rates'),
    traderDashboard: (params: { period?: string; trader?: string; method?: string; bank?: string; tla?: string; htl?: string; agent?: string; merchant?: string } = {}) => {
      const q = new URLSearchParams()
      if (params.period) q.set('period', params.period)
      if (params.trader) q.set('trader', params.trader)
      if (params.method) q.set('method', params.method)
      if (params.bank) q.set('bank', params.bank)
      if (params.tla) q.set('tla', params.tla)
      if (params.htl) q.set('htl', params.htl)
      if (params.agent) q.set('agent', params.agent)
      if (params.merchant) q.set('merchant', params.merchant)
      const qs = q.toString()
      return req<TraderDashboardData>(`/api/analytics/trader-dashboard${qs ? '?' + qs : ''}`)
    },
    traderFilterOptions: () => req<TraderFilterOptions>('/api/analytics/trader-filter-options'),
    bizdevDashboard: (params: { period?: string } = {}) => {
      const q = new URLSearchParams()
      if (params.period) q.set('period', params.period)
      const qs = q.toString()
      return req<BizDevDashboardData>(`/api/analytics/bizdev-dashboard${qs ? '?' + qs : ''}`)
    },
    comparePeriods: (p1Start: string, p1End: string, p2Start: string, p2End: string) => {
      const q = new URLSearchParams({ period1_start: p1Start, period1_end: p1End, period2_start: p2Start, period2_end: p2End })
      return req<Record<string, any>>(`/api/analytics/compare-periods?${q}`, { timeoutMs: 90000 })
    },
    heatmap: (days: number) => req<Record<string, any>>(`/api/analytics/heatmap?days=${days}`, { timeoutMs: 90000 }),
    funnel: () => req<Record<string, any>>(`/api/analytics/funnel`, { timeoutMs: 90000 }),
  },

  messages: {
    list: () => req<ChatGroup[]>('/api/messages'),
  },

  merchants: {
    list: (params?: { search?: string; status?: string }) => {
      const q = new URLSearchParams()
      if (params?.search) q.set('search', params.search)
      if (params?.status) q.set('status', params.status)
      const qs = q.toString()
      return req<{ items: Merchant[]; total: number }>(`/api/merchants${qs ? '?' + qs : ''}`)
    },
    get: (id: number) => req<{ merchant: Merchant; open_incidents: Incident[]; history: any[]; tags: string[] }>(`/api/merchants/${id}`),
    update: (id: number, field: string, value: string | number) =>
      req<{ success: boolean }>(`/api/merchants/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ field, value: String(value) }),
      }),
    canonicalValues: () => req<CanonicalValues>('/api/merchants/canonical-values'),
    messages: (id: number, limit = 20, offset = 0, search = '', group_name = '') => {
      const q = new URLSearchParams()
      q.set('limit', String(limit))
      if (offset) q.set('offset', String(offset))
      if (search) q.set('search', search)
      if (group_name) q.set('group_name', group_name)
      return req<{ merchant_id: number; messages: MerchantChatMessage[]; total: number; has_more: boolean }>(
        `/api/merchants/${id}/messages?${q.toString()}`
      )
    },
    chatSummary: (id: number, force = false) =>
      req<MerchantChatSummary>(`/api/merchants/${id}/chat-summary${force ? '?force=true' : ''}`),
  },

  // NEW: Ops Phase 1 - Incidents & Alerts
  incidents: {
    list: (params?: { status?: string; severity?: string; scope?: string; limit?: number; offset?: number }) => {
      const q = new URLSearchParams()
      if (params?.status) q.set('status', params.status)
      if (params?.severity) q.set('severity', params.severity)
      if (params?.scope) q.set('scope', params.scope)
      if (params?.limit) q.set('limit', String(params.limit))
      if (params?.offset) q.set('offset', String(params.offset))
      const qs = q.toString()
      return req<IncidentListResponse>(`/api/incidents${qs ? '?' + qs : ''}`)
    },
    get: (id: string) => req<IncidentDetailResponse>(`/api/incidents/${id}`),
    ack: (id: string, user_id?: string) =>
      req<{ success: boolean }>(`/api/incidents/${id}/ack`, { method: 'POST', body: JSON.stringify({ user_id }) }),
    resolve: (id: string, user_id?: string) =>
      req<{ success: boolean }>(`/api/incidents/${id}/resolve`, { method: 'POST', body: JSON.stringify({ user_id }) }),
    reopen: (id: string, user_id?: string) =>
      req<{ success: boolean }>(`/api/incidents/${id}/reopen`, { method: 'POST', body: JSON.stringify({ user_id }) }),
    assign: (id: string, owner_user_id: string, user_id?: string) =>
      req<{ success: boolean }>(`/api/incidents/${id}/assign`, { method: 'POST', body: JSON.stringify({ owner_user_id, user_id }) }),
    mute: (id: string, minutes?: number, until?: string, user_id?: string) =>
      req<{ success: boolean }>(`/api/incidents/${id}/mute`, { method: 'POST', body: JSON.stringify({ minutes, until, user_id }) }),
    unmute: (id: string, user_id?: string) =>
      req<{ success: boolean }>(`/api/incidents/${id}/unmute`, { method: 'POST', body: JSON.stringify({ user_id }) }),
  },

  alerts: {
    triggerCheck: () => req<any>('/api/alerts/scheduler/trigger', { method: 'POST' }),
    schedulerStatus: () => req<any>('/api/alerts/scheduler/status'),
  },

  scanner: {
    status: () => req<ScannerStatus>('/api/scanner/status'),
  },

  chatExport: {
    status: (taskId: string) =>
      req<{ task_id: string; status: 'processing' | 'completed' | 'error'; chat_name: string; total: number; processed: number; updated: number; merchants: string[]; error?: string }>(
        `/api/chat-export/status/${taskId}`
      ),
  },
}
