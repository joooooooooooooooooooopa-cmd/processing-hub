import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'

import { fmtShort } from '../../utils/format'

const EMERALD = '#10b981'
const BG = '#0d1117'

export default function EmeraldBarChart({
  title,
  data,
  nameKey,
  valueKey,
  height = 260,
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

  const prepared = data.slice(0, 15).map(item => ({
    name: String(item[nk] ?? '—'),
    value: parseFloat(item[vk]) || 0,
  }))

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">{title}</h2>
      <div
        className="border border-emerald-500/10 rounded-2xl p-3"
        style={{ background: BG }}
      >
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={prepared}
            margin={{ top: 4, right: 4, left: -12, bottom: 0 }}
          >
            <XAxis
              dataKey="name"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              interval={0}
              angle={prepared.length > 8 ? -45 : 0}
              textAnchor={prepared.length > 8 ? 'end' : 'middle'}
              height={prepared.length > 8 ? 60 : 30}
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
              cursor={{ fill: 'rgba(16,185,129,0.08)' }}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={32}>
              {prepared.map((_, i) => (
                <Cell key={i} fill={EMERALD} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
