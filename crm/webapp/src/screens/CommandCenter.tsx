import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { AlertTriangle, Bell, ChevronRight, Sparkles, TrendingDown } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import Sparkline from '../components/Sparkline'
import Trend from '../components/Trend'
import { SkeletonDashboard } from '../components/Skeleton'
import { useCountUp } from '../hooks/useCountUp'
import { useHaptic } from '../hooks/useHaptic'
import { usePullToRefresh } from '../hooks/usePullToRefresh'
import { api } from '../api/client'
import type { FullDashboardData, FullDashboardKpi, Incident, LiveData } from '../types'
import { fmt, fmtPct, fmtAmount } from '../utils/format'

// ── Props ────────────────────────────────────────────────────────────────────

interface Props {
  active?: boolean
  onNavigate?: (tab: string) => void
  onMerchantSelect?: (id: number) => void
  onIncidentSelect?: (id: string) => void
}

// ── Bars (hourly mini chart for hero) ────────────────────────────────────────

function Bars({ data, w = 344, h = 42, color = '#10b981' }: { data: number[]; w?: number; h?: number; color?: string }) {
  if (!data || !data.length) return null
  const max = Math.max(...data, 1)
  const bw = w / data.length - 1
  return (
    <svg width={w} height={h} style={{ display: 'block', width: '100%' }}>
      {data.map((v, i) => {
        const bh = Math.max(1, (v / max) * h)
        const isPast = v > 0
        return (
          <rect key={i} x={i * (bw + 1)} y={h - bh} width={bw} height={bh} rx={1.5}
            fill={isPast ? color : 'rgba(255,255,255,0.06)'}
            opacity={isPast ? (0.45 + (v / max) * 0.55) : 1} />
        )
      })}
    </svg>
  )
}

// ── HeroTurnover ─────────────────────────────────────────────────────────────

function HeroTurnover({
  value,
  previousValue,
  hourly,
}: {
  value: number | null
  previousValue: number | null
  hourly: { hour: number; total: number; successful: number }[]
}) {
  const animated = useCountUp(value, 1100)
  const now = new Date()
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`

  return (
    <div className="card-em rise" style={{ padding: '16px 16px 0', overflow: 'hidden', position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            Оборот · сегодня
          </div>
          <div className="num" style={{ fontSize: 38, fontWeight: 600, lineHeight: 1, letterSpacing: '-0.04em' }}>
            <span className="hero-text">
              {value == null ? '---' : fmt(Math.round(animated))}
            </span>
            <span style={{ fontSize: 16, color: 'var(--text-3)', marginLeft: 6, fontWeight: 500, letterSpacing: '-0.01em' }}>{'\u20BD'}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
            <Trend current={value} previous={previousValue} size={12} />
            <span style={{ color: 'var(--text-3)', fontSize: 11 }}>vs вчера</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 999, background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.20)' }}>
          <span className="live-dot" />
          <span className="mono" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.10em', color: 'var(--em-400)' }}>LIVE</span>
        </div>
      </div>
      {hourly.length > 0 && (
        <div style={{ marginTop: 14, marginBottom: -1, marginLeft: -1, marginRight: -1 }}>
          <Bars data={hourly.map(h => h.total)} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-4)', padding: '4px 4px 10px' }} className="mono">
            <span>00</span><span>06</span><span>12</span><span>{timeStr}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── MetricCell (design-aligned) ──────────────────────────────────────────────

function MetricCell({
  label,
  value,
  current,
  previous,
  accent,
  warn,
  badge,
  sparkData,
  onClick,
}: {
  label: string
  value: string
  current?: number | null
  previous?: number | null
  accent?: boolean
  warn?: boolean
  badge?: number
  sparkData?: number[]
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className="card press"
      style={{
        textAlign: 'left',
        padding: '12px 14px',
        display: 'flex', flexDirection: 'column', gap: 4,
        position: 'relative',
        border: warn ? '1px solid rgba(248,113,113,0.22)' : '1px solid var(--hairline)',
        background: warn ? 'rgba(248,113,113,0.04)' : 'var(--surface)',
        cursor: onClick ? 'pointer' : 'default',
        borderRadius: 'var(--r-lg)',
      }}
    >
      <div className="eyebrow">{label}</div>
      <div className="mono num" style={{
        fontSize: 22, fontWeight: 600, lineHeight: 1.1,
        color: warn ? 'var(--danger)' : accent ? 'var(--em-400)' : 'var(--text-1)',
        letterSpacing: '-0.02em',
      }}>{value}</div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 2, minHeight: 14 }}>
        {current != null && previous != null ? <Trend current={current} previous={previous} /> : <span />}
        {sparkData && sparkData.length > 1 && <Sparkline data={sparkData} w={60} h={16} color={accent ? '#34d399' : '#10b981'} strokeW={1.4} />}
      </div>
      {badge != null && badge > 0 && (
        <span className="mono" style={{ position: 'absolute', top: 10, right: 10, minWidth: 18, height: 18, padding: '0 5px', borderRadius: 6, background: 'var(--danger)', color: '#fff', fontSize: 10, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>{badge}</span>
      )}
    </button>
  )
}

// ── AlertStrip ───────────────────────────────────────────────────────────────

interface AlertItem {
  text: string
  severity: 'critical' | 'warn' | 'info'
}

function AlertStrip({
  kpi,
  yesterdayKpi,
  incidents,
  onTap,
}: {
  kpi: FullDashboardKpi
  yesterdayKpi: FullDashboardKpi | null
  incidents: Incident[]
  onTap?: () => void
}) {
  const alerts = useMemo<AlertItem[]>(() => {
    const result: AlertItem[] = []

    if (kpi.conversion_pct != null && yesterdayKpi?.conversion_pct != null && yesterdayKpi.conversion_pct > 0) {
      const drop = ((yesterdayKpi.conversion_pct - kpi.conversion_pct) / yesterdayKpi.conversion_pct) * 100
      if (drop > 10) {
        result.push({
          text: `Конверсия снизилась на ${drop.toFixed(0)}% vs вчера (${kpi.conversion_pct.toFixed(1)}%)`,
          severity: drop > 20 ? 'critical' : 'warn',
        })
      }
    }

    const criticalCount = incidents.filter(inc => inc.severity === 'P0' || inc.severity === 'P1').length
    if (criticalCount > 0) {
      result.push({
        text: `${criticalCount} критических P0/P1 инцидент${criticalCount === 1 ? '' : criticalCount < 5 ? 'а' : 'ов'} открыто`,
        severity: 'critical',
      })
    }

    if (kpi.decline_pct != null && kpi.decline_pct > 25) {
      result.push({
        text: `Уровень отказов ${kpi.decline_pct.toFixed(1)}% — выше порога 25%`,
        severity: kpi.decline_pct > 40 ? 'critical' : 'warn',
      })
    }

    if (kpi.total != null && yesterdayKpi?.total != null && yesterdayKpi.total > 0) {
      const drop = ((yesterdayKpi.total - kpi.total) / yesterdayKpi.total) * 100
      if (drop > 30) {
        result.push({
          text: `Объём транзакций упал на ${drop.toFixed(0)}%`,
          severity: 'critical',
        })
      }
    }

    return result.slice(0, 3)
  }, [kpi, yesterdayKpi, incidents])

  if (alerts.length === 0) return null

  const iconForSeverity = (sev: string) => {
    if (sev === 'critical') return <TrendingDown size={14} />
    if (sev === 'warn') return <AlertTriangle size={14} />
    return <Bell size={14} />
  }

  const colorForSeverity = (sev: string) => {
    if (sev === 'critical') return { bg: 'rgba(248,113,113,0.07)', border: 'rgba(248,113,113,0.20)', fg: 'var(--danger)' }
    if (sev === 'warn') return { bg: 'rgba(251,191,36,0.07)', border: 'rgba(251,191,36,0.20)', fg: 'var(--warn)' }
    return { bg: 'rgba(125,211,252,0.07)', border: 'rgba(125,211,252,0.20)', fg: 'var(--info)' }
  }

  return (
    <div className="rise" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="section-title" style={{ marginBottom: 2 }}>Требует внимания</div>
      {alerts.map((a, i) => {
        const c = colorForSeverity(a.severity)
        return (
          <button key={i} className="press" onClick={onTap}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 12px', borderRadius: 12, textAlign: 'left',
              background: c.bg,
              border: `1px solid ${c.border}`,
              cursor: 'pointer',
            }}>
            <span style={{
              width: 26, height: 26, borderRadius: 8,
              background: 'rgba(255,255,255,0.04)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              color: c.fg,
            }}>
              {iconForSeverity(a.severity)}
            </span>
            <span style={{ flex: 1, fontSize: 12.5, fontWeight: 500, color: 'var(--text-1)', lineHeight: 1.3 }}>{a.text}</span>
            <ChevronRight size={14} style={{ color: 'var(--text-4)', flexShrink: 0 }} />
          </button>
        )
      })}
    </div>
  )
}

// ── DailyDigest ──────────────────────────────────────────────────────────────

function DailyDigest({
  kpi,
  yesterdayKpi,
  topMerchants,
}: {
  kpi: FullDashboardKpi
  yesterdayKpi: FullDashboardKpi | null
  topMerchants: Record<string, any>[]
}) {
  const insights = useMemo(() => {
    const result: { text: string; tone: 'good' | 'bad' | 'neutral' }[] = []

    if (kpi.total != null && yesterdayKpi?.total != null && yesterdayKpi.total > 0) {
      const pct = ((kpi.total - yesterdayKpi.total) / yesterdayKpi.total) * 100
      if (pct > 0) result.push({ text: `Транзакций на ${pct.toFixed(0)}% больше чем вчера`, tone: 'good' })
      else if (pct < -5) result.push({ text: `Транзакций на ${Math.abs(pct).toFixed(0)}% меньше чем вчера`, tone: 'bad' })
      else result.push({ text: 'Объём транзакций на уровне вчерашнего', tone: 'neutral' })
    }

    if (topMerchants.length > 0) {
      const nameKey = Object.keys(topMerchants[0]).find(k => /merchant|name|мерчант/i.test(k))
      const amountKey = Object.keys(topMerchants[0]).find(k => /amount|сумма|оборот/i.test(k))
      if (nameKey && amountKey) {
        const sorted = [...topMerchants].sort((a, b) => Number(b[amountKey] ?? 0) - Number(a[amountKey] ?? 0))
        if (sorted[0]) result.push({ text: `Лидер дня: ${sorted[0][nameKey]}`, tone: 'good' })
      }
    }

    if (kpi.conversion_pct != null) {
      if (kpi.conversion_pct > 50) result.push({ text: 'Конверсия выше 50% — отличный результат', tone: 'good' })
      else if (kpi.conversion_pct > 40) result.push({ text: 'Конверсия в норме — хороший день', tone: 'neutral' })
      else result.push({ text: `Конверсия ${fmtPct(kpi.conversion_pct)} — ниже обычного`, tone: 'bad' })
    }

    if (kpi.avg_profit_per_order != null && kpi.avg_profit_per_order > 0) {
      result.push({ text: `Средняя прибыль ${fmtAmount(kpi.avg_profit_per_order)} за транзакцию`, tone: 'neutral' })
    }

    return result
  }, [kpi, yesterdayKpi, topMerchants])

  if (insights.length === 0) return null

  const dotColor = (tone: string) =>
    tone === 'good' ? 'var(--em-400)' : tone === 'bad' ? 'var(--danger)' : 'var(--text-4)'

  return (
    <div className="rise card" style={{ padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        <Sparkles size={13} style={{ color: 'var(--em-400)' }} />
        <span className="section-title" style={{ color: 'var(--em-400)' }}>Итоги дня</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {insights.map((it, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <span style={{ width: 4, height: 4, borderRadius: '50%', background: dotColor(it.tone), marginTop: 7, flexShrink: 0 }} />
            <span style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.5 }}>{it.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── TopMerchantsRow ──────────────────────────────────────────────────────────

function TopMerchantsRow({
  merchants,
  onSelect,
}: {
  merchants: Record<string, any>[]
  onSelect?: (id: number) => void
}) {
  const haptic = useHaptic()

  if (!merchants || merchants.length === 0) return null

  const nameKey = Object.keys(merchants[0]).find(k => /merchant|name|мерчант/i.test(k)) || 'merchant_name'
  const amountKey = Object.keys(merchants[0]).find(k => /amount|сумма|оборот/i.test(k)) || 'amount'
  const convKey = Object.keys(merchants[0]).find(k => /conv/i.test(k))
  const sorted = [...merchants].sort((a, b) => Number(b[amountKey] ?? 0) - Number(a[amountKey] ?? 0)).slice(0, 4)

  return (
    <div className="rise">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span className="section-title">Топ-мерчанты</span>
        <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)' }}>ОБОРОТ</span>
      </div>
      <div className="card" style={{ overflow: 'hidden' }}>
        {sorted.map((m, i) => (
          <button key={i} className="press"
            onClick={() => {
              haptic.impact('light')
              if (m.id) onSelect?.(m.id)
            }}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 14px',
              borderTop: i === 0 ? 'none' : '1px solid var(--hairline)',
              background: 'transparent', textAlign: 'left', cursor: 'pointer',
            }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)', width: 14, textAlign: 'right' }}>{i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m[nameKey]}</div>
              {convKey && (
                <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>
                  {Number(m[convKey]).toFixed(1)}% conv
                </div>
              )}
            </div>
            <div className="num mono" style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-1)', minWidth: 56, textAlign: 'right' }}>
              {fmtAmount(Number(m[amountKey]))}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── RecentIncidents ──────────────────────────────────────────────────────────

const PRIORITY_STYLES: Record<string, { bg: string; fg: string }> = {
  P0: { bg: 'rgba(248,113,113,0.18)', fg: '#fca5a5' },
  P1: { bg: 'rgba(251,191,36,0.18)', fg: '#fcd34d' },
  P2: { bg: 'rgba(125,211,252,0.18)', fg: '#7dd3fc' },
  P3: { bg: 'rgba(255,255,255,0.06)', fg: 'var(--text-3)' },
}

function RecentIncidentsList({
  incidents,
  onSelect,
  onViewAll,
}: {
  incidents: Incident[]
  onSelect?: (id: string) => void
  onViewAll?: () => void
}) {
  const haptic = useHaptic()

  if (incidents.length === 0) return null

  return (
    <div className="rise">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span className="section-title">Открытые инциденты</span>
        {onViewAll && (
          <button onClick={() => { haptic.selection(); onViewAll() }}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11, fontWeight: 600, color: 'var(--em-400)' }}>
            Все <ChevronRight size={11} />
          </button>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {incidents.map(inc => {
          const isHigh = inc.severity === 'P0' || inc.severity === 'P1'
          const ps = PRIORITY_STYLES[inc.severity] || PRIORITY_STYLES.P3
          return (
            <button key={inc.id} className="press"
              onClick={() => { haptic.impact('light'); onSelect?.(inc.id) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px', borderRadius: 12, textAlign: 'left',
                background: 'var(--surface)',
                border: `1px solid ${isHigh ? 'rgba(248,113,113,0.18)' : 'var(--hairline)'}`,
                cursor: 'pointer',
              }}>
              <span className="mono" style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                padding: '2px 6px', borderRadius: 5, fontSize: 10, fontWeight: 700,
                letterSpacing: '0.04em', background: ps.bg, color: ps.fg,
                border: `1px solid ${ps.fg}25`, flexShrink: 0,
              }}>{inc.severity}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{inc.title}</div>
                <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }} className="mono">
                  {inc.id} · {(inc.dimensions?.merchant_name || inc.scope || '').slice(0, 22)}
                  {inc.delta_pct != null ? ` · ${inc.delta_pct > 0 ? '+' : ''}${inc.delta_pct.toFixed(1)}%` : ''}
                </div>
              </div>
              <ChevronRight size={14} style={{ color: 'var(--text-4)', flexShrink: 0 }} />
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

export default function CommandCenter({
  active = true,
  onNavigate,
  onIncidentSelect,
}: Props) {
  const [todayData, setTodayData] = useState<FullDashboardData | null>(null)
  const [yesterdayKpi, setYesterdayKpi] = useState<FullDashboardKpi | null>(null)
  const [liveData, setLiveData] = useState<LiveData | null>(null)
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const hasLoaded = useRef(false)
  const haptic = useHaptic()

  const loadAll = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }

    try {
      const [todayRes, yesterdayRes, liveRes, incidentsRes] = await Promise.all([
        api.analytics.fullDashboard({ period: 'today' }),
        api.analytics.fullDashboard({ period: 'yesterday' }).catch(() => null),
        api.analytics.live().catch(() => null),
        api.incidents.list({ limit: 3, status: 'open' }).catch(() => ({ incidents: [], total: 0 })),
      ])

      setTodayData(todayRes)
      setYesterdayKpi(yesterdayRes?.kpi ?? null)
      setLiveData(liveRes)
      setIncidents(incidentsRes.incidents)
      hasLoaded.current = true
    } catch (e: any) {
      if (!silent) setError(e.message || 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  useEffect(() => {
    if (!active || !hasLoaded.current) return
    loadAll(true)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps

  const { scrollRef, pullHandlers, PullIndicator } = usePullToRefresh({
    onRefresh: async () => {
      haptic.impact('medium')
      await loadAll(true)
      haptic.notification('success')
    },
  })

  const kpi = todayData?.kpi ?? null
  const ykpi = yesterdayKpi
  const liveKpi = liveData?.kpi ?? null
  const hourly = liveData?.hourly ?? []

  const openIncidentCount = incidents.length
  const criticalCount = incidents.filter(inc => inc.severity === 'P0' || inc.severity === 'P1').length

  // Sparkline data from hourly transactions
  const hourlyTotals = (todayData?.hourly_transactions ?? []).map((h: any) => Number(h.total ?? h.orders ?? 0))
  const hourlyConv = (todayData?.hourly_transactions ?? []).map((h: any) => Number(h.conversion_pct ?? 0))

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh', paddingBottom: 96 }}>
      <AppHeader title="Command Center">
        <button className="press" onClick={() => { haptic.selection(); onNavigate?.('alerts') }}
          style={{ width: 36, height: 36, borderRadius: 12, background: 'var(--surface)', border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
          <Bell size={15} style={{ color: 'var(--text-2)' }} />
          {openIncidentCount > 0 && <span style={{ position: 'absolute', top: 7, right: 7, width: 7, height: 7, borderRadius: '50%', background: 'var(--danger)', boxShadow: '0 0 0 2px var(--bg)' }} />}
        </button>
      </AppHeader>

      <div
        ref={scrollRef}
        {...pullHandlers}
        className="overflow-y-auto"
        style={{ maxHeight: 'calc(100vh - 56px)' }}
      >
        {PullIndicator}

        <div style={{ padding: '0 12px 24px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {loading && !hasLoaded.current && <SkeletonDashboard />}

          {error && !loading && (
            <div style={{ fontSize: 14, color: 'var(--danger)', textAlign: 'center', padding: '32px 0' }}>{error}</div>
          )}

          {kpi && (
            <>
              {/* HERO */}
              <HeroTurnover
                value={liveKpi?.turnover ?? kpi.turnover}
                previousValue={ykpi?.turnover ?? null}
                hourly={hourly}
              />

              {/* 2x2 METRICS */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }} className="rise rise-1">
                <MetricCell
                  label="Транзакции"
                  value={fmt(liveKpi?.total ?? kpi.total)}
                  current={kpi.total}
                  previous={ykpi?.total ?? null}
                  sparkData={hourlyTotals.length > 1 ? hourlyTotals : undefined}
                />
                <MetricCell
                  label="Конверсия"
                  value={fmtPct(liveKpi?.conversion_pct ?? kpi.conversion_pct)}
                  current={kpi.conversion_pct}
                  previous={ykpi?.conversion_pct ?? null}
                  accent
                  sparkData={hourlyConv.length > 1 ? hourlyConv : undefined}
                />
                <MetricCell
                  label="Прибыль"
                  value={fmtAmount(liveKpi?.profit ?? kpi.profit)}
                  current={kpi.profit}
                  previous={ykpi?.profit ?? null}
                  accent
                />
                <MetricCell
                  label="Инциденты"
                  value={String(openIncidentCount)}
                  warn={openIncidentCount > 0}
                  badge={criticalCount > 0 ? criticalCount : undefined}
                  onClick={openIncidentCount > 0 ? () => {
                    haptic.impact('light')
                    onNavigate?.('alerts')
                  } : undefined}
                />
              </div>

              {/* ALERTS */}
              <div className="rise rise-2">
                <AlertStrip kpi={kpi} yesterdayKpi={ykpi} incidents={incidents} onTap={() => onNavigate?.('alerts')} />
              </div>

              {/* DIGEST */}
              <div className="rise rise-3">
                <DailyDigest kpi={kpi} yesterdayKpi={ykpi} topMerchants={todayData?.top_merchants ?? []} />
              </div>

              {/* TOP MERCHANTS */}
              <div className="rise rise-4">
                <TopMerchantsRow merchants={todayData?.top_merchants ?? []} />
              </div>

              {/* RECENT INCIDENTS */}
              <div className="rise rise-5">
                <RecentIncidentsList
                  incidents={incidents}
                  onSelect={(id) => { haptic.impact('light'); onIncidentSelect?.(id) }}
                  onViewAll={() => { haptic.selection(); onNavigate?.('alerts') }}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
