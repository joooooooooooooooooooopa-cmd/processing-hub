import { useEffect } from 'react'

interface Props {
  title: string
  onClose: () => void
  children: React.ReactNode
}

export default function BottomSheet({ title, onClose, children }: Props) {
  useEffect(() => {
    const handler = (e: TouchEvent) => {
      const el = document.getElementById('bottom-sheet-inner')
      if (el && !el.contains(e.target as Node)) onClose()
    }
    document.addEventListener('touchstart', handler)
    return () => document.removeEventListener('touchstart', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-end backdrop-blur-sm"
      style={{ background: 'rgba(0,0,0,0.7)' }}
    >
      <div
        id="bottom-sheet-inner"
        className="w-full rounded-t-3xl p-4"
        style={{
          background: '#0d1117',
          maxHeight: '80vh',
          overflowY: 'auto',
          borderTop: '1px solid rgba(16,185,129,0.2)',
          boxShadow: '0 -4px 20px rgba(16,185,129,0.1)',
        }}
      >
        <div className="flex items-center justify-between mb-4">
          <span className="font-semibold text-base" style={{ color: '#f0fdf4' }}>
            {title}
          </span>
          <button
            onClick={onClose}
            className="text-2xl leading-none transition-colors duration-200 rounded-full w-8 h-8 flex items-center justify-center"
            style={{
              color: '#10b981',
              background: 'rgba(16,185,129,0.1)',
            }}
          >
            &times;
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
