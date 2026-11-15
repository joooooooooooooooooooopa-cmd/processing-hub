-- Daily delta
-- Engine: PostgreSQL, orders; Metabase field filters period/merchant/provider/method/currency/bank/amount/op_type

WITH daily AS (
  SELECT 
    (orders.created_at AT TIME ZONE 'Europe/Moscow')::date AS day,
    COUNT(*) AS total,
    COUNT(CASE WHEN orders.requisites IS NOT NULL THEN 1 END) AS issued,
    COUNT(CASE WHEN orders.status = 'closed' THEN 1 END) AS success,
    ROUND(COUNT(CASE WHEN orders.status = 'closed' THEN 1 END) * 100.0 /
      NULLIF(COUNT(CASE WHEN orders.requisites IS NOT NULL THEN 1 END), 0), 1) AS conv,
    ROUND(SUM(CASE WHEN orders.status = 'closed' THEN orders.amount ELSE 0 END)::numeric, 0) AS turnover,
    ROUND(SUM(CASE WHEN orders.status = 'closed' THEN ABS(orders.amount - (orders.merchant_coins * orders.merchant_currency_rate))
    - CASE WHEN orders.exchange_platform_amount IS NOT NULL
           THEN ABS(orders.amount - orders.exchange_platform_amount)
           ELSE ABS(COALESCE(orders.trader_amount, 0))
      END ELSE 0 END)::numeric, 0) AS profit
  FROM orders
LEFT JOIN merchants ON orders.merchant_id = merchants.id
LEFT JOIN exchange_platforms ON orders.exchange_platform_id = exchange_platforms.id
WHERE orders.status != 'deleted'
  AND orders.type = 'deposit'
  [[AND {{period}}]]
  [[AND {{merchant}}]]
  [[AND {{provider}}]]
  [[AND {{method}}]]
  [[AND {{currency}}]]
  [[AND {{bank}}]]
  [[AND orders.amount >= {{amount_from}}]]
  [[AND orders.amount <= {{amount_to}}]]
  [[AND {{op_type}}]]
  GROUP BY day
)
SELECT 
  day AS "Дата",
  total AS "Всего",
  issued AS "Выдано",
  success AS "Успешных",
  conv AS "Конв %",
  turnover AS "Оборот",
  profit AS "Прибыль",
  turnover - LAG(turnover) OVER (ORDER BY day) AS "Δ Оборот",
  profit - LAG(profit) OVER (ORDER BY day) AS "Δ Прибыль",
  ROUND((turnover - LAG(turnover) OVER (ORDER BY day)) * 100.0 / NULLIF(LAG(turnover) OVER (ORDER BY day), 0), 1) AS "Δ Об %",
  ROUND((profit - LAG(profit) OVER (ORDER BY day)) * 100.0 / NULLIF(LAG(profit) OVER (ORDER BY day), 0), 1) AS "Δ Приб %"
FROM daily
ORDER BY day DESC
