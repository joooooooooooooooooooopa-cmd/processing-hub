"""
Создание дашборда для биздевов в Metabase
Создаёт все необходимые карточки и дашборд #14
"""
from metabase import get_client, VERIFY_SSL
import requests
import json

def create_card(name, sql, description="", display="scalar", database_id=2):
    """Создать карточку в Metabase"""
    client = get_client()
    headers = client._headers()

    payload = {
        "name": name,
        "description": description,
        "display": display,
        "dataset_query": {
            "database": database_id,
            "type": "native",
            "native": {
                "query": sql,
                "template-tags": {
                    "created_at": {
                        "name": "created_at",
                        "display-name": "Период",
                        "type": "text",
                        "widget-type": "date/all-options",
                        "required": True,
                        "id": "f208220c-70fa-5ee5-b32f-d836942cb9e3",
                        "default": "default"
                    }
                }
            }
        },
        "visualization_settings": {}
    }

    response = requests.post(
        f"{client.base_url}/api/card",
        headers=headers,
        json=payload,
        verify=VERIFY_SSL,
        timeout=30
    )

    if response.ok:
        card = response.json()
        print(f"✅ Создана карточка #{card['id']}: {name}")
        return card['id']
    else:
        print(f"❌ Ошибка создания карточки {name}: {response.status_code}")
        print(response.text[:500])
        return None


# SQL запросы для карточек
CARDS = {
    "bizdev_total_processed": {
        "name": "БизДев: Общая обработка",
        "description": "Всего обработано транзакций (все кроме deleted)",
        "display": "scalar",
        "sql": """
SELECT COUNT(*)
FROM orders
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.status != 'deleted'
"""
    },

    "bizdev_total_profit": {
        "name": "БизДев: Общая прибыль",
        "description": "Общая прибыль по успешным транзакциям",
        "display": "scalar",
        "sql": """
SELECT ROUND(SUM(ABS(orders.amount - (orders.merchant_coins * orders.merchant_currency_rate))
    - CASE
        WHEN orders.exchange_platform_amount IS NOT NULL
        THEN ABS(orders.amount - orders.exchange_platform_amount)
        ELSE ABS(COALESCE(orders.trader_amount, 0))
    END)::numeric, 2)
FROM orders
LEFT JOIN exchange_platforms ON orders.exchange_platform_id = exchange_platforms.id
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.status = 'closed'
"""
    },

    "bizdev_providers_count": {
        "name": "БизДев: Количество провайдеров",
        "description": "Количество провайдеров с обработкой",
        "display": "scalar",
        "sql": """
SELECT COUNT(DISTINCT ep.name)
FROM orders
LEFT JOIN exchange_platforms ep ON orders.exchange_platform_id = ep.id
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.status != 'deleted'
AND ep.name IS NOT NULL
"""
    },

    "bizdev_hourly_issued": {
        "name": "БизДев: Выданные реки по часам",
        "description": "Количество выданных реквизитов в разрезе по часам",
        "display": "bar",
        "sql": """
SELECT
    EXTRACT(HOUR FROM orders.created_at AT TIME ZONE 'Europe/Moscow')::int as hour,
    COUNT(*) as issued_count
FROM orders
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.requisites IS NOT NULL
AND orders.status != 'deleted'
GROUP BY hour
ORDER BY hour
"""
    },

    "bizdev_methods_pie_count": {
        "name": "БизДев: Методы - количество реков",
        "description": "Распределение выданных реквизитов по методам оплаты",
        "display": "pie",
        "sql": """
SELECT
    COALESCE(orders.payment_type, 'Не указано') as method,
    COUNT(*) as count
FROM orders
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.requisites IS NOT NULL
AND orders.status != 'deleted'
GROUP BY orders.payment_type
ORDER BY count DESC
"""
    },

    "bizdev_methods_pie_profit": {
        "name": "БизДев: Методы - прибыль",
        "description": "Распределение прибыли по методам оплаты",
        "display": "pie",
        "sql": """
SELECT
    COALESCE(orders.payment_type, 'Не указано') as method,
    ROUND(SUM(ABS(orders.amount - (orders.merchant_coins * orders.merchant_currency_rate))
        - CASE
            WHEN orders.exchange_platform_amount IS NOT NULL
            THEN ABS(orders.amount - orders.exchange_platform_amount)
            ELSE ABS(COALESCE(orders.trader_amount, 0))
        END)::numeric, 2) as profit
FROM orders
LEFT JOIN exchange_platforms ON orders.exchange_platform_id = exchange_platforms.id
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.status = 'closed'
GROUP BY orders.payment_type
ORDER BY profit DESC
"""
    },

    "bizdev_providers_table": {
        "name": "БизДев: Таблица провайдеров",
        "description": "Детальная статистика по провайдерам",
        "display": "table",
        "sql": """
SELECT
    COALESCE(ep.name, 'Не указано') as provider_name,
    COUNT(*) as total_transactions,
    COUNT(CASE WHEN orders.requisites IS NOT NULL THEN 1 END) as issued,
    COUNT(CASE WHEN orders.status = 'closed' THEN 1 END) as success,
    ROUND(SUM(CASE WHEN orders.requisites IS NOT NULL THEN orders.amount ELSE 0 END)::numeric, 2) as total_issued,
    ROUND(SUM(CASE WHEN orders.status = 'closed' THEN orders.amount ELSE 0 END)::numeric, 2) as total_success,
    ROUND(SUM(CASE WHEN orders.status = 'closed' THEN ABS(amount - (merchant_coins * merchant_currency_rate))
                    - CASE
                        WHEN exchange_platform_amount IS NOT NULL THEN ABS(amount - exchange_platform_amount)
                        ELSE ABS(COALESCE(trader_amount, 0))
                      END ELSE 0 END)::numeric, 2) as profit
FROM orders
LEFT JOIN exchange_platforms ep ON orders.exchange_platform_id = ep.id
WHERE (orders.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 1)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                 - regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int * INTERVAL '1 day'
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND
    CASE
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN split_part({{created_at}}, '~', 2)::date
        WHEN {{created_at}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN {{created_at}}::date
        WHEN {{created_at}} ~ '^past([0-9]+)days$'
            THEN CASE
                WHEN regexp_replace({{created_at}}, 'past([0-9]+)days', '\\1')::int = 0
                    THEN (NOW() AT TIME ZONE 'Europe/Moscow')::date
                ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date - INTERVAL '1 day'
            END
        ELSE (NOW() AT TIME ZONE 'Europe/Moscow')::date
    END
AND orders.status != 'deleted'
GROUP BY ep.name
ORDER BY profit DESC
LIMIT 50
"""
    }
}

if __name__ == "__main__":
    print("=== СОЗДАНИЕ КАРТОЧЕК ДЛЯ ДАШБОРДА БИЗДЕВОВ ===\n")

    card_ids = {}

    for key, config in CARDS.items():
        card_id = create_card(
            name=config["name"],
            sql=config["sql"],
            description=config["description"],
            display=config["display"]
        )
        if card_id:
            card_ids[key] = card_id

    print(f"\n✅ Создано карточек: {len(card_ids)}/{len(CARDS)}")
    print("\nID карточек:")
    for key, card_id in card_ids.items():
        print(f"  {key}: {card_id}")
