import { useState, useEffect, useRef, useCallback } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts'
import { api } from '../api/client'
import type { LiveData, LiveMerchant } from '../types'
import Spinner from '../components/Spinner'
import { fmt, fmtAmount, fmtPct, fmtShort } from '../utils/format'

// ── Animated number hook ────────────────────────────────────────────────────

function useAnimatedNumber(target: number | null, duration = 800): number {
  const [display, setDisplay] = useState(target ?? 0)
  const prevRef = useRef(target ?? 0)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (target == null) return
    const start = prevRef.current
    const diff = target - start
    if (Math.abs(diff) < 0.5) {
      setDisplay(target)
      prevRef.current = target
      return
    }

    const startTime = performance.now()
    const step = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3) // easeOutCubic
      setDisplay(start + diff * eased)
      if (progress < 1) rafRef.current = requestAnimationFrame(step)
      else prevRef.current = target
    }
    rafRef.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, duration])

  return display
}

// ── TrendBadge ──────────────────────────────────────────────────────────────

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

// ── LiveKpiCard ─────────────────────────────────────────────────────────────

function LiveKpiCard({
  label,
  value,
  yesterdayValue,
  format,
  unit,
}: {
  label: string
  value: number | null
  yesterdayValue: number | null
  format: 'number' | 'pct' | 'amount'
  unit?: string
}) {
  const animated = useAnimatedNumber(value)
  const formatted =
    format === 'pct' ? fmtPct(animated)
    : format === 'amount' ? fmtAmount(animated)
    : fmt(animated)

  return (
    <div className="bg-surface border border-em-500/10 rounded-2xl p-4 flex flex-col gap-1">
      <div className="text-[10px] text-text-3 uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold text-text-1 leading-tight">{formatted}</div>
      <div className="flex items-center gap-2">
        <TrendBadge current={value} previous={yesterdayValue} />
        {unit && <span className="text-[10px] text-text-4">{unit}</span>}
      </div>
    </div>
  )
}

// ── LiveFeed ────────────────────────────────────────────────────────────────

function LiveFeed({ merchants, prevMerchants }: { merchants: LiveMerchant[]; prevMerchants: LiveMerchant[] }) {
  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider">Топ мерчанты сейчас</h2>
      {merchants.slice(0, 5).map((m, i) => {
        const prevM = prevMerchants?.find(p => p.name === m.name)
        const isNew = !prevM
        const conv = m.total > 0 ? (m.successful / m.total * 100) : 0
        return (
          <div
            key={m.name}
            className={`bg-surface border border-em-500/10 rounded-xl p-3 flex items-center justify-between ${isNew ? 'animate-slide-in' : ''}`}
          >
            <div className="flex items-center gap-3">
              <span className="text-em-500 font-bold text-sm w-6">#{i + 1}</span>
              <div>
                <span className="text-text-1 text-sm font-medium truncate block max-w-[140px]">{m.name}</span>
                <span className="text-text-3 text-xs">{fmtAmount(m.amount)}</span>
              </div>
            </div>
            <div className="text-right">
              <div className="text-em-400 text-sm font-bold">{m.successful}/{m.total}</div>
              <div className="text-text-3 text-xs">{conv.toFixed(1)}%</div>
            </div>
          </div>
        )
      })}
      {merchants.length === 0 && (
        <div className="text-center text-text-4 text-sm py-4">Нет данных</div>
      )}
    </div>
  )
}

// ── HourlyChart ─────────────────────────────────────────────────────────────

function HourlyChart({ data }: { data: { hour: number; total: number; successful: number }[] }) {
  if (!data || data.length === 0) return null

  const prepared = data.map(d => ({
    hour: `${d.hour}:00`,
    'Всего': d.total,
    'Успешных': d.successful,
  }))

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-3 uppercase tracking-wider mb-2">Транзакции по часам</h2>
      <div className="border border-em-500/10 rounded-2xl p-3" style={{ background: 'var(--surface)' }}>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={prepared} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
            <XAxis
              dataKey="hour"
              tick={{ fill: '#9ca3af', fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              interval={2}
            />
            <YAxis
              tick={{ fill: '#9ca3af', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={fmtShort}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--surface-2)',
                border: '1px solid rgba(16,185,129,0.2)',
                borderRadius: 12,
                color: '#fff',
                fontSize: 12,
              }}
              formatter={(v: number | undefined, name?: string) => [v != null ? v.toLocaleString('ru-RU') : '—', name ?? '']}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: '#9ca3af' }}
            />
            <Bar dataKey="Всего" fill="#1e3a5f" radius={[3, 3, 0, 0]} maxBarSize={16}>
              {prepared.map((_, i) => (
                <Cell key={i} fill="#1e3a5f" />
              ))}
            </Bar>
            <Bar dataKey="Успешных" fill="#10b981" radius={[3, 3, 0, 0]} maxBarSize={16}>
              {prepared.map((_, i) => (
                <Cell key={i} fill="#10b981" />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function LiveMonitor({ active = true }: { active?: boolean }) {
  const [data, setData] = useState<LiveData | null>(null)
  const [prevMerchants, setPrevMerchants] = useState<LiveMerchant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastFetch, setLastFetch] = useState(Date.now())
  const [secondsAgo, setSecondsAgo] = useState(0)
  const dataRef = useRef<LiveData | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const result = await api.analytics.live()
      setPrevMerchants(dataRef.current?.top_merchants_live || [])
      dataRef.current = result
      setData(result)
      setLastFetch(Date.now())
      setError('')
    } catch (e: any) {
      setError(e.message || 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  // Fetch + poll only when active
  useEffect(() => {
    if (!active) return
    fetchData()
    const interval = setInterval(fetchData, 30_000)
    return () => clearInterval(interval)
  }, [active, fetchData])

  // "X seconds ago" counter — only when active
  useEffect(() => {
    if (!active) return
    const tick = setInterval(() => {
      setSecondsAgo(Math.floor((Date.now() - lastFetch) / 1000))
    }, 1000)
    return () => clearInterval(tick)
  }, [lastFetch, active])

  const kpi = data?.kpi
  const yesterday = data?.yesterday

  return (
    <div className="pb-24 space-y-4 bg-bg min-h-screen">
      <AppHeader title="Live Monitor">
        <div className="w-2 h-2 rounded-full bg-em-500 animate-live-pulse" />
        <span className="text-xs text-em-400 font-medium">LIVE</span>
        <span className="text-[10px] text-text-4">{secondsAgo}с назад</span>
      </AppHeader>

      <div className="px-4 space-y-4">

      {loading && !data && (
        <div className="flex items-center justify-center py-16">
          <Spinner size={28} />
        </div>
      )}

      {error && !data && (
        <div className="text-sm text-danger text-center py-8">{error}</div>
      )}

      {kpi && (
        <>
          {/* Hero KPIs — 2x2 grid */}
          <div className="grid grid-cols-2 gap-3">
            <LiveKpiCard
              label="Всего заявок"
              value={kpi.total}
              yesterdayValue={yesterday?.total ?? null}
              format="number"
            />
            <LiveKpiCard
              label="Успешных оплат"
              value={kpi.successful}
              yesterdayValue={yesterday?.successful ?? null}
              format="number"
            />
            <LiveKpiCard
              label="Общая конверсия"
              value={kpi.conversion_pct}
              yesterdayValue={yesterday?.conversion_pct ?? null}
              format="pct"
            />
            <LiveKpiCard
              label="Общий оборот"
              value={kpi.turnover}
              yesterdayValue={yesterday?.turnover ?? null}
              format="amount"
              unit="RUB"
            />
          </div>

          {/* Profit card */}
          {kpi.profit != null && (
            <div className="bg-surface border border-em-500/10 rounded-2xl p-4">
              <div className="text-[10px] text-text-3 uppercase tracking-wider mb-1">Чистая прибыль</div>
              <div className="text-3xl font-bold text-gradient">{fmtAmount(kpi.profit)}</div>
              <div className="text-[10px] text-text-4 mt-1">RUB</div>
            </div>
          )}

          {/* Hourly chart */}
          <HourlyChart data={data?.hourly || []} />

          {/* Top merchants feed */}
          <LiveFeed
            merchants={data?.top_merchants_live || []}
            prevMerchants={prevMerchants}
          />
        </>
      )}
      </div>
    </div>
  )
}
