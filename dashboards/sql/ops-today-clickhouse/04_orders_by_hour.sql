-- Orders by hour
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT
    toHour(created_at, 'Europe/Moscow') as hour,
    COUNT(*) as count
FROM orders_analytics
WHERE toDate(created_at, 'Europe/Moscow') = toDate(now(), 'Europe/Moscow')
AND status != 'deleted'
GROUP BY hour
ORDER BY hour
