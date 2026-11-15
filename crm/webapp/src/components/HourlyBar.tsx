import type { HourlyRow } from '../types'

export default function HourlyBar({ data }: { data: HourlyRow[] }) {
  if (!data.length) return null

  const maxOrders = Math.max(...data.map(r => r.orders), 1)
  const H = 80

  return (
    <div className="flex items-end gap-0.5 h-24 w-full">
      {data.map(row => {
        const barH = Math.max(4, (row.orders / maxOrders) * H)
        const successH = Math.max(0, (row.successful / maxOrders) * H)
        return (
          <div key={row.hour} className="flex-1 flex flex-col items-center gap-0.5">
            <div className="w-full flex flex-col-reverse" style={{ height: H }}>
              <div
                className="w-full rounded-sm"
                style={{
                  height: barH,
                  background: 'rgba(107,114,128,0.2)',
                  position: 'relative',
                }}
              >
                <div
                  className="w-full rounded-sm absolute bottom-0"
                  style={{
                    height: successH,
                    background: 'linear-gradient(180deg, #34d399, #059669)',
                    boxShadow: successH > 4 ? '0 0 6px rgba(16,185,129,0.3)' : 'none',
                  }}
                />
              </div>
            </div>
            <span
              className="leading-none"
              style={{ color: '#9ca3af', fontSize: 9 }}
            >
              {row.hour}
            </span>
          </div>
        )
      })}
    </div>
  )
}
