import { useEffect, useState } from 'react'
import { CalendarDays, Clock, Building2, XCircle, CalendarRange, CalendarCheck, CreditCard, AlertTriangle, Coins, MessageSquare } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import { api } from '../api/client'
import type { WeeklyData, ChatGroup } from '../types'
import Spinner from '../components/Spinner'
import { fmt, fmtPct, fmtAmount, fmtTime } from '../utils/format'

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({
  title,
  icon,
  loading,
  children,
}: {
  title: string
  icon: React.ReactNode
  loading: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-2xl overflow-hidden bg-surface border border-em-500/10">
      {/* Clickable header block */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-4 text-left active:opacity-70"
        style={{ WebkitTapHighlightColor: 'transparent' }}
      >
        <span className="flex-shrink-0 text-em-400">{icon}</span>
        <span className="flex-1 text-sm font-semibold text-text-1">
          {title}
        </span>
        <span
          className="flex-shrink-0 text-lg font-bold text-em-400"
          style={{
            transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
            display: 'inline-block',
          }}
        >
          ›
        </span>
      </button>

      {/* Expanded content */}
      {open && (
        <div className="px-3 pb-4 pt-1 bg-surface/50 rounded-b-2xl border-t border-em-500/5">
          {loading ? (
            <div className="flex justify-center py-6"><Spinner size={22} /></div>
          ) : children}
        </div>
      )}
    </div>
  )
}

// ── Generic table ─────────────────────────────────────────────────────────────

const COL_LABELS: Record<string, string> = {
  day: 'День', orders: 'Заявки', successful: 'Успешн.', amount: 'Сумма',
  conversion_pct: 'Конв.%', hour: 'Час', bank: 'Банк', reason: 'Причина',
  count: 'Кол-во', merchant: 'Мерчант', method: 'Метод', rate: 'Ставка',
}

function DataTable({ rows }: { rows: Record<string, any>[] }) {
  if (!rows || rows.length === 0)
    return (
      <p className="text-xs py-3 text-center text-text-3">
        Нет данных
      </p>
    )

  const cols = Object.keys(rows[0])
  return (
    <div className="rounded-xl overflow-hidden text-xs overflow-x-auto">
      {/* Header */}
      <div className="flex px-3 py-2 gap-2 font-semibold bg-em-500/10 text-em-400 text-xs uppercase tracking-wider" style={{ minWidth: 'max-content' }}>
        {cols.map((c, idx) => (
          <span
            key={c}
            className={idx === 0 ? '' : 'text-right'}
            style={{ minWidth: idx === 0 ? 80 : 70, flexShrink: 0, whiteSpace: 'nowrap' }}
          >
            {COL_LABELS[c.toLowerCase()] ?? c}
          </span>
        ))}
      </div>
      {/* Rows */}
      {rows.map((row, i) => (
        <div
          key={i}
          className={`flex px-3 py-2 gap-2 border-b border-em-500/5 ${i % 2 === 1 ? 'bg-surface/30' : 'bg-transparent'}`}
          style={{ minWidth: 'max-content' }}
        >
          {cols.map((c, idx) => {
            const val = row[c]
            const isNum = typeof val === 'number'
            return (
              <span
                key={c}
                className={`${idx === 0 ? '' : 'text-right'} ${isNum ? 'text-text-1 font-mono' : 'text-text-3'}`}
                style={{ minWidth: idx === 0 ? 80 : 70, flexShrink: 0, whiteSpace: 'nowrap' }}
              >
                {isNum
                  ? (String(c).toLowerCase().includes('pct') || String(c).toLowerCase().includes('%') || String(c).toLowerCase().includes('conv'))
                    ? fmtPct(val)
                    : String(c).toLowerCase().includes('sum') || String(c).toLowerCase().includes('amount') || String(c).toLowerCase().includes('сумм')
                      ? fmtAmount(val)
                      : fmt(val)
                  : String(val ?? '—')}
              </span>
            )
          })}
        </div>
      ))}
    </div>
  )
}

// ── KPI mini cards ────────────────────────────────────────────────────────────

function MiniKpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface/80 backdrop-blur-sm border border-em-500/10 rounded-2xl p-3 flex flex-col gap-1">
      <div className="text-xs text-text-3 uppercase tracking-wider">{label}</div>
      <div className="text-sm font-bold text-text-1">{value}</div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Analytics() {
  const [compareRows, setCompareRows] = useState<Record<string, any>[] | null>(null)
  const [hourlyRows, setHourlyRows] = useState<Record<string, any>[] | null>(null)
  const [banksRows, setBanksRows] = useState<Record<string, any>[] | null>(null)
  const [canceledRows, setCanceledRows] = useState<Record<string, any>[] | null>(null)
  const [weekly, setWeekly] = useState<WeeklyData | null>(null)
  const [monthly, setMonthly] = useState<Record<string, any> | null>(null)
  const [unpaid, setUnpaid] = useState<Record<string, any> | null>(null)
  const [badClients, setBadClients] = useState<Record<string, any>[] | null>(null)
  const [rates, setRates] = useState<Record<string, any>[] | null>(null)
  const [chats, setChats] = useState<ChatGroup[] | null>(null)

  const [loading, setLoading] = useState<Record<string, boolean>>({
    compare: true, hourly: true, banks: true, canceled: true,
    weekly: true, monthly: true, unpaid: true, badClients: true,
    rates: true, chats: true,
  })

  const setDone = (key: string) =>
    setLoading(prev => ({ ...prev, [key]: false }))

  useEffect(() => {
    api.analytics.compareYesterday().then(setCompareRows).catch(() => setCompareRows([])).finally(() => setDone('compare'))
    api.analytics.hourly().then(rows => setHourlyRows(rows as Record<string, any>[])).catch(() => setHourlyRows([])).finally(() => setDone('hourly'))
    api.analytics.banks().then(setBanksRows).catch(() => setBanksRows([])).finally(() => setDone('banks'))
    api.analytics.canceled().then(setCanceledRows).catch(() => setCanceledRows([])).finally(() => setDone('canceled'))
    api.analytics.weekly().then(setWeekly).catch(() => setWeekly(null)).finally(() => setDone('weekly'))
    api.analytics.monthly().then(setMonthly).catch(() => setMonthly(null)).finally(() => setDone('monthly'))
    api.analytics.unpaid().then(setUnpaid).catch(() => setUnpaid(null)).finally(() => setDone('unpaid'))
    api.analytics.badClients().then(setBadClients).catch(() => setBadClients([])).finally(() => setDone('badClients'))
    api.analytics.rates().then(setRates).catch(() => setRates([])).finally(() => setDone('rates'))
    api.messages.list().then(setChats).catch(() => setChats([])).finally(() => setDone('chats'))
  }, [])

  // Convert unpaid dict to rows
  const unpaidRows: Record<string, any>[] = unpaid
    ? Object.entries(unpaid).map(([merchant, orders]) => ({
        Мерчант: merchant,
        'Кол-во': Array.isArray(orders) ? orders.length : 0,
      }))
    : []

  // Monthly KPIs
  const monthlyKpis = monthly
    ? Object.entries(monthly)
        .filter(([, v]) => v != null && v !== '')
        .map(([k, v]) => ({ label: k, value: typeof v === 'number' ? (k.toLowerCase().includes('conv') || k.toLowerCase().includes('%') || k.toLowerCase().includes('pct') ? fmtPct(v) : fmtAmount(v)) : String(v) }))
    : []

  // Weekly KPIs
  const weeklyKpis = weekly?.summary
    ? Object.entries(weekly.summary)
        .filter(([, v]) => v != null && v !== '')
        .map(([k, v]) => ({ label: k, value: typeof v === 'number' ? (k.toLowerCase().includes('conv') || k.toLowerCase().includes('%') || k.toLowerCase().includes('pct') ? fmtPct(v) : fmtAmount(v)) : String(v) }))
    : []

  return (
    <div className="pb-24 space-y-6 bg-bg min-h-screen">
      <AppHeader title="Аналитика" />
      <div className="px-4 space-y-6">

      {/* Сравнение с вчера */}
      <Section title="Сравнение сегодня / вчера" icon={<CalendarDays size={20} />} loading={loading.compare}>
        <DataTable rows={compareRows || []} />
      </Section>

      {/* Почасовая */}
      <Section title="Почасовая статистика" icon={<Clock size={20} />} loading={loading.hourly}>
        <DataTable rows={hourlyRows || []} />
      </Section>

      {/* По банкам */}
      <Section title="По банкам" icon={<Building2 size={20} />} loading={loading.banks}>
        <DataTable rows={banksRows || []} />
      </Section>

      {/* Причины отмен */}
      <Section title="Причины отмен" icon={<XCircle size={20} />} loading={loading.canceled}>
        <DataTable rows={canceledRows || []} />
      </Section>

      {/* Неделя */}
      <Section title="Неделя — сводка" icon={<CalendarRange size={20} />} loading={loading.weekly}>
        {weeklyKpis.length > 0 && (
          <div className="grid grid-cols-2 gap-3 mb-3">
            {weeklyKpis.map(k => (
              <MiniKpi key={k.label} label={k.label} value={k.value} />
            ))}
          </div>
        )}
        {weekly?.by_day && weekly.by_day.length > 0 && (
          <DataTable rows={weekly.by_day} />
        )}
        {(!weeklyKpis.length && !weekly?.by_day?.length) && (
          <p className="text-xs py-3 text-center text-text-3">Нет данных</p>
        )}
      </Section>

      {/* Месяц */}
      <Section title="Месяц — сводка" icon={<CalendarCheck size={20} />} loading={loading.monthly}>
        {monthlyKpis.length > 0 ? (
          <div className="grid grid-cols-2 gap-3">
            {monthlyKpis.map(k => (
              <MiniKpi key={k.label} label={k.label} value={k.value} />
            ))}
          </div>
        ) : (
          <p className="text-xs py-3 text-center text-text-3">Нет данных</p>
        )}
      </Section>

      {/* Неоплаченные */}
      <Section title="Неоплаченные заказы" icon={<CreditCard size={20} />} loading={loading.unpaid}>
        <DataTable rows={unpaidRows} />
      </Section>

      {/* Плохие клиенты */}
      <Section title="Проблемные клиенты" icon={<AlertTriangle size={20} />} loading={loading.badClients}>
        <DataTable rows={badClients || []} />
      </Section>

      {/* Ставки по методам */}
      <Section title="Ставки по методам оплаты" icon={<Coins size={20} />} loading={loading.rates}>
        <DataTable rows={rates || []} />
      </Section>

      {/* Чаты */}
      <Section title="Рабочие чаты" icon={<MessageSquare size={20} />} loading={loading.chats}>
        {chats && chats.length > 0 ? (
          <div className="space-y-4">
            {chats.map(group => (
              <div key={group.id}>
                <div className="flex items-center gap-2 px-3 py-2 rounded-t-xl font-semibold text-sm bg-em-500/20 border border-em-500/10 text-text-1">
                  <span className="flex-1 truncate">{group.name || `Группа ${group.id}`}</span>
                  {group.type && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-em-500/20 text-em-400">{group.type}</span>
                  )}
                </div>
                <div className="rounded-b-xl overflow-hidden bg-surface-2">
                  {group.messages.length === 0 ? (
                    <p className="text-xs px-3 py-2 text-text-3">
                      Нет сообщений
                    </p>
                  ) : (
                    group.messages.map((msg, i) => (
                      <div
                        key={msg.id || i}
                        className="px-3 py-2 text-xs"
                        style={{ borderTop: i > 0 ? '1px solid rgba(16,185,129,0.05)' : undefined }}
                      >
                        <div className="flex items-baseline gap-2 mb-0.5">
                          <span className="font-medium flex-shrink-0 text-em-400">
                            {msg.sender || 'Unknown'}
                          </span>
                          <span className="text-xs flex-shrink-0 text-text-3">
                            {fmtTime(msg.created_at)}
                          </span>
                        </div>
                        <div className="text-text-1" style={{ wordBreak: 'break-word' }}>
                          {msg.text}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : chats !== null ? (
          <p className="text-xs py-3 text-center text-text-3">
            Нет подключённых групп
          </p>
        ) : null}
      </Section>
      </div>
    </div>
  )
}
