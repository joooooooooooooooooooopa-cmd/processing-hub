import { memo, useMemo } from 'react'
import { parseMerchantKeys, parseMerchantRows } from '../../utils/merchantData'

function fmtAmount(n: number): string {
  if (Math.abs(n) >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + ' млрд'
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' млн'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + ' тыс'
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

const MEDALS = ['🥇', '🥈', '🥉']

export default memo(function MerchantRating({ data, favorites, onToggle }: {
  data: Record<string, any>[]
  favorites: string[]
  onToggle: (name: string) => void
}) {
  if (!data || data.length === 0) return null

  const keys = useMemo(() => parseMerchantKeys(data), [data])
  const parsed = useMemo(() => parseMerchantRows(data, keys), [data, keys])

  const topByAmount = useMemo(() => [...parsed].sort((a, b) => b.amount - a.amount).slice(0, 5), [parsed])
  const bottomByConv = useMemo(
    () => [...parsed].filter(m => m.total >= 10).sort((a, b) => a.conv - b.conv).slice(0, 5),
    [parsed],
  )

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Топ по обороту</h2>
        <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl overflow-hidden">
          {topByAmount.map((m, i) => (
            <div key={m.name} className={`flex items-center justify-between px-4 py-3 ${i > 0 ? 'border-t border-emerald-500/5' : ''}`}>
              <div className="flex items-center gap-3">
                <span className="text-lg w-7 text-center">{i < 3 ? MEDALS[i] : `#${i + 1}`}</span>
                <span className="text-sm text-white font-medium truncate max-w-[130px]">{m.name}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="text-right">
                  <div className="text-sm font-bold text-emerald-400">{fmtAmount(m.amount)}</div>
                  <div className="text-[10px] text-gray-500">{m.conv.toFixed(1)}%</div>
                </div>
                <button onClick={() => onToggle(m.name)} className="text-sm">
                  {favorites.includes(m.name) ? <span className="text-yellow-500">★</span> : <span className="text-gray-600">☆</span>}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {bottomByConv.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Низкая конверсия</h2>
          <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-red-500/10 rounded-2xl overflow-hidden">
            {bottomByConv.map((m, i) => (
              <div key={m.name} className={`flex items-center justify-between px-4 py-3 ${i > 0 ? 'border-t border-red-500/5' : ''}`}>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-red-400 w-7 text-center font-bold">#{i + 1}</span>
                  <span className="text-sm text-white font-medium truncate max-w-[130px]">{m.name}</span>
                </div>
                <div className="text-right">
                  <div className="text-sm font-bold text-red-400">{m.conv.toFixed(1)}%</div>
                  <div className="text-[10px] text-gray-500">{m.successful}/{m.total}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
})
