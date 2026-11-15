import { useState, useEffect, useCallback, lazy, Suspense } from 'react'
import logoCrown from '/logo.svg'
import { api } from './api/client'
import type { TabId } from './types'
import TabBar from './components/TabBar'
import Spinner from './components/Spinner'
import ErrorBoundary from './components/ErrorBoundary'
import StandaloneLogin from './components/StandaloneLogin'

// Lazy-load all screens
const CommandCenter = lazy(() => import('./screens/CommandCenter'))
const AnalyticsCombined = lazy(() => import('./screens/AnalyticsCombined'))
const Traders = lazy(() => import('./screens/Traders'))
const MerchantList = lazy(() => import('./screens/MerchantList'))
const MerchantDetail = lazy(() => import('./screens/MerchantDetail'))
const AlertsCombined = lazy(() => import('./screens/AlertsCombined'))
const IncidentDetail = lazy(() => import('./screens/IncidentDetail'))

const CACHEABLE_TABS: TabId[] = ['home', 'analytics', 'traders', 'merchants', 'alerts']

function ScreenSpinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <Spinner size={28} />
    </div>
  )
}

type Screen =
  | { id: TabId }
  | { id: 'merchant-detail'; merchantId: number }
  | { id: 'incident-detail'; incidentId: string }

function ScreenPane({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <div className={`absolute inset-0 overflow-y-auto ${active ? 'z-10' : 'invisible pointer-events-none z-0'}`}>
      <ErrorBoundary>
        <Suspense fallback={<ScreenSpinner />}>
          {children}
        </Suspense>
      </ErrorBoundary>
    </div>
  )
}

export default function App() {
  const [authState, setAuthState] = useState<'loading' | 'ok' | 'error' | 'need_login'>('loading')
  const [authError, setAuthError] = useState('')
  const [screen, setScreen] = useState<Screen>({ id: 'home' })
  const [visited, setVisited] = useState<string[]>(['home'])
  const [openIncidentCount, setOpenIncidentCount] = useState(0)

  const tg = (window as any).Telegram?.WebApp
  const isStandalone = !tg?.initData

  const checkAuth = () => {
    setAuthState('loading')
    setAuthError('')

    api.auth.verify()
      .then(u => {
        if (u.is_authorized || u.is_admin) {
          setAuthState('ok')
        } else {
          setAuthError('Нет доступа. Обратитесь к администратору.')
          setAuthState('error')
        }
      })
      .catch(e => {
        if (isStandalone && !localStorage.getItem('pwa_auth')) {
          setAuthState('need_login')
        } else {
          setAuthError(e.message || 'Ошибка авторизации')
          setAuthState('error')
        }
      })
  }

  useEffect(() => {
    checkAuth()
  }, [])

  // Prefetch screen chunks after auth
  useEffect(() => {
    if (authState !== 'ok') return
    const t = setTimeout(() => {
      import('./screens/AnalyticsCombined')
      import('./screens/Traders')
      import('./screens/MerchantList')
      import('./screens/AlertsCombined')
      import('./screens/MerchantDetail')
      import('./screens/IncidentDetail')
    }, 2000)
    return () => clearTimeout(t)
  }, [authState])

  // Load incident count for tab badge
  useEffect(() => {
    if (authState !== 'ok') return
    api.incidents.list({ status: 'open', limit: 1 })
      .then(r => setOpenIncidentCount(r.total))
      .catch(() => {})
    // Refresh every 2 minutes
    const interval = setInterval(() => {
      api.incidents.list({ status: 'open', limit: 1 })
        .then(r => setOpenIncidentCount(r.total))
        .catch(() => {})
    }, 120_000)
    return () => clearInterval(interval)
  }, [authState])

  // Track visited cacheable screens
  useEffect(() => {
    if (CACHEABLE_TABS.includes(screen.id as TabId)) {
      setVisited(prev => prev.includes(screen.id) ? prev : [...prev, screen.id])
    }
  }, [screen.id])

  // Telegram back button
  useEffect(() => {
    if (!tg) return
    const isNested = screen.id === 'merchant-detail' || screen.id === 'incident-detail'
    if (isNested) {
      tg.BackButton.show()
    } else {
      tg.BackButton.hide()
    }
  }, [screen, tg])

  useEffect(() => {
    if (!tg) return
    const handler = () => {
      if (screen.id === 'merchant-detail') setScreen({ id: 'merchants' })
      else if (screen.id === 'incident-detail') setScreen({ id: 'alerts' })
    }
    tg.BackButton.onClick(handler)
    return () => tg.BackButton.offClick(handler)
  }, [screen, tg])

  const activeTab: TabId =
    screen.id === 'merchant-detail' ? 'merchants'
    : screen.id === 'incident-detail' ? 'alerts'
    : (screen.id as TabId)

  const onTabChange = useCallback((tab: TabId) => {
    setScreen({ id: tab })
  }, [])

  // Navigation from Command Center
  const onNavigate = useCallback((tab: string) => {
    if (['home', 'analytics', 'traders', 'merchants', 'alerts'].includes(tab)) {
      setScreen({ id: tab as TabId })
    }
  }, [])

  const handleLogin = useCallback((userId: number, accessKey: string) => {
    localStorage.setItem('pwa_auth', JSON.stringify({ userId, accessKey }))
    checkAuth()
  }, [])

  const goToMerchant = useCallback((id: number) => setScreen({ id: 'merchant-detail', merchantId: id }), [])
  const goToIncident = useCallback((id: string) => setScreen({ id: 'incident-detail', incidentId: id }), [])
  const goBackToAlerts = useCallback(() => setScreen({ id: 'alerts' }), [])

  if (authState === 'need_login') {
    return <StandaloneLogin onLogin={handleLogin} />
  }

  if (authState === 'loading') {
    return (
      <div className="bg-grid-pattern" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#050505', gap: '12px' }}>
        <div className="animate-bounce-in" style={{
          width: 80, height: 80, borderRadius: '50%',
          background: 'rgba(16, 185, 129, 0.08)',
          border: '1px solid rgba(16, 185, 129, 0.2)',
          boxShadow: '0 0 24px rgba(16, 185, 129, 0.2)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <img src={logoCrown} alt="ProcessingHub" width={48} height={48} />
        </div>
        <span className="animate-bounce-in" style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '0.05em', background: 'linear-gradient(135deg, #34d399, #10b981)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>ProcessingHub</span>
        <div style={{ width: 60, height: 1, background: 'linear-gradient(90deg, transparent, #10b981, transparent)', opacity: 0.4 }} />
        <div className="animate-fade-in-delayed" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
          <Spinner size={24} />
          <p style={{ color: '#6b7280', fontSize: '12px', letterSpacing: '0.05em' }}>Авторизация...</p>
        </div>
      </div>
    )
  }

  if (authState === 'error') {
    return (
      <div className="bg-grid-pattern" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px', minHeight: '100vh', background: '#050505', gap: '12px' }}>
        <div style={{ width: '48px', height: '48px', borderRadius: '50%', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ fontSize: '20px', color: '#ef4444' }}>!</span>
        </div>
        <p style={{ textAlign: 'center', color: '#ef4444', fontSize: '14px', fontWeight: 500 }}>{authError}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-tg-bg bg-grid-pattern">
      <div className="flex-1 overflow-hidden relative">
        {/* ── Cacheable tab screens ── */}
        {visited.includes('home') && (
          <ScreenPane active={screen.id === 'home'}>
            <CommandCenter
              active={screen.id === 'home'}
              onNavigate={onNavigate}
              onMerchantSelect={goToMerchant}
              onIncidentSelect={goToIncident}
            />
          </ScreenPane>
        )}
        {visited.includes('analytics') && (
          <ScreenPane active={screen.id === 'analytics'}>
            <AnalyticsCombined
              active={screen.id === 'analytics'}
              onMerchantSelect={goToMerchant}
              onIncidentSelect={goToIncident}
            />
          </ScreenPane>
        )}
        {visited.includes('traders') && (
          <ScreenPane active={screen.id === 'traders'}>
            <Traders />
          </ScreenPane>
        )}
        {visited.includes('merchants') && (
          <ScreenPane active={screen.id === 'merchants'}>
            <MerchantList onSelect={goToMerchant} />
          </ScreenPane>
        )}
        {visited.includes('alerts') && (
          <ScreenPane active={screen.id === 'alerts'}>
            <AlertsCombined
              active={screen.id === 'alerts'}
              onIncidentSelect={goToIncident}
            />
          </ScreenPane>
        )}

        {/* ── Detail screens — mount/unmount as usual ── */}
        {screen.id === 'merchant-detail' && (
          <ScreenPane active>
            <MerchantDetail
              merchantId={(screen as any).merchantId}
              onIncident={goToIncident}
            />
          </ScreenPane>
        )}
        {screen.id === 'incident-detail' && (
          <ScreenPane active>
            <IncidentDetail incidentId={(screen as any).incidentId} onBack={goBackToAlerts} />
          </ScreenPane>
        )}
      </div>
      <div className="relative z-50">
        <TabBar active={activeTab} onChange={onTabChange} alertCount={openIncidentCount} />
      </div>
    </div>
  )
}
