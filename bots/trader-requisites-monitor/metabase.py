"""
Работа с Metabase API для проверки реквизитов
Использует готовый вопрос #96 "Плохие реки"
"""
import requests
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from config import METABASE_URL, METABASE_EMAIL, METABASE_PASSWORD

logger = logging.getLogger(__name__)

# Московский часовой пояс (UTC+3)
MSK = timezone(timedelta(hours=3))

# ID вопроса в Metabase с проблемными реквизитами
METABASE_QUESTION_ID = 96

# Кеш сессии
metabase_session: Optional[str] = None


def get_session() -> str:
    """
    Получает session token от Metabase API

    Returns:
        Session token
    """
    global metabase_session

    if metabase_session:
        return metabase_session

    try:
        response = requests.post(
            f"{METABASE_URL}/api/session",
            json={
                "username": METABASE_EMAIL,
                "password": METABASE_PASSWORD
            },
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if not response.ok:
            error_text = response.text[:200]
            logger.error(f"Metabase auth failed: {response.status_code} - {error_text}")
            raise Exception(f"Metabase auth failed: {response.status_code}")

        data = response.json()
        metabase_session = data.get("id")
        logger.info("✅ Metabase авторизация успешна")
        return metabase_session

    except Exception as e:
        logger.error(f"Ошибка авторизации Metabase: {e}")
        raise


def check_problem_requisites() -> List[Dict]:
    """
    Проверяет проблемные реквизиты через готовый вопрос Metabase #96

    Returns:
        Список проблемных реквизитов
    """
    session_token = get_session()

    try:
        # Запрашиваем результаты готового вопроса с параметром ignore_cache для свежих данных
        response = requests.post(
            f"{METABASE_URL}/api/card/{METABASE_QUESTION_ID}/query",
            headers={
                "Content-Type": "application/json",
                "X-Metabase-Session": session_token
            },
            json={"ignore_cache": True},
            timeout=60
        )

        if not response.ok:
            error_text = response.text[:200]
            logger.error(f"Metabase query failed: {response.status_code} - {error_text}")
            raise Exception(f"Query failed: {response.status_code}")

        data = response.json()

        # Парсим результаты
        columns = [col["name"] for col in data.get("data", {}).get("cols", [])]
        rows = data.get("data", {}).get("rows", [])

        results = []
        for row in rows:
            req = dict(zip(columns, row))
            # Фильтруем только трейдеров (исключаем провайдеров)
            if req.get('gate_type') != 'Provider':
                results.append(req)

        # Логируем названия колонок для отладки
        if results:
            logger.info(f"Доступные колонки: {list(results[0].keys())}")
            logger.info(f"Пример данных первого реквизита: {results[0]}")

        logger.info(f"✅ Найдено проблемных реквизитов трейдеров: {len(results)}")
        return results

    except Exception as e:
        logger.error(f"Ошибка проверки реквизитов: {e}")
        return []


def test_connection() -> bool:
    """
    Тестирует подключение к Metabase

    Returns:
        True если подключение успешно
    """
    try:
        get_session()
        return True
    except:
        return False
