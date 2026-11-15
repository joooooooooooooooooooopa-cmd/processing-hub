/** Skeleton shimmer placeholders for loading states */

export function SkeletonLine({ width = '100%', height = 14 }: { width?: string | number; height?: number }) {
  return <div className="skeleton" style={{ width, height }} />
}

export function SkeletonCard({ height = 100 }: { height?: number }) {
  return <div className="skeleton-card" style={{ height }} />
}

/** KPI card skeleton — mimics the hero metric layout */
export function SkeletonKpiCard() {
  return (
    <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl p-4 space-y-2">
      <div className="skeleton" style={{ width: '60%', height: 10 }} />
      <div className="skeleton" style={{ width: '80%', height: 24 }} />
      <div className="skeleton" style={{ width: '40%', height: 10 }} />
    </div>
  )
}

/** Hero section skeleton — for the main big number at top */
export function SkeletonHero() {
  return (
    <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl p-5 space-y-4 animate-fade-in">
      <div className="flex flex-col items-center gap-2">
        <div className="skeleton" style={{ width: 80, height: 10 }} />
        <div className="skeleton" style={{ width: 160, height: 36 }} />
        <div className="skeleton" style={{ width: 60, height: 10 }} />
      </div>
      <div className="grid grid-cols-3 gap-3 pt-3 border-t border-emerald-500/5">
        {[0, 1, 2].map(i => (
          <div key={i} className="flex flex-col items-center gap-1.5">
            <div className="skeleton" style={{ width: 50, height: 8 }} />
            <div className="skeleton" style={{ width: 40, height: 18 }} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** Chart skeleton */
export function SkeletonChart({ height = 180 }: { height?: number }) {
  return (
    <div className="bg-gradient-to-br from-[#0d1117] to-[#0a0f14] border border-emerald-500/10 rounded-2xl p-4 space-y-2">
      <div className="skeleton" style={{ width: '40%', height: 10 }} />
      <div className="skeleton" style={{ width: '100%', height }} />
    </div>
  )
}

/** Dashboard skeleton — full page placeholder */
export function SkeletonDashboard() {
  return (
    <div className="px-4 space-y-4 animate-fade-in">
      <SkeletonHero />
      <div className="grid grid-cols-2 gap-3">
        <SkeletonKpiCard />
        <SkeletonKpiCard />
      </div>
      <SkeletonChart />
      <SkeletonChart height={120} />
    </div>
  )
}

/** List item skeleton */
export function SkeletonListItem() {
  return (
    <div className="bg-[#0d1117] border border-emerald-500/10 rounded-2xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className="skeleton" style={{ width: '60%', height: 14 }} />
        <div className="skeleton" style={{ width: 50, height: 20, borderRadius: 20 }} />
      </div>
      <div className="flex gap-3">
        <div className="skeleton" style={{ width: 60, height: 10 }} />
        <div className="skeleton" style={{ width: 40, height: 10 }} />
      </div>
    </div>
  )
}

/** List skeleton — multiple items */
export function SkeletonList({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2 animate-fade-in">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonListItem key={i} />
      ))}
    </div>
  )
}
