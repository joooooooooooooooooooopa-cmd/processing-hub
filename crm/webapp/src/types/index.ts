export type MerchantStatus = 'new' | 'negotiation' | 'integration' | 'testing' | 'active' | 'paused' | 'problem' | 'disconnected'
export type MoodType = 'loyal' | 'neutral' | 'difficult' | 'aggressive'
export type IntegrationStatus = 'request' | 'docs' | 'tech' | 'testing' | 'completed'
export type RateFlexibility = 'flexible' | 'negotiable' | 'firm'
export type IncidentPriority = 'P0' | 'P1' | 'P2' | 'P3'

export interface Merchant {
  id: number
  name: string
  status: MerchantStatus
  mood?: MoodType
  integration_status?: IntegrationStatus
  rate_flexibility?: RateFlexibility
  current_rate?: number
  min_rate?: number
  conversion?: number
  payment_methods?: string
  contact_person?: string
  notes?: string
  updated_at?: string
  open_incidents_count: number
}

export interface StatusChange {
  id: number
  field_name: string
  old_value?: string
  new_value?: string
  reason?: string
  confidence?: number
  decided_by?: string
  created_at: string
}

// NEW: Ops Phase 1 - Incidents & Alerts
export type IncidentStatus = 'open' | 'ack' | 'resolved' | 'reopened'
export type IncidentType = 'conversion_drop' | 'profit_drop' | 'decline_spike' | 'metric_breach'
export type IncidentScope = 'global' | 'merchant' | 'method' | 'bank' | 'provider' | 'team' | 'trader' | 'tl' | 'htl' | 'agent'

export interface Incident {
  id: string
  type: IncidentType
  severity: IncidentPriority  // P0, P1, P2, P3
  status: IncidentStatus
  scope: IncidentScope
  metric: string  // conversion_success, profit_total, decline_rate
  baseline_value?: number
  current_value: number
  delta_value?: number
  delta_pct?: number  // процент изменения
  period_from: string  // ISO datetime
  period_to: string  // ISO datetime
  dimensions: Record<string, any>  // { merchant_name, method, bank, trader, etc. }
  title: string
  description?: string
  owner_user_id?: string
  created_by: string  // "rule" | "manual" | user_id
  rule_id?: string  // ID алерта который создал инцидент
  dedupe_key: string
  ack_at?: string  // ISO datetime
  resolved_at?: string
  next_review_at?: string
  is_muted: boolean
  mute_until?: string
  created_at: string
  updated_at: string
}

export interface IncidentEvent {
  id: string
  incident_id: string
  event_type: string  // created, ack, resolved, reopened, assigned, muted, commented
  actor_user_id?: string
  payload: Record<string, any>
  created_at: string
}

export interface IncidentListResponse {
  incidents: Incident[]
  total: number
}

export interface IncidentDetailResponse {
  incident: Incident
  events: IncidentEvent[]
}

export interface Comment {
  id: number
  user_id: number
  user_name: string
  text: string
  created_at: string
}

export interface DashboardData {
  summary: {
    merchants_count?: number
    total_orders?: number
    successful_orders?: number
    total_amount?: number
    successful_amount?: number
    conversion?: number
  }
  db_stats: {
    total_merchants?: number
    by_status?: Record<string, number>
    open_incidents?: number
  }
  operational: {
    open_by_priority?: Record<string, number>
    avg_time_to_ack_minutes?: number
    incidents_opened_today?: number
    incidents_resolved_today?: number
    problem_merchants?: Array<{ name: string; incident_count: number }>
  }
}

export interface ConversionRow {
  merchant: string
  total: number
  successful: number
  amount: number
  amount_successful: number
  conversion_pct: number
}

export interface HourlyRow {
  hour: number
  orders: number
  successful: number
  amount: number
  conversion_pct: number
}

export interface CompareRow {
  day: string
  orders: number
  successful: number
  amount: number
  amount_successful: number
  conversion_pct: number
}

export interface CanonicalValues {
  statuses: string[]
  moods: string[]
  integration_statuses: string[]
  rate_flexibility: string[]
}

export type TabId = 'home' | 'analytics' | 'traders' | 'merchants' | 'alerts'

// Sub-tab types for combined screens
export type AnalyticsSubTab = 'overview' | 'details' | 'heatmap' | 'funnel' | 'compare' | 'bizdev'
export type AlertsSubTab = 'live' | 'incidents'

// ── Live Monitor types ──────────────────────────────────────────────────────

export interface LiveKpi {
  total: number | null
  successful: number | null
  conversion_pct: number | null
  turnover: number | null
  profit: number | null
}

export interface LiveYesterday {
  total: number | null
  successful: number | null
  conversion_pct: number | null
  turnover: number | null
}

export interface LiveMerchant {
  name: string
  total: number
  successful: number
  amount: number
}

export interface LiveData {
  kpi: LiveKpi
  yesterday: LiveYesterday
  hourly: { hour: number; total: number; successful: number }[]
  top_merchants_live: LiveMerchant[]
  updated_at: string
}

export type DashboardPeriod = 'today' | 'yesterday' | 'week' | 'month'

export interface FullDashboardKpi {
  total: number | null
  successful: number | null
  turnover: number | null
  profit: number | null
  conversion_pct: number | null
  conversion_req_pct: number | null
  issued_req: number | null
  avg_check: number | null
  decline_pct: number | null
  avg_profit_per_order: number | null
  total_amount_all: number | null
}

export interface FullDashboardData {
  kpi: FullDashboardKpi
  top_merchants: Record<string, any>[]
  top_providers: Record<string, any>[]
  top_methods: Record<string, any>[]
  top_providers_conv: Record<string, any>[]
  hourly_transactions: Record<string, any>[]
  funnel_statuses: Record<string, any>[]
  week_dynamics: Record<string, any>[]
  hourly_profit: Record<string, any>[]
}

export interface PeriodOption {
  value: DashboardPeriod
  label: string
}

export interface FilterOptions {
  merchants: string[]
  periods: PeriodOption[]
}

// ── Analytics extended types ──────────────────────────────────────────────────

export interface WeeklyData {
  summary: Record<string, any>
  by_day: Record<string, any>[]
}

export interface ChatMessage {
  id: number
  sender: string
  text: string
  created_at: string
}

export interface ChatGroup {
  id: number
  name: string
  type: string
  messages: ChatMessage[]
}

// ── Scanner / Chat History types ─────────────────────────────────────────────

export interface MerchantChatMessage {
  id: number
  sender_name: string
  text: string
  group_name: string
  created_at: string
}

export interface MerchantChatSummary {
  merchant_id: number
  summary: string
  message_count: number
  generated_at: string
  cached: boolean
}

export interface ScannerStatus {
  status: string
  state: Record<string, { value: string; updated_at: string }>
  groups_monitored: string
  last_full_scan?: string
  last_error?: string
}

// ── Trader Dashboard types ────────────────────────────────────────────────────

export interface TraderDashboardKpi {
  total_payin: number | null
  amount_payin: number | null
  amount_successful: number | null
  count_successful: number | null
  count_failed: number | null
  conversion_success: number | null
  conversion_issued: number | null
}

export interface TraderDashboardData {
  kpi: TraderDashboardKpi
  by_methods: Record<string, any>[]
  by_banks: Record<string, any>[]
  bank_method: Record<string, any>[]
}

export interface TraderFilterOptions {
  methods: string[]
  banks: string[]
  traders: string[]
  tlas: string[]
  htls: string[]
  agents: string[]
  merchants: string[]
}

// ── BizDev Dashboard types ────────────────────────────────────────────────────

export interface BizDevKpi {
  total_processed: number | null
  total_profit: number | null
  providers_count: number | null
}

export interface BizDevDashboardData {
  kpi: BizDevKpi
  hourly_issued: Record<string, any>[]
  methods_pie_count: Record<string, any>[]
  methods_pie_profit: Record<string, any>[]
  providers_table: Record<string, any>[]
}
