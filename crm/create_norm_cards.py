"""
Создание карточек "Норма конверсии" для Dashboard #13 (Трейдерка)

Норма — базовый уровень конверсии за предыдущие 4 недели.
Учитываются только заявки с выдачей реквизитов ≤ 1 сек (process_time <= 1).
Формула: count(closed) / nullif(count(closed) + count(expired), 0) * 100

Карточки:
1. Скаляр: общая норма конверсии %
2. Таблица: норма по часам
3. Таблица: норма по дням недели
4. Таблица: норма по банкам
5. Таблица: норма по методам
6. Таблица: норма по категориям сумм
7. Таблица: норма по мерчантам
"""

import requests
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD")
DATABASE_ID = 2  # Main DB (PostgreSQL)
DASHBOARD_ID = 13  # Trader dashboard

VERIFY_SSL = False

# ── Template tags (same as existing Dashboard #13 cards + new merchant) ──

TEMPLATE_TAGS = {
    "period": {
        "name": "period",
        "display-name": "Период",
        "type": "text",
        "required": True,
        "widget-type": "date/all-options",
        "id": "6fc40b04-64c1-4af1-b309-44919c5f66c3",
        "default": "2026-02-19"
    },
    "method": {
        "id": "eda0c6ed-dbf7-44cc-ab04-f3f99a898322",
        "name": "method",
        "display-name": "Метод",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
    "bank": {
        "id": "5b603b53-2f33-45f6-bc11-f6bd32b859be",
        "name": "bank",
        "display-name": "Банк",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
    "trader": {
        "id": "6f2702fc-19ec-4707-be63-7829ed133a11",
        "name": "trader",
        "display-name": "Трейдер",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
    "tla": {
        "id": "aeb604df-6c01-4229-a2af-1e604993f494",
        "name": "tla",
        "display-name": "ТЛ (тимлид)",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
    "htl": {
        "id": "98302128-11ab-41dc-8f4f-56f7f916474c",
        "name": "htl",
        "display-name": "ХТЛ (хедтимлид)",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
    "agent": {
        "id": "45f852b5-612a-4dde-b7ad-23a406575cf7",
        "name": "agent",
        "display-name": "Агент",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
    "merchant": {
        "id": "b1c2d3e4-f5a6-7890-abcd-ef1234567890",
        "name": "merchant",
        "display-name": "Мерчант",
        "required": False,
        "type": "text",
        "widget-type": "string/="
    },
}

# ── Common CTE for norm calculation ──
# Uses previous 4 weeks from the selected period date, process_time <= 1
# Matches the same hierarchy/filter pattern as card 177

NORM_BASE_CTE = """WITH h AS (
    SELECT
        child_user_id,
        MAX(CASE WHEN as_role = 'teamlead' THEN parent_user_id END) AS tl_id,
        MAX(CASE WHEN as_role = 'headteam' THEN parent_user_id END) AS htl_id,
        MAX(CASE WHEN as_role = 'agent'    THEN parent_user_id END) AS agent_id
    FROM user_parents
    GROUP BY child_user_id
),
norm_base AS (
    SELECT
        o.amount,
        o.status,
        o.payment_type,
        o.bank,
        o.process_time,
        o.created_at,
        m.name AS merchant_name,
        u.name AS trader_name,
        EXTRACT(HOUR FROM o.created_at AT TIME ZONE 'Europe/Moscow') AS hour_msk,
        EXTRACT(ISODOW FROM o.created_at AT TIME ZONE 'Europe/Moscow') AS dow_msk
    FROM orders o
    JOIN merchants m ON m.id = o.merchant_id AND m.actual = true
    LEFT JOIN users u ON u.id = o.user_id
    LEFT JOIN h ON h.child_user_id = o.user_id
    LEFT JOIN users tl ON tl.id = h.tl_id
    LEFT JOIN users ht ON ht.id = h.htl_id
    LEFT JOIN users ag ON ag.id = h.agent_id
    WHERE o.type = 'deposit'
      AND o.process_time IS NOT NULL
      AND o.process_time <= 1
      AND o.status IN ('closed', 'expired')
      AND (u.role IS NULL OR u.role != 'provider')
      AND o.created_at::date BETWEEN
          (CASE
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN split_part({{period}}, '~', 1)::date
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN {{period}}::date
              WHEN {{period}} ~ '^past[0-9]+days$'
                  THEN current_date - regexp_replace({{period}}, '[^0-9]', '', 'g')::int
              WHEN {{period}} = 'thisweek'
                  THEN date_trunc('week', current_date)::date
              WHEN {{period}} = 'thismonth'
                  THEN date_trunc('month', current_date)::date
              WHEN {{period}} = 'lastweek'
                  THEN date_trunc('week', current_date - 7)::date
              WHEN {{period}} = 'lastmonth'
                  THEN date_trunc('month', current_date - 32)::date
              ELSE current_date
          END) - INTERVAL '28 days'
          AND
          CASE
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN split_part({{period}}, '~', 1)::date - INTERVAL '1 day'
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN {{period}}::date - INTERVAL '1 day'
              WHEN {{period}} ~ '^past[0-9]+days$'
                  THEN current_date - regexp_replace({{period}}, '[^0-9]', '', 'g')::int - INTERVAL '1 day'
              WHEN {{period}} = 'thisweek'
                  THEN date_trunc('week', current_date)::date - INTERVAL '1 day'
              WHEN {{period}} = 'thismonth'
                  THEN date_trunc('month', current_date)::date - INTERVAL '1 day'
              WHEN {{period}} = 'lastweek'
                  THEN date_trunc('week', current_date - 7)::date - INTERVAL '1 day'
              WHEN {{period}} = 'lastmonth'
                  THEN date_trunc('month', current_date - 32)::date - INTERVAL '1 day'
              ELSE current_date - INTERVAL '1 day'
          END
      [[AND o.payment_type = {{method}}]]
      [[AND o.bank = {{bank}}]]
      [[AND u.name = {{trader}}]]
      [[AND tl.name = {{tla}}]]
      [[AND ht.name = {{htl}}]]
      [[AND ag.name = {{agent}}]]
      [[AND m.name = {{merchant}}]]
)"""

NORM_FORMULA = """ROUND(
    COUNT(CASE WHEN status = 'closed' THEN 1 END) * 100.0
    / NULLIF(COUNT(*), 0),
    2
)"""


# ── Card definitions ──

CARDS = [
    {
        "key": "norm_scalar",
        "name": "Норма: Общая конверсия %",
        "description": "Базовый уровень конверсии за предыдущие 4 недели (process_time ≤ 1 сек)",
        "display": "scalar",
        "sql": f"""{NORM_BASE_CTE}
SELECT {NORM_FORMULA} AS "Норма конверсии %"
FROM norm_base"""
    },
    {
        "key": "norm_by_hour",
        "name": "Норма: По часам",
        "description": "Норма конверсии в разрезе по часам (МСК)",
        "display": "table",
        "sql": f"""{NORM_BASE_CTE}
SELECT
    hour_msk::int AS "Час",
    {NORM_FORMULA} AS "Норма %",
    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS "Успешных",
    COUNT(*) AS "Всего"
FROM norm_base
GROUP BY hour_msk
ORDER BY hour_msk"""
    },
    {
        "key": "norm_by_dow",
        "name": "Норма: По дням недели",
        "description": "Норма конверсии в разрезе по дням недели",
        "display": "table",
        "sql": f"""{NORM_BASE_CTE}
SELECT
    CASE dow_msk
        WHEN 1 THEN 'Пн'
        WHEN 2 THEN 'Вт'
        WHEN 3 THEN 'Ср'
        WHEN 4 THEN 'Чт'
        WHEN 5 THEN 'Пт'
        WHEN 6 THEN 'Сб'
        WHEN 7 THEN 'Вс'
    END AS "День",
    {NORM_FORMULA} AS "Норма %",
    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS "Успешных",
    COUNT(*) AS "Всего"
FROM norm_base
GROUP BY dow_msk
ORDER BY dow_msk"""
    },
    {
        "key": "norm_by_bank",
        "name": "Норма: По банкам",
        "description": "Норма конверсии в разрезе по банкам",
        "display": "table",
        "sql": f"""{NORM_BASE_CTE}
SELECT
    bank AS "Банк",
    {NORM_FORMULA} AS "Норма %",
    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS "Успешных",
    COUNT(*) AS "Всего"
FROM norm_base
GROUP BY bank
ORDER BY "Всего" DESC
LIMIT 30"""
    },
    {
        "key": "norm_by_method",
        "name": "Норма: По методам",
        "description": "Норма конверсии в разрезе по методам оплаты",
        "display": "table",
        "sql": f"""{NORM_BASE_CTE}
SELECT
    payment_type AS "Метод",
    {NORM_FORMULA} AS "Норма %",
    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS "Успешных",
    COUNT(*) AS "Всего"
FROM norm_base
GROUP BY payment_type
ORDER BY "Всего" DESC
LIMIT 30"""
    },
    {
        "key": "norm_by_amount",
        "name": "Норма: По категориям сумм",
        "description": "Норма конверсии в разрезе по категориям суммы заявки",
        "display": "table",
        "sql": f"""{NORM_BASE_CTE}
SELECT
    CASE
        WHEN amount < 1000 THEN '< 1 000'
        WHEN amount < 5000 THEN '1 000 - 5 000'
        WHEN amount < 10000 THEN '5 000 - 10 000'
        WHEN amount < 30000 THEN '10 000 - 30 000'
        WHEN amount < 50000 THEN '30 000 - 50 000'
        WHEN amount < 100000 THEN '50 000 - 100 000'
        ELSE '100 000+'
    END AS "Категория суммы",
    {NORM_FORMULA} AS "Норма %",
    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS "Успешных",
    COUNT(*) AS "Всего",
    CASE
        WHEN amount < 1000 THEN 1
        WHEN amount < 5000 THEN 2
        WHEN amount < 10000 THEN 3
        WHEN amount < 30000 THEN 4
        WHEN amount < 50000 THEN 5
        WHEN amount < 100000 THEN 6
        ELSE 7
    END AS sort_order
FROM norm_base
GROUP BY "Категория суммы", sort_order
ORDER BY sort_order"""
    },
    {
        "key": "norm_by_merchant",
        "name": "Норма: По мерчантам",
        "description": "Норма конверсии в разрезе по мерчантам",
        "display": "table",
        "sql": f"""{NORM_BASE_CTE}
SELECT
    merchant_name AS "Мерчант",
    {NORM_FORMULA} AS "Норма %",
    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS "Успешных",
    COUNT(*) AS "Всего"
FROM norm_base
GROUP BY merchant_name
ORDER BY "Всего" DESC
LIMIT 30"""
    },
]


def get_session():
    """Get Metabase session token."""
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
        verify=VERIFY_SSL,
        timeout=15,
    )
    if r.status_code == 200:
        return r.json()["id"]
    raise Exception(f"Login failed: {r.status_code} {r.text[:200]}")


def create_card(session, name, sql, description="", display="scalar"):
    """Create a Metabase card with template tags matching Dashboard #13."""
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}

    payload = {
        "name": name,
        "description": description,
        "display": display,
        "dataset_query": {
            "database": DATABASE_ID,
            "type": "native",
            "native": {
                "query": sql,
                "template-tags": TEMPLATE_TAGS,
            },
        },
        "visualization_settings": {},
    }

    r = requests.post(
        f"{METABASE_URL}/api/card",
        headers=headers,
        json=payload,
        verify=VERIFY_SSL,
        timeout=30,
    )

    if r.ok:
        card = r.json()
        print(f"  Created card #{card['id']}: {name}")
        return card["id"]
    else:
        print(f"  FAILED {name}: {r.status_code} {r.text[:300]}")
        return None


def get_dashboard(session):
    """Get current dashboard structure."""
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}
    r = requests.get(
        f"{METABASE_URL}/api/dashboard/{DASHBOARD_ID}",
        headers=headers,
        verify=VERIFY_SSL,
        timeout=30,
    )
    if r.ok:
        return r.json()
    raise Exception(f"Failed to get dashboard: {r.status_code}")


def add_cards_to_dashboard(session, card_ids, dashboard_data):
    """Add new cards to Dashboard #13 and wire up parameter mappings."""
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}

    # Get existing dashcards
    existing_dashcards = dashboard_data.get("dashcards", [])

    # Find max row to place new cards below existing ones
    max_row = 0
    for dc in existing_dashcards:
        bottom = dc.get("row", 0) + dc.get("size_y", 1)
        if bottom > max_row:
            max_row = bottom

    # Build parameter_mappings for each new card
    # Maps dashboard parameter IDs to card template tag names
    DASHBOARD_PARAM_MAPPINGS = [
        {"parameter_id": "dcbf42a6-bce3-4bee-b2dd-65483117533a",  # period
         "target": ["variable", ["template-tag", "period"]]},
        {"parameter_id": "32941394-06ae-4f92-97b4-7a00f70b6218",  # method
         "target": ["variable", ["template-tag", "method"]]},
        {"parameter_id": "e4a69a1f-5720-487e-8988-b7c5ba2cdb90",  # bank
         "target": ["variable", ["template-tag", "bank"]]},
        {"parameter_id": "f421bda1-cf63-4555-befc-06d5c1902860",  # trader
         "target": ["variable", ["template-tag", "trader"]]},
        {"parameter_id": "17915e7d-5bef-4714-8231-195ad4d7da81",  # tla
         "target": ["variable", ["template-tag", "tla"]]},
        {"parameter_id": "c8ec3138-3731-4fc2-bfe5-7a257a2b2a09",  # htl
         "target": ["variable", ["template-tag", "htl"]]},
        {"parameter_id": "2d55dc9d-5afb-4f3d-a1db-dfbbc117209b",  # agent
         "target": ["variable", ["template-tag", "agent"]]},
    ]

    # Layout: scalar at top, then tables in 2-column grid
    new_dashcards = []
    current_row = max_row + 1

    for i, (key, card_id) in enumerate(card_ids.items()):
        if key == "norm_scalar":
            # Scalar: full width, small height
            dc = {
                "card_id": card_id,
                "row": current_row,
                "col": 0,
                "size_x": 6,
                "size_y": 3,
                "parameter_mappings": [
                    {**m, "card_id": card_id} for m in DASHBOARD_PARAM_MAPPINGS
                ],
            }
            new_dashcards.append(dc)
            current_row += 3
        else:
            # Tables: 2-column layout
            col_offset = 0 if (len(new_dashcards) - 1) % 2 == 0 else 9
            if col_offset == 0 and len(new_dashcards) > 1:
                current_row += 6
            dc = {
                "card_id": card_id,
                "row": current_row,
                "col": col_offset,
                "size_x": 9,
                "size_y": 6,
                "parameter_mappings": [
                    {**m, "card_id": card_id} for m in DASHBOARD_PARAM_MAPPINGS
                ],
            }
            new_dashcards.append(dc)

    # Prepare the full dashcards list (existing + new)
    all_dashcards = []
    for dc in existing_dashcards:
        all_dashcards.append({
            "id": dc["id"],
            "card_id": dc.get("card_id"),
            "row": dc.get("row", 0),
            "col": dc.get("col", 0),
            "size_x": dc.get("size_x", 6),
            "size_y": dc.get("size_y", 4),
            "parameter_mappings": dc.get("parameter_mappings", []),
        })

    for dc in new_dashcards:
        all_dashcards.append(dc)

    # Update dashboard
    payload = {
        "dashcards": all_dashcards,
    }

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{DASHBOARD_ID}",
        headers=headers,
        json=payload,
        verify=VERIFY_SSL,
        timeout=60,
    )

    if r.ok:
        print(f"\n  Dashboard #{DASHBOARD_ID} updated with {len(new_dashcards)} new cards")
        # Extract dashcard IDs for the new cards
        updated = r.json()
        new_dc_map = {}
        for dc in updated.get("dashcards", []):
            cid = dc.get("card_id")
            for key, card_id in card_ids.items():
                if cid == card_id:
                    new_dc_map[card_id] = dc["id"]
        return new_dc_map
    else:
        print(f"  FAILED to update dashboard: {r.status_code}")
        print(f"  {r.text[:500]}")
        return {}


def add_merchant_parameter(session, dashboard_data):
    """Add merchant parameter to Dashboard #13 if not already present."""
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}

    params = dashboard_data.get("parameters", [])

    # Check if merchant param already exists
    for p in params:
        if p.get("slug") == "merchant" or p.get("name") == "Мерчант":
            print("  Merchant parameter already exists on dashboard")
            return p.get("id")

    # Add merchant parameter
    new_param = {
        "id": "a1b2c3d4-e5f6-7890-abcd-merchant00001",
        "name": "Мерчант",
        "slug": "merchant",
        "type": "string/=",
        "sectionId": "string",
    }
    params.append(new_param)

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{DASHBOARD_ID}",
        headers=headers,
        json={"parameters": params},
        verify=VERIFY_SSL,
        timeout=30,
    )

    if r.ok:
        print(f"  Added merchant parameter to dashboard #{DASHBOARD_ID}")
        return new_param["id"]
    else:
        print(f"  FAILED to add merchant param: {r.status_code} {r.text[:300]}")
        return None


def main():
    print("=== Creating Norm Conversion Cards for Dashboard #13 ===\n")

    session = get_session()
    print(f"Logged in to Metabase\n")

    # Step 1: Create all cards
    print("Step 1: Creating cards...")
    card_ids = {}
    for card_def in CARDS:
        card_id = create_card(
            session,
            name=card_def["name"],
            sql=card_def["sql"],
            description=card_def["description"],
            display=card_def["display"],
        )
        if card_id:
            card_ids[card_def["key"]] = card_id

    print(f"\nCreated {len(card_ids)}/{len(CARDS)} cards")
    print("Card IDs:")
    for key, cid in card_ids.items():
        print(f"  {key}: {cid}")

    if not card_ids:
        print("\nNo cards created, aborting.")
        sys.exit(1)

    # Step 2: Get dashboard structure
    print("\nStep 2: Getting dashboard structure...")
    dashboard_data = get_dashboard(session)

    # Step 3: Add merchant parameter
    print("\nStep 3: Adding merchant parameter...")
    merchant_param_id = add_merchant_parameter(session, dashboard_data)

    # Re-fetch dashboard after parameter update
    dashboard_data = get_dashboard(session)

    # Step 4: Add cards to dashboard
    print("\nStep 4: Adding cards to dashboard...")
    dashcard_map = add_cards_to_dashboard(session, card_ids, dashboard_data)

    print(f"\nDashcard mappings (card_id → dashcard_id):")
    for card_id, dc_id in dashcard_map.items():
        print(f"  card {card_id} → dashcard {dc_id}")

    # Output summary for integration
    print("\n=== SUMMARY ===")
    print(f"Card IDs: {json.dumps(card_ids, indent=2)}")
    print(f"Dashcard Map: {json.dumps(dashcard_map, indent=2)}")
    print(f"Merchant Param ID: {merchant_param_id}")

    # Save to file for later use
    result = {
        "card_ids": card_ids,
        "dashcard_map": dashcard_map,
        "merchant_param_id": merchant_param_id,
    }
    with open("norm_cards_result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nResults saved to norm_cards_result.json")


if __name__ == "__main__":
    main()
