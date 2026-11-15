import { useState, lazy, Suspense, useEffect } from 'react'
import AppHeader from '../components/AppHeader'
import Spinner from '../components/Spinner'
import { api } from '../api/client'
import type { AlertsSubTab } from '../types'

const LiveMonitor = lazy(() => import('./LiveMonitor'))
const IncidentList = lazy(() => import('./IncidentList'))

interface Props {
  active?: boolean
  onIncidentSelect?: (id: string) => void
  defaultSubTab?: AlertsSubTab
}

const SUB_TABS: { id: AlertsSubTab; label: string }[] = [
  { id: 'live', label: 'Live' },
  { id: 'incidents', label: 'Инциденты' },
]

const fallback = (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '80px 0' }}>
    <Spinner size={28} />
  </div>
)

export default function AlertsCombined({ active = true, onIncidentSelect, defaultSubTab = 'live' }: Props) {
  const [subTab, setSubTab] = useState<AlertsSubTab>(defaultSubTab)
  const [mounted, setMounted] = useState<Set<AlertsSubTab>>(() => new Set([defaultSubTab]))
  const [openCount, setOpenCount] = useState<number | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    api.incidents.list({ status: 'open', limit: 1 }).then(res => { if (!cancelled) setOpenCount(res.total) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const handleTabChange = (tab: AlertsSubTab) => {
    setSubTab(tab)
    setMounted(prev => { if (prev.has(tab)) return prev; const next = new Set(prev); next.add(tab); return next })
  }

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppHeader title="Мониторинг">
        {subTab === 'live' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 999, background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.20)' }}>
            <span className="live-dot" />
            <span className="mono" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.10em', color: 'var(--em-400)' }}>LIVE</span>
          </div>
        )}
      </AppHeader>

      {/* Segment control */}
      <div style={{ padding: '4px 12px 8px', position: 'sticky', top: 0, zIndex: 20, background: 'rgba(8,9,11,0.95)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}>
        <div className="seg">
          {SUB_TABS.map(tab => (
            <button key={tab.id} className={subTab === tab.id ? 'on' : ''} onClick={() => handleTabChange(tab.id)}>
              {tab.label}
              {tab.id === 'incidents' && openCount != null && openCount > 0 && (
                <span className="mono" style={{ marginLeft: 6, padding: '0 5px', borderRadius: 4, background: 'rgba(248,113,113,0.20)', color: 'var(--danger)', fontSize: 9, fontWeight: 700 }}>{openCount}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, position: 'relative' }}>
        {SUB_TABS.map(({ id }) => {
          if (!mounted.has(id)) return null
          const isActive = subTab === id
          return (
            <div key={id} style={{ display: isActive ? 'block' : 'none' }}>
              <Suspense fallback={fallback}>
                {id === 'live' && <LiveMonitor active={isActive && active} />}
                {id === 'incidents' && <IncidentList onSelect={onIncidentSelect ?? (() => {})} />}
              </Suspense>
            </div>
          )
        })}
      </div>
    </div>
  )
}
