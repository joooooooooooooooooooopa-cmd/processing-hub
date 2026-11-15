-- Successful
-- Engine: PostgreSQL, orders; Metabase field filters period/merchant/provider/method/currency/bank/amount/op_type

SELECT COUNT(*) AS val FROM orders
LEFT JOIN merchants ON orders.merchant_id = merchants.id
LEFT JOIN exchange_platforms ON orders.exchange_platform_id = exchange_platforms.id
WHERE orders.status = 'closed'
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
