import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'

const PALETTE = [
  '#10b981',
  '#34d399',
  '#059669',
  '#6ee7b7',
  '#047857',
  '#a7f3d0',
  '#065f46',
  '#d1fae5',
]

export default function EmeraldPieChart({
  title,
  data,
  nameKey,
  valueKey,
}: {
  title: string
  data: Record<string, any>[]
  nameKey: string
  valueKey: string
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

  const total = prepared.reduce((s, d) => s + d.value, 0)

  return (
    <div>
      <h2 className="text-sm font-semibold mb-2 text-gray-400">{title}</h2>
      <div className="bg-[#0d1117] border border-emerald-500/10 rounded-2xl p-3">
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie
              data={prepared}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={40}
              outerRadius={70}
              paddingAngle={2}
              stroke="none"
            >
              {prepared.map((_, i) => (
                <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>

        {/* Legend */}
        <div className="mt-2 space-y-1">
          {prepared.map((d, i) => {
            const pct = total > 0 ? ((d.value / total) * 100).toFixed(1) : '0'
            return (
              <div key={i} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
                  />
                  <span className="text-white truncate">{d.name}</span>
                </div>
                <span className="text-emerald-400 font-medium">{pct}%</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
