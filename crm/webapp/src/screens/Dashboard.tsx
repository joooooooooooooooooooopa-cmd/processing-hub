import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { TrendingUp, TrendingDown, Search, AlertTriangle, Zap, Copy, Check } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  Line, Area, ComposedChart,
} from 'recharts'
import { api } from '../api/client'
import type { FullDashboardData, FullDashboardKpi, DashboardPeriod, Incident } from '../types'
import { SkeletonDashboard } from '../components/Skeleton'
import EmeraldBarChart from '../components/charts/EmeraldBarChart'
import SearchOverlay from '../components/dashboard/SearchOverlay'
import MerchantRating from '../components/dashboard/MerchantRating'
import MerchantCompare from '../components/dashboard/MerchantCompare'
import MerchantHealth from '../components/dashboard/MerchantHealth'
import SLAMonitor from '../components/dashboard/SLAMonitor'
import ProfitTimeline from '../components/dashboard/ProfitTimeline'
import { parseMerchantKeys, parseMerchantRows } from '../utils/merchantData'
import { fmt, fmtPct, fmtAmount, fmtShort } from '../utils/format'

// ── TrendBadge ────────────────────────────────────────────────────────────────

function TrendBadge({ current, previous }: { current: number | null; previous: number | null }) {
  if (current == null || previous == null || previous === 0) return null
  const delta = ((current - previous) / Math.abs(previous)) * 100
  const isUp = delta >= 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${isUp ? 'text-em-400' : 'text-danger'}`}>
      {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
      {isUp ? '+' : ''}{delta.toFixed(1)}%
    </span>
  )
}

// ── HeroMetric ────────────────────────────────────────────────────────────────

function HeroMetric({
  label,
  value,
  trend,
  accent,
}: {
  label: string
  value: string
  trend?: React.ReactNode
  accent?: boolean
}) {
  return (
    <div className="text-center">
      <div className="text-[10px] text-text-3 uppercase tracking-wider mb-0.5">{label}</div>
      <div className={`text-lg font-bold leading-tight ${accent ? 'text-em-400' : 'text-text-1'}`}>{value}</div>
      {trend && <div className="mt-0.5">{trend}</div>}
    </div>
  )
}

// ── KpiCard ───────────────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  accent,
  sub,
  warn,
}: {
  label: string
  value: string
  accent?: boolean
  sub?: string
  warn?: boolean
}) {
  const isNoData = value === '—' || value === '—%'
  return (
    <div className="bg-surface border border-em-500/10 rounded-2xl p-4 flex flex-col gap-1">
      <div className="text-xs text-text-3 uppercase tracking-wider">{label}</div>
      {isNoData ? (
        <div className="text-sm text-text-3 leading-tight mt-1">Нет данных</div>
      ) : (
        <div className={`text-2xl font-bold leading-tight ${warn ? 'text-danger' : accent ? 'text-em-400' : 'text-text-1'}`}>
          {value}
        </div>
      )}
      {sub && <div className="text-xs text-text-3">{sub}</div>}
    </div>
  )
}

// ── Conversion Funnel ─────────────────────────────────────────────────────────

function ConversionFunnel({ total, issued, successful }: {
  total: number | null
  issued: number | null
  successful: number | null
}) {
  const stages = useMemo(() => {
    if (total == null || total === 0) return null
    return [
      { label: 'Заявки', value: total, color: '#1e3a5f' },
      { label: 'Реквизиты', value: issued ?? 0, color: '#0d6e5e' },
      { label: 'Оплачено', value: successful ?? 0, color: '#10b981' },
    ]
  }, [total, issued, successful])

  if (!stages) return null

  const maxVal = stages[0].value

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-3">Воронка конверсии</h2>
      <div className="bg-surface border border-em-500/10 rounded-2xl p-4 space-y-3">
        {stages.map((stage, i) => {
          const pct = maxVal > 0 ? (stage.value / maxVal) * 100 : 0
          const lossPct = i > 0 && stages[i - 1].value > 0 ? (((stages[i - 1].value - stage.value) / stages[i - 1].value) * 100) : 0
          const widthPct = Math.max(pct, 8)
          return (
            <div key={stage.label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-text-3">{stage.label}</span>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-text-1">{fmt(stage.value)}</span>
                  {i > 0 && lossPct > 0 && (
                    <span className="text-[10px] text-danger">-{lossPct.toFixed(1)}%</span>
                  )}
                </div>
              </div>
              <div className="w-full h-6 rounded-lg overflow-hidden" style={{ background: 'var(--surface-2)' }}>
                <div
                  className="h-full rounded-lg flex items-center justify-end pr-2 transition-all duration-700"
                  style={{
                    width: `${widthPct}%`,
                    background: `linear-gradient(90deg, ${stage.color}, ${stage.color}dd)`,
                  }}
                >
                  <span className="text-[10px] font-bold text-text-1/80">{pct.toFixed(1)}%</span>
                </div>
              </div>
            </div>
          )
        })}
        <div className="pt-2 border-t border-em-500/5 flex items-center justify-between">
          <span className="text-xs text-text-3">Общая конверсия</span>
          <span className="text-lg font-bold text-em-400">
            {maxVal > 0 ? ((successful ?? 0) / maxVal * 100).toFixed(2) : '0.00'}%
          </span>
        </div>
      </div>
    </div>
  )
}

// ── Activity Heatmap ──────────────────────────────────────────────────────────

function ActivityHeatmap({ data }: { data: Record<string, any>[] }) {
  const { cells, maxVal } = useMemo(() => {
    if (!data || data.length === 0) return { cells: [], maxVal: 1 }
    const c = data.map(d => {
      const hour = d.hour ?? d['Час'] ?? d.hour_of_day ?? 0
      const value = d.total ?? d['Ордеров'] ?? d.orders ?? 0
      return { hour: Number(hour), value: Number(value) }
    }).sort((a, b) => a.hour - b.hour)
    return { cells: c, maxVal: Math.max(...c.map(x => x.value), 1) }
  }, [data])

  if (cells.length === 0) return null

  function getColor(value: number): string {
    if (value === 0) return '#111827'
    const intensity = value / maxVal
    if (intensity < 0.25) return '#064e3b'
    if (intensity < 0.5) return '#047857'
    if (intensity < 0.75) return '#059669'
    return '#10b981'
  }

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-3">Активность по часам</h2>
      <div className="bg-surface border border-em-500/10 rounded-2xl p-4">
        <div className="grid grid-cols-12 gap-1">
          {cells.map(cell => (
            <div
              key={cell.hour}
              className="aspect-square rounded-md flex items-center justify-center relative group"
              style={{ background: getColor(cell.value) }}
              title={`${cell.hour}:00 — ${cell.value} заявок`}
            >
              <span className="text-[8px] font-medium text-text-1/60">{cell.hour}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between mt-3 px-1">
          <span className="text-[10px] text-text-4">Меньше</span>
          <div className="flex gap-1">
            {['#111827', '#064e3b', '#047857', '#059669', '#10b981'].map(c => (
              <div key={c} className="w-3 h-3 rounded-sm" style={{ background: c }} />
            ))}
          </div>
          <span className="text-[10px] text-text-4">Больше</span>
        </div>
      </div>
    </div>
  )
}

// ── Weekly Trend Chart ────────────────────────────────────────────────────────

function WeekTrendChart({ data }: { data: Record<string, any>[] }) {
  const { prepared, successKey } = useMemo(() => {
    if (!data || data.length < 2) return { prepared: [], successKey: undefined }
    const keys = Object.keys(data[0])
    const dayKey = keys.find(k => /day|день|date|дата/i.test(k)) || keys[0]
    const totalKey = keys.find(k => /total|ордер|order|всего/i.test(k)) || keys[1]
    const sk = keys.find(k => /success|успеш/i.test(k))
    const p = data.map(d => ({
      day: String(d[dayKey] ?? ''),
      total: Number(d[totalKey] ?? 0),
      ...(sk ? { successful: Number(d[sk] ?? 0) } : {}),
    }))
    return { prepared: p, successKey: sk }
  }, [data])

  if (prepared.length < 2) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-2">Тренд за период</h2>
      <div className="border border-em-500/10 rounded-2xl p-3" style={{ background: 'var(--surface)' }}>
        <ResponsiveContainer width="100%" height={180}>
          <ComposedChart data={prepared} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="day" tick={{ fill: '#9ca3af', fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={fmtShort} />
            <Tooltip
              contentStyle={{ background: 'var(--surface-2)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 12, color: '#fff', fontSize: 12 }}
              formatter={(v: number | undefined, name?: string) => [v != null ? v.toLocaleString('ru-RU') : '—', name ?? '']}
            />
            {successKey && <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />}
            <Area type="monotone" dataKey="total" fill="url(#trendFill)" stroke="none" legendType="none" tooltipType="none" />
            <Line type="monotone" dataKey="total" stroke="#10b981" strokeWidth={2} dot={{ r: 3, fill: '#10b981' }} name="Всего" />
            {successKey && (
              <Line type="monotone" dataKey="successful" stroke="#34d399" strokeWidth={2} strokeDasharray="4 4" dot={{ r: 3, fill: '#34d399' }} name="Успешных" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ── Favorites ─────────────────────────────────────────────────────────────────

const FAVORITES_KEY = 'crm_favorite_merchants'

function getFavorites(): string[] {
  try {
    return JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]')
  } catch {
    return []
  }
}

function setFavoritesStorage(favs: string[]) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(favs))
}

function FavoriteMerchants({
  data,
  onToggle,
  favorites,
}: {
  data: Record<string, any>[]
  onToggle: (name: string) => void
  favorites: string[]
}) {
  const keys = useMemo(() => parseMerchantKeys(data), [data])
  const allRows = useMemo(() => parseMerchantRows(data, keys), [data, keys])

  const favData = useMemo(() => {
    if (!data || data.length === 0 || favorites.length === 0) return []
    return favorites
      .map(fav => allRows.find(r => r.name === fav) ?? null)
      .filter(Boolean) as typeof allRows
  }, [allRows, data, favorites])

  if (favData.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-2">Избранные</h2>
      <div className="grid grid-cols-2 gap-2">
        {favData.map(m => (
          <div
            key={m.name}
            className="bg-surface border border-yellow-500/20 rounded-2xl p-3 relative"
          >
            <button
              onClick={() => onToggle(m.name)}
              className="absolute top-2 right-2 text-yellow-500 text-sm"
              title="Убрать из избранного"
            >
              ★
            </button>
            <div className="text-xs text-text-1 font-medium truncate pr-5">{m.name}</div>
            <div className="text-lg font-bold text-em-400 mt-1">{m.conv.toFixed(1)}%</div>
            <div className="text-[10px] text-text-3">{fmtAmount(m.amount)} / {m.successful} из {m.total}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Status Breakdown ─────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  active: '#10b981', new: '#3b82f6', negotiation: '#8b5cf6', integration: '#06b6d4',
  testing: '#f59e0b', paused: '#6b7280', problem: '#ef4444', disconnected: '#374151',
}

const STATUS_LABELS: Record<string, string> = {
  active: 'Активные', new: 'Новые', negotiation: 'Переговоры', integration: 'Интеграция',
  testing: 'Тестирование', paused: 'Пауза', problem: 'Проблемы', disconnected: 'Отключены',
}

function StatusBreakdown({ stats }: { stats: Record<string, number> | undefined }) {
  const entries = useMemo(() => {
    if (!stats || Object.keys(stats).length === 0) return null
    const total = Object.values(stats).reduce((s, v) => s + v, 0)
    if (total === 0) return null
    return Object.entries(stats)
      .map(([status, count]) => ({ status, count, pct: (count / total) * 100 }))
      .sort((a, b) => b.count - a.count)
  }, [stats])

  if (!entries) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-2">Статусы мерчантов</h2>
      <div className="bg-surface border border-em-500/10 rounded-2xl p-4 space-y-2">
        <div className="flex h-3 rounded-full overflow-hidden">
          {entries.map(e => (
            <div
              key={e.status}
              style={{ width: `${e.pct}%`, background: STATUS_COLORS[e.status] || '#6b7280' }}
              title={`${STATUS_LABELS[e.status] || e.status}: ${e.count}`}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {entries.map(e => (
            <div key={e.status} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ background: STATUS_COLORS[e.status] || '#6b7280' }} />
              <span className="text-[10px] text-text-3">{STATUS_LABELS[e.status] || e.status}</span>
              <span className="text-[10px] text-text-4">{e.count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Recent Incidents ─────────────────────────────────────────────────────────

const PRIORITY_COLORS: Record<string, string> = {
  P0: '#ef4444', P1: '#f97316', P2: '#fbbf24', P3: '#6b7280',
}

function RecentIncidents({ onSelect }: { onSelect: (id: string) => void }) {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api.incidents.list({ limit: 5, status: 'open' })
      .then(r => setIncidents(r.incidents))
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [])

  if (!loaded || incidents.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-2">Открытые инциденты</h2>
      <div className="space-y-1.5">
        {incidents.map(inc => (
          <button
            key={inc.id}
            onClick={() => onSelect(inc.id)}
            className="w-full bg-surface border border-danger/10 rounded-xl p-3 flex items-center gap-3 text-left"
          >
            <div className="flex-shrink-0">
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold"
                style={{ background: (PRIORITY_COLORS[inc.severity] || '#6b7280') + '22', color: PRIORITY_COLORS[inc.severity] || '#6b7280' }}
              >
                {inc.severity}
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs text-text-1 font-medium truncate">{inc.title}</div>
              <div className="text-[10px] text-text-3 truncate">
                {inc.dimensions?.merchant_name || inc.scope} · {new Date(inc.created_at).toLocaleDateString('ru-RU')}
              </div>
            </div>
            <AlertTriangle size={14} className="text-danger/50 flex-shrink-0" />
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Alert Banner ─────────────────────────────────────────────────────────────

function AlertBanner({ kpi, yesterdayKpi }: {
  kpi: FullDashboardKpi
  yesterdayKpi: FullDashboardKpi | null
}) {
  const alerts = useMemo(() => {
    if (!yesterdayKpi) return []
    const result: { text: string; severity: 'warn' | 'critical' }[] = []

    if (kpi.conversion_pct != null && yesterdayKpi.conversion_pct != null && yesterdayKpi.conversion_pct > 0) {
      const drop = ((yesterdayKpi.conversion_pct - kpi.conversion_pct) / yesterdayKpi.conversion_pct) * 100
      if (drop > 20) result.push({ text: `Конверсия упала на ${drop.toFixed(0)}%`, severity: 'critical' })
      else if (drop > 10) result.push({ text: `Конверсия снизилась на ${drop.toFixed(0)}%`, severity: 'warn' })
    }

    if (kpi.total != null && yesterdayKpi.total != null && yesterdayKpi.total > 0) {
      const drop = ((yesterdayKpi.total - kpi.total) / yesterdayKpi.total) * 100
      if (drop > 30) result.push({ text: `Объём транзакций упал на ${drop.toFixed(0)}%`, severity: 'critical' })
    }

    if (kpi.decline_pct != null && kpi.decline_pct > 30) {
      result.push({ text: `Высокий % отказов: ${kpi.decline_pct.toFixed(1)}%`, severity: kpi.decline_pct > 50 ? 'critical' : 'warn' })
    }

    return result
  }, [kpi, yesterdayKpi])

  if (alerts.length === 0) return null

  return (
    <div className="space-y-2">
      {alerts.map((a, i) => (
        <div
          key={i}
          className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium ${
            a.severity === 'critical'
              ? 'bg-danger/10 border border-danger/20 text-danger'
              : 'bg-yellow-500/10 border border-yellow-500/20 text-yellow-400'
          }`}
        >
          <Zap size={14} />
          {a.text}
        </div>
      ))}
    </div>
  )
}

// ── Daily Digest ─────────────────────────────────────────────────────────────

function DailyDigest({ kpi, yesterdayKpi, merchants }: {
  kpi: FullDashboardKpi
  yesterdayKpi: FullDashboardKpi | null
  merchants: Record<string, any>[]
}) {
  const insights = useMemo(() => {
    const result: string[] = []

    if (kpi.total != null && yesterdayKpi?.total != null && yesterdayKpi.total > 0) {
      const pct = ((kpi.total - yesterdayKpi.total) / yesterdayKpi.total) * 100
      if (pct > 0) result.push(`Транзакций на ${pct.toFixed(0)}% больше чем вчера`)
      else if (pct < -5) result.push(`Транзакций на ${Math.abs(pct).toFixed(0)}% меньше чем вчера`)
    }

    if (kpi.conversion_pct != null && kpi.conversion_pct > 50) {
      result.push(`Конверсия выше 50% — отличный результат`)
    }

    if (merchants.length > 0) {
      const keys = parseMerchantKeys(merchants)
      const rows = parseMerchantRows(merchants, keys)
      const top = [...rows].sort((a, b) => b.amount - a.amount)[0]
      if (top) result.push(`Лидер дня: ${top.name}`)
    }

    if (kpi.avg_profit_per_order != null && kpi.avg_profit_per_order > 0) {
      result.push(`Средняя прибыль: ${fmtAmount(kpi.avg_profit_per_order)} за транзакцию`)
    }

    return result
  }, [kpi, yesterdayKpi, merchants])

  if (insights.length === 0) return null

  return (
    <div className="bg-gradient-to-br from-emerald-500/5 to-[#0d1117] border border-em-500/15 rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <Zap size={14} className="text-em-400" />
        <span className="text-xs font-semibold text-em-400 uppercase tracking-wider">Дайджест</span>
      </div>
      <div className="space-y-1.5">
        {insights.map((text, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="text-em-500 text-xs mt-0.5">•</span>
            <span className="text-xs text-text-2">{text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Share Report ─────────────────────────────────────────────────────────────

function ShareButton({ kpi, period }: { kpi: FullDashboardKpi; period: string }) {
  const [copied, setCopied] = useState(false)

  const handleShare = useCallback(async () => {
    const lines = [
      `ProcessingHub — ${period === 'today' ? 'Сегодня' : period === 'yesterday' ? 'Вчера' : period === 'week' ? '7 дней' : '30 дней'}`,
      `────────────────────`,
      `Транзакций: ${fmt(kpi.total)}`,
      `Успешных: ${fmt(kpi.successful)}`,
      `Конверсия: ${fmtPct(kpi.conversion_pct)}`,
      `Оборот: ${fmtAmount(kpi.turnover)} RUB`,
    ]
    if (kpi.profit != null) lines.push(`Прибыль: ${fmtAmount(kpi.profit)} RUB`)
    if (kpi.avg_check != null) lines.push(`Средний чек: ${fmtAmount(kpi.avg_check)} RUB`)
    if (kpi.decline_pct != null) lines.push(`Отказов: ${fmtPct(kpi.decline_pct)}`)
    const text = lines.join('\n')

    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [kpi, period])

  return (
    <button
      onClick={handleShare}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
        copied
          ? 'bg-em-500/20 text-em-400 border border-em-500/30'
          : 'bg-surface-2 text-text-3 border border-em-500/10 hover:text-em-400'
      }`}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? 'Скопировано!' : 'Отчёт'}
    </button>
  )
}

const PERIOD_LABELS: Record<DashboardPeriod, string> = {
  today: 'Сегодня',
  yesterday: 'Вчера',
  week: '7 дней',
  month: '30 дней',
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Dashboard({ active = true, onMerchantSelect, onIncidentSelect }: {
  active?: boolean
  onMerchantSelect?: (id: number) => void
  onIncidentSelect?: (id: string) => void
} = {}) {
  const [period, setPeriod] = useState<DashboardPeriod>('today')
  const [merchant, setMerchant] = useState('')
  const [merchants, setMerchants] = useState<string[]>([])
  const [data, setData] = useState<FullDashboardData | null>(null)
  const [yesterdayKpi, setYesterdayKpi] = useState<FullDashboardKpi | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [favorites, setFavorites] = useState<string[]>(getFavorites)
  const [searchOpen, setSearchOpen] = useState(false)
  const [dbStats, setDbStats] = useState<Record<string, number> | undefined>()

  const toggleFavorite = useCallback((name: string) => {
    setFavorites(prev => {
      const next = prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
      setFavoritesStorage(next)
      return next
    })
  }, [])

  const closeSearch = useCallback(() => setSearchOpen(false), [])
  const openSearch = useCallback(() => setSearchOpen(true), [])
  const handleSearchSelect = useCallback((id: number) => onMerchantSelect?.(id), [onMerchantSelect])
  const handleIncidentSelect = useCallback((id: string) => onIncidentSelect?.(id), [onIncidentSelect])

  useEffect(() => {
    api.analytics.filterOptions()
      .then(opts => setMerchants(opts.merchants || []))
      .catch(() => {})
    api.analytics.dashboard()
      .then(d => setDbStats(d.db_stats?.by_status))
      .catch(() => {})
  }, [])

  const hasLoaded = useRef(false)

  const load = useCallback(
    (p: DashboardPeriod, m: string, silent = false) => {
      if (!silent) {
        setLoading(true)
        setError('')
      }

      const promises: Promise<any>[] = [
        api.analytics.fullDashboard({ period: p, merchant: m || undefined }),
      ]

      if (p === 'today') {
        promises.push(
          api.analytics.fullDashboard({ period: 'yesterday', merchant: m || undefined })
            .catch(() => null)
        )
      }

      Promise.all(promises)
        .then(([todayData, yesterdayData]) => {
          setData(todayData)
          setYesterdayKpi(yesterdayData?.kpi ?? null)
          hasLoaded.current = true
        })
        .catch(e => { if (!silent) setError(e.message || 'Ошибка загрузки') })
        .finally(() => setLoading(false))
    },
    [],
  )

  useEffect(() => {
    load(period, merchant)
  }, [period, merchant, load])

  // Silent background refresh when returning to this tab
  useEffect(() => {
    if (!active || !hasLoaded.current) return
    load(period, merchant, true)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps

  const kpi = data?.kpi
  const ykpi = yesterdayKpi

  return (
    <div className="pb-24 space-y-4 bg-bg min-h-screen">
      <SearchOverlay open={searchOpen} onClose={closeSearch} onSelect={handleSearchSelect} />

      <AppHeader title="Дашборд">
        {kpi && <ShareButton kpi={kpi} period={period} />}
        <button
          onClick={openSearch}
          className="p-2 rounded-xl bg-surface-2 border border-em-500/10 text-text-3 hover:text-em-400 transition-colors"
        >
          <Search size={18} />
        </button>
      </AppHeader>

      <div className="px-4 space-y-4">

      {/* Period filter */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {(Object.keys(PERIOD_LABELS) as DashboardPeriod[]).map(p => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`flex-shrink-0 px-3 py-1 rounded-xl text-sm font-medium transition-all ${
              period === p
                ? 'bg-em-500 text-text-1 shadow-[0_0_12px_rgba(16,185,129,0.4)]'
                : 'bg-surface-2 text-text-3 border border-em-500/10'
            }`}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
      </div>

      {/* Merchant filter */}
      {merchants.length > 0 && (
        <div>
          <select
            value={merchant}
            onChange={e => setMerchant(e.target.value)}
            className="w-full rounded-xl px-3 py-2 text-sm bg-surface-2 text-text-1 border border-em-500/10 outline-none focus:ring-1 focus:ring-emerald-500"
          >
            <option value="">Все мерчанты</option>
            {merchants.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      )}

      {loading && <SkeletonDashboard />}

      {error && !loading && (
        <div className="text-sm text-danger">{error}</div>
      )}

      {!loading && !error && kpi && (
        <>
          {/* ── Hero Section ─────────────────────────────────────────── */}
          <div className="bg-surface border border-em-500/10 rounded-2xl p-5 space-y-4">
            <div className="text-center">
              <div className="text-[10px] text-text-3 uppercase tracking-wider mb-1">Общий оборот</div>
              <div className="text-4xl font-bold text-gradient leading-tight">{fmtAmount(kpi.turnover)}</div>
              <div className="flex items-center justify-center gap-2 mt-1">
                <span className="text-[10px] text-text-4">RUB</span>
                {period === 'today' && <TrendBadge current={kpi.turnover} previous={ykpi?.turnover ?? null} />}
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 pt-3 border-t border-em-500/5">
              <HeroMetric label="Всего заявок" value={fmt(kpi.total)} trend={period === 'today' ? <TrendBadge current={kpi.total} previous={ykpi?.total ?? null} /> : undefined} />
              <HeroMetric label="Успешных оплат" value={fmt(kpi.successful)} trend={period === 'today' ? <TrendBadge current={kpi.successful} previous={ykpi?.successful ?? null} /> : undefined} accent />
              <HeroMetric label="Общая конверсия" value={fmtPct(kpi.conversion_pct)} trend={period === 'today' ? <TrendBadge current={kpi.conversion_pct} previous={ykpi?.conversion_pct ?? null} /> : undefined} accent />
            </div>
          </div>

          {/* ── Alert Banner ───────────────────────────────────────── */}
          {period === 'today' && <AlertBanner kpi={kpi} yesterdayKpi={ykpi} />}

          {/* Profit card */}
          {kpi.profit != null && (
            <div className="bg-surface border border-em-500/10 rounded-2xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[10px] text-text-3 uppercase tracking-wider">Чистая прибыль</div>
                <div className="text-3xl font-bold text-em-400">{fmtAmount(kpi.profit)}</div>
                <div className="text-[10px] text-text-4 mt-0.5">RUB</div>
              </div>
              {period === 'today' && <TrendBadge current={kpi.profit} previous={ykpi?.profit ?? null} />}
            </div>
          )}

          {/* ── Margin indicator ──────────────────────────────────── */}
          {kpi.profit != null && kpi.turnover != null && kpi.turnover > 0 && (
            <div className="flex items-center justify-center gap-2 -mt-2">
              <span className="text-[10px] text-text-3 uppercase tracking-wider">Маржа</span>
              <span className="text-sm font-bold text-em-400">
                {((kpi.profit / kpi.turnover) * 100).toFixed(2)}%
              </span>
            </div>
          )}

          {/* ── Daily Digest ───────────────────────────────────────── */}
          {period === 'today' && (
            <DailyDigest kpi={kpi} yesterdayKpi={ykpi} merchants={data.top_merchants} />
          )}

          {/* ── Favorites ──────────────────────────────────────────────── */}
          <FavoriteMerchants data={data.top_merchants} onToggle={toggleFavorite} favorites={favorites} />

          {/* ── Conversion Funnel ──────────────────────────────────────── */}
          <ConversionFunnel
            total={kpi.total}
            issued={kpi.issued_req}
            successful={kpi.successful}
          />

          {/* ── Secondary KPIs ───────────────────────────────────────── */}
          <div className="grid grid-cols-2 gap-3">
            <KpiCard label="Конверсия реквизитов" value={fmtPct(kpi.conversion_req_pct)} accent />
            <KpiCard label="Процент отказов" value={fmtPct(kpi.decline_pct)} warn />
          </div>

          {(kpi.issued_req != null || kpi.avg_check != null) && (
            <div className="grid grid-cols-2 gap-3">
              {kpi.issued_req != null && <KpiCard label="Выдано реквизитов" value={fmt(kpi.issued_req)} />}
              {kpi.avg_check != null && <KpiCard label="Средний чек" value={fmtAmount(kpi.avg_check)} sub="RUB" />}
            </div>
          )}

          {/* ── SLA Monitor ────────────────────────────────────────────── */}
          <SLAMonitor kpi={kpi} yesterdayKpi={ykpi} />

          {/* ── Profit Timeline ─────────────────────────────────────────── */}
          <ProfitTimeline data={data.hourly_profit} />

          {/* ── Activity Heatmap ───────────────────────────────────────── */}
          <ActivityHeatmap data={data.hourly_transactions} />

          {/* ── Trend Chart (week/month periods) ──────────────────────── */}
          {(period === 'week' || period === 'month') && data.week_dynamics && data.week_dynamics.length > 1 && (
            <WeekTrendChart data={data.week_dynamics} />
          )}

          {/* ── Merchant Health ─────────────────────────────────────────── */}
          <MerchantHealth data={data.top_merchants} />

          {/* ── Merchant Rating ─────────────────────────────────────── */}
          <MerchantRating data={data.top_merchants} favorites={favorites} onToggle={toggleFavorite} />

          {/* ── Merchant Compare ────────────────────────────────────── */}
          <MerchantCompare data={data.top_merchants} merchants={merchants} />

          {/* ── Status Breakdown ──────────────────────────────────────── */}
          <StatusBreakdown stats={dbStats} />

          {/* ── Recent Incidents ──────────────────────────────────────── */}
          <RecentIncidents onSelect={handleIncidentSelect} />

          {data.funnel_statuses && data.funnel_statuses.length > 0 && (
            <EmeraldBarChart
              title="Воронка статусов"
              data={data.funnel_statuses}
              nameKey="status"
              valueKey="count"
            />
          )}
        </>
      )}
      </div>
    </div>
  )
}
