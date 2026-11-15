-- Top merchants
-- Engine: PostgreSQL, orders; Metabase field filters period/merchant/provider/method/currency/bank/amount/op_type

SELECT 
  merchants.name AS "Мерчант",
  COUNT(*) AS "Всего",
  COUNT(CASE WHEN orders.requisites IS NOT NULL THEN 1 END) AS "Выдано",
  COUNT(CASE WHEN orders.status = 'closed' THEN 1 END) AS "Успешных",
  ROUND(COUNT(CASE WHEN orders.status = 'closed' THEN 1 END) * 100.0 /
    NULLIF(COUNT(CASE WHEN orders.requisites IS NOT NULL THEN 1 END), 0), 1) AS "Конверсия %",
  ROUND(SUM(CASE WHEN orders.status = 'closed' THEN orders.amount ELSE 0 END)::numeric, 0) AS "Оборот",
  ROUND(SUM(CASE WHEN orders.status = 'closed' THEN ABS(orders.amount - (orders.merchant_coins * orders.merchant_currency_rate))
    - CASE WHEN orders.exchange_platform_amount IS NOT NULL
           THEN ABS(orders.amount - orders.exchange_platform_amount)
           ELSE ABS(COALESCE(orders.trader_amount, 0))
      END ELSE 0 END)::numeric, 0) AS "Прибыль"
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
GROUP BY merchants.name
ORDER BY "Оборот" DESC
LIMIT 15
