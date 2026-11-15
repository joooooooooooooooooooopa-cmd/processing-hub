export interface MerchantKeys {
  nameKey: string
  totalKey: string | undefined
  successKey: string | undefined
  convKey: string | undefined
  amountKey: string | undefined
  dayKey: string | undefined
}

export interface MerchantRow {
  name: string
  total: number
  successful: number
  conv: number
  amount: number
}

export function parseMerchantKeys(data: Record<string, any>[]): MerchantKeys {
  if (!data || data.length === 0) {
    return { nameKey: '', totalKey: undefined, successKey: undefined, convKey: undefined, amountKey: undefined, dayKey: undefined }
  }

  const keys = Object.keys(data[0])
  return {
    nameKey: keys.find(k => /мерч|merch|name/i.test(k)) || keys[0],
    totalKey: keys.find(k => /всего|total/i.test(k)),
    successKey: keys.find(k => /успеш|success/i.test(k)),
    convKey: keys.find(k => /конверс|conv|pct/i.test(k)),
    amountKey: keys.find(k => /сумм|amount|sum/i.test(k)),
    dayKey: keys.find(k => /day|день|date|дата/i.test(k)),
  }
}

export function parseMerchantRows(data: Record<string, any>[], keys: MerchantKeys): MerchantRow[] {
  return data
    .filter(d => !/итого/i.test(String(d[keys.nameKey] ?? '')))
    .map(d => {
      const total = keys.totalKey ? Number(d[keys.totalKey] ?? 0) : 0
      const successful = keys.successKey ? Number(d[keys.successKey] ?? 0) : 0
      // Parse conv: try convKey first, fallback to successful/total
      let conv = 0
      if (keys.convKey) {
        const raw = d[keys.convKey]
        const parsed = typeof raw === 'string' ? Number(raw.replace('%', '').replace(',', '.')) : Number(raw ?? 0)
        if (!isNaN(parsed) && parsed > 0) conv = parsed
      }
      if (conv === 0 && total > 0) {
        conv = (successful / total) * 100
      }

      return {
        name: String(d[keys.nameKey] ?? ''),
        total,
        successful,
        conv,
        amount: keys.amountKey ? Number(d[keys.amountKey] ?? 0) : 0,
      }
    })
}
