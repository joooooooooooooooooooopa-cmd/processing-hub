import type { MerchantStatus } from '../types'

const MAP: Record<MerchantStatus, { label: string; color: string; bg: string; border: string }> = {
  new:          { label: 'Новый',        color: '#9ca3af', bg: 'rgba(107,114,128,0.15)', border: 'rgba(107,114,128,0.3)' },
  negotiation:  { label: 'Переговоры',   color: '#60a5fa', bg: 'rgba(59,130,246,0.15)',  border: 'rgba(59,130,246,0.3)' },
  integration:  { label: 'Интеграция',   color: '#a78bfa', bg: 'rgba(139,92,246,0.15)',  border: 'rgba(139,92,246,0.3)' },
  testing:      { label: 'Тестирование', color: '#fbbf24', bg: 'rgba(245,158,11,0.15)',  border: 'rgba(245,158,11,0.3)' },
  active:       { label: 'Активный',     color: '#10b981', bg: 'rgba(16,185,129,0.15)',  border: 'rgba(16,185,129,0.3)' },
  paused:       { label: 'Пауза',        color: '#9ca3af', bg: 'rgba(107,114,128,0.15)', border: 'rgba(107,114,128,0.3)' },
  problem:      { label: 'Проблема',     color: '#f87171', bg: 'rgba(239,68,68,0.15)',   border: 'rgba(239,68,68,0.3)' },
  disconnected: { label: 'Отключён',     color: '#6b7280', bg: 'rgba(55,65,81,0.2)',     border: 'rgba(55,65,81,0.4)' },
}

export default function StatusBadge({ status }: { status: MerchantStatus }) {
  const info = MAP[status] ?? { label: status, color: '#9ca3af', bg: 'rgba(107,114,128,0.15)', border: 'rgba(107,114,128,0.3)' }
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors duration-200"
      style={{
        color: info.color,
        background: info.bg,
        border: `1px solid ${info.border}`,
      }}
    >
      {info.label}
    </span>
  )
}
