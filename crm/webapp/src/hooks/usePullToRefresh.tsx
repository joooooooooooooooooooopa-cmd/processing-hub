import { useRef, useCallback, useState } from 'react'

interface PullToRefreshOptions {
  onRefresh: () => Promise<void>
  threshold?: number
}

export function usePullToRefresh({ onRefresh, threshold = 60 }: PullToRefreshOptions) {
  const [pulling, setPulling] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [pullDistance, setPullDistance] = useState(0)
  const startY = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (scrollRef.current && scrollRef.current.scrollTop === 0) {
      startY.current = e.touches[0].clientY
      setPulling(true)
    }
  }, [])

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (!pulling || refreshing) return
    const delta = e.touches[0].clientY - startY.current
    if (delta > 0) {
      setPullDistance(Math.min(delta * 0.5, threshold * 1.5))
    }
  }, [pulling, refreshing, threshold])

  const onTouchEnd = useCallback(async () => {
    if (!pulling) return
    if (pullDistance >= threshold && !refreshing) {
      setRefreshing(true)
      setPullDistance(threshold * 0.5)
      try {
        await onRefresh()
      } finally {
        setRefreshing(false)
      }
    }
    setPullDistance(0)
    setPulling(false)
  }, [pulling, pullDistance, threshold, refreshing, onRefresh])

  const PullIndicator = pullDistance > 0 ? (
    <div
      className="flex items-center justify-center overflow-hidden transition-all"
      style={{ height: pullDistance, opacity: Math.min(pullDistance / threshold, 1) }}
    >
      <div
        className={`w-6 h-6 border-2 border-emerald-500/40 border-t-emerald-400 rounded-full ${refreshing ? 'animate-ptr-spin' : ''}`}
        style={{ transform: refreshing ? undefined : `rotate(${(pullDistance / threshold) * 360}deg)` }}
      />
    </div>
  ) : null

  return {
    scrollRef,
    pullHandlers: { onTouchStart, onTouchMove, onTouchEnd },
    PullIndicator,
    refreshing,
  }
}
