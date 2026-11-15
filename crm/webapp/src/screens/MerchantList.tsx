import { useEffect, useState, useCallback, useRef } from 'react'
import { Upload, HelpCircle, Search, X, ChevronRight } from 'lucide-react'
import { api } from '../api/client'
import type { Merchant } from '../types'
import StatusBadge from '../components/StatusBadge'
import { SkeletonList } from '../components/Skeleton'
import HealthScore, { calculateHealthScore } from '../components/HealthScore'
import ExportInstructions from '../components/ExportInstructions'
import ChatSelector, { isBizChat, type ChatPreview } from '../components/ChatSelector'

const STATUS_CHIPS: { id: string; label: string }[] = [
  { id: '', label: 'Все' },
  { id: 'active', label: 'Активные' },
  { id: 'problem', label: 'Проблемы' },
  { id: 'integration', label: 'Интеграция' },
  { id: 'new', label: 'Новые' },
  { id: 'paused', label: 'Пауза' },
  { id: 'negotiation', label: 'Переговоры' },
  { id: 'testing', label: 'Тест' },
  { id: 'disconnected', label: 'Откл.' },
]

interface Props {
  onSelect: (id: number) => void
}

export default function MerchantList({ onSelect }: Props) {
  const [merchants, setMerchants] = useState<Merchant[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState<{ processed: number; total: number } | null>(null)
  const [showHelp, setShowHelp] = useState(false)
  const [chatSelection, setChatSelection] = useState<{ chats: ChatPreview[]; fullData: any } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const load = useCallback((s: string, st: string) => {
    setLoading(true)
    api.merchants.list({ search: s || undefined, status: st || undefined })
      .then(r => { setMerchants(r.items); setTotal(r.total) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const t = setTimeout(() => load(search, status), 300)
    return () => clearTimeout(t)
  }, [search, status, load])

  const pollUploadStatus = async (taskId: string) => {
    const poll = async () => {
      try {
        const task = await api.chatExport.status(taskId)
        setUploadProgress({ processed: task.processed, total: task.total })
        if (task.status === 'completed') {
          setUploadResult(`Обработано: ${task.processed} сообщ., обновлено: ${task.updated} мерчантов${task.merchants?.length ? ` (${task.merchants.join(', ')})` : ''}`)
          setUploading(false); setUploadProgress(null); load(search, status)
          const tg = (window as any).Telegram?.WebApp; tg?.HapticFeedback?.notificationOccurred('success')
        } else if (task.status === 'error') {
          setUploadResult(`Ошибка: ${task.error || 'unknown'}`); setUploading(false); setUploadProgress(null)
        } else { setTimeout(poll, 2000) }
      } catch { setUploadResult('Ошибка получения статуса'); setUploading(false); setUploadProgress(null) }
    }
    poll()
  }

  const getHeaders = () => {
    const initData = (window as any).Telegram?.WebApp?.initData
    const storedAuth = localStorage.getItem('pwa_auth')
    const headers: Record<string, string> = {}
    if (initData) { headers['X-Init-Data'] = initData }
    else if (storedAuth) {
      try { const { userId, accessKey } = JSON.parse(storedAuth); headers['Authorization'] = `Bearer ${accessKey}:${userId}` } catch { /* ignore */ }
    }
    return headers
  }

  const uploadJsonBlob = async (jsonData: any, filename: string) => {
    const blob = new Blob([JSON.stringify(jsonData)], { type: 'application/json' })
    const formData = new FormData(); formData.append('file', blob, filename)
    const BASE = import.meta.env.VITE_API_URL || ''
    const res = await fetch(`${BASE}/api/chat-export/upload`, { method: 'POST', headers: getHeaders(), body: formData })
    if (!res.ok) { const err = await res.json().catch(() => ({ detail: res.statusText })); throw new Error(err.detail || `HTTP ${res.status}`) }
    return res.json()
  }

  const handleChatSelectionConfirm = async (selectedIndices: number[]) => {
    if (!chatSelection) return
    setChatSelection(null); setUploading(true); setUploadResult(null)
    const chatsData = chatSelection.fullData
    const selectedChats = Array.isArray(chatsData.chats?.list) ? chatsData.chats.list.filter((_: any, i: number) => selectedIndices.includes(i)) : []
    let totalProcessed = 0, totalUpdated = 0; const allMerchants: string[] = []
    for (const chat of selectedChats) {
      try {
        const singleExport = { name: chat.name, id: chat.id, messages: chat.messages || [] }
        const data = await uploadJsonBlob(singleExport, `${chat.name || 'chat'}.json`)
        if (data.task_id) {
          await new Promise<void>((resolve) => {
            const poll = async () => {
              try {
                const task = await api.chatExport.status(data.task_id)
                setUploadProgress({ processed: totalProcessed + task.processed, total: selectedChats.reduce((s: number, c: any) => s + (c.messages?.length || 0), 0) })
                if (task.status === 'completed' || task.status === 'error') {
                  totalProcessed += task.processed; totalUpdated += task.updated
                  task.merchants?.forEach((m: string) => { if (!allMerchants.includes(m)) allMerchants.push(m) })
                  resolve()
                } else { setTimeout(poll, 1500) }
              } catch { resolve() }
            }; poll()
          })
        }
      } catch { /* continue */ }
    }
    setUploadResult(`Обработано: ${totalProcessed} сообщ., обновлено: ${totalUpdated} мерчантов${allMerchants.length ? ` (${allMerchants.join(', ')})` : ''}`)
    setUploading(false); setUploadProgress(null); load(search, status)
    const tg = (window as any).Telegram?.WebApp; tg?.HapticFeedback?.notificationOccurred('success')
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return
    const ext = file.name.toLowerCase()
    if (!ext.endsWith('.json') && !ext.endsWith('.zip')) { setUploadResult('Поддерживаются только .json и .zip файлы'); return }
    if (ext.endsWith('.json') && file.size < 50 * 1024 * 1024) {
      try {
        const text = await file.text(); const data = JSON.parse(text)
        if (data.chats?.list && Array.isArray(data.chats.list)) {
          const chats: ChatPreview[] = data.chats.list.map((chat: any, i: number) => ({
            index: i, name: chat.name || `Chat ${i}`, id: chat.id || 0,
            message_count: (chat.messages || []).filter((m: any) => m.type === 'message').length,
            is_business: isBizChat(chat.name || ''),
          })).filter((c: ChatPreview) => c.message_count > 0)
          if (chats.length > 1) { setChatSelection({ chats, fullData: data }); if (fileInputRef.current) fileInputRef.current.value = ''; return }
        }
      } catch { /* fall through */ }
    }
    setUploading(true); setUploadResult(null); setUploadProgress(null)
    try {
      const formData = new FormData(); formData.append('file', file)
      const BASE = import.meta.env.VITE_API_URL || ''
      const res = await fetch(`${BASE}/api/chat-export/upload`, { method: 'POST', headers: getHeaders(), body: formData })
      if (!res.ok) { const err = await res.json().catch(() => ({ detail: res.statusText })); throw new Error(err.detail || `HTTP ${res.status}`) }
      const data = await res.json()
      if (data.task_id) { setUploadProgress({ processed: 0, total: data.total_messages }); pollUploadStatus(data.task_id) }
      else { setUploadResult('Обработано: 0 сообщений'); setUploading(false) }
    } catch (err: any) { setUploadResult(`Ошибка: ${err.message}`); setUploading(false); setUploadProgress(null) }
    finally { if (fileInputRef.current) fileInputRef.current.value = '' }
  }

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Search & filters — sticky */}
      <div style={{ padding: '8px 12px', position: 'sticky', top: 0, zIndex: 10, background: 'var(--bg)', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {/* Search */}
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px' }}>
          <Search size={14} style={{ color: 'var(--text-3)', flexShrink: 0 }} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Поиск по имени"
            style={{ flex: 1, background: 'transparent', border: 0, outline: 0, color: 'var(--text-1)', fontSize: 13, fontFamily: 'var(--font-sans)' }} />
          {search && <button onClick={() => setSearch('')}><X size={14} style={{ color: 'var(--text-3)' }} /></button>}
        </div>

        {/* Status chips */}
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4 }}>
          {STATUS_CHIPS.map(c => (
            <button key={c.id} onClick={() => setStatus(c.id)} className="press"
              style={{
                flexShrink: 0, padding: '6px 12px', borderRadius: 999, fontSize: 11.5, fontWeight: 600,
                background: status === c.id ? 'var(--em-tint)' : 'var(--surface)',
                color: status === c.id ? 'var(--em-400)' : 'var(--text-3)',
                border: `1px solid ${status === c.id ? 'var(--em-tint-2)' : 'var(--hairline)'}`,
              }}>
              {c.label}
            </button>
          ))}
        </div>

        {/* Upload */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input ref={fileInputRef} type="file" accept=".json,.zip" onChange={handleFileUpload} style={{ display: 'none' }} />
          <button onClick={() => fileInputRef.current?.click()} disabled={uploading} className="press" style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 'var(--r-md)', fontSize: 11, fontWeight: 600,
            background: 'var(--surface)', color: 'var(--em-400)', border: '1px solid var(--em-tint-2)',
            opacity: uploading ? 0.5 : 1,
          }}>
            <Upload size={12} />
            {uploading ? 'Обработка...' : 'Загрузить экспорт'}
          </button>
          <button onClick={() => setShowHelp(true)} className="press" style={{
            width: 28, height: 28, borderRadius: 'var(--r-md)', background: 'var(--surface)', border: '1px solid var(--hairline)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <HelpCircle size={13} style={{ color: 'var(--text-3)' }} />
          </button>
          {uploadResult && !uploadProgress && (
            <span style={{ fontSize: 10.5, color: 'var(--text-3)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{uploadResult}</span>
          )}
        </div>
        {uploadProgress && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ width: '100%', height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.04)', overflow: 'hidden' }}>
              <div style={{ height: '100%', borderRadius: 2, background: 'var(--em-500)', transition: 'width 0.5s', width: `${uploadProgress.total ? (uploadProgress.processed / uploadProgress.total * 100) : 0}%` }} />
            </div>
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)' }}>{uploadProgress.processed} / {uploadProgress.total}</span>
          </div>
        )}
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 24px' }}>
        {loading ? (
          <div style={{ paddingTop: 8 }}><SkeletonList count={6} /></div>
        ) : error ? (
          <div style={{ padding: '16px 0', color: 'var(--danger)', fontSize: 14 }}>{error}</div>
        ) : (
          <>
            <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-4)', marginBottom: 8 }}>
              Найдено: {total}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {merchants.map((m, i) => {
                const healthScore = calculateHealthScore({ conversion: m.conversion, incidents: m.open_incidents_count, mood: m.mood })
                return (
                  <button key={m.id} onClick={() => onSelect(m.id)} className="card press rise"
                    style={{ padding: '12px 14px', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10, animationDelay: `${i * 25}ms` }}>
                    <HealthScore score={healthScore} size={40} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.name}</span>
                        {m.open_incidents_count > 0 && (
                          <span className="mono" style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 5px', borderRadius: 4, background: 'rgba(248,113,113,0.14)', color: 'var(--danger)' }}>{m.open_incidents_count}</span>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <StatusBadge status={m.status} />
                        <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
                          {m.conversion != null ? `${m.conversion.toFixed(1)}% conv` : '\u2014'}
                          {m.current_rate != null ? ` \u00B7 ${m.current_rate}%` : ''}
                        </span>
                      </div>
                    </div>
                    <ChevronRight size={14} style={{ color: 'var(--text-4)', flexShrink: 0 }} />
                  </button>
                )
              })}
            </div>
          </>
        )}
      </div>
      {showHelp && <ExportInstructions onClose={() => setShowHelp(false)} />}
      {chatSelection && <ChatSelector chats={chatSelection.chats} onConfirm={handleChatSelectionConfirm} onClose={() => setChatSelection(null)} />}
    </div>
  )
}
