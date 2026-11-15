import {
  Home, BarChart3, Users, Store, Bell,
} from 'lucide-react'
import type { TabId } from '../types'

const TABS: { id: TabId; label: string; Icon: React.FC<{ size?: number; className?: string }> }[] = [
  { id: 'home', label: 'Главная', Icon: Home },
  { id: 'analytics', label: 'Аналитика', Icon: BarChart3 },
  { id: 'traders', label: 'Трейдеры', Icon: Users },
  { id: 'merchants', label: 'Мерчанты', Icon: Store },
  { id: 'alerts', label: 'Алерты', Icon: Bell },
]

interface Props {
  active: TabId
  onChange: (tab: TabId) => void
  alertCount?: number
}

export default function TabBar({ active, onChange, alertCount = 0 }: Props) {
  return (
    <div
      className="flex"
      style={{
        background: 'rgba(5, 5, 5, 0.92)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderTop: '1px solid rgba(16, 185, 129, 0.06)',
        paddingBottom: 'env(safe-area-inset-bottom, 0)',
      }}
    >
      {TABS.map(tab => {
        const isActive = active === tab.id
        const showBadge = tab.id === 'alerts' && alertCount > 0

        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className="flex-1 flex flex-col items-center pt-2 pb-1.5 gap-0.5 text-xs relative active:opacity-70"
            style={{ color: isActive ? '#34d399' : '#4b5563' }}
          >
            <div className="relative">
              <tab.Icon
                size={22}
                className={`transition-colors duration-200${isActive ? ' drop-shadow-[0_0_6px_rgba(52,211,153,0.4)]' : ''}`}
              />
              {showBadge && (
                <span className="notification-dot" />
              )}
            </div>
            <span
              className="font-semibold transition-colors duration-200"
              style={{ fontSize: 10, color: isActive ? '#34d399' : '#4b5563' }}
            >
              {tab.label}
            </span>
            {isActive && (
              <div
                className="absolute bottom-0 left-1/2 -translate-x-1/2"
                style={{
                  width: '50%',
                  height: 2,
                  borderRadius: 1,
                  background: 'linear-gradient(90deg, transparent, #10b981, transparent)',
                  boxShadow: '0 0 10px rgba(16,185,129,0.5)',
                }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}
