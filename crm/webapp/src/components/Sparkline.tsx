interface Props {
  data: number[]
  w?: number
  h?: number
  color?: string
  strokeW?: number
  fill?: boolean
}

export default function Sparkline({ data, w = 60, h = 18, color = '#10b981', strokeW = 1.4, fill = true }: Props) {
  if (!data || data.length < 2) return <svg width={w} height={h} />

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const stepX = w / (data.length - 1)
  const pts = data.map((v, i) => [i * stepX, h - 2 - ((v - min) / range) * (h - 4)])
  const path = pts.map((p, i) => (i === 0 ? `M${p[0].toFixed(1)},${p[1].toFixed(1)}` : `L${p[0].toFixed(1)},${p[1].toFixed(1)}`)).join(' ')
  const area = `${path} L${w},${h} L0,${h} Z`
  const id = `spk-${color.replace('#', '')}-${data.length}`

  return (
    <svg width={w} height={h} style={{ overflow: 'visible' }}>
      {fill && (
        <>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${id})`} />
        </>
      )}
      <path d={path} fill="none" stroke={color} strokeWidth={strokeW} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
