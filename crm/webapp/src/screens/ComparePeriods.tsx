import { useState } from 'react'
import { ArrowRightLeft, TrendingUp, TrendingDown, Minus, Calendar, Zap } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import Spinner from '../components/Spinner'
import { api } from '../api/client'
import { fmt, fmtPct, fmtAmount } from '../utils/format'

// ── Helpers ─────────────────────────────────────────────────────────────────

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function weekRange(offset: number): [string, string] {
  const now = new Date()
  const day = now.getDay() || 7
  const mon = new Date(now)
  mon.setDate(now.getDate() - day + 1 + offset * 7)
  const sun = new Date(mon)
  sun.setDate(mon.getDate() + 6)
  return [isoDate(mon), isoDate(sun)]
}

function monthRange(offset: number): [string, string] {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth() + offset, 1)
  const end = new Date(now.getFullYear(), now.getMonth() + offset + 1, 0)
  return [isoDate(start), isoDate(end)]
}

function isPctKey(key: string): boolean {
  const k = key.toLowerCase()
  return k.includes('conv') || k.includes('pct') || k.includes('%')
}

function fmtVal(key: string, val: number): string {
  const k = key.toLowerCase()
  if (k.includes('conv') || k.includes('pct') || k.includes('%')) return fmtPct(val)
  if (k.includes('sum') || k.includes('amount') || k.includes('revenue') || k.includes('сумм') || k.includes('profit') || k.includes('turnover')) return fmtAmount(val)
  return fmt(val)
}

const METRIC_LABELS: Record<string, string> = {
  total: 'Всего заявок',
  successful: 'Успешных',
  conversion_pct: 'Конверсия выдачи',
  conversion_req_pct: 'Конверсия в успех',
  conversion_success: 'Конверсия',
  issued_req: 'Выдано реквизитов',
  amount: 'Оборот',
  amount_successful: 'Оборот (успеш.)',
  turnover: 'Оборот',
  total_amount_all: 'Сумма всех ордеров',
  profit: 'Прибыль',
  profit_total: 'Прибыль',
  avg_check: 'Средний чек',
  avg_profit_per_order: 'Прибыль на ордер',
  decline_pct: 'Процент отказов',
  decline_rate: 'Отказы',
}

// Keys to show in order (skip internal/redundant ones)
const DISPLAY_ORDER = [
  'total', 'successful', 'issued_req',
  'conversion_pct', 'conversion_req_pct',
  'turnover', 'total_amount_all', 'profit',
  'avg_check', 'avg_profit_per_order', 'decline_pct',
]

function prettyKey(key: string): string {
  return METRIC_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ── Delta indicator ────────────────────────────────────────────────────────

function DeltaIndicator({ v1, v2, isPct }: { v1: number; v2: number; isPct?: boolean }) {
  const diff = v2 - v1
  const pctChange = v1 !== 0 ? ((v2 - v1) / Math.abs(v1)) * 100 : v2 > 0 ? 100 : 0
  const isUp = diff > 0
  const isZero = diff === 0

  if (isZero) {
    return (
      <div className="flex items-center gap-1 text-text-3">
        <Minus size={12} />
        <span className="text-xs font-mono">0</span>
      </div>
    )
  }

  return (
    <div className={`flex items-center gap-1 ${isUp ? 'text-em-400' : 'text-danger'}`}>
      {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
      <span className="text-xs font-mono font-semibold">
        {isUp ? '+' : ''}{isPct ? `${diff.toFixed(2)}%` : fmt(diff)}
      </span>
      {!isPct && v1 !== 0 && (
        <span className="text-[10px] opacity-60">
          ({isUp ? '+' : ''}{pctChange.toFixed(1)}%)
        </span>
      )}
    </div>
  )
}

// ── Main ────────────────────────────────────────────────────────────────────

export default function ComparePeriods() {
  const [p1Start, setP1Start] = useState('')
  const [p1End, setP1End] = useState('')
  const [p2Start, setP2Start] = useState('')
  const [p2End, setP2End] = useState('')
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activePreset, setActivePreset] = useState<string | null>(null)

  async function load(s1: string, e1: string, s2: string, e2: string, preset?: string) {
    setP1Start(s1); setP1End(e1); setP2Start(s2); setP2End(e2)
    setActivePreset(preset || null)
    setLoading(true); setError(''); setData(null)
    try {
      setData(await api.analytics.comparePeriods(s1, e1, s2, e2))
    } catch (e: any) {
      setError(e.message || 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit() {
    if (!p1Start || !p1End || !p2Start || !p2End) return
    load(p1Start, p1End, p2Start, p2End, 'custom')
  }

  // Build rows from response — use deltas or kpi sub-objects
  const rows: { key: string; v1: number; v2: number }[] = []
  if (data) {
    if (data.deltas) {
      // API returns { deltas: { metric: { period1, period2, delta, delta_pct } } }
      for (const [key, d] of Object.entries(data.deltas as Record<string, any>)) {
        const v1 = Number(d?.period1 ?? 0)
        const v2 = Number(d?.period2 ?? 0)
        if (!isNaN(v1) && !isNaN(v2)) {
          rows.push({ key, v1, v2 })
        }
      }
    } else if (data.period1?.kpi && data.period2?.kpi) {
      // Fallback: use kpi sub-objects
      const kpi1 = data.period1.kpi
      const kpi2 = data.period2.kpi
      for (const key of Object.keys(kpi1)) {
        const v1 = Number(kpi1[key] ?? 0)
        const v2 = Number(kpi2[key] ?? 0)
        if (!isNaN(v1) && !isNaN(v2)) {
          rows.push({ key, v1, v2 })
        }
      }
    } else if (Array.isArray(data)) {
      for (const row of data) {
        rows.push({ key: row.metric || row.name || '', v1: Number(row.period1 ?? row.v1 ?? 0), v2: Number(row.period2 ?? row.v2 ?? 0) })
      }
    }
  }

  // Sort by display order and filter only known metrics
  const sortedRows = DISPLAY_ORDER
    .map(key => rows.find(r => r.key === key))
    .filter((r): r is { key: string; v1: number; v2: number } => !!r && (r.v1 !== 0 || r.v2 !== 0))

  // Highlight rows: which improved, which got worse
  function rowStatus(r: { v1: number; v2: number; key: string }): 'up' | 'down' | 'same' {
    const diff = r.v2 - r.v1
    if (diff === 0) return 'same'
    // For decline_pct, decline_rate: lower is better
    const k = r.key.toLowerCase()
    if (k.includes('decline') || k.includes('отказ')) return diff < 0 ? 'up' : 'down'
    return diff > 0 ? 'up' : 'down'
  }

  const presets = [
    { id: 'week', label: 'Нед vs нед', action: () => { const [s1,e1] = weekRange(-1); const [s2,e2] = weekRange(0); load(s1,e1,s2,e2,'week') } },
    { id: 'month', label: 'Мес vs мес', action: () => { const [s1,e1] = monthRange(-1); const [s2,e2] = monthRange(0); load(s1,e1,s2,e2,'month') } },
    { id: 'yesterday', label: 'Вчера vs сегодня', action: () => {
      const today = new Date(); const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
      load(isoDate(yesterday), isoDate(yesterday), isoDate(today), isoDate(today), 'yesterday')
    }},
  ]

  return (
    <div className="pb-24 space-y-5 bg-bg min-h-screen">
      <AppHeader title="Сравнение периодов" />
      <div className="px-4 space-y-4">

        {/* Header card with icon */}
        <div className="flex items-center gap-3 rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(16, 185, 129, 0.02))',
            border: '1px solid rgba(16, 185, 129, 0.12)',
          }}
        >
          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(16, 185, 129, 0.15)', boxShadow: '0 0 16px rgba(16, 185, 129, 0.15)' }}
          >
            <ArrowRightLeft size={20} className="text-em-400" />
          </div>
          <div>
            <div className="text-sm font-semibold text-text-1">Сравните метрики</div>
            <div className="text-[11px] text-text-3">Выберите два периода для анализа динамики</div>
          </div>
        </div>

        {/* Quick presets */}
        <div className="flex gap-2">
          {presets.map(p => (
            <button
              key={p.id}
              onClick={p.action}
              className="flex-1 py-2.5 rounded-xl text-xs font-semibold transition-all duration-200 active:scale-95"
              style={{
                background: activePreset === p.id
                  ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.25), rgba(16, 185, 129, 0.15))'
                  : 'rgba(13, 17, 23, 0.8)',
                border: `1px solid ${activePreset === p.id ? 'rgba(16, 185, 129, 0.4)' : 'rgba(16, 185, 129, 0.1)'}`,
                color: activePreset === p.id ? '#34d399' : '#9ca3af',
                boxShadow: activePreset === p.id ? '0 0 12px rgba(16, 185, 129, 0.15)' : 'none',
              }}
            >
              <Zap size={10} className="inline mr-1" style={{ opacity: activePreset === p.id ? 1 : 0.4 }} />
              {p.label}
            </button>
          ))}
        </div>

        {/* Custom date selectors */}
        <div className="rounded-2xl overflow-hidden"
          style={{ background: 'linear-gradient(180deg, #0d1117, #0a0f14)', border: '1px solid rgba(16, 185, 129, 0.08)' }}
        >
          <div className="p-4 space-y-3">
            {/* Period 1 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-emerald-400" style={{ boxShadow: '0 0 6px #10b981' }} />
                <span className="text-[11px] font-semibold text-em-400 uppercase tracking-wider">Период 1</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="relative">
                  <Calendar size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3" />
                  <input type="date" value={p1Start} onChange={e => setP1Start(e.target.value)}
                    className="w-full bg-surface-2 border border-em-500/10 rounded-xl pl-8 pr-3 py-2.5 text-xs text-text-1 focus:outline-none focus:border-em-500/40 transition-colors" />
                </div>
                <div className="relative">
                  <Calendar size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3" />
                  <input type="date" value={p1End} onChange={e => setP1End(e.target.value)}
                    className="w-full bg-surface-2 border border-em-500/10 rounded-xl pl-8 pr-3 py-2.5 text-xs text-text-1 focus:outline-none focus:border-em-500/40 transition-colors" />
                </div>
              </div>
            </div>

            {/* Separator */}
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-em-500/10" />
              <span className="text-[10px] text-text-3 uppercase">vs</span>
              <div className="flex-1 h-px bg-em-500/10" />
            </div>

            {/* Period 2 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-blue-400" style={{ boxShadow: '0 0 6px #3b82f6' }} />
                <span className="text-[11px] font-semibold text-blue-400 uppercase tracking-wider">Период 2</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="relative">
                  <Calendar size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3" />
                  <input type="date" value={p2Start} onChange={e => setP2Start(e.target.value)}
                    className="w-full bg-surface-2 border border-em-500/10 rounded-xl pl-8 pr-3 py-2.5 text-xs text-text-1 focus:outline-none focus:border-em-500/40 transition-colors" />
                </div>
                <div className="relative">
                  <Calendar size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3" />
                  <input type="date" value={p2End} onChange={e => setP2End(e.target.value)}
                    className="w-full bg-surface-2 border border-em-500/10 rounded-xl pl-8 pr-3 py-2.5 text-xs text-text-1 focus:outline-none focus:border-em-500/40 transition-colors" />
                </div>
              </div>
            </div>
          </div>

          {/* Compare button */}
          <button
            onClick={handleSubmit}
            disabled={!p1Start || !p1End || !p2Start || !p2End || loading}
            className="w-full py-3 text-sm font-semibold disabled:opacity-30 active:opacity-80 transition-all"
            style={{
              background: 'linear-gradient(90deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.12))',
              color: '#34d399',
              borderTop: '1px solid rgba(16, 185, 129, 0.15)',
            }}
          >
            <ArrowRightLeft size={14} className="inline mr-2" />
            Сравнить периоды
          </button>
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex flex-col items-center gap-3 py-12">
            <Spinner size={28} />
            <span className="text-xs text-text-3">Загружаю данные...</span>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-2xl bg-danger/8 border border-danger/20 p-4 text-center">
            <span className="text-xs text-danger">{error}</span>
          </div>
        )}

        {/* Results */}
        {!loading && sortedRows.length > 0 && (
          <div className="space-y-2">
            {/* Period labels */}
            <div className="flex items-center justify-between px-1">
              <span className="text-[10px] text-text-3 uppercase tracking-wider">Результаты сравнения</span>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-emerald-400" />
                  <span className="text-[10px] text-text-3">П1</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-blue-400" />
                  <span className="text-[10px] text-text-3">П2</span>
                </div>
              </div>
            </div>

            {/* Metric cards */}
            {sortedRows.map((r) => {
              const status = rowStatus(r)
              return (
                <div
                  key={r.key}
                  className="rounded-xl p-3.5 transition-all"
                  style={{
                    background: status === 'up'
                      ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.06), rgba(16, 185, 129, 0.02))'
                      : status === 'down'
                      ? 'linear-gradient(135deg, rgba(239, 68, 68, 0.06), rgba(239, 68, 68, 0.02))'
                      : 'rgba(13, 17, 23, 0.6)',
                    border: `1px solid ${
                      status === 'up' ? 'rgba(16, 185, 129, 0.12)' :
                      status === 'down' ? 'rgba(239, 68, 68, 0.12)' :
                      'rgba(255, 255, 255, 0.04)'
                    }`,
                  }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-text-2">{prettyKey(r.key)}</span>
                    <DeltaIndicator v1={r.v1} v2={r.v2} isPct={isPctKey(r.key)} />
                  </div>
                  <div className="flex items-end gap-4">
                    <div className="flex-1">
                      <div className="text-[10px] text-text-3 mb-0.5">Период 1</div>
                      <div className="text-sm font-bold text-text-1 font-mono">{fmtVal(r.key, r.v1)}</div>
                    </div>
                    <div className="text-text-4 pb-1">
                      <ArrowRightLeft size={12} />
                    </div>
                    <div className="flex-1 text-right">
                      <div className="text-[10px] text-text-3 mb-0.5">Период 2</div>
                      <div className="text-sm font-bold text-text-1 font-mono">{fmtVal(r.key, r.v2)}</div>
                    </div>
                  </div>
                  {/* Visual bar comparison */}
                  <div className="mt-2.5 space-y-1">
                    <div className="h-1.5 rounded-full overflow-hidden bg-surface-3">
                      <div className="h-full rounded-full transition-all duration-700"
                        style={{
                          width: `${Math.min(100, Math.max(2, (r.v1 / Math.max(r.v1, r.v2, 1)) * 100))}%`,
                          background: 'linear-gradient(90deg, #10b981, #34d399)',
                          boxShadow: '0 0 6px rgba(16, 185, 129, 0.4)',
                        }}
                      />
                    </div>
                    <div className="h-1.5 rounded-full overflow-hidden bg-surface-3">
                      <div className="h-full rounded-full transition-all duration-700"
                        style={{
                          width: `${Math.min(100, Math.max(2, (r.v2 / Math.max(r.v1, r.v2, 1)) * 100))}%`,
                          background: 'linear-gradient(90deg, #3b82f6, #60a5fa)',
                          boxShadow: '0 0 6px rgba(59, 130, 246, 0.4)',
                        }}
                      />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* No data */}
        {!loading && !error && data && sortedRows.length === 0 && (
          <div className="rounded-2xl p-8 text-center" style={{ background: 'rgba(13, 17, 23, 0.5)', border: '1px solid rgba(255,255,255,0.04)' }}>
            <ArrowRightLeft size={24} className="mx-auto text-text-4 mb-2" />
            <p className="text-xs text-text-3">Нет данных для сравнения</p>
          </div>
        )}
      </div>
    </div>
  )
}
