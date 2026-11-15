import { useEffect, useState } from 'react'
import { Filter, TrendingDown, CheckCircle } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import Spinner from '../components/Spinner'
import { api } from '../api/client'
import { fmt, fmtPct } from '../utils/format'

// ── Types ───────────────────────────────────────────────────────────────────

interface FunnelStage {
  name: string
  count: number
}

const DEFAULT_STAGE_NAMES = ['Заявки', 'С реквизитами', 'В обработке', 'Оплачено']

// ── Stage colors ────────────────────────────────────────────────────────────

const STAGE_COLORS = [
  { from: '#10b981', to: '#34d399', glow: 'rgba(16, 185, 129, 0.3)' },
  { from: '#06b6d4', to: '#22d3ee', glow: 'rgba(6, 182, 212, 0.3)' },
  { from: '#8b5cf6', to: '#a78bfa', glow: 'rgba(139, 92, 246, 0.3)' },
  { from: '#f59e0b', to: '#fbbf24', glow: 'rgba(245, 158, 11, 0.3)' },
  { from: '#ec4899', to: '#f472b6', glow: 'rgba(236, 72, 153, 0.3)' },
  { from: '#6366f1', to: '#818cf8', glow: 'rgba(99, 102, 241, 0.3)' },
]

// ── Main ────────────────────────────────────────────────────────────────────

export default function Funnel() {
  const [stages, setStages] = useState<FunnelStage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.analytics.funnel()
      .then(result => {
        const raw: any[] = Array.isArray(result)
          ? result
          : result.stages || result.funnel || result.data || []
        setStages(raw.map((item, i) => ({
          name: item.name || item.stage || DEFAULT_STAGE_NAMES[i] || `Этап ${i + 1}`,
          count: Number(item.count ?? item.value ?? item.total ?? 0),
        })))
      })
      .catch(e => setError(e.message || 'Ошибка'))
      .finally(() => setLoading(false))
  }, [])

  const maxCount = stages.length > 0 ? Math.max(1, stages[0].count) : 1
  const overallConversion = stages.length >= 2
    ? (stages[stages.length - 1].count / maxCount) * 100
    : 0

  return (
    <div className="pb-24 space-y-5 bg-bg min-h-screen">
      <AppHeader title="Воронка конверсии" />
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
            <Filter size={20} className="text-em-400" />
          </div>
          <div>
            <div className="text-sm font-semibold text-text-1">Воронка статусов</div>
            <div className="text-[11px] text-text-3">Проходимость заявок от создания до оплаты</div>
          </div>
        </div>

        {loading && (
          <div className="flex flex-col items-center gap-3 py-12">
            <Spinner size={28} />
            <span className="text-xs text-text-3">Загружаю воронку...</span>
          </div>
        )}

        {error && (
          <div className="rounded-2xl bg-danger/8 border border-danger/20 p-4 text-center">
            <span className="text-xs text-danger">{error}</span>
          </div>
        )}

        {/* Overall conversion hero */}
        {!loading && stages.length >= 2 && (
          <div className="rounded-2xl p-5 text-center"
            style={{
              background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(16, 185, 129, 0.03))',
              border: '1px solid rgba(16, 185, 129, 0.15)',
              boxShadow: '0 4px 24px rgba(16, 185, 129, 0.08)',
            }}
          >
            <div className="text-[10px] text-text-3 uppercase tracking-wider mb-1">Общая конверсия</div>
            <div className="text-3xl font-bold text-em-400" style={{ textShadow: '0 0 20px rgba(16, 185, 129, 0.4)' }}>
              {fmtPct(overallConversion)}
            </div>
            <div className="text-[11px] text-text-3 mt-1">
              {fmt(stages[0].count)} → {fmt(stages[stages.length - 1].count)}
            </div>
          </div>
        )}

        {/* Funnel stages */}
        {!loading && stages.length > 0 && (
          <div className="space-y-0">
            {stages.map((stage, i) => {
              const widthPct = Math.max(12, (stage.count / maxCount) * 100)
              const pctOfFirst = (stage.count / maxCount) * 100
              const prevCount = i > 0 ? stages[i - 1].count : null
              const dropOff = prevCount && prevCount > 0
                ? ((prevCount - stage.count) / prevCount) * 100
                : null
              const color = STAGE_COLORS[i % STAGE_COLORS.length]

              return (
                <div key={stage.name}>
                  {/* Drop-off indicator between stages */}
                  {i > 0 && dropOff !== null && (
                    <div className="flex items-center justify-center gap-2 py-2">
                      <div className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.04)' }} />
                      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full"
                        style={{
                          background: dropOff > 50 ? 'rgba(239, 68, 68, 0.08)' : 'rgba(255, 255, 255, 0.03)',
                          border: `1px solid ${dropOff > 50 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(255, 255, 255, 0.06)'}`,
                        }}
                      >
                        <TrendingDown size={10} className={dropOff > 50 ? 'text-danger' : 'text-text-3'} />
                        <span className={`text-[10px] font-mono font-semibold ${dropOff > 50 ? 'text-danger' : 'text-text-3'}`}>
                          -{dropOff.toFixed(1)}%
                        </span>
                        <span className="text-[10px] text-text-3">
                          ({fmt(prevCount! - stage.count)})
                        </span>
                      </div>
                      <div className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.04)' }} />
                    </div>
                  )}

                  {/* Stage card */}
                  <div className="rounded-xl p-3.5"
                    style={{
                      background: 'linear-gradient(135deg, rgba(13, 17, 23, 0.8), rgba(13, 17, 23, 0.5))',
                      border: '1px solid rgba(255, 255, 255, 0.04)',
                    }}
                  >
                    {/* Label row */}
                    <div className="flex items-center justify-between mb-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-1.5 h-5 rounded-full" style={{ background: `linear-gradient(180deg, ${color.from}, ${color.to})` }} />
                        <span className="text-xs font-semibold text-text-1">{stage.name}</span>
                        {i === stages.length - 1 && (
                          <CheckCircle size={12} className="text-em-400" />
                        )}
                      </div>
                      <div className="flex items-baseline gap-2">
                        <span className="text-sm font-bold font-mono text-text-1">{fmt(stage.count)}</span>
                        <span className="text-[10px] text-text-3 font-mono">{fmtPct(pctOfFirst)}</span>
                      </div>
                    </div>

                    {/* Funnel bar — centered, trapezoid-like */}
                    <div className="flex justify-center">
                      <div className="relative overflow-hidden rounded-lg"
                        style={{
                          width: `${widthPct}%`,
                          height: 32,
                          transition: 'width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                        }}
                      >
                        {/* Background bar */}
                        <div className="absolute inset-0 rounded-lg"
                          style={{
                            background: `linear-gradient(90deg, ${color.from}, ${color.to})`,
                            boxShadow: `0 0 20px ${color.glow}, inset 0 1px 0 rgba(255,255,255,0.15)`,
                          }}
                        />
                        {/* Shine effect */}
                        <div className="absolute inset-0 rounded-lg"
                          style={{
                            background: 'linear-gradient(180deg, rgba(255,255,255,0.12) 0%, transparent 50%, rgba(0,0,0,0.1) 100%)',
                          }}
                        />
                        {/* Value inside bar */}
                        <div className="absolute inset-0 flex items-center justify-center">
                          <span className="text-[11px] font-bold text-text-1 drop-shadow-sm"
                            style={{ textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}
                          >
                            {fmtPct(pctOfFirst)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* No data */}
        {!loading && !error && stages.length === 0 && (
          <div className="rounded-2xl p-8 text-center" style={{ background: 'rgba(13, 17, 23, 0.5)', border: '1px solid rgba(255,255,255,0.04)' }}>
            <Filter size={24} className="mx-auto text-text-4 mb-2" />
            <p className="text-xs text-text-3">Нет данных для воронки</p>
          </div>
        )}
      </div>
    </div>
  )
}
