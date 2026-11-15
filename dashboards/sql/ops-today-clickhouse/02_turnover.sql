-- Turnover
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT ROUND(SUM(amount), 2)
FROM orders_analytics
WHERE toDate(created_at, 'Europe/Moscow') = toDate(now(), 'Europe/Moscow')
AND status = 'closed'
