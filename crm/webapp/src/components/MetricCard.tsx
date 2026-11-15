interface Props {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}

export default function MetricCard({ label, value, sub, accent }: Props) {
  return (
    <div
      className="rounded-2xl p-4 flex flex-col gap-1 transition-all duration-200"
      style={{
        background: 'rgba(13,17,23,0.8)',
        border: '1px solid rgba(16,185,129,0.1)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = '0 0 15px rgba(16,185,129,0.15)'
        e.currentTarget.style.borderColor = 'rgba(16,185,129,0.25)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.borderColor = 'rgba(16,185,129,0.1)'
      }}
    >
      {/* Subtle accent bar */}
      {accent && (
        <div
          style={{
            width: 24,
            height: 3,
            borderRadius: 2,
            background: 'linear-gradient(90deg, #10b981, #059669)',
            marginBottom: 4,
          }}
        />
      )}
      <span className="text-xs" style={{ color: '#9ca3af' }}>
        {label}
      </span>
      <span
        className="text-2xl font-bold leading-none"
        style={{ color: accent ? '#34d399' : '#f0fdf4' }}
      >
        {value}
      </span>
      {sub && (
        <span className="text-xs" style={{ color: '#9ca3af' }}>
          {sub}
        </span>
      )}
    </div>
  )
}
