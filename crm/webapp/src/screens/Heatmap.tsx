import { useEffect, useState, useCallback } from 'react'
import { Grid3X3, Flame } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import Spinner from '../components/Spinner'
import { api } from '../api/client'
import { fmt } from '../utils/format'

// ── Constants ───────────────────────────────────────────────────────────────

const DAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const HOURS = Array.from({ length: 24 }, (_, i) => i)
const DAYS_OPTIONS = [
  { value: 7, label: '7 дней' },
  { value: 14, label: '14 дней' },
  { value: 30, label: '30 дней' },
] as const

// ── Color interpolation ────────────────────────────────────────────────────

function cellStyle(value: number, max: number): React.CSSProperties {
  if (max === 0 || value === 0) {
    return {
      backgroundColor: 'rgba(16, 185, 129, 0.03)',
      border: '1px solid rgba(16, 185, 129, 0.04)',
    }
  }
  const intensity = value / max
  // Multi-stop gradient: low = dark emerald, mid = emerald, high = bright with glow
  if (intensity < 0.25) {
    return {
      backgroundColor: `rgba(16, 185, 129, ${(0.06 + intensity * 0.36).toFixed(2)})`,
      border: '1px solid rgba(16, 185, 129, 0.06)',
    }
  }
  if (intensity < 0.6) {
    return {
      backgroundColor: `rgba(16, 185, 129, ${(0.15 + intensity * 0.45).toFixed(2)})`,
      border: '1px solid rgba(16, 185, 129, 0.1)',
    }
  }
  // Hot cells get a glow
  return {
    backgroundColor: `rgba(16, 185, 129, ${(0.4 + intensity * 0.5).toFixed(2)})`,
    border: '1px solid rgba(52, 211, 153, 0.3)',
    boxShadow: `0 0 ${Math.round(intensity * 12)}px rgba(16, 185, 129, ${(intensity * 0.4).toFixed(2)})`,
  }
}

// ── Main ────────────────────────────────────────────────────────────────────

export default function Heatmap() {
  const [days, setDays] = useState<number>(7)
  const [grid, setGrid] = useState<number[][] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tooltip, setTooltip] = useState<{ day: number; hour: number; value: number; x: number; y: number } | null>(null)

  const load = useCallback(async (d: number) => {
    setLoading(true); setError(''); setGrid(null)
    try {
      const result = await api.analytics.heatmap(d)
      const matrix: number[][] = Array.isArray(result)
        ? result
        : result.grid || result.data || result.heatmap || []
      // Ensure 7x24
      const normalized: number[][] = DAY_LABELS.map((_, dayIdx) => {
        const row = matrix[dayIdx] || []
        return HOURS.map(h => Number(row[h] ?? 0))
      })
      setGrid(normalized)
    } catch (e: any) {
      setError(e.message || 'Ошибка')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(days) }, [days, load])

  const maxVal = grid ? Math.max(1, ...grid.flat()) : 1
  const totalOrders = grid ? grid.flat().reduce((s, v) => s + v, 0) : 0

  // Peak hour/day
  let peakDay = 0, peakHour = 0, peakVal = 0
  if (grid) {
    grid.forEach((row, d) => row.forEach((v, h) => {
      if (v > peakVal) { peakVal = v; peakDay = d; peakHour = h }
    }))
  }

  function handleCellTouch(e: React.TouchEvent | React.MouseEvent, day: number, hour: number, value: number) {
    const rect = (e.target as HTMLElement).getBoundingClientRect()
    setTooltip({ day, hour, value, x: rect.left + rect.width / 2, y: rect.top - 8 })
  }

  return (
    <div className="pb-24 space-y-5 bg-bg min-h-screen">
      <AppHeader title="Тепловая карта" />
      <div className="px-4 space-y-4">

        {/* Header card */}
        <div className="flex items-center gap-3 rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(16, 185, 129, 0.02))',
            border: '1px solid rgba(16, 185, 129, 0.12)',
          }}
        >
          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(16, 185, 129, 0.15)', boxShadow: '0 0 16px rgba(16, 185, 129, 0.15)' }}
          >
            <Grid3X3 size={20} className="text-em-400" />
          </div>
          <div>
            <div className="text-sm font-semibold text-text-1">Активность по часам</div>
            <div className="text-[11px] text-text-3">Распределение заявок по дням недели и часам</div>
          </div>
        </div>

        {/* Days selector pills */}
        <div className="flex gap-2 p-1 rounded-xl"
          style={{ background: 'rgba(13, 17, 23, 0.6)', border: '1px solid rgba(16, 185, 129, 0.06)' }}
        >
          {DAYS_OPTIONS.map(d => (
            <button
              key={d.value}
              onClick={() => setDays(d.value)}
              className="flex-1 py-2 rounded-lg text-xs font-semibold transition-all duration-200"
              style={{
                background: days === d.value
                  ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.1))'
                  : 'transparent',
                color: days === d.value ? '#34d399' : '#6b7280',
                boxShadow: days === d.value ? '0 0 10px rgba(16, 185, 129, 0.1)' : 'none',
              }}
            >
              {d.label}
            </button>
          ))}
        </div>

        {loading && (
          <div className="flex flex-col items-center gap-3 py-12">
            <Spinner size={28} />
            <span className="text-xs text-text-3">Загружаю карту...</span>
          </div>
        )}

        {error && (
          <div className="rounded-2xl bg-danger/8 border border-danger/20 p-4 text-center">
            <span className="text-xs text-danger">{error}</span>
          </div>
        )}

        {/* Summary stats */}
        {!loading && grid && (
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-xl p-3 text-center"
              style={{ background: 'linear-gradient(135deg, #0d1117, #0a0f14)', border: '1px solid rgba(16, 185, 129, 0.08)' }}
            >
              <div className="text-[10px] text-text-3 uppercase tracking-wider">Всего</div>
              <div className="text-base font-bold text-text-1 mt-0.5">{fmt(totalOrders)}</div>
            </div>
            <div className="rounded-xl p-3 text-center"
              style={{ background: 'linear-gradient(135deg, #0d1117, #0a0f14)', border: '1px solid rgba(16, 185, 129, 0.08)' }}
            >
              <div className="text-[10px] text-text-3 uppercase tracking-wider">Пик</div>
              <div className="text-base font-bold text-em-400 mt-0.5">{fmt(peakVal)}</div>
            </div>
            <div className="rounded-xl p-3 text-center"
              style={{ background: 'linear-gradient(135deg, #0d1117, #0a0f14)', border: '1px solid rgba(16, 185, 129, 0.08)' }}
            >
              <div className="text-[10px] text-text-3 uppercase tracking-wider flex items-center justify-center gap-1">
                <Flame size={10} className="text-orange-400" /> Горячо
              </div>
              <div className="text-base font-bold text-orange-400 mt-0.5">
                {DAY_LABELS[peakDay]} {String(peakHour).padStart(2, '0')}:00
              </div>
            </div>
          </div>
        )}

        {/* Heatmap grid */}
        {!loading && grid && (
          <div className="rounded-2xl overflow-hidden p-3 pt-2"
            style={{ background: 'linear-gradient(180deg, #0d1117, #0a0f14)', border: '1px solid rgba(16, 185, 129, 0.08)' }}
          >
            {/* Hour labels */}
            <div className="flex ml-8 mb-1.5">
              {HOURS.map(h => (
                <div
                  key={h}
                  className="text-center font-mono flex-shrink-0"
                  style={{ width: 'calc(100% / 24)', minWidth: 12, fontSize: 8, color: h % 3 === 0 ? '#6b7280' : 'transparent' }}
                >
                  {h % 3 === 0 ? String(h).padStart(2, '0') : '.'}
                </div>
              ))}
            </div>

            {/* Grid rows */}
            {grid.map((row, dayIdx) => (
              <div key={dayIdx} className="flex items-center gap-1 mb-[3px]">
                <span className="w-7 text-right flex-shrink-0 font-semibold"
                  style={{ fontSize: 10, color: dayIdx >= 5 ? '#f59e0b' : '#6b7280' }}
                >
                  {DAY_LABELS[dayIdx]}
                </span>
                <div className="flex flex-1 gap-[2px]">
                  {row.map((val, hourIdx) => (
                    <div
                      key={hourIdx}
                      className="rounded-[3px] cursor-pointer transition-all duration-150 hover:scale-[1.3] hover:z-10"
                      style={{
                        flex: 1,
                        minWidth: 10,
                        height: 24,
                        ...cellStyle(val, maxVal),
                      }}
                      onMouseEnter={e => handleCellTouch(e, dayIdx, hourIdx, val)}
                      onMouseLeave={() => setTooltip(null)}
                      onTouchStart={e => handleCellTouch(e, dayIdx, hourIdx, val)}
                      onTouchEnd={() => setTooltip(null)}
                    />
                  ))}
                </div>
              </div>
            ))}

            {/* Legend */}
            <div className="flex items-center justify-between mt-3 px-1">
              <span style={{ fontSize: 9 }} className="text-text-3">Меньше</span>
              <div className="flex gap-[3px]">
                {[0, 0.15, 0.3, 0.5, 0.7, 0.9].map((intensity, i) => (
                  <div
                    key={i}
                    className="rounded-[2px]"
                    style={{
                      width: 14,
                      height: 14,
                      ...cellStyle(intensity * maxVal, maxVal),
                    }}
                  />
                ))}
              </div>
              <span style={{ fontSize: 9 }} className="text-text-3">Больше</span>
            </div>
          </div>
        )}

        {/* Tooltip */}
        {tooltip && (
          <div
            className="fixed z-50 pointer-events-none px-3 py-2 rounded-xl shadow-xl"
            style={{
              left: tooltip.x,
              top: tooltip.y,
              transform: 'translate(-50%, -100%)',
              background: 'rgba(13, 17, 23, 0.95)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
              backdropFilter: 'blur(12px)',
              boxShadow: '0 8px 32px rgba(0,0,0,0.4), 0 0 12px rgba(16, 185, 129, 0.1)',
            }}
          >
            <div className="flex items-center gap-2">
              <span className="text-em-400 font-semibold text-xs">{DAY_LABELS[tooltip.day]}</span>
              <span className="text-text-3 text-xs font-mono">{String(tooltip.hour).padStart(2, '0')}:00</span>
            </div>
            <div className="text-text-1 font-bold text-sm font-mono mt-0.5">
              {fmt(tooltip.value)} <span className="text-text-3 font-normal text-[10px]">заявок</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
