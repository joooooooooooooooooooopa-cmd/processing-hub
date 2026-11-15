import type { IncidentPriority } from '../types'

const MAP: Record<IncidentPriority, { color: string; bg: string; border: string }> = {
  P0: { color: '#f87171', bg: 'rgba(239,68,68,0.2)',   border: 'rgba(239,68,68,0.35)' },
  P1: { color: '#fb923c', bg: 'rgba(249,115,22,0.2)',  border: 'rgba(249,115,22,0.35)' },
  P2: { color: '#fbbf24', bg: 'rgba(245,158,11,0.2)',  border: 'rgba(245,158,11,0.35)' },
  P3: { color: '#9ca3af', bg: 'rgba(107,114,128,0.2)', border: 'rgba(107,114,128,0.35)' },
}

export default function PriorityBadge({ priority }: { priority: IncidentPriority }) {
  const info = MAP[priority] ?? { color: '#9ca3af', bg: 'rgba(107,114,128,0.2)', border: 'rgba(107,114,128,0.35)' }
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-xs font-bold transition-colors duration-200"
      style={{
        color: info.color,
        background: info.bg,
        border: `1px solid ${info.border}`,
      }}
    >
      {priority}
    </span>
  )
}
