-- Conversion to issued
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT ROUND(COUNT(CASE WHEN status IN ('process', 'closed') THEN 1 END) * 100.0 / COUNT(*), 2)
FROM orders_analytics
WHERE toDate(created_at, 'Europe/Moscow') = toDate(now(), 'Europe/Moscow')
AND status != 'deleted'
