"""
Создание дашборда "Реквизиты Онлайн" в Metabase.

Матрица: строки = методы оплаты, столбцы = категории чеков.
Значение = кол-во уникальных реквизитов (DISTINCT payment_id),
выданных за период в каждой категории.
"""

import requests
import json
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD")
DATABASE_ID = 2  # Main DB (PostgreSQL)
VERIFY_SSL = False

# ── Template tags ──

PERIOD_TAG_ID = str(uuid.uuid4())
METHOD_TAG_ID = str(uuid.uuid4())

TEMPLATE_TAGS = {
    "period": {
        "id": PERIOD_TAG_ID,
        "name": "period",
        "display-name": "Период",
        "type": "text",
        "required": True,
        "widget-type": "date/all-options",
        "default": None,
    },
    "method": {
        "id": METHOD_TAG_ID,
        "name": "method",
        "display-name": "Метод",
        "type": "text",
        "required": False,
        "widget-type": "string/=",
    },
}

# ── SQL ──

REQUISITES_ONLINE_SQL = """
SELECT
    o.payment_type AS "Метод",
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 100   AND o.amount < 1000)  AS "100-999",
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 1000  AND o.amount < 5000)  AS "1000-4999",
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 5000  AND o.amount < 10000) AS "5000-9999",
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 10000 AND o.amount < 15000) AS "10000-14999",
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 15000 AND o.amount < 20000) AS "15000-19999",
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 20000)                      AS "20000+"
FROM orders o
WHERE o.type = 'deposit'
  AND o.requisites IS NOT NULL
  AND o.payment_id IS NOT NULL
  AND (o.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
      CASE
          WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              THEN split_part({{period}}, '~', 1)::date
          WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              THEN {{period}}::date
          WHEN {{period}} ~ '^past[0-9]+days$'
              THEN (now() AT TIME ZONE 'Europe/Moscow')::date
                   - regexp_replace({{period}}, '[^0-9]', '', 'g')::int
          WHEN {{period}} = 'thisweek'
              THEN date_trunc('week', (now() AT TIME ZONE 'Europe/Moscow')::date)::date
          WHEN {{period}} = 'thismonth'
              THEN date_trunc('month', (now() AT TIME ZONE 'Europe/Moscow')::date)::date
          WHEN {{period}} = 'lastweek'
              THEN date_trunc('week', (now() AT TIME ZONE 'Europe/Moscow')::date - 7)::date
          WHEN {{period}} = 'lastmonth'
              THEN date_trunc('month', (now() AT TIME ZONE 'Europe/Moscow')::date - 32)::date
          ELSE (now() AT TIME ZONE 'Europe/Moscow')::date
      END
      AND
      CASE
          WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              THEN split_part({{period}}, '~', 2)::date
          WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              THEN {{period}}::date
          WHEN {{period}} = 'lastweek'
              THEN (date_trunc('week', (now() AT TIME ZONE 'Europe/Moscow')::date)
                    - interval '1 day')::date
          WHEN {{period}} = 'lastmonth'
              THEN (date_trunc('month', (now() AT TIME ZONE 'Europe/Moscow')::date)
                    - interval '1 day')::date
          ELSE (now() AT TIME ZONE 'Europe/Moscow')::date
      END
  [[AND o.payment_type = {{method}}]]
GROUP BY o.payment_type
HAVING
    COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 100   AND o.amount < 1000)  > 0
 OR COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 1000  AND o.amount < 5000)  > 0
 OR COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 5000  AND o.amount < 10000) > 0
 OR COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 10000 AND o.amount < 15000) > 0
 OR COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 15000 AND o.amount < 20000) > 0
 OR COUNT(DISTINCT o.payment_id)
        FILTER (WHERE o.amount >= 20000)                      > 0
ORDER BY o.payment_type
""".strip()


# ── Metabase helpers ──

def get_session():
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
        verify=VERIFY_SSL,
        timeout=15,
    )
    if r.status_code == 200:
        return r.json()["id"]
    raise Exception(f"Login failed: {r.status_code} {r.text[:200]}")


def headers(session):
    return {"X-Metabase-Session": session, "Content-Type": "application/json"}


def create_card(session, name, sql, description=""):
    payload = {
        "name": name,
        "description": description,
        "display": "table",
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
        headers=headers(session),
        json=payload,
        verify=VERIFY_SSL,
        timeout=30,
    )
    if r.ok:
        card = r.json()
        print(f"  Card #{card['id']}: {name}")
        return card["id"]
    raise Exception(f"Failed to create card: {r.status_code} {r.text[:300]}")


def create_dashboard(session, name):
    r = requests.post(
        f"{METABASE_URL}/api/dashboard",
        headers=headers(session),
        json={"name": name},
        verify=VERIFY_SSL,
        timeout=15,
    )
    if r.ok:
        dash = r.json()
        print(f"  Dashboard #{dash['id']}: {name}")
        return dash["id"]
    raise Exception(f"Failed to create dashboard: {r.status_code} {r.text[:300]}")


def setup_dashboard(session, dashboard_id, card_id):
    """Add parameters and card to the dashboard."""
    period_param_id = str(uuid.uuid4())
    method_param_id = str(uuid.uuid4())

    parameters = [
        {
            "id": period_param_id,
            "name": "Период",
            "slug": "period",
            "type": "date/all-options",
            "sectionId": "date",
            "default": None,
        },
        {
            "id": method_param_id,
            "name": "Метод",
            "slug": "method",
            "type": "string/=",
        },
    ]

    dashcards = [
        {
            "id": -1,
            "card_id": card_id,
            "row": 0,
            "col": 0,
            "size_x": 18,
            "size_y": 8,
            "parameter_mappings": [
                {
                    "parameter_id": period_param_id,
                    "card_id": card_id,
                    "target": ["variable", ["template-tag", "period"]],
                },
                {
                    "parameter_id": method_param_id,
                    "card_id": card_id,
                    "target": ["variable", ["template-tag", "method"]],
                },
            ],
        },
    ]

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{dashboard_id}",
        headers=headers(session),
        json={"parameters": parameters, "dashcards": dashcards},
        verify=VERIFY_SSL,
        timeout=30,
    )
    if r.ok:
        print("  Dashboard configured with card + parameters")
    else:
        print(f"  WARNING: dashboard config failed: {r.status_code} {r.text[:300]}")


def main():
    print("=" * 50)
    print("Создание дашборда 'Реквизиты Онлайн'")
    print("=" * 50)

    if not METABASE_EMAIL or not METABASE_PASSWORD:
        print("ERROR: METABASE_EMAIL / METABASE_PASSWORD not set")
        return

    print("\n1. Авторизация в Metabase...")
    session = get_session()
    print("   OK")

    print("\n2. Создание карточки...")
    card_id = create_card(
        session,
        name="Реквизиты по категориям чеков",
        sql=REQUISITES_ONLINE_SQL,
        description="Уникальные реквизиты (payment_id) по методу оплаты и категории чека. Вариант 2: фактическая выдача.",
    )

    print("\n3. Создание дашборда...")
    dash_id = create_dashboard(session, "Реквизиты Онлайн")

    print("\n4. Настройка дашборда (параметры + карточка)...")
    setup_dashboard(session, dash_id, card_id)

    url = f"{METABASE_URL}/dashboard/{dash_id}"
    print(f"\n{'=' * 50}")
    print(f"ГОТОВО! Дашборд: {url}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
