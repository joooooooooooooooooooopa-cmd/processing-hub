import {
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Area,
  ComposedChart,
} from 'recharts'

const EMERALD = '#10b981'

function fmtShort(n: number): string {
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

export default function EmeraldLineChart({
  title,
  data,
  nameKey,
  valueKey,
  height = 220,
}: {
  title: string
  data: Record<string, any>[]
  nameKey: string
  valueKey: string
  height?: number
}) {
  if (!data || data.length === 0) return null

  const keys = Object.keys(data[0] || {})
  const nk = nameKey in data[0] ? nameKey : keys[0]
  const vk =
    valueKey in data[0] && valueKey !== nk
      ? valueKey
      : (keys.find(k => k !== nk) ?? keys[1])

  const prepared = data.map(item => ({
    name: String(item[nk] ?? '—'),
    value: parseFloat(item[vk]) || 0,
  }))

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">{title}</h2>
      <div className="bg-[#0d1117] border border-emerald-500/10 rounded-2xl p-3">
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart
            data={prepared}
            margin={{ top: 4, right: 4, left: -12, bottom: 0 }}
          >
            <defs>
              <linearGradient id="emeraldFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={EMERALD} stopOpacity={0.3} />
                <stop offset="100%" stopColor={EMERALD} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="name"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#9ca3af', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={fmtShort}
            />
            <Tooltip
              contentStyle={{
                background: '#111827',
                border: '1px solid rgba(16,185,129,0.2)',
                borderRadius: 12,
                color: '#fff',
                fontSize: 12,
              }}
              formatter={(v: number | undefined) => [v != null ? v.toLocaleString('ru-RU') : '—', '']}
              cursor={{ stroke: 'rgba(16,185,129,0.3)' }}
            />
            <Area
              type="monotone"
              dataKey="value"
              fill="url(#emeraldFill)"
              stroke="none"
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={EMERALD}
              strokeWidth={2}
              dot={{ r: 3, fill: EMERALD, stroke: '#0d1117', strokeWidth: 2 }}
              activeDot={{ r: 5, fill: EMERALD }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
