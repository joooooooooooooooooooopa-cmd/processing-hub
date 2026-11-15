-- Top payment methods
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT
    payment_type,
    COUNT(*) as count,
    ROUND(SUM(amount), 2) as total,
    ROUND(SUM(merchant_amount - COALESCE(trader_amount, 0)), 2) as profit
FROM orders_analytics
WHERE toDate(created_at, 'Europe/Moscow') = toDate(now(), 'Europe/Moscow')
AND status = 'closed'
AND payment_type IS NOT NULL
GROUP BY payment_type
ORDER BY count DESC
LIMIT 10
