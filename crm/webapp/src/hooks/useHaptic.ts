/**
 * Hook for Telegram WebApp haptic feedback.
 * Safely wraps calls — no-ops outside Telegram.
 */
export function useHaptic() {
  const tg = (window as any).Telegram?.WebApp

  const impact = (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft' = 'medium') => {
    try { tg?.HapticFeedback?.impactOccurred(style) } catch {}
  }

  const notification = (type: 'success' | 'warning' | 'error' = 'success') => {
    try { tg?.HapticFeedback?.notificationOccurred(type) } catch {}
  }

  const selection = () => {
    try { tg?.HapticFeedback?.selectionChanged() } catch {}
  }

  return { impact, notification, selection }
}
