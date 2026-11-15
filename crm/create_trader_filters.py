"""
Создаём карточки для получения списков трейдеров, ТЛ, ХТЛ, агентов
для фильтров на дашборде трейдерки
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD")
DATABASE_ID = 2  # Main DB (PostgreSQL)


def get_session():
    """Get Metabase session token"""
    response = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
        verify=False
    )
    if response.status_code == 200:
        return response.json()["id"]
    else:
        raise Exception(f"Login failed: {response.status_code}")


def create_card(session, name, sql):
    """Create a Metabase card"""
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}

    card = {
        "name": name,
        "dataset_query": {
            "type": "native",
            "native": {
                "query": sql,
                "template-tags": {}
            },
            "database": DATABASE_ID
        },
        "display": "table",
        "visualization_settings": {}
    }

    response = requests.post(
        f"{METABASE_URL}/api/card",
        headers=headers,
        json=card,
        verify=False
    )

    if response.status_code in (200, 201):
        card_id = response.json()["id"]
        print(f"✓ Created card #{card_id}: {name}")
        return card_id
    else:
        print(f"✗ Failed to create {name}: {response.status_code}")
        print(f"  Response: {response.text}")
        return None


def main():
    print("Creating trader filter cards...")

    session = get_session()
    print(f"✓ Logged in to Metabase\n")

    # SQL для получения уникальных значений трейдеров
    # Нужно узнать правильные названия полей - попробуем разные варианты

    cards = [
        {
            "name": "Трейдеры: список для фильтра",
            "sql": """
SELECT DISTINCT name as trader
FROM users
WHERE role = 'trader'
  AND deleted_at IS NULL
  AND name IS NOT NULL
  AND name != ''
ORDER BY name
            """,
        },
        {
            "name": "ТЛ: список для фильтра",
            "sql": """
SELECT DISTINCT parent.name as tla
FROM user_parents up
JOIN users parent ON parent.id = up.parent_user_id
WHERE up.as_role = 'tla'
  AND parent.deleted_at IS NULL
  AND parent.name IS NOT NULL
ORDER BY parent.name
            """,
        },
        {
            "name": "ХТЛ: список для фильтра",
            "sql": """
SELECT DISTINCT parent.name as htl
FROM user_parents up
JOIN users parent ON parent.id = up.parent_user_id
WHERE up.as_role = 'htl'
  AND parent.deleted_at IS NULL
  AND parent.name IS NOT NULL
ORDER BY parent.name
            """,
        },
        {
            "name": "Агенты: список для фильтра",
            "sql": """
SELECT DISTINCT parent.name as agent
FROM user_parents up
JOIN users parent ON parent.id = up.parent_user_id
WHERE up.as_role = 'agent'
  AND parent.deleted_at IS NULL
  AND parent.name IS NOT NULL
ORDER BY parent.name
            """,
        },
    ]

    created_ids = []
    for card_def in cards:
        card_id = create_card(session, card_def["name"], card_def["sql"])
        if card_id:
            created_ids.append(card_id)

    print(f"\n✓ Created {len(created_ids)} cards:")
    print(f"  Card IDs: {created_ids}")
    print("\nNext steps:")
    print("1. Update config.py with new card IDs")
    print("2. Update metabase.py get_trader_filter_options() to use these cards")


if __name__ == "__main__":
    main()
