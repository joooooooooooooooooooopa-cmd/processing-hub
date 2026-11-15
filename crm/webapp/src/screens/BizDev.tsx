import { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client'
import type { BizDevDashboardData } from '../types'
import Spinner from '../components/Spinner'
import AppHeader from '../components/AppHeader'
import EmeraldLineChart from '../components/charts/EmeraldLineChart'
import EmeraldPieChart from '../components/charts/EmeraldPieChart'
import { fmt, fmtAmount } from '../utils/format'

// ── KpiCard ───────────────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  accent,
  sub,
}: {
  label: string
  value: string
  accent?: boolean
  sub?: string
}) {
  return (
    <div className="bg-surface border border-em-500/10 rounded-2xl p-4 flex flex-col gap-1">
      <div className="text-xs text-text-3 uppercase tracking-wider">
        {label}
      </div>
      <div
        className={`text-2xl font-bold leading-tight ${
          accent ? 'text-em-400' : 'text-text-1'
        }`}
      >
        {value}
      </div>
      {sub && (
        <div className="text-xs text-text-3">
          {sub}
        </div>
      )}
    </div>
  )
}

// ── SimpleTable ───────────────────────────────────────────────────────────────

function SimpleTable({
  title,
  rows,
  columns,
}: {
  title: string
  rows: Record<string, any>[]
  columns: { key: string; label: string; format?: (v: any) => string }[]
}) {
  if (!rows || rows.length === 0) return null

  return (
    <div>
      <div className="bg-surface border border-em-500/10 rounded-2xl overflow-hidden">
        <div className="p-3 text-sm font-semibold text-text-1 border-b border-em-500/10">
          {title}
        </div>
        {/* Header row */}
        <div className="flex items-center px-3 py-2 text-xs uppercase tracking-wider bg-em-500/10 text-em-400 gap-2">
          <span className="w-5 text-center flex-shrink-0">#</span>
          {columns.map((col, j) => (
            <span
              key={j}
              className={j === 0 ? 'flex-1 truncate' : 'text-xs flex-shrink-0 min-w-[48px] text-right'}
            >
              {col.label}
            </span>
          ))}
        </div>
        {rows.map((row, i) => (
          <div
            key={i}
            className={`flex items-center px-3 py-2 text-sm gap-2 ${
              i % 2 === 0 ? 'bg-transparent' : 'bg-surface/30'
            }`}
          >
            <span className={`text-xs w-5 text-center flex-shrink-0 font-bold ${i < 3 ? 'text-em-400' : 'text-text-3'}`}>
              {i + 1}
            </span>
            {columns.map((col, j) => {
              const val = row[col.key]
              const formatted = col.format ? col.format(val) : String(val ?? '—')
              return (
                <span
                  key={j}
                  className={
                    j === 0
                      ? 'flex-1 truncate font-medium text-text-1'
                      : 'text-xs flex-shrink-0 min-w-[48px] text-right font-mono text-text-1'
                  }
                >
                  {formatted}
                </span>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function BizDev() {
  const getTodayMSK = () => {
    const now = new Date()
    const mskTime = new Date(now.getTime() + (3 * 3600000))
    const year = mskTime.getUTCFullYear()
    const month = String(mskTime.getUTCMonth() + 1).padStart(2, '0')
    const day = String(mskTime.getUTCDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  const [period, setPeriod] = useState(getTodayMSK())
  const [data, setData] = useState<BizDevDashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback((p: string) => {
    setLoading(true)
    setError('')
    api.analytics
      .bizdevDashboard({ period: p })
      .then(setData)
      .catch(e => setError(e.message || 'Ошибка загрузки'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load(period)
  }, [period, load])

  const kpi = data?.kpi

  return (
    <div className="pb-24 space-y-4" style={{ background: 'var(--bg)', minHeight: '100vh' }}>
      <AppHeader title="БизДев" />
      <div className="px-4 space-y-4">

      {/* Period input */}
      <div>
        <input
          type="date"
          value={period}
          onChange={e => setPeriod(e.target.value)}
          className="w-full rounded-xl px-3 py-2 text-sm bg-surface-2 text-text-1 border border-em-500/10 outline-none focus:ring-2 focus:ring-emerald-500/50"
        />
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Spinner size={28} />
        </div>
      )}

      {error && !loading && (
        <div className="text-sm text-danger">
          {error}
        </div>
      )}

      {!loading && !error && kpi && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-3 gap-2">
            <KpiCard label="Общая обработка" value={fmt(kpi.total_processed)} />
            <KpiCard label="Общая прибыль" value={fmtAmount(kpi.total_profit)} accent sub="RUB" />
            <KpiCard label="Провайдеров" value={fmt(kpi.providers_count)} />
          </div>

          {/* Hourly chart */}
          {data.hourly_issued && data.hourly_issued.length > 0 && (
            <EmeraldLineChart
              title="Выданные реки по часам"
              data={data.hourly_issued}
              nameKey="hour"
              valueKey="issued_count"
            />
          )}

          {/* Pie charts */}
          <div className="grid grid-cols-2 gap-3">
            {data.methods_pie_count && data.methods_pie_count.length > 0 && (
              <EmeraldPieChart
                title="По методам: кол-во"
                data={data.methods_pie_count}
                nameKey="method"
                valueKey="count"
              />
            )}

            {data.methods_pie_profit && data.methods_pie_profit.length > 0 && (
              <EmeraldPieChart
                title="По методам: прибыль"
                data={data.methods_pie_profit}
                nameKey="method"
                valueKey="profit"
              />
            )}
          </div>

          {/* Providers table */}
          {data.providers_table && data.providers_table.length > 0 && (
            <SimpleTable
              title="Провайдеры"
              rows={data.providers_table}
              columns={[
                { key: 'provider_name', label: 'Провайдер' },
                { key: 'total_transactions', label: 'Всего', format: fmt },
                { key: 'issued', label: 'Выдано', format: fmt },
                { key: 'success', label: 'Успех', format: fmt },
                { key: 'total_issued', label: 'Сумма выд.', format: fmtAmount },
                { key: 'total_success', label: 'Сумма усп.', format: fmtAmount },
                { key: 'profit', label: 'Прибыль', format: fmtAmount },
              ]}
            />
          )}
        </>
      )}
      </div>
    </div>
  )
}
