import { useMemo } from 'react'

interface HealthScoreProps {
  score: number // 0-100
  size?: number
  showLabel?: boolean
}

function getColor(score: number): string {
  if (score >= 80) return '#10b981' // green
  if (score >= 60) return '#f59e0b' // yellow
  if (score >= 40) return '#f97316' // orange
  return '#ef4444' // red
}

function getLabel(score: number): string {
  if (score >= 80) return 'Отлично'
  if (score >= 60) return 'Хорошо'
  if (score >= 40) return 'Внимание'
  return 'Критично'
}

/** Circular health score indicator */
export default function HealthScore({ score, size = 48, showLabel = false }: HealthScoreProps) {
  const { color, label, offset, circ } = useMemo(() => {
    const clamped = Math.min(Math.max(score, 0), 100)
    const stroke = size < 40 ? 3 : 4
    const radius = (size - stroke * 2) / 2
    const c = 2 * Math.PI * radius
    return {
      color: getColor(clamped),
      label: getLabel(clamped),
      offset: c - (clamped / 100) * c,
      circ: c,
      radius,
      stroke,
    }
  }, [score, size])

  const stroke = size < 40 ? 3 : 4
  const radius = (size - stroke * 2) / 2

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="block">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.05)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          className="health-ring"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ filter: `drop-shadow(0 0 4px ${color}40)` }}
        />
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="central"
          fill={color}
          style={{ fontSize: size < 40 ? 10 : 13, fontWeight: 700 }}
        >
          {Math.round(score)}
        </text>
      </svg>
      {showLabel && (
        <span className="text-[10px] font-medium" style={{ color }}>
          {label}
        </span>
      )}
    </div>
  )
}

/** Calculate health score from merchant metrics */
export function calculateHealthScore(data: {
  conversion?: number | null
  volume?: number
  incidents?: number
  mood?: string
}): number {
  let score = 50 // base

  // Conversion impact (0-35 points)
  if (data.conversion != null) {
    if (data.conversion >= 60) score += 35
    else if (data.conversion >= 40) score += 25
    else if (data.conversion >= 20) score += 15
    else score += 5
  }

  // Volume impact (0-15 points)
  if (data.volume != null) {
    if (data.volume > 100) score += 15
    else if (data.volume > 50) score += 10
    else if (data.volume > 10) score += 5
  }

  // Incidents penalty (-30 max)
  if (data.incidents != null) {
    score -= Math.min(data.incidents * 10, 30)
  }

  // Mood impact
  if (data.mood === 'loyal') score += 10
  else if (data.mood === 'aggressive') score -= 15
  else if (data.mood === 'difficult') score -= 10

  return Math.min(Math.max(score, 0), 100)
}
