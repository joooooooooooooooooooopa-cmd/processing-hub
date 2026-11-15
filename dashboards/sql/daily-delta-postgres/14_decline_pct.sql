-- Decline pct
-- Engine: PostgreSQL, orders; Metabase field filters period/merchant/provider/method/currency/bank/amount/op_type

SELECT ROUND(
  COUNT(CASE WHEN orders.status = 'canceled' THEN 1 END) * 100.0 /
  NULLIF(COUNT(*), 0), 2) AS val
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
