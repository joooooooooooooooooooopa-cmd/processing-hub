import { useEffect, useState, useCallback } from 'react'
import { VolumeX, MessageSquare, Sparkles, ChevronDown, ChevronUp, RefreshCw, Search, ChevronRight, ChevronLeft } from 'lucide-react'
import { api } from '../api/client'
import type { Merchant, Incident, CanonicalValues, MerchantStatus, MerchantChatMessage, MerchantChatSummary } from '../types'
import StatusBadge from '../components/StatusBadge'
import PriorityBadge from '../components/PriorityBadge'
import BottomSheet from '../components/BottomSheet'
import Spinner from '../components/Spinner'

interface Props {
  merchantId: number
  onIncident: (id: string) => void
  onBack?: () => void
}

type EditField = { field: string; label: string }

const EDITABLE: EditField[] = [
  { field: 'status', label: 'Статус' },
  { field: 'mood', label: 'Настроение' },
  { field: 'integration_status', label: 'Статус интеграции' },
  { field: 'rate_flexibility', label: 'Гибкость ставки' },
  { field: 'current_rate', label: 'Текущая ставка (%)' },
  { field: 'min_rate', label: 'Мин. ставка (%)' },
  { field: 'contact_person', label: 'Контактное лицо' },
  { field: 'payment_methods', label: 'Методы оплаты' },
  { field: 'notes', label: 'Заметки' },
]

function InfoRow({ label, value }: { label: string; value?: string | number | null }) {
  if (!value && value !== 0) return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '10px 0', borderTop: '1px solid var(--hairline)' }}>
      <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>{label}</span>
      <span style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-1)', textAlign: 'right', maxWidth: '60%' }}>{String(value)}</span>
    </div>
  )
}

export default function MerchantDetail({ merchantId, onIncident, onBack }: Props) {
  const [merchant, setMerchant] = useState<Merchant | null>(null)
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [, setHistory] = useState<any[]>([])
  const [canonical, setCanonical] = useState<CanonicalValues | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editField, setEditField] = useState<EditField | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [tab, setTab] = useState<'overview' | 'finance' | 'history'>('overview')
  const [summary, setSummary] = useState<MerchantChatSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [chatMessages, setChatMessages] = useState<MerchantChatMessage[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const [chatLoadingMore, setChatLoadingMore] = useState(false)
  const [showChat, setShowChat] = useState(false)
  const [chatTotal, setChatTotal] = useState(0)
  const [chatHasMore, setChatHasMore] = useState(false)
  const [chatSearch, setChatSearch] = useState('')
  const [chatGroupFilter, setChatGroupFilter] = useState('')

  useEffect(() => {
    Promise.all([api.merchants.get(merchantId), api.merchants.canonicalValues()])
      .then(([data, cv]) => { setMerchant(data.merchant); setIncidents(data.open_incidents); setHistory(data.history || []); setCanonical(cv) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    setSummaryLoading(true)
    api.merchants.chatSummary(merchantId).then(setSummary).catch(() => {}).finally(() => setSummaryLoading(false))
  }, [merchantId])

  const loadChat = useCallback((reset = false, search = chatSearch, group = chatGroupFilter) => {
    const offset = reset ? 0 : chatMessages.length
    const setLoad = reset ? setChatLoading : setChatLoadingMore
    setLoad(true)
    api.merchants.messages(merchantId, 20, offset, search, group)
      .then(data => { setChatMessages(prev => reset ? data.messages : [...prev, ...data.messages]); setChatTotal(data.total); setChatHasMore(data.has_more) })
      .catch(() => {}).finally(() => setLoad(false))
  }, [merchantId, chatMessages.length, chatSearch, chatGroupFilter])

  const openEdit = (f: EditField) => {
    const val = merchant ? (merchant as any)[f.field] : ''
    setEditValue(val != null ? String(val) : ''); setEditField(f)
  }

  const getOptions = (field: string): string[] => {
    if (!canonical) return []
    if (field === 'status') return canonical.statuses
    if (field === 'mood') return canonical.moods
    if (field === 'integration_status') return canonical.integration_statuses
    if (field === 'rate_flexibility') return canonical.rate_flexibility
    return []
  }

  const save = async () => {
    if (!editField || !merchant) return
    setSaving(true)
    try {
      await api.merchants.update(merchantId, editField.field, editValue)
      setMerchant({ ...merchant, [editField.field]: editValue } as Merchant)
      setEditField(null)
      const tg = (window as any).Telegram?.WebApp; tg?.HapticFeedback?.impactOccurred('medium')
    } catch (e: any) { alert(e.message) }
    finally { setSaving(false) }
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 48 }}><Spinner size={32} /></div>
  if (error) return <div style={{ padding: 16, color: 'var(--danger)' }}>{error}</div>
  if (!merchant) return null

  const opts = editField ? getOptions(editField.field) : []
  const initials = merchant.name.split(' ').map(s => s[0]).join('').slice(0, 2).toUpperCase()

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px 12px', borderBottom: '1px solid var(--hairline)', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 5 }}>
        {onBack && (
          <button onClick={onBack} className="press" style={{ width: 32, height: 32, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <ChevronLeft size={15} style={{ color: 'var(--text-1)' }} />
          </button>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)', letterSpacing: '-0.02em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{merchant.name}</div>
          <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{merchant.contact_person || '\u2014'}</div>
        </div>
      </div>

      <div style={{ padding: '12px 12px 96px' }}>
        {/* Identity strip */}
        <div className="card rise" style={{ padding: 14, marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={{ width: 48, height: 48, borderRadius: 14, background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.20)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: 'var(--em-400)', flexShrink: 0 }}>
              {initials}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
                <StatusBadge status={merchant.status as MerchantStatus} />
                {incidents.length > 0 && (
                  <span className="mono" style={{ fontSize: 9.5, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: 'rgba(248,113,113,0.14)', color: 'var(--danger)' }}>{incidents.length} INC</span>
                )}
              </div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{merchant.payment_methods || '\u2014'}</div>
            </div>
          </div>
          {/* Edit buttons */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {EDITABLE.slice(0, 4).map(f => (
              <button key={f.field} onClick={() => openEdit(f)} className="press" style={{
                padding: '6px 10px', borderRadius: 'var(--r-md)', fontSize: 11, fontWeight: 600,
                background: 'var(--surface-2)', color: 'var(--text-2)', border: '1px solid var(--hairline)',
              }}>{f.label}</button>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div className="seg rise rise-1" style={{ marginBottom: 10 }}>
          <button className={tab === 'overview' ? 'on' : ''} onClick={() => setTab('overview')}>Обзор</button>
          <button className={tab === 'finance' ? 'on' : ''} onClick={() => setTab('finance')}>Детали</button>
          <button className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')}>Чат</button>
        </div>

        {tab === 'overview' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* Info card */}
            <div className="card rise rise-2" style={{ padding: '4px 14px' }}>
              <InfoRow label="Статус" value={merchant.status} />
              <InfoRow label="Настроение" value={merchant.mood} />
              <InfoRow label="Интеграция" value={merchant.integration_status} />
              <InfoRow label="Гибкость ставки" value={merchant.rate_flexibility} />
              <InfoRow label="Текущая ставка" value={merchant.current_rate != null ? merchant.current_rate + '%' : null} />
              <InfoRow label="Мин. ставка" value={merchant.min_rate != null ? merchant.min_rate + '%' : null} />
              <InfoRow label="Конверсия" value={merchant.conversion != null ? merchant.conversion.toFixed(1) + '%' : null} />
              <InfoRow label="Контакт" value={merchant.contact_person} />
              <InfoRow label="Методы" value={merchant.payment_methods} />
              <InfoRow label="Заметки" value={merchant.notes} />
            </div>

            {/* Open incidents */}
            {incidents.length > 0 && (
              <div className="rise rise-3">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span className="section-title">Связанные инциденты</span>
                  <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)' }}>{incidents.length}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {incidents.map(inc => (
                    <button key={inc.id} onClick={() => onIncident(inc.id)} className="card press" style={{ padding: '10px 12px', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <PriorityBadge priority={inc.severity} />
                      <span style={{ flex: 1, fontSize: 12, color: 'var(--text-1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{inc.title}</span>
                      {inc.is_muted && <VolumeX size={12} style={{ color: 'var(--text-4)' }} />}
                      <ChevronRight size={12} style={{ color: 'var(--text-4)' }} />
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* More edit buttons */}
            <div className="rise rise-4">
              <span className="section-title" style={{ marginBottom: 8, display: 'block' }}>Редактировать</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {EDITABLE.map(f => (
                  <button key={f.field} onClick={() => openEdit(f)} className="press" style={{
                    padding: '6px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600,
                    background: 'var(--surface)', color: 'var(--em-400)', border: '1px solid var(--em-tint-2)',
                  }}>{f.label}</button>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === 'finance' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* AI Summary */}
            {(summary || summaryLoading) && (
              <div className="card rise" style={{ padding: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
                  <Sparkles size={13} style={{ color: 'var(--em-400)' }} />
                  <span className="section-title" style={{ color: 'var(--em-400)' }}>AI-сводка</span>
                  {summary?.cached && <span style={{ fontSize: 10, color: 'var(--text-4)' }}>(кэш)</span>}
                  {summary && (
                    <button onClick={() => { setSummaryLoading(true); api.merchants.chatSummary(merchantId, true).then(setSummary).catch(() => {}).finally(() => setSummaryLoading(false)) }}
                      disabled={summaryLoading} className="press" style={{ marginLeft: 'auto', width: 24, height: 24, borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--hairline)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                      <RefreshCw size={11} style={{ color: 'var(--text-3)', animation: summaryLoading ? 'spin 1s linear infinite' : 'none' }} />
                    </button>
                  )}
                </div>
                {summaryLoading ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Spinner size={16} /><span style={{ fontSize: 12, color: 'var(--text-3)' }}>Генерация...</span></div>
                ) : summary && summary.message_count > 0 ? (
                  <>
                    <p style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.5, margin: 0 }}>{summary.summary}</p>
                    <div className="mono" style={{ marginTop: 8, display: 'flex', gap: 12, fontSize: 10, color: 'var(--text-4)' }}>
                      <span>{summary.message_count} сообщ.</span>
                      {summary.generated_at && <span>{summary.generated_at.slice(0, 16)}</span>}
                    </div>
                  </>
                ) : null}
              </div>
            )}
          </div>
        )}

        {tab === 'history' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button onClick={() => { if (!showChat && chatMessages.length === 0) loadChat(true); setShowChat(!showChat) }} className="press"
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 'var(--r-lg)', background: 'var(--surface)', border: '1px solid var(--hairline)' }}>
              <MessageSquare size={14} style={{ color: 'var(--em-400)' }} />
              <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--text-1)', textAlign: 'left' }}>
                История чата {chatTotal > 0 && <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)', fontWeight: 400 }}>({chatTotal})</span>}
              </span>
              {showChat ? <ChevronUp size={14} style={{ color: 'var(--text-4)' }} /> : <ChevronDown size={14} style={{ color: 'var(--text-4)' }} />}
            </button>

            {showChat && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px' }}>
                  <Search size={12} style={{ color: 'var(--text-4)' }} />
                  <input type="text" placeholder="Поиск..." value={chatSearch}
                    onChange={e => { setChatSearch(e.target.value); clearTimeout((window as any).__chatSearchTimer); const v = e.target.value; (window as any).__chatSearchTimer = setTimeout(() => loadChat(true, v, chatGroupFilter), 400) }}
                    style={{ flex: 1, background: 'transparent', border: 0, outline: 0, color: 'var(--text-1)', fontSize: 12, fontFamily: 'var(--font-sans)' }} />
                </div>

                {(() => {
                  const groups = [...new Set(chatMessages.map(m => m.group_name).filter(Boolean))]
                  if (groups.length <= 1) return null
                  return (
                    <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
                      <button onClick={() => { setChatGroupFilter(''); loadChat(true, chatSearch, '') }} className="press" style={{
                        flexShrink: 0, padding: '4px 8px', borderRadius: 999, fontSize: 10, fontWeight: 600,
                        background: !chatGroupFilter ? 'var(--em-tint)' : 'var(--surface)', color: !chatGroupFilter ? 'var(--em-400)' : 'var(--text-3)',
                        border: `1px solid ${!chatGroupFilter ? 'var(--em-tint-2)' : 'var(--hairline)'}`,
                      }}>Все</button>
                      {groups.map(g => (
                        <button key={g} onClick={() => { setChatGroupFilter(g); loadChat(true, chatSearch, g) }} className="press" style={{
                          flexShrink: 0, padding: '4px 8px', borderRadius: 999, fontSize: 10, fontWeight: 600, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          background: chatGroupFilter === g ? 'var(--em-tint)' : 'var(--surface)', color: chatGroupFilter === g ? 'var(--em-400)' : 'var(--text-3)',
                          border: `1px solid ${chatGroupFilter === g ? 'var(--em-tint-2)' : 'var(--hairline)'}`,
                        }}>{g}</button>
                      ))}
                    </div>
                  )
                })()}

                <div style={{ maxHeight: '60vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {chatLoading ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}><Spinner size={20} /></div>
                  ) : chatMessages.length === 0 ? (
                    <p style={{ fontSize: 12, color: 'var(--text-4)', textAlign: 'center', padding: 16 }}>Нет сообщений</p>
                  ) : (
                    <>
                      {chatMessages.map((msg, i) => {
                        const curDate = msg.created_at?.slice(0, 10)
                        const prevDate = i > 0 ? chatMessages[i - 1].created_at?.slice(0, 10) : null
                        const showDate = i === 0 || curDate !== prevDate
                        return (
                          <div key={msg.id}>
                            {showDate && curDate && <div style={{ textAlign: 'center', fontSize: 10, color: 'var(--text-4)', padding: '4px 0' }} className="mono">{curDate}</div>}
                            <div className="card" style={{ padding: 10 }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--em-400)' }}>{msg.sender_name || 'Unknown'}</span>
                                <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)' }}>{msg.created_at?.slice(11, 16)}</span>
                              </div>
                              <p style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.4, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.text}</p>
                              {msg.group_name && <span style={{ marginTop: 4, display: 'inline-block', fontSize: 10, color: 'var(--text-4)' }}>{msg.group_name}</span>}
                            </div>
                          </div>
                        )
                      })}
                      {chatHasMore && (
                        <button onClick={() => loadChat(false)} disabled={chatLoadingMore} className="press" style={{
                          padding: '8px 16px', borderRadius: 'var(--r-md)', fontSize: 12, fontWeight: 600,
                          background: 'var(--surface)', color: 'var(--em-400)', border: '1px solid var(--em-tint-2)',
                          opacity: chatLoadingMore ? 0.5 : 1,
                        }}>{chatLoadingMore ? 'Загрузка...' : 'Показать ещё'}</button>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Edit BottomSheet */}
      {editField && (
        <BottomSheet title={editField.label} onClose={() => setEditField(null)}>
          {opts.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {opts.map(o => (
                <button key={o} onClick={() => setEditValue(o)} className="press" style={{
                  padding: '12px 14px', borderRadius: 'var(--r-md)', fontSize: 13, textAlign: 'left',
                  background: editValue === o ? 'var(--em-500)' : 'var(--surface)', color: editValue === o ? '#fff' : 'var(--text-1)',
                  border: editValue === o ? 'none' : '1px solid var(--hairline)',
                }}>{o}</button>
              ))}
            </div>
          ) : (
            <input type={editField.field.includes('rate') ? 'number' : 'text'} value={editValue} onChange={e => setEditValue(e.target.value)}
              style={{ width: '100%', padding: '12px 14px', borderRadius: 'var(--r-md)', fontSize: 13, background: 'var(--surface)', color: 'var(--text-1)', border: '1px solid var(--hairline)', outline: 'none', fontFamily: 'var(--font-sans)' }}
              placeholder={editField.label} />
          )}
          <button onClick={save} disabled={saving} className="press" style={{
            width: '100%', marginTop: 12, padding: '12px 16px', borderRadius: 'var(--r-md)', fontSize: 14, fontWeight: 600,
            background: 'var(--em-500)', color: '#fff', border: 'none', opacity: saving ? 0.5 : 1,
          }}>{saving ? 'Сохранение...' : 'Сохранить'}</button>
        </BottomSheet>
      )}
    </div>
  )
}
