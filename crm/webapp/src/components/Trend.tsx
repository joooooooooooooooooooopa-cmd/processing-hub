interface Props {
  current: number | null
  previous: number | null
  size?: number
}

export default function Trend({ current, previous, size = 11 }: Props) {
  if (current == null || previous == null || previous === 0) return null
  const delta = ((current - previous) / Math.abs(previous)) * 100
  const positive = delta > 0
  const flat = Math.abs(delta) < 0.5
  const color = flat ? 'var(--text-3)' : positive ? 'var(--em-400)' : 'var(--danger)'

  return (
    <span className="mono" style={{ fontSize: size, fontWeight: 600, color, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
      {!flat && <span style={{ fontSize: size - 2 }}>{positive ? '\u25B2' : '\u25BC'}</span>}
      {flat ? '0%' : `${Math.abs(delta).toFixed(1)}%`}
    </span>
  )
}
