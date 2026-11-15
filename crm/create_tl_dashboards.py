"""
Создание дашбордов для ТЛ и ХТЛ в Metabase

1. Убрать нормы из Dashboard #13
2. Создать карточку "Реквизиты сегодня"
3. Добавить "Реквизиты сегодня" на Dashboard #13
4. Создать коллекцию "ТЛ ХТЛ"
5. Создать карточку фильтра мерчантов (замена norm card 214)
6. Скопировать Dashboard #13 для каждого ТЛ (5 шт) + 1 общий ХТЛ
7. Установить default tla на ТЛ-дашбордах
"""

import requests
import json
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD")
DATABASE_ID = 2  # Main DB (PostgreSQL)
DASHBOARD_ID = 13  # Trader dashboard
VERIFY_SSL = False

# Norm card IDs to remove
NORM_CARD_IDS = {208, 209, 210, 211, 212, 213, 214}

# Team leads: по одному дашборду на тимлида; список берётся из окружения, чтобы не хранить имена в коде
TL_NAMES = [x.strip() for x in os.getenv("TL_NAMES", "").split(",") if x.strip()]

# ── Template tags (same as Dashboard #13 cards) ──

TEMPLATE_TAGS = {
    "period": {
        "name": "period",
        "display-name": "Период",
        "type": "text",
        "required": True,
        "widget-type": "date/all-options",
        "id": "6fc40b04-64c1-4af1-b309-44919c5f66c3",
        "default": None,
    },
    "method": {
        "id": "eda0c6ed-dbf7-44cc-ab04-f3f99a898322",
        "name": "method",
        "display-name": "Метод",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
    "bank": {
        "id": "5b603b53-2f33-45f6-bc11-f6bd32b859be",
        "name": "bank",
        "display-name": "Банк",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
    "trader": {
        "id": "6f2702fc-19ec-4707-be63-7829ed133a11",
        "name": "trader",
        "display-name": "Трейдер",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
    "tla": {
        "id": "aeb604df-6c01-4229-a2af-1e604993f494",
        "name": "tla",
        "display-name": "ТЛ (тимлид)",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
    "htl": {
        "id": "98302128-11ab-41dc-8f4f-56f7f916474c",
        "name": "htl",
        "display-name": "ХТЛ (хедтимлид)",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
    "agent": {
        "id": "45f852b5-612a-4dde-b7ad-23a406575cf7",
        "name": "agent",
        "display-name": "Агент",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
    "merchant": {
        "id": "b1c2d3e4-f5a6-7890-abcd-ef1234567890",
        "name": "merchant",
        "display-name": "Мерчант",
        "required": False,
        "type": "text",
        "widget-type": "string/=",
    },
}

# Dashboard parameter mappings (dashboard param ID → template-tag name)
DASHBOARD_PARAM_MAPPINGS = [
    {"parameter_id": "dcbf42a6-bce3-4bee-b2dd-65483117533a",
     "target": ["variable", ["template-tag", "period"]]},
    {"parameter_id": "32941394-06ae-4f92-97b4-7a00f70b6218",
     "target": ["variable", ["template-tag", "method"]]},
    {"parameter_id": "e4a69a1f-5720-487e-8988-b7c5ba2cdb90",
     "target": ["variable", ["template-tag", "bank"]]},
    {"parameter_id": "f421bda1-cf63-4555-befc-06d5c1902860",
     "target": ["variable", ["template-tag", "trader"]]},
    {"parameter_id": "17915e7d-5bef-4714-8231-195ad4d7da81",
     "target": ["variable", ["template-tag", "tla"]]},
    {"parameter_id": "c8ec3138-3731-4fc2-bfe5-7a257a2b2a09",
     "target": ["variable", ["template-tag", "htl"]]},
    {"parameter_id": "2d55dc9d-5afb-4f3d-a1db-dfbbc117209b",
     "target": ["variable", ["template-tag", "agent"]]},
    {"parameter_id": "a1b2c3d4-e5f6-7890-abcd-merchant00001",
     "target": ["variable", ["template-tag", "merchant"]]},
]

# ── SQL for "Реквизиты сегодня" ──

REQUISITES_SQL = """WITH h AS (
    SELECT
        child_user_id,
        MAX(CASE WHEN as_role = 'teamlead' THEN parent_user_id END) AS tl_id,
        MAX(CASE WHEN as_role = 'headteam' THEN parent_user_id END) AS htl_id,
        MAX(CASE WHEN as_role = 'agent'    THEN parent_user_id END) AS agent_id
    FROM user_parents
    GROUP BY child_user_id
)
SELECT
    p.bank AS "Банк",
    o.payment_type AS "Метод",
    MIN(p.deposit_order_min_amount) AS "Мин. сумма",
    COUNT(DISTINCT p.id) AS "Кол-во реквизитов",
    COUNT(DISTINCT o.id) AS "Заявок"
FROM payments p
JOIN orders o ON o.payment_id = p.id
LEFT JOIN users u ON u.id = p.user_id
LEFT JOIN h ON h.child_user_id = p.user_id
LEFT JOIN users tl ON tl.id = h.tl_id
LEFT JOIN users ht ON ht.id = h.htl_id
LEFT JOIN users ag ON ag.id = h.agent_id
WHERE o.type = 'deposit'
  AND p.deleted_at IS NULL
  AND (o.created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN
      CASE
          WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              THEN split_part({{period}}, '~', 1)::date
          WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              THEN {{period}}::date
          WHEN {{period}} ~ '^past[0-9]+days$'
              THEN (now() AT TIME ZONE 'Europe/Moscow')::date - regexp_replace({{period}}, '[^0-9]', '', 'g')::int
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
              THEN (date_trunc('week', (now() AT TIME ZONE 'Europe/Moscow')::date) - interval '1 day')::date
          WHEN {{period}} = 'lastmonth'
              THEN (date_trunc('month', (now() AT TIME ZONE 'Europe/Moscow')::date) - interval '1 day')::date
          ELSE (now() AT TIME ZONE 'Europe/Moscow')::date
      END
  [[AND o.payment_type = {{method}}]]
  [[AND p.bank = {{bank}}]]
  [[AND u.name = {{trader}}]]
  [[AND tl.name = {{tla}}]]
  [[AND ht.name = {{htl}}]]
  [[AND ag.name = {{agent}}]]
  [[AND EXISTS (
      SELECT 1 FROM merchants mm
      WHERE mm.id = o.merchant_id AND mm.name = {{merchant}}
  )]]
GROUP BY p.bank, o.payment_type
ORDER BY "Заявок" DESC"""

# ── SQL for merchant filter card (replacement for norm card 214) ──

MERCHANTS_FILTER_SQL = """SELECT DISTINCT m.name AS "Мерчант"
FROM merchants m
WHERE m.actual = true
  AND m.name IS NOT NULL
ORDER BY m.name"""


# ── Helper functions ──

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


def headers(session):
    return {"X-Metabase-Session": session, "Content-Type": "application/json"}


def get_dashboard(session, dashboard_id=DASHBOARD_ID):
    """Get dashboard structure."""
    r = requests.get(
        f"{METABASE_URL}/api/dashboard/{dashboard_id}",
        headers=headers(session),
        verify=VERIFY_SSL,
        timeout=30,
    )
    if r.ok:
        return r.json()
    raise Exception(f"Failed to get dashboard {dashboard_id}: {r.status_code}")


def create_card(session, name, sql, description="", display="table", collection_id=None, template_tags=None):
    """Create a Metabase card with template tags."""
    payload = {
        "name": name,
        "description": description,
        "display": display,
        "dataset_query": {
            "database": DATABASE_ID,
            "type": "native",
            "native": {
                "query": sql,
                "template-tags": template_tags or TEMPLATE_TAGS,
            },
        },
        "visualization_settings": {},
    }
    if collection_id:
        payload["collection_id"] = collection_id

    r = requests.post(
        f"{METABASE_URL}/api/card",
        headers=headers(session),
        json=payload,
        verify=VERIFY_SSL,
        timeout=30,
    )

    if r.ok:
        card = r.json()
        print(f"  Created card #{card['id']}: {name}")
        return card["id"]
    else:
        print(f"  FAILED to create card {name}: {r.status_code} {r.text[:300]}")
        return None


def create_collection(session, name):
    """Create a Metabase collection (folder)."""
    r = requests.post(
        f"{METABASE_URL}/api/collection",
        headers=headers(session),
        json={"name": name, "color": "#509EE3"},
        verify=VERIFY_SSL,
        timeout=15,
    )
    if r.ok:
        coll = r.json()
        print(f"  Created collection #{coll['id']}: {name}")
        return coll["id"]
    else:
        print(f"  FAILED to create collection: {r.status_code} {r.text[:300]}")
        return None


# ── Step 1: Remove norm cards from Dashboard #13 ──

def remove_norm_cards(session):
    """Remove norm dashcards from Dashboard #13."""
    print("\n=== Step 1: Remove norm cards from Dashboard #13 ===")

    dashboard = get_dashboard(session)
    existing_dashcards = dashboard.get("dashcards", [])

    # Filter out norm cards
    filtered = []
    removed = []
    for dc in existing_dashcards:
        cid = dc.get("card_id")
        if cid in NORM_CARD_IDS:
            removed.append(f"card #{cid} (dashcard #{dc['id']})")
        else:
            filtered.append({
                "id": dc["id"],
                "card_id": dc.get("card_id"),
                "row": dc.get("row", 0),
                "col": dc.get("col", 0),
                "size_x": dc.get("size_x", 6),
                "size_y": dc.get("size_y", 4),
                "parameter_mappings": dc.get("parameter_mappings", []),
            })

    if not removed:
        print("  No norm cards found on dashboard — already removed?")
        return dashboard

    print(f"  Removing {len(removed)} norm cards: {', '.join(removed)}")

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{DASHBOARD_ID}",
        headers=headers(session),
        json={"dashcards": filtered},
        verify=VERIFY_SSL,
        timeout=60,
    )

    if r.ok:
        print(f"  Dashboard #{DASHBOARD_ID} updated — {len(removed)} norm cards removed")
        return r.json()
    else:
        print(f"  FAILED to update dashboard: {r.status_code} {r.text[:300]}")
        return dashboard


# ── Step 2: Create "Реквизиты сегодня" card ──

def create_requisites_card(session, collection_id=None):
    """Create the 'Реквизиты сегодня' card."""
    print("\n=== Step 2: Create 'Реквизиты сегодня' card ===")
    return create_card(
        session,
        name="Реквизиты сегодня",
        sql=REQUISITES_SQL,
        description="Реквизиты, задействованные в заявках за выбранный период. "
                    "Показывает банк, метод, мин. сумму и количество.",
        display="table",
        collection_id=collection_id,
    )


# ── Step 3: Add "Реквизиты сегодня" to Dashboard #13 ──

def add_card_to_dashboard(session, dashboard_id, card_id, dashboard_data=None):
    """Add a card to a dashboard at the bottom."""
    if not dashboard_data:
        dashboard_data = get_dashboard(session, dashboard_id)

    existing_dashcards = dashboard_data.get("dashcards", [])

    # Find max row
    max_row = 0
    for dc in existing_dashcards:
        bottom = dc.get("row", 0) + dc.get("size_y", 1)
        if bottom > max_row:
            max_row = bottom

    # Build dashcard list: keep existing + add new
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

    # New card: full width table at bottom
    # Metabase requires negative id for new dashcards
    new_dc = {
        "id": -1,
        "card_id": card_id,
        "row": max_row + 1,
        "col": 0,
        "size_x": 18,
        "size_y": 6,
        "parameter_mappings": [
            {**m, "card_id": card_id} for m in DASHBOARD_PARAM_MAPPINGS
        ],
    }
    all_dashcards.append(new_dc)

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{dashboard_id}",
        headers=headers(session),
        json={"dashcards": all_dashcards},
        verify=VERIFY_SSL,
        timeout=60,
    )

    if r.ok:
        updated = r.json()
        # Find the new dashcard ID
        for dc in updated.get("dashcards", []):
            if dc.get("card_id") == card_id:
                print(f"  Added card #{card_id} to dashboard #{dashboard_id} as dashcard #{dc['id']}")
                return dc["id"]
        print(f"  Added card #{card_id} to dashboard #{dashboard_id}")
        return None
    else:
        print(f"  FAILED to add card to dashboard #{dashboard_id}: {r.status_code} {r.text[:300]}")
        return None


# ── Step 4: Create collection ──

def setup_collection(session):
    """Create 'ТЛ ХТЛ' collection."""
    print("\n=== Step 4: Create collection 'ТЛ ХТЛ' ===")
    return create_collection(session, "ТЛ ХТЛ")


# ── Step 5: Create merchant filter card ──

def create_merchant_filter_card(session, collection_id=None):
    """Create a merchant filter question card (replacement for norm card 214)."""
    print("\n=== Step 5: Create merchant filter card ===")
    return create_card(
        session,
        name="Фильтр: Мерчанты",
        sql=MERCHANTS_FILTER_SQL,
        description="Список активных мерчантов для фильтра в трейдерском дашборде",
        display="table",
        collection_id=collection_id,
        template_tags={},
    )


# ── Step 6: Copy dashboards for TLs ──

def copy_dashboard(session, source_id, name, collection_id):
    """Copy a dashboard using Metabase copy API."""
    r = requests.post(
        f"{METABASE_URL}/api/dashboard/{source_id}/copy",
        headers=headers(session),
        json={
            "name": name,
            "collection_id": collection_id,
            "is_deep_copy": False,
        },
        verify=VERIFY_SSL,
        timeout=60,
    )
    if r.ok:
        new_dash = r.json()
        print(f"  Copied dashboard #{source_id} → #{new_dash['id']}: {name}")
        return new_dash["id"]
    else:
        print(f"  Copy API failed ({r.status_code}), falling back to manual creation")
        return create_dashboard_manually(session, source_id, name, collection_id)


def create_dashboard_manually(session, source_id, name, collection_id):
    """Manually create a dashboard by recreating its structure."""
    # Create empty dashboard
    r = requests.post(
        f"{METABASE_URL}/api/dashboard",
        headers=headers(session),
        json={
            "name": name,
            "collection_id": collection_id,
        },
        verify=VERIFY_SSL,
        timeout=30,
    )
    if not r.ok:
        print(f"  FAILED to create dashboard {name}: {r.status_code}")
        return None

    new_id = r.json()["id"]
    print(f"  Created empty dashboard #{new_id}: {name}")

    # Get source dashboard structure
    source = get_dashboard(session, source_id)

    # Copy parameters
    params = source.get("parameters", [])
    requests.put(
        f"{METABASE_URL}/api/dashboard/{new_id}",
        headers=headers(session),
        json={"parameters": params},
        verify=VERIFY_SSL,
        timeout=30,
    )

    # Copy dashcards (excluding norms)
    dashcards = []
    for dc in source.get("dashcards", []):
        cid = dc.get("card_id")
        if cid in NORM_CARD_IDS:
            continue
        dashcards.append({
            "card_id": cid,
            "row": dc.get("row", 0),
            "col": dc.get("col", 0),
            "size_x": dc.get("size_x", 6),
            "size_y": dc.get("size_y", 4),
            "parameter_mappings": dc.get("parameter_mappings", []),
        })

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{new_id}",
        headers=headers(session),
        json={"dashcards": dashcards},
        verify=VERIFY_SSL,
        timeout=60,
    )

    if r.ok:
        print(f"  Dashboard #{new_id} populated with {len(dashcards)} cards")
    else:
        print(f"  FAILED to populate dashboard: {r.status_code}")

    return new_id


def remove_norm_from_dashboard(session, dashboard_id):
    """Remove norm cards from a copied dashboard."""
    dashboard = get_dashboard(session, dashboard_id)
    existing = dashboard.get("dashcards", [])

    filtered = []
    removed_count = 0
    for dc in existing:
        cid = dc.get("card_id")
        if cid in NORM_CARD_IDS:
            removed_count += 1
        else:
            filtered.append({
                "id": dc["id"],
                "card_id": dc.get("card_id"),
                "row": dc.get("row", 0),
                "col": dc.get("col", 0),
                "size_x": dc.get("size_x", 6),
                "size_y": dc.get("size_y", 4),
                "parameter_mappings": dc.get("parameter_mappings", []),
            })

    if removed_count > 0:
        r = requests.put(
            f"{METABASE_URL}/api/dashboard/{dashboard_id}",
            headers=headers(session),
            json={"dashcards": filtered},
            verify=VERIFY_SSL,
            timeout=60,
        )
        if r.ok:
            print(f"  Removed {removed_count} norm cards from dashboard #{dashboard_id}")
        else:
            print(f"  FAILED to remove norms: {r.status_code}")


def set_tla_default(session, dashboard_id, tla_name):
    """Set default value for tla parameter on a dashboard."""
    dashboard = get_dashboard(session, dashboard_id)
    params = dashboard.get("parameters", [])

    found = False
    for p in params:
        if p.get("slug") == "tla" or p.get("id") == "17915e7d-5bef-4714-8231-195ad4d7da81":
            p["default"] = [tla_name]
            found = True
            break

    if not found:
        print(f"  WARNING: tla parameter not found on dashboard #{dashboard_id}")
        return

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{dashboard_id}",
        headers=headers(session),
        json={"parameters": params},
        verify=VERIFY_SSL,
        timeout=30,
    )
    if r.ok:
        print(f"  Set tla default = '{tla_name}' on dashboard #{dashboard_id}")
    else:
        print(f"  FAILED to set tla default: {r.status_code} {r.text[:200]}")


def create_tl_dashboards(session, collection_id, requisites_card_id):
    """Create TL dashboards + 1 general HTL dashboard."""
    print("\n=== Step 6: Create TL/HTL dashboards ===")

    results = {}

    # General HTL dashboard (no tla filter)
    print("\n  --- General HTL dashboard ---")
    htl_id = copy_dashboard(session, DASHBOARD_ID, "Аналитика трейдерки (ХТЛ)", collection_id)
    if htl_id:
        remove_norm_from_dashboard(session, htl_id)
        add_card_to_dashboard(session, htl_id, requisites_card_id)
        results["HTL"] = htl_id

    time.sleep(1)

    # Per-TL dashboards
    for tl_name in TL_NAMES:
        print(f"\n  --- TL dashboard: {tl_name} ---")
        dash_id = copy_dashboard(session, DASHBOARD_ID, f"Аналитика трейдерки — {tl_name}", collection_id)
        if dash_id:
            remove_norm_from_dashboard(session, dash_id)
            add_card_to_dashboard(session, dash_id, requisites_card_id)
            set_tla_default(session, dash_id, tl_name)
            results[tl_name] = dash_id
        time.sleep(1)

    return results


# ── Main ──

def main():
    print("=" * 60)
    print("  Создание дашбордов для ТЛ и ХТЛ")
    print("=" * 60)

    session = get_session()
    print(f"  Metabase session: {session[:8]}...")

    # Step 1: Remove norms from Dashboard #13
    dashboard_data = remove_norm_cards(session)

    # Step 2: Create "Реквизиты сегодня" card
    requisites_card_id = create_requisites_card(session)
    if not requisites_card_id:
        print("FATAL: Failed to create requisites card")
        sys.exit(1)

    # Step 3: Add "Реквизиты сегодня" to Dashboard #13
    print("\n=== Step 3: Add 'Реквизиты сегодня' to Dashboard #13 ===")
    dashboard_data = get_dashboard(session)  # refresh after norm removal
    req_dashcard_id = add_card_to_dashboard(session, DASHBOARD_ID, requisites_card_id, dashboard_data)

    # Step 4: Create collection
    collection_id = setup_collection(session)
    if not collection_id:
        print("FATAL: Failed to create collection")
        sys.exit(1)

    # Step 5: Create merchant filter card
    merchants_card_id = create_merchant_filter_card(session, collection_id)

    # Step 6: Create TL/HTL dashboards
    tl_results = create_tl_dashboards(session, collection_id, requisites_card_id)

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Requisites card ID: {requisites_card_id}")
    print(f"  Requisites dashcard ID on D#13: {req_dashcard_id}")
    print(f"  Merchants filter card ID: {merchants_card_id}")
    print(f"  Collection ID: {collection_id}")
    print(f"  Dashboards created:")
    for name, dash_id in tl_results.items():
        url = f"{METABASE_URL}/dashboard/{dash_id}"
        print(f"    {name}: #{dash_id} — {url}")

    # Save results to file
    result = {
        "requisites_card_id": requisites_card_id,
        "requisites_dashcard_id_on_d13": req_dashcard_id,
        "merchants_card_id": merchants_card_id,
        "collection_id": collection_id,
        "dashboards": tl_results,
    }
    with open("tl_dashboards_result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to tl_dashboards_result.json")

    print("\n  IMPORTANT: Update metabase.py with new card IDs:")
    print(f"    - Add to DASHBOARD_13_DASHCARD_MAP: {requisites_card_id}: {req_dashcard_id}")
    print(f"    - Replace merchant filter card 214 with: {merchants_card_id}")


if __name__ == "__main__":
    main()
