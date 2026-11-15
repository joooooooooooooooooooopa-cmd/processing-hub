import { memo, useMemo } from 'react'
import { parseMerchantKeys, parseMerchantRows } from '../../utils/merchantData'

function getGrade(score: number): { grade: string; color: string; bg: string } {
  if (score >= 90) return { grade: 'A', color: '#10b981', bg: 'rgba(16,185,129,0.1)' }
  if (score >= 75) return { grade: 'B', color: '#34d399', bg: 'rgba(52,211,153,0.1)' }
  if (score >= 55) return { grade: 'C', color: '#fbbf24', bg: 'rgba(251,191,36,0.1)' }
  if (score >= 35) return { grade: 'D', color: '#f97316', bg: 'rgba(249,115,22,0.1)' }
  return { grade: 'F', color: '#ef4444', bg: 'rgba(239,68,68,0.1)' }
}

export default memo(function MerchantHealth({ data }: { data: Record<string, any>[] }) {
  if (!data || data.length === 0) return null

  const keys = useMemo(() => parseMerchantKeys(data), [data])
  const parsed = useMemo(() => parseMerchantRows(data, keys).filter(m => m.total >= 5), [data, keys])

  const withScore = useMemo(() => {
    if (parsed.length === 0) return []
    const maxAmount = Math.max(...parsed.map(m => m.amount), 1)
    const maxConv = Math.max(...parsed.map(m => m.conv), 1)

    return parsed.map(m => {
      const convScore = Math.min((m.conv / Math.max(maxConv, 1)) * 100, 100)
      const volScore = Math.min((m.amount / Math.max(maxAmount, 1)) * 100, 100)
      const score = convScore * 0.6 + volScore * 0.4
      return { ...m, score, ...getGrade(score) }
    }).sort((a, b) => b.score - a.score)
  }, [parsed])

  if (withScore.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Здоровье мерчантов</h2>
      <div className="grid grid-cols-3 gap-2">
        {withScore.slice(0, 9).map(m => (
          <div
            key={m.name}
            className="rounded-xl p-2.5 flex flex-col items-center gap-1 border"
            style={{ background: m.bg, borderColor: m.color + '33' }}
          >
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-black"
              style={{ background: m.color + '22', color: m.color, border: `2px solid ${m.color}` }}
            >
              {m.grade}
            </div>
            <div className="text-[10px] text-white font-medium text-center truncate w-full">{m.name}</div>
            <div className="text-[9px] text-gray-500">{m.conv.toFixed(1)}%</div>
          </div>
        ))}
      </div>
    </div>
  )
})
