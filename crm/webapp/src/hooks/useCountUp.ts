import { useState, useEffect, useRef } from 'react'

/**
 * Smoothly animates a number from its previous value to the target.
 * Uses easeOutCubic for natural deceleration.
 */
export function useCountUp(target: number | null, duration = 800): number {
  const [display, setDisplay] = useState(target ?? 0)
  const prevRef = useRef(target ?? 0)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (target == null) return
    const start = prevRef.current
    const diff = target - start
    if (Math.abs(diff) < 0.5) {
      setDisplay(target)
      prevRef.current = target
      return
    }

    const startTime = performance.now()
    const step = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      // easeOutCubic
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(start + diff * eased)
      if (progress < 1) rafRef.current = requestAnimationFrame(step)
      else prevRef.current = target
    }
    rafRef.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, duration])

  return display
}
