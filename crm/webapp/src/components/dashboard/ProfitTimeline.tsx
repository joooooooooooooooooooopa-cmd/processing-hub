import { memo, useMemo } from 'react'
import { XAxis, YAxis, Tooltip, ResponsiveContainer, Line, Area, ComposedChart } from 'recharts'

function fmtAmount(n: number): string {
  if (Math.abs(n) >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + ' млрд'
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' млн'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + ' тыс'
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

function fmtShort(n: number): string {
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

export default memo(function ProfitTimeline({ data }: { data: Record<string, any>[] }) {
  if (!data || data.length === 0) return null

  const { prepared, total, maxHour } = useMemo(() => {
    const keys = Object.keys(data[0])
    const hourKey = keys.find(k => /час|hour/i.test(k)) || keys[0]
    const profitKey = keys.find(k => /прибыль|profit/i.test(k)) || keys[1]

    const p = data.map(d => ({
      hour: `${d[hourKey]}:00`,
      profit: Number(d[profitKey] ?? 0),
    })).sort((a, b) => parseInt(a.hour) - parseInt(b.hour))

    return {
      prepared: p,
      total: p.reduce((s, d) => s + d.profit, 0),
      maxHour: p.reduce((best, d) => d.profit > best.profit ? d : best, p[0]),
    }
  }, [data])

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Прибыль по часам</h2>
      <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-2xl font-bold text-emerald-400">{fmtAmount(total)}</div>
            <div className="text-[10px] text-gray-500">Итого за период</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-bold text-white">{maxHour.hour}</div>
            <div className="text-[10px] text-gray-500">Пик: {fmtAmount(maxHour.profit)}</div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={prepared} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="profitGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="hour" tick={{ fill: '#9ca3af', fontSize: 9 }} axisLine={false} tickLine={false} interval={3} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={fmtShort} />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 12, color: '#fff', fontSize: 12 }}
              formatter={(v: number | undefined) => [v != null ? fmtAmount(v) : '—', 'Прибыль']}
            />
            <Area type="monotone" dataKey="profit" fill="url(#profitGrad)" stroke="none" />
            <Line type="monotone" dataKey="profit" stroke="#10b981" strokeWidth={2} dot={{ r: 2, fill: '#10b981' }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
})
