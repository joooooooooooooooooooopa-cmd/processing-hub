import { useEffect, useState } from 'react'
import { TrendingDown, DollarSign, AlertTriangle, BarChart3, VolumeX, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { Incident, IncidentPriority } from '../types'
import PriorityBadge from '../components/PriorityBadge'
import Spinner from '../components/Spinner'

const SEVERITIES: IncidentPriority[] = ['P0', 'P1', 'P2', 'P3']

const SEVERITY_DOT_COLORS: Record<string, string> = {
  P0: 'bg-danger',
  P1: 'bg-orange-500',
  P2: 'bg-yellow-500',
  P3: 'bg-em-500',
}

const TYPE_ICONS: Record<string, React.ReactNode> = {
  conversion_drop: <TrendingDown size={16} className="text-em-400" />,
  profit_drop: <DollarSign size={16} className="text-em-400" />,
  decline_spike: <AlertTriangle size={16} className="text-em-400" />,
  metric_breach: <BarChart3 size={16} className="text-em-400" />,
}

const SEVERITY_ACTIVE_CLASSES: Record<string, string> = {
  P0: 'bg-danger/20 text-danger shadow-[0_0_12px_rgba(239,68,68,0.3)]',
  P1: 'bg-orange-500/20 text-orange-400 shadow-[0_0_12px_rgba(249,115,22,0.3)]',
  P2: 'bg-yellow-500/20 text-yellow-400 shadow-[0_0_12px_rgba(234,179,8,0.3)]',
  P3: 'bg-em-500/20 text-em-400 shadow-[0_0_12px_rgba(16,185,129,0.3)]',
}

interface Props {
  onSelect: (id: string) => void
}

export default function IncidentList({ onSelect }: Props) {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filterSeverity, setFilterSeverity] = useState('')

  const load = () => {
    setLoading(true)
    api.incidents.list({ status: 'open', limit: 100 })
      .then(r => setIncidents(r.incidents))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const filtered = filterSeverity
    ? incidents.filter(i => i.severity === filterSeverity)
    : incidents

  const formatDate = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleString('ru-RU', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  const formatDelta = (pct?: number) => {
    if (pct === undefined || pct === null) return ''
    const sign = pct > 0 ? '+' : ''
    return `${sign}${pct.toFixed(1)}%`
  }

  return (
    <div className="flex flex-col h-full relative" style={{ background: 'var(--bg)' }}>
      {/* Фильтры */}
      <div className="p-3 sticky top-0 z-10" style={{ background: 'var(--bg)' }}>
        <div className="flex gap-2 overflow-x-auto pb-2">
          <button
            onClick={() => setFilterSeverity('')}
            className={`flex-shrink-0 px-3 py-1 rounded-xl text-xs font-medium transition-all ${
              !filterSeverity
                ? 'bg-em-500 text-text-1 shadow-[0_0_12px_rgba(16,185,129,0.4)]'
                : 'bg-surface-2 text-text-3 border border-em-500/10'
            }`}
          >
            Все ({incidents.length})
          </button>
          {SEVERITIES.map(s => {
            const cnt = incidents.filter(i => i.severity === s).length
            if (cnt === 0) return null
            return (
              <button
                key={s}
                onClick={() => setFilterSeverity(s === filterSeverity ? '' : s)}
                className={`flex-shrink-0 px-3 py-1 rounded-xl text-xs font-medium transition-all flex items-center gap-1.5 ${
                  filterSeverity === s
                    ? SEVERITY_ACTIVE_CLASSES[s]
                    : 'bg-surface-2 text-text-3 border border-em-500/10'
                }`}
              >
                <span className={`inline-block w-2 h-2 rounded-full ${SEVERITY_DOT_COLORS[s]}`} />
                {s} ({cnt})
              </button>
            )
          })}
        </div>
      </div>

      {/* Список */}
      <div className="flex-1 overflow-y-auto px-3 pb-20">
        {loading ? (
          <div className="flex justify-center pt-8"><Spinner size={28} /></div>
        ) : error ? (
          <div className="pt-4 text-danger text-sm">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="pt-8 text-center text-sm text-text-3">
            {filterSeverity ? `Нет инцидентов ${filterSeverity}` : 'Нет открытых инцидентов'}
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map(inc => (
              <button
                key={inc.id}
                onClick={() => onSelect(inc.id)}
                className="w-full text-left rounded-2xl p-4 bg-surface border border-em-500/10 transition-all active:border-em-500/20 active:shadow-[0_0_15px_rgba(16,185,129,0.15)]"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="flex-shrink-0">{TYPE_ICONS[inc.type] || <BarChart3 size={16} className="text-em-400" />}</span>
                  <PriorityBadge priority={inc.severity} />
                  <span className="text-xs text-em-400 uppercase">
                    {inc.scope}
                  </span>
                  {inc.is_muted && (
                    <span className="ml-auto">
                      <VolumeX size={14} className="text-text-3" />
                    </span>
                  )}
                </div>

                <div className="text-sm font-medium mb-1 text-text-1">{inc.title}</div>

                <div className="flex items-center gap-3 text-xs text-text-3">
                  <span>{formatDate(inc.created_at)}</span>
                  {inc.delta_pct !== undefined && inc.delta_pct !== null && (
                    <span className={inc.delta_pct < 0 ? 'text-danger' : 'text-em-400'}>
                      {formatDelta(inc.delta_pct)}
                    </span>
                  )}
                  {inc.dimensions?.merchant_name && (
                    <span className="ml-auto text-text-3">{inc.dimensions.merchant_name}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Refresh button */}
      <button
        onClick={load}
        className="absolute bottom-4 right-4 w-12 h-12 rounded-full text-text-1 shadow-[0_0_15px_rgba(16,185,129,0.4)] flex items-center justify-center bg-em-500 active:bg-emerald-600 transition-all animate-pulse"
        style={{ animationDuration: '3s' }}
      >
        <RefreshCw size={20} />
      </button>
    </div>
  )
}
