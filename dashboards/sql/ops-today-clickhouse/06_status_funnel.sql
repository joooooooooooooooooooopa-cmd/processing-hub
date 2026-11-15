-- Status funnel
-- Engine: ClickHouse, orders_analytics; Moscow-time 'today' window

SELECT
    CASE
        WHEN status = 'closed' THEN '1. Успешные'
        WHEN status = 'process' THEN '2. В обработке'
        WHEN status = 'canceled' THEN '3. Отменённые'
        WHEN status = 'failed' THEN '4. Проваленные'
        ELSE '5. Прочие'
    END as status_label,
    COUNT(*) as count
FROM orders_analytics
WHERE toDate(created_at, 'Europe/Moscow') = toDate(now(), 'Europe/Moscow')
AND status != 'deleted'
GROUP BY status_label
ORDER BY status_label
