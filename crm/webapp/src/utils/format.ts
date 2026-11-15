/**
 * Общие функции форматирования чисел, процентов, сумм и времени.
 * Используются во всех экранах вместо локальных дублей.
 */

/** Форматирование числа с разделителями (ru-RU) */
export function fmt(n: number | null | undefined, decimals = 0): string {
  if (n == null) return '—'
  return n.toLocaleString('ru-RU', { maximumFractionDigits: decimals })
}

/** Форматирование процентов: "45.23%" */
export function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—'
  return Number(n).toFixed(2) + '%'
}

/** Форматирование суммы: "1.2 млрд", "5.3 млн", "120 тыс" */
export function fmtAmount(n: number | null | undefined): string {
  if (n == null) return '—'
  const v = Number(n)
  if (Math.abs(v) >= 1_000_000_000) return (v / 1_000_000_000).toFixed(1) + ' млрд'
  if (Math.abs(v) >= 1_000_000) return (v / 1_000_000).toFixed(1) + ' млн'
  if (Math.abs(v) >= 1_000) return (v / 1_000).toFixed(0) + ' тыс'
  return v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

/** Короткое число: "1.2M", "5K" */
export function fmtShort(n: number): string {
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

/** Форматирование ISO-даты в "HH:MM" */
export function fmtTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(11, 16)
  }
}
