import { useState, useCallback, lazy, Suspense } from 'react'
import AppHeader from '../components/AppHeader'
import Spinner from '../components/Spinner'
import type { AnalyticsSubTab } from '../types'

const Dashboard = lazy(() => import('./Dashboard'))
const Analytics = lazy(() => import('./Analytics'))
const Heatmap = lazy(() => import('./Heatmap'))
const Funnel = lazy(() => import('./Funnel'))
const ComparePeriods = lazy(() => import('./ComparePeriods'))
const BizDev = lazy(() => import('./BizDev'))

const SUB_TABS: { id: AnalyticsSubTab; label: string }[] = [
  { id: 'overview', label: 'Обзор' },
  { id: 'details', label: 'Детали' },
  { id: 'heatmap', label: 'Тепло' },
  { id: 'funnel', label: 'Воронка' },
  { id: 'compare', label: 'Сравнение' },
  { id: 'bizdev', label: 'БизДев' },
]

function LoadingFallback() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
      <Spinner />
    </div>
  )
}

function SubPane({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <div
      style={{
        position: 'absolute', inset: 0, overflowY: 'auto',
        zIndex: active ? 10 : 0,
        opacity: active ? 1 : 0,
        visibility: active ? 'visible' : 'hidden',
        pointerEvents: active ? 'auto' : 'none',
        transition: 'opacity 0.15s ease',
      }}
    >
      {children}
    </div>
  )
}

interface Props {
  active?: boolean
  onMerchantSelect?: (id: number) => void
  onIncidentSelect?: (id: string) => void
}

export default function AnalyticsCombined({ active, onMerchantSelect, onIncidentSelect }: Props) {
  const [activeTab, setActiveTab] = useState<AnalyticsSubTab>('overview')
  const [visited, setVisited] = useState<AnalyticsSubTab[]>(['overview'])

  const handleTabChange = useCallback((tab: AnalyticsSubTab) => {
    setActiveTab(tab)
    setVisited(prev => (prev.includes(tab) ? prev : [...prev, tab]))
  }, [])

  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppHeader title="Аналитика" />

      {/* Segment control */}
      <div style={{ padding: '4px 12px 8px', position: 'sticky', top: 0, zIndex: 20, background: 'rgba(8,9,11,0.95)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}>
        <div style={{ display: 'flex', overflowX: 'auto', gap: 0, paddingBottom: 2 }}>
          <div className="seg" style={{ flexShrink: 0 }}>
            {SUB_TABS.map(tab => (
              <button
                key={tab.id}
                className={activeTab === tab.id ? 'on' : ''}
                onClick={() => handleTabChange(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, position: 'relative' }}>
        <Suspense fallback={<LoadingFallback />}>
          {visited.includes('overview') && (
            <SubPane active={activeTab === 'overview'}>
              <Dashboard active={active && activeTab === 'overview'} onMerchantSelect={onMerchantSelect} onIncidentSelect={onIncidentSelect} />
            </SubPane>
          )}
          {visited.includes('details') && (
            <SubPane active={activeTab === 'details'}>
              <Analytics />
            </SubPane>
          )}
          {visited.includes('heatmap') && (
            <SubPane active={activeTab === 'heatmap'}>
              <Heatmap />
            </SubPane>
          )}
          {visited.includes('funnel') && (
            <SubPane active={activeTab === 'funnel'}>
              <Funnel />
            </SubPane>
          )}
          {visited.includes('compare') && (
            <SubPane active={activeTab === 'compare'}>
              <ComparePeriods />
            </SubPane>
          )}
          {visited.includes('bizdev') && (
            <SubPane active={activeTab === 'bizdev'}>
              <BizDev />
            </SubPane>
          )}
        </Suspense>
      </div>
    </div>
  )
}
