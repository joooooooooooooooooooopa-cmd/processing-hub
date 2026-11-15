import { memo, useState, useEffect, useRef } from 'react'
import { Search, X, ChevronRight } from 'lucide-react'
import { api } from '../../api/client'
import type { Merchant } from '../../types'

const STATUS_COLORS: Record<string, string> = {
  active: '#10b981', new: '#3b82f6', negotiation: '#8b5cf6', integration: '#06b6d4',
  testing: '#f59e0b', paused: '#6b7280', problem: '#ef4444', disconnected: '#374151',
}

export default memo(function SearchOverlay({
  open,
  onClose,
  onSelect,
}: {
  open: boolean
  onClose: () => void
  onSelect: (id: number) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Merchant[]>([])
  const [searching, setSearching] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(null)

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100)
      setQuery('')
      setResults([])
    }
  }, [open])

  useEffect(() => {
    if (!query.trim()) { setResults([]); return }
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const r = await api.merchants.list({ search: query })
        setResults(r.items.slice(0, 8))
      } catch { setResults([]) }
      finally { setSearching(false) }
    }, 300)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [query])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex flex-col p-4 pt-safe">
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1 relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Поиск мерчантов..."
            className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-[#111827] text-white text-sm border border-emerald-500/20 outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
        <button onClick={onClose} className="p-2 text-gray-400">
          <X size={20} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-1.5">
        {searching && <div className="text-center text-gray-500 text-sm py-4">Поиск...</div>}
        {!searching && query && results.length === 0 && (
          <div className="text-center text-gray-600 text-sm py-4">Ничего не найдено</div>
        )}
        {results.map(m => (
          <button
            key={m.id}
            onClick={() => { onSelect(m.id); onClose() }}
            className="w-full flex items-center justify-between bg-[#0d1117] border border-emerald-500/10 rounded-xl p-3 text-left"
          >
            <div className="flex items-center gap-3">
              <div
                className="w-2 h-2 rounded-full"
                style={{ background: STATUS_COLORS[m.status] || '#6b7280' }}
              />
              <div>
                <div className="text-sm text-white font-medium">{m.name}</div>
                <div className="text-[10px] text-gray-500">{m.status} {m.contact_person ? `· ${m.contact_person}` : ''}</div>
              </div>
            </div>
            <ChevronRight size={16} className="text-gray-600" />
          </button>
        ))}
        {!query && (
          <div className="text-center text-gray-600 text-sm py-8">Начните вводить название мерчанта</div>
        )}
      </div>
    </div>
  )
})
