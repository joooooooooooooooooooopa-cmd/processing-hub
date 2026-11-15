-- Bad clients: client_id with abnormal fail ratio per merchant
-- Engine: ClickHouse, orders_analytics

WITH client_stats AS (
    SELECT
        merchant_name,
        client_id,
        COUNT(*) as total_orders,
        countIf(status = 'completed') as completed_orders,
        countIf(status IN ('expired', 'cancelled', 'failed')) as failed_orders,
        ROUND(100.0 * countIf(status = 'completed') / COUNT(*), 1) as conversion_pct
    FROM orders_analytics
    WHERE
        created_at >= today() - INTERVAL 30 DAY
        AND client_id IS NOT NULL
        AND client_id != ''
        AND client_id NOT IN ('null', 'undefined', 'None', '0', '1', 'test', 'Test')
    GROUP BY merchant_name, client_id
    HAVING COUNT(*) >= 5
),

-- Мерчанты с анализом client_id
merchant_stats AS (
    SELECT
        merchant_name,
        COUNT(*) as total_orders,
        uniq(client_id) as unique_clients,
        ROUND(100.0 * uniq(client_id) / COUNT(*), 1) as uniqueness_pct
    FROM orders_analytics
    WHERE
        created_at >= today() - INTERVAL 30 DAY
        AND client_id IS NOT NULL
        AND client_id != ''
    GROUP BY merchant_name
    HAVING COUNT(*) >= 10
),

-- Топовый client_id для каждого мерчанта
top_client_per_merchant AS (
    SELECT
        merchant_name,
        client_id,
        COUNT(*) as orders_count
    FROM orders_analytics
    WHERE
        created_at >= today() - INTERVAL 30 DAY
        AND client_id IS NOT NULL
        AND client_id != ''
    GROUP BY merchant_name, client_id
),

-- Мерчанты с заглушками
merchant_with_stubs AS (
    SELECT
        t.merchant_name,
        'ЗАГЛУШКА' as client_id,
        m.total_orders,
        0 as completed_orders,
        0 as failed_orders,
        0.0 as conversion_pct,
        'stub_client_id' as issue_type,
        ROUND(100.0 * MAX(t.orders_count) / m.total_orders, 1) as stub_pct
    FROM top_client_per_merchant t
    JOIN merchant_stats m ON t.merchant_name = m.merchant_name
    GROUP BY t.merchant_name, m.total_orders
    HAVING stub_pct > 90
),

-- Мерчанты с рандомом
merchant_with_random AS (
    SELECT
        merchant_name,
        'РАНДОМ' as client_id,
        total_orders,
        0 as completed_orders,
        0 as failed_orders,
        0.0 as conversion_pct,
        'random_client_id' as issue_type,
        uniqueness_pct
    FROM merchant_stats
    WHERE uniqueness_pct > 95
),

-- Плохие пользователи
bad_users AS (
    SELECT
        merchant_name,
        client_id,
        total_orders,
        completed_orders,
        failed_orders,
        conversion_pct,
        'bad_user' as issue_type,
        0.0 as stub_pct
    FROM client_stats
    WHERE conversion_pct < 30
)

-- Объединяем результаты
SELECT
    merchant_name,
    client_id,
    total_orders,
    completed_orders,
    failed_orders,
    conversion_pct,
    issue_type
FROM (
    SELECT merchant_name, client_id, total_orders, completed_orders, failed_orders, conversion_pct, issue_type, stub_pct FROM bad_users
    UNION ALL
    SELECT merchant_name, client_id, total_orders, completed_orders, failed_orders, conversion_pct, issue_type, stub_pct FROM merchant_with_stubs
    UNION ALL
    SELECT merchant_name, client_id, total_orders, completed_orders, failed_orders, conversion_pct, issue_type, uniqueness_pct as stub_pct FROM merchant_with_random
)
ORDER BY
    multiIf(
        issue_type = 'bad_user', 1,
        issue_type = 'stub_client_id', 2,
        issue_type = 'random_client_id', 3,
        4
    ),
    conversion_pct ASC,
    total_orders DESC
LIMIT 100;
