import { memo, useState, useMemo } from 'react'
import { parseMerchantKeys, parseMerchantRows } from '../../utils/merchantData'

function fmt(n: number): string {
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

function fmtAmount(n: number): string {
  if (Math.abs(n) >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + ' млрд'
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' млн'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + ' тыс'
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

export default memo(function MerchantCompare({
  data,
  merchants,
}: {
  data: Record<string, any>[]
  merchants: string[]
}) {
  const [selected, setSelected] = useState<string[]>([])

  const keys = useMemo(() => parseMerchantKeys(data), [data])
  const parsed = useMemo(() => parseMerchantRows(data, keys), [data, keys])

  if (!data || data.length === 0 || merchants.length < 2) return null

  const toggleMerchant = (name: string) => {
    setSelected(prev =>
      prev.includes(name)
        ? prev.filter(n => n !== name)
        : prev.length >= 3 ? prev : [...prev, name]
    )
  }

  const compared = parsed.filter(m => selected.includes(m.name))
  const maxAmount = Math.max(...compared.map(c => c.amount), 1)

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Сравнение мерчантов</h2>
      <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl p-4 space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {parsed.slice(0, 15).map(m => (
            <button
              key={m.name}
              onClick={() => toggleMerchant(m.name)}
              className={`px-2 py-1 rounded-lg text-[10px] font-medium transition-all ${
                selected.includes(m.name)
                  ? 'bg-emerald-500 text-white shadow-[0_0_8px_rgba(16,185,129,0.3)]'
                  : 'bg-[#111827] text-gray-400 border border-emerald-500/10'
              }`}
            >
              {m.name}
            </button>
          ))}
        </div>
        <div className="text-[10px] text-gray-600">Выберите 2-3 мерчанта для сравнения</div>

        {compared.length >= 2 && (
          <div className="space-y-2 pt-2 border-t border-emerald-500/5">
            {compared.map(m => (
              <div key={m.name} className="bg-[#111827] rounded-xl p-3 space-y-2">
                <div className="text-sm font-bold text-white truncate">{m.name}</div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-[10px] text-gray-500">Конверсия</div>
                    <div className="text-sm font-bold text-emerald-400">{m.conv.toFixed(1)}%</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500">Транзакций</div>
                    <div className="text-sm font-bold text-white">{fmt(m.total)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500">Оборот</div>
                    <div className="text-sm font-bold text-white">{fmtAmount(m.amount)}</div>
                  </div>
                </div>
                <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: '#1e293b' }}>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(m.amount / maxAmount * 100)}%`,
                      background: 'linear-gradient(90deg, #10b981, #34d399)',
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
})
