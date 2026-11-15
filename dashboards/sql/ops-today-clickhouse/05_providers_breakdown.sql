-- Providers breakdown
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT
    provider_name,
    COUNT(CASE WHEN status IN ('process', 'closed') THEN 1 END) as issued,
    COUNT(CASE WHEN status = 'closed' THEN 1 END) as success,
    ROUND(SUM(CASE WHEN status = 'closed' THEN amount ELSE 0 END), 2) as total,
    ROUND(SUM(CASE WHEN status = 'closed' THEN merchant_amount - COALESCE(trader_amount, 0) ELSE 0 END), 2) as profit
FROM orders_analytics
WHERE toDate(created_at, 'Europe/Moscow') = toDate(now(), 'Europe/Moscow')
AND provider_name IS NOT NULL
GROUP BY provider_name
ORDER BY profit DESC
LIMIT 20
