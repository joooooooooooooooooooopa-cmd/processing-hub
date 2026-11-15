import { memo, useMemo } from 'react'

function fmt(n: number): string {
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

function SlaGauge({ label, value, target, unit }: {
  label: string; value: number; target: number; unit: string
}) {
  const pct = Math.min((value / target) * 100, 100)
  const isMet = value >= target
  const color = isMet ? '#10b981' : value >= target * 0.7 ? '#fbbf24' : '#ef4444'
  const radius = 40
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (pct / 100) * circumference

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="96" height="96" className="-rotate-90" style={{ filter: `drop-shadow(0 0 6px ${color}44)` }}>
        <circle cx="48" cy="48" r={radius} fill="none" stroke="#111827" strokeWidth="6" />
        <circle
          cx="48" cy="48" r={radius} fill="none" stroke={color} strokeWidth="6"
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-1000"
        />
      </svg>
      <div className="text-center -mt-16 mb-6">
        <div className="text-sm font-bold" style={{ color }}>{pct.toFixed(0)}%</div>
        <div className="text-[9px] text-gray-400">{fmt(value)}{unit}</div>
      </div>
      <div className="text-[10px] text-gray-400 text-center">{label}</div>
      <div className="text-[9px] text-gray-600">цель: {fmt(target)}{unit}</div>
    </div>
  )
}

export default memo(function SLAMonitor({ kpi, yesterdayKpi }: {
  kpi: Record<string, any>
  yesterdayKpi?: Record<string, any> | null
}) {
  const total = Number(kpi.total ?? 0)
  const successful = Number(kpi.successful ?? 0)
  const conv = Number(kpi.conversion_pct ?? 0)

  const yTotal = Number(yesterdayKpi?.total ?? 0)
  const ySuccessful = Number(yesterdayKpi?.successful ?? 0)

  const convTarget = useMemo(() => {
    if (conv < 5) return 5
    if (conv < 20) return 20
    return 50
  }, [conv])

  const targets = useMemo(() => [
    { label: 'Цель конверсии', value: conv, target: convTarget, unit: '%' },
    { label: 'Успешных оплат', value: successful, target: ySuccessful > 0 ? ySuccessful : 1000, unit: '' },
    { label: 'Объём заявок', value: total, target: yTotal > 0 ? yTotal : 2000, unit: '' },
  ], [conv, convTarget, successful, total, ySuccessful, yTotal])

  if (total === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">SLA Мониторинг</h2>
      <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl p-4">
        <div className="flex justify-around">
          {targets.map(t => (
            <SlaGauge key={t.label} {...t} />
          ))}
        </div>
      </div>
    </div>
  )
})
