import { useEffect, useState, useCallback } from 'react'
import { ChevronDown, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import type { TraderDashboardData, TraderFilterOptions } from '../types'
import { SkeletonDashboard } from '../components/Skeleton'
import AppHeader from '../components/AppHeader'
import EmeraldBarChart from '../components/charts/EmeraldBarChart'
import EmeraldPieChart from '../components/charts/EmeraldPieChart'
import { fmt, fmtPct, fmtAmount } from '../utils/format'

// ── StatBlock (design-aligned) ───────────────────────────────────────────────

function StatBlock({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div style={{ flex: 1, padding: '10px 14px', borderRight: '1px solid var(--hairline)' }}>
      <div className="eyebrow" style={{ marginBottom: 4 }}>{label}</div>
      <div className="mono num" style={{ fontSize: 18, fontWeight: 600, color: accent ? 'var(--em-400)' : 'var(--text-1)', letterSpacing: '-0.02em' }}>{value}</div>
      {sub && <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// ── CircularProgress ─────────────────────────────────────────────────────────

function CircularProgress({ value, size = 88, stroke = 6 }: { value: number; size?: number; stroke?: number }) {
  const radius = (size - stroke) / 2
  const circ = 2 * Math.PI * radius
  const clamped = Math.min(Math.max(value, 0), 100)
  const offset = circ - (clamped / 100) * circ

  return (
    <svg width={size} height={size} style={{ display: 'block', margin: '0 auto' }}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(16,185,129,0.1)" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgb(16,185,129)" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: 'stroke-dashoffset 0.6s ease' }} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" className="mono" style={{ fontSize: 18, fontWeight: 600, fill: 'var(--em-400)' }}>
        {fmtPct(value)}
      </text>
    </svg>
  )
}

// ── CollapsibleSection ───────────────────────────────────────────────────────

function CollapsibleSection({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <button onClick={() => setOpen(o => !o)} className="press" style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', textAlign: 'left' }}>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--text-1)' }}>{title}</span>
        <ChevronDown size={16} style={{ color: 'var(--em-400)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>
      {open && <div style={{ padding: '0 14px 14px', borderTop: '1px solid var(--hairline)' }}>{children}</div>}
    </div>
  )
}

// ── SimpleTable ──────────────────────────────────────────────────────────────

function SimpleTable({ rows, nameKey, valueKey, extraKey, extraFmt }: { rows: Record<string, any>[]; nameKey: string; valueKey: string; extraKey?: string; extraFmt?: (v: any) => string }) {
  if (!rows || rows.length === 0) return null
  const efmt = extraFmt || ((v: any) => String(v ?? '\u2014'))
  return (
    <div style={{ marginTop: 8 }}>
      {rows.slice(0, 15).map((row, i) => {
        const keys = Object.keys(row)
        const nk = nameKey in row ? nameKey : keys[0]
        const vk = (valueKey in row && valueKey !== nk) ? valueKey : (keys.find(k => k !== nk) ?? keys[1] ?? '')
        const ek = extraKey && extraKey in row ? extraKey : null
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderTop: i === 0 ? 'none' : '1px solid var(--hairline)' }}>
            <span className="mono" style={{ fontSize: 10, color: i < 3 ? 'var(--em-400)' : 'var(--text-4)', width: 16, textAlign: 'right', fontWeight: 700 }}>{i + 1}</span>
            <span style={{ flex: 1, fontSize: 12.5, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row[nk]}</span>
            {ek && <span className="mono" style={{ fontSize: 10.5, color: 'var(--em-400)' }}>{efmt(row[ek])}</span>}
            <span className="mono num" style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-1)' }}>{fmtAmount(row[vk])}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function Traders() {
  const getTodayMSK = () => {
    const now = new Date()
    const mskTime = new Date(now.getTime() + (3 * 3600000))
    return `${mskTime.getUTCFullYear()}-${String(mskTime.getUTCMonth() + 1).padStart(2, '0')}-${String(mskTime.getUTCDate()).padStart(2, '0')}`
  }

  const [period, setPeriod] = useState(getTodayMSK())
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [filterOptions, setFilterOptions] = useState<TraderFilterOptions | null>(null)

  const [trader, setTrader] = useState('')
  const [method, setMethod] = useState('')
  const [bank, setBank] = useState('')
  const [tla, setTla] = useState('')
  const [htl, setHtl] = useState('')
  const [agent, setAgent] = useState('')
  const [merchant, setMerchant] = useState('')

  const [appliedTrader, setAppliedTrader] = useState('')
  const [appliedMethod, setAppliedMethod] = useState('')
  const [appliedBank, setAppliedBank] = useState('')
  const [appliedTla, setAppliedTla] = useState('')
  const [appliedHtl, setAppliedHtl] = useState('')
  const [appliedAgent, setAppliedAgent] = useState('')
  const [appliedMerchant, setAppliedMerchant] = useState('')

  const [data, setData] = useState<TraderDashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.analytics.traderFilterOptions().then(setFilterOptions).catch(() => {})
  }, [])

  const load = useCallback((p: string, tr: string, m: string, b: string, t: string, h: string, a: string, mc: string) => {
    setLoading(true)
    setError('')
    api.analytics.traderDashboard({ period: p, trader: tr || undefined, method: m || undefined, bank: b || undefined, tla: t || undefined, htl: h || undefined, agent: a || undefined, merchant: mc || undefined })
      .then(setData)
      .catch(e => setError(e.message || 'Ошибка загрузки'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load(period, appliedTrader, appliedMethod, appliedBank, appliedTla, appliedHtl, appliedAgent, appliedMerchant)
  }, [period, appliedTrader, appliedMethod, appliedBank, appliedTla, appliedHtl, appliedAgent, appliedMerchant, load])

  const handleApplyFilters = () => {
    setAppliedTrader(trader); setAppliedMethod(method); setAppliedBank(bank)
    setAppliedTla(tla); setAppliedHtl(htl); setAppliedAgent(agent); setAppliedMerchant(merchant)
    setFiltersOpen(false)
  }

  const activeFilterCount = [appliedTrader, appliedMethod, appliedBank, appliedTla, appliedHtl, appliedAgent, appliedMerchant].filter(Boolean).length
  const kpi = data?.kpi
  const margin = kpi && kpi.amount_payin && kpi.amount_payin > 0
    ? ((kpi.amount_successful ?? 0) / kpi.amount_payin) * 100
    : null

  const inputStyle: React.CSSProperties = {
    width: '100%', borderRadius: 'var(--r-md)', padding: '8px 12px', fontSize: 13,
    background: 'var(--surface)', color: 'var(--text-1)',
    border: '1px solid var(--hairline)', outline: 'none',
    fontFamily: 'var(--font-sans)',
  }

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh', paddingBottom: 96 }}>
      <AppHeader title="Трейдеры" />

      <div style={{ padding: '0 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* Date + Filters row */}
        <div style={{ display: 'flex', gap: 8 }} className="rise">
          <input type="date" value={period} onChange={e => setPeriod(e.target.value)} style={{ ...inputStyle, flex: 1 }} />
          <button onClick={() => setFiltersOpen(o => !o)} className="press" style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderRadius: 'var(--r-md)', fontSize: 12, fontWeight: 600,
            background: activeFilterCount > 0 ? 'var(--em-tint)' : 'var(--surface)',
            color: activeFilterCount > 0 ? 'var(--em-400)' : 'var(--text-2)',
            border: `1px solid ${activeFilterCount > 0 ? 'var(--em-tint-2)' : 'var(--hairline)'}`,
          }}>
            Фильтры
            {activeFilterCount > 0 && (
              <span className="mono" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: '50%', background: 'var(--em-500)', color: '#fff', fontSize: 10, fontWeight: 700 }}>{activeFilterCount}</span>
            )}
            <ChevronDown size={14} style={{ transform: filtersOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
          </button>
        </div>

        {/* Filters panel */}
        {filtersOpen && (
          <div className="card" style={{ padding: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {[
                { label: 'Трейдер', val: trader, set: setTrader, opts: filterOptions?.traders },
                { label: 'Метод', val: method, set: setMethod, opts: filterOptions?.methods },
                { label: 'Банк', val: bank, set: setBank, opts: filterOptions?.banks },
                { label: 'ТЛ', val: tla, set: setTla, opts: filterOptions?.tlas },
                { label: 'ХТЛ', val: htl, set: setHtl, opts: filterOptions?.htls },
                { label: 'Агент', val: agent, set: setAgent, opts: filterOptions?.agents },
              ].map(f => (
                <div key={f.label}>
                  <div className="eyebrow" style={{ marginBottom: 4 }}>{f.label}</div>
                  <select value={f.val} onChange={e => f.set(e.target.value)} style={inputStyle}>
                    <option value="">Все</option>
                    {f.opts?.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
              ))}
              <div style={{ gridColumn: '1 / -1' }}>
                <div className="eyebrow" style={{ marginBottom: 4 }}>Мерчант</div>
                <select value={merchant} onChange={e => setMerchant(e.target.value)} style={inputStyle}>
                  <option value="">Все</option>
                  {filterOptions?.merchants.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button onClick={handleApplyFilters} className="press" style={{
                flex: 1, padding: '10px 16px', borderRadius: 'var(--r-md)', fontSize: 13, fontWeight: 600,
                background: 'var(--em-500)', color: '#fff', border: 'none',
              }}>Применить</button>
              {activeFilterCount > 0 && (
                <button onClick={() => {
                  setTrader(''); setMethod(''); setBank(''); setTla(''); setHtl(''); setAgent(''); setMerchant('')
                  setAppliedTrader(''); setAppliedMethod(''); setAppliedBank(''); setAppliedTla(''); setAppliedHtl(''); setAppliedAgent(''); setAppliedMerchant('')
                  setFiltersOpen(false)
                }} className="press" style={{
                  display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderRadius: 'var(--r-md)', fontSize: 13, fontWeight: 600,
                  background: 'var(--surface)', color: 'var(--text-3)', border: '1px solid var(--hairline)',
                }}>
                  <RotateCcw size={13} /> Сброс
                </button>
              )}
            </div>
          </div>
        )}

        {loading && <SkeletonDashboard />}
        {error && !loading && <div style={{ fontSize: 14, color: 'var(--danger)', textAlign: 'center', padding: '32px 0' }}>{error}</div>}

        {!loading && !error && kpi && (
          <>
            {/* Summary stats row */}
            <div className="card rise" style={{ display: 'flex', overflow: 'hidden' }}>
              <StatBlock label="Конверсия" value={fmtPct(kpi.conversion_success)} sub="в успех" accent />
              <StatBlock label="Объём" value={fmtAmount(kpi.amount_payin)} sub="payin" />
              <div style={{ flex: 1, padding: '10px 14px' }}>
                <div className="eyebrow" style={{ marginBottom: 4 }}>Сделок</div>
                <div className="mono num" style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.02em' }}>{fmt(kpi.total_payin)}</div>
                <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{fmt(kpi.count_successful)} ok</div>
              </div>
            </div>

            {/* Conversion circles */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }} className="rise rise-1">
              <div className="card" style={{ padding: 14, textAlign: 'center' }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>Конверсия в успех</div>
                <CircularProgress value={kpi.conversion_success ?? 0} />
              </div>
              <div className="card" style={{ padding: 14, textAlign: 'center' }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>{margin !== null ? 'Маржа' : 'Конв. в выдачу'}</div>
                <CircularProgress value={margin ?? kpi.conversion_issued ?? 0} />
              </div>
            </div>

            {/* KPI grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }} className="rise rise-2">
              <div className="card" style={{ padding: '12px 14px' }}>
                <div className="eyebrow" style={{ marginBottom: 4 }}>Сумма успешных</div>
                <div className="mono num" style={{ fontSize: 18, fontWeight: 600, color: 'var(--em-400)', letterSpacing: '-0.02em' }}>{fmtAmount(kpi.amount_successful)}</div>
              </div>
              <div className="card" style={{ padding: '12px 14px', border: '1px solid rgba(248,113,113,0.22)', background: 'rgba(248,113,113,0.04)' }}>
                <div className="eyebrow" style={{ marginBottom: 4 }}>Не успешных</div>
                <div className="mono num" style={{ fontSize: 18, fontWeight: 600, color: 'var(--danger)', letterSpacing: '-0.02em' }}>{fmt(kpi.count_failed)}</div>
              </div>
            </div>

            {/* Charts */}
            {data.by_methods && data.by_methods.length > 0 && (
              <div className="rise rise-3">
                <EmeraldBarChart title="По методам" data={data.by_methods} nameKey="payment_type" valueKey="total" />
              </div>
            )}
            {data.by_methods && data.by_methods.length > 0 && (
              <div className="rise rise-4">
                <EmeraldPieChart title="Распределение по методам" data={data.by_methods} nameKey="payment_type" valueKey="total" />
              </div>
            )}
            {data.by_banks && data.by_banks.length > 0 && (
              <div className="rise rise-5">
                <EmeraldBarChart title="По банкам" data={data.by_banks} nameKey="bank" valueKey="total" />
              </div>
            )}
            {data.bank_method && data.bank_method.length > 0 && (
              <div className="rise rise-6">
                <CollapsibleSection title="Банк × Метод">
                  <SimpleTable rows={data.bank_method} nameKey="bank" valueKey="total" extraKey="payment_type" extraFmt={v => String(v ?? '\u2014')} />
                </CollapsibleSection>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
