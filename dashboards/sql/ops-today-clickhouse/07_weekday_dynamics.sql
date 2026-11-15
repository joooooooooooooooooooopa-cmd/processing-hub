-- Weekday dynamics
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT
    CASE toDayOfWeek(created_at, 'Europe/Moscow')
        WHEN 1 THEN 'Пн'
        WHEN 2 THEN 'Вт'
        WHEN 3 THEN 'Ср'
        WHEN 4 THEN 'Чт'
        WHEN 5 THEN 'Пт'
        WHEN 6 THEN 'Сб'
        WHEN 7 THEN 'Вс'
    END as day_name,
    COUNT(*) as count,
    ROUND(SUM(merchant_amount - COALESCE(trader_amount, 0)), 2) as profit
FROM orders_analytics
WHERE created_at >= toStartOfDay(now(), 'Europe/Moscow') - INTERVAL 7 DAY
AND status = 'closed'
GROUP BY toDayOfWeek(created_at, 'Europe/Moscow')
ORDER BY toDayOfWeek(created_at, 'Europe/Moscow')
