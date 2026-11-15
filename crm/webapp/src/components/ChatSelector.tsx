import { useState } from 'react'
import BottomSheet from './BottomSheet'

export interface ChatPreview {
  index: number
  name: string
  id: number | string
  message_count: number
  is_business: boolean
}

interface Props {
  chats: ChatPreview[]
  onConfirm: (selectedIndices: number[]) => void
  onClose: () => void
}

function isBizChat(name: string): boolean {
  const n = name.toLowerCase()
  if (!n.includes('processinghub')) return false
  if (n.includes('tech')) return false
  return ['business', 'buisness', 'integration', ' x ', ' | ', ' & '].some(x => n.includes(x))
}

export { isBizChat }

export default function ChatSelector({ chats, onConfirm, onClose }: Props) {
  const [selected, setSelected] = useState<Set<number>>(() => {
    const biz = new Set<number>()
    chats.forEach(c => { if (c.is_business) biz.add(c.index) })
    return biz
  })

  const toggle = (idx: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const selectAll = () => setSelected(new Set(chats.map(c => c.index)))
  const deselectAll = () => setSelected(new Set())

  const totalMessages = chats
    .filter(c => selected.has(c.index))
    .reduce((sum, c) => sum + c.message_count, 0)

  return (
    <BottomSheet title="Выберите чаты для анализа" onClose={onClose}>
      <div className="space-y-3">
        {/* Select all / deselect */}
        <div className="flex gap-2">
          <button
            onClick={selectAll}
            className="px-3 py-1 rounded-lg text-[11px] bg-[#111827] text-emerald-400 border border-emerald-500/10 transition-all active:bg-emerald-500/20"
          >
            Выбрать все
          </button>
          <button
            onClick={deselectAll}
            className="px-3 py-1 rounded-lg text-[11px] bg-[#111827] text-gray-400 border border-emerald-500/10 transition-all active:bg-gray-500/20"
          >
            Снять все
          </button>
          <span className="ml-auto text-[11px] text-gray-500 self-center">
            {selected.size} из {chats.length}
          </span>
        </div>

        {/* Chat list */}
        <div className="space-y-1 max-h-[50vh] overflow-y-auto">
          {chats.map(chat => (
            <button
              key={chat.index}
              onClick={() => toggle(chat.index)}
              className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all ${
                selected.has(chat.index)
                  ? 'bg-emerald-500/10 border border-emerald-500/20'
                  : 'bg-[#111827] border border-transparent'
              }`}
            >
              <div className={`w-4 h-4 rounded flex-shrink-0 border flex items-center justify-center ${
                selected.has(chat.index)
                  ? 'bg-emerald-500 border-emerald-500'
                  : 'border-gray-600'
              }`}>
                {selected.has(chat.index) && (
                  <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="truncate text-white text-xs">{chat.name}</div>
                <div className="text-[10px] text-gray-500">
                  {chat.message_count} сообщ.
                  {chat.is_business && <span className="ml-1 text-emerald-500">biz</span>}
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* Confirm */}
        <button
          onClick={() => onConfirm(Array.from(selected))}
          disabled={selected.size === 0}
          className="w-full py-3 rounded-xl font-semibold text-sm text-white bg-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.25)] transition-all active:bg-emerald-600 disabled:opacity-40"
        >
          Обработать {selected.size} чатов ({totalMessages} сообщ.)
        </button>
      </div>
    </BottomSheet>
  )
}
