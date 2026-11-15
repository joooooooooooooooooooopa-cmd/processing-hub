interface SubTab {
  id: string
  label: string
  badge?: number
}

interface Props {
  tabs: SubTab[]
  active: string
  onChange: (id: string) => void
}

/** Horizontal scrollable sub-tab navigation bar */
export default function SubTabBar({ tabs, active, onChange }: Props) {
  return (
    <div className="sub-tab-bar">
      {tabs.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`sub-tab ${active === tab.id ? 'sub-tab-active' : ''}`}
        >
          {tab.label}
          {tab.badge != null && tab.badge > 0 && (
            <span
              className="inline-flex items-center justify-center ml-1.5 min-w-[16px] h-4 px-1 rounded-full text-[9px] font-bold"
              style={{
                background: active === tab.id ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.2)',
                color: active === tab.id ? '#34d399' : '#ef4444',
              }}
            >
              {tab.badge}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
