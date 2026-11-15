import { useEffect, useState } from 'react'
import { Eye, CheckCircle2, RefreshCw, UserCheck, VolumeX, Volume2, MessageCircle, Pin, ChevronLeft, ArrowRight } from 'lucide-react'
import { api } from '../api/client'
import type { Incident, IncidentEvent } from '../types'
import Spinner from '../components/Spinner'
import { fmt } from '../utils/format'

const EVENT_LABELS: Record<string, string> = {
  created: 'Создан', ack: 'Принят', resolved: 'Решён', reopened: 'Переоткрыт',
  assigned: 'Назначен', muted: 'Заглушен', unmuted: 'Разглушен', commented: 'Комментарий',
}

const EVENT_ICONS: Record<string, React.ReactNode> = {
  created: <Pin size={12} />, ack: <Eye size={12} />, resolved: <CheckCircle2 size={12} />,
  reopened: <RefreshCw size={12} />, assigned: <UserCheck size={12} />,
  muted: <VolumeX size={12} />, unmuted: <Volume2 size={12} />, commented: <MessageCircle size={12} />,
}

const PRIORITY_COLORS: Record<string, { bg: string; fg: string; bar: string }> = {
  P0: { bg: 'rgba(248,113,113,0.18)', fg: '#fca5a5', bar: 'var(--danger)' },
  P1: { bg: 'rgba(251,191,36,0.18)', fg: '#fcd34d', bar: 'var(--warn)' },
  P2: { bg: 'rgba(125,211,252,0.18)', fg: '#7dd3fc', bar: 'var(--info)' },
  P3: { bg: 'rgba(255,255,255,0.06)', fg: 'var(--text-3)', bar: 'var(--text-4)' },
}

interface Props {
  incidentId: string
  onBack: () => void
}

export default function IncidentDetail({ incidentId, onBack }: Props) {
  const [incident, setIncident] = useState<Incident | null>(null)
  const [events, setEvents] = useState<IncidentEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [acting, setActing] = useState(false)

  const load = () => {
    setLoading(true)
    api.incidents.get(incidentId)
      .then(r => { setIncident(r.incident); setEvents(r.events || []) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [incidentId])

  const doAction = async (fn: () => Promise<any>) => {
    if (acting) return; setActing(true)
    try { await fn(); load(); const tg = (window as any).Telegram?.WebApp; tg?.HapticFeedback?.notificationOccurred('success') }
    catch (e: any) { alert(e.message) } finally { setActing(false) }
  }

  const formatDate = (iso: string) => new Date(iso).toLocaleString('ru-RU', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  // Loading / Error states
  if (loading || error || !incident) {
    return (
      <div style={{ background: 'var(--bg)', minHeight: '100vh' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px 12px', borderBottom: '1px solid var(--hairline)' }}>
          <button onClick={onBack} className="press" style={{ width: 32, height: 32, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            <ChevronLeft size={15} style={{ color: 'var(--text-1)' }} />
          </button>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)' }}>Инцидент</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '80px 0' }}>
          {loading ? <Spinner size={32} /> : <span style={{ color: 'var(--danger)', fontSize: 14 }}>{error || 'Не найден'}</span>}
        </div>
      </div>
    )
  }

  const pc = PRIORITY_COLORS[incident.severity] || PRIORITY_COLORS.P3
  const statusText = incident.status === 'ack' ? 'принят' : incident.status === 'resolved' ? 'решён' : incident.status === 'reopened' ? 'переоткрыт' : 'открыт'

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px 12px', borderBottom: '1px solid var(--hairline)', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 5 }}>
        <button onClick={onBack} className="press" style={{ width: 32, height: 32, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <ChevronLeft size={15} style={{ color: 'var(--text-1)' }} />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)', letterSpacing: '-0.02em' }}>{incident.id}</div>
          <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>
            {incident.severity} · {incident.created_at.slice(11, 16)} · {statusText}
          </div>
        </div>
      </div>

      <div style={{ padding: '12px 12px 120px' }}>
        {/* Hero card with priority bar */}
        <div className="card rise" style={{ padding: 14, marginBottom: 10, position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 3, background: pc.bar }} />

          {/* Priority + Title */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
            <span className="mono" style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              padding: '3px 8px', borderRadius: 5, fontSize: 11, fontWeight: 700,
              letterSpacing: '0.04em', background: pc.bg, color: pc.fg,
              border: `1px solid ${pc.fg}25`, flexShrink: 0,
            }}>{incident.severity}</span>
            <div style={{ flex: 1, fontSize: 14.5, fontWeight: 600, color: 'var(--text-1)', lineHeight: 1.35 }}>{incident.title}</div>
          </div>

          {/* Metric delta */}
          {incident.delta_pct != null && (
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 10 }}>
              <div>
                <div className="eyebrow" style={{ marginBottom: 2 }}>Метрика</div>
                <div className="mono num" style={{ fontSize: 22, fontWeight: 600, color: incident.delta_pct < 0 ? 'var(--danger)' : 'var(--em-400)', letterSpacing: '-0.02em' }}>
                  {incident.delta_pct > 0 ? '+' : ''}{incident.delta_pct.toFixed(1)}%
                </div>
              </div>
              {incident.baseline_value != null && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 2 }}>Было</div>
                    <div className="mono num" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-2)' }}>
                      {incident.baseline_value > 1000 ? fmt(Math.round(incident.baseline_value)) : incident.baseline_value.toFixed(1)}
                    </div>
                  </div>
                  <ArrowRight size={14} style={{ color: 'var(--text-4)' }} />
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 2 }}>Стало</div>
                    <div className="mono num" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-1)' }}>
                      {incident.current_value > 1000 ? fmt(Math.round(incident.current_value)) : incident.current_value.toFixed(1)}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Action buttons inside hero */}
          <div style={{ display: 'flex', gap: 6 }}>
            {incident.status === 'open' && (
              <button onClick={() => doAction(() => api.incidents.ack(incidentId))} disabled={acting} className="press" style={{
                flex: 1, padding: '8px 12px', borderRadius: 10, background: 'var(--em-500)', color: '#fff', fontSize: 12, fontWeight: 600, border: 'none',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, opacity: acting ? 0.5 : 1,
              }}><Eye size={13} /> Принять</button>
            )}
            {incident.status === 'ack' && (
              <button onClick={() => doAction(() => api.incidents.resolve(incidentId))} disabled={acting} className="press" style={{
                flex: 1, padding: '8px 12px', borderRadius: 10, background: 'var(--em-500)', color: '#fff', fontSize: 12, fontWeight: 600, border: 'none',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, opacity: acting ? 0.5 : 1,
              }}><CheckCircle2 size={13} /> Закрыть</button>
            )}
            {incident.status === 'resolved' && (
              <button onClick={() => doAction(() => api.incidents.reopen(incidentId))} disabled={acting} className="press" style={{
                flex: 1, padding: '8px 12px', borderRadius: 10, background: 'rgba(16,185,129,0.10)', color: 'var(--em-400)', fontSize: 12, fontWeight: 600,
                border: '1px solid rgba(16,185,129,0.20)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, opacity: acting ? 0.5 : 1,
              }}><RefreshCw size={13} /> Переоткрыть</button>
            )}
            {!incident.is_muted ? (
              <button onClick={() => doAction(() => api.incidents.mute(incidentId, 60))} disabled={acting} className="press" style={{
                padding: '8px 14px', borderRadius: 10, background: 'var(--surface-2)', color: 'var(--text-1)', fontSize: 12, fontWeight: 600,
                border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', gap: 6, opacity: acting ? 0.5 : 1,
              }}><VolumeX size={12} /> 1ч</button>
            ) : (
              <button onClick={() => doAction(() => api.incidents.unmute(incidentId))} disabled={acting} className="press" style={{
                padding: '8px 14px', borderRadius: 10, background: 'var(--surface-2)', color: 'var(--text-1)', fontSize: 12, fontWeight: 600,
                border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', gap: 6, opacity: acting ? 0.5 : 1,
              }}><Volume2 size={12} /> Вкл.</button>
            )}
          </div>
        </div>

        {/* Context table */}
        <div className="card rise rise-1" style={{ padding: 14, marginBottom: 10 }}>
          <div className="section-title" style={{ marginBottom: 10 }}>Контекст</div>
          {[
            { k: 'Тип', v: incident.type },
            { k: 'Область', v: incident.scope },
            { k: 'Метрика', v: incident.metric },
            ...Object.entries(incident.dimensions || {}).map(([key, value]) => ({ k: key, v: String(value) })),
            { k: 'Период', v: `${incident.period_from?.slice(11, 16) || ''} — ${incident.period_to?.slice(11, 16) || ''}` },
          ].filter(r => r.v).map((row, i) => (
            <div key={row.k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderTop: i === 0 ? 'none' : '1px solid var(--hairline)' }}>
              <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>{row.k}</span>
              <span style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-1)' }}>{row.v}</span>
            </div>
          ))}
        </div>

        {/* Timeline */}
        <div className="card rise rise-2" style={{ padding: 14 }}>
          <div className="section-title" style={{ marginBottom: 12 }}>Хронология</div>
          {events.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--text-4)' }}>Нет событий</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {events.map((evt, i) => {
                const tone = evt.event_type === 'resolved' ? 'good' : evt.event_type === 'created' ? 'bad' : 'neutral'
                return (
                  <div key={evt.id} style={{ display: 'flex', gap: 10 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 3 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: tone === 'good' ? 'var(--em-400)' : tone === 'bad' ? 'var(--danger)' : 'var(--text-4)' }} />
                      {i < events.length - 1 && <span style={{ width: 1, flex: 1, background: 'var(--hairline)', minHeight: 18, marginTop: 2 }} />}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                        <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-1)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          {EVENT_ICONS[evt.event_type] || <Pin size={12} />}
                          {EVENT_LABELS[evt.event_type] || evt.event_type}
                        </span>
                        <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)' }}>{formatDate(evt.created_at)}</span>
                      </div>
                      {evt.actor_user_id && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>user {evt.actor_user_id}</div>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
