"""
Metabase API клиент для Merchant CRM
- Авторизация через session token
- Выполнение questions
- Получение данных о мерчантах, ставках, конверсиях
"""
import requests
import json
import os
import urllib3
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta

from config import METABASE_URL, METABASE_EMAIL, METABASE_PASSWORD, METABASE_QUESTIONS

# Отключаем предупреждения о SSL для Railway (где может быть проблема с сертификатами)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Флаг для отключения проверки SSL (для Railway)
VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() == "true"


class MetabaseClient:
    """Клиент для работы с Metabase API"""

    def __init__(self):
        self.base_url = METABASE_URL.rstrip('/')
        self.session_token = None
        self.session_expires = None

    def _get_session(self) -> Optional[str]:
        """Получить session token (с кешированием)"""
        if self.session_token and self.session_expires:
            if datetime.now() < self.session_expires:
                return self.session_token

        try:
            response = requests.post(
                f"{self.base_url}/api/session",
                json={
                    "username": METABASE_EMAIL,
                    "password": METABASE_PASSWORD
                },
                timeout=30,
                verify=VERIFY_SSL
            )

            if response.status_code == 200:
                data = response.json()
                self.session_token = data.get("id")
                self.session_expires = datetime.now() + timedelta(hours=12)
                print(f"[Metabase] Авторизация успешна")
                return self.session_token
            else:
                print(f"[Metabase] Ошибка авторизации: {response.status_code}")
                return None

        except Exception as e:
            print(f"[Metabase] Ошибка подключения: {e}")
            return None

    def _headers(self) -> Dict[str, str]:
        """Заголовки для запросов"""
        token = self._get_session()
        if not token:
            return {}
        return {
            "X-Metabase-Session": token,
            "Content-Type": "application/json"
        }

    def execute_dashboard_card(
        self,
        dashboard_id: int,
        dashcard_id: int,
        card_id: int,
        parameters: List[Dict] = None,
    ) -> Optional[List[Dict]]:
        """Execute a dashboard card query via /api/dashboard/{id}/dashcard/{dc}/card/{c}/query"""
        headers = self._headers()
        if not headers:
            return None
        try:
            url = f"{self.base_url}/api/dashboard/{dashboard_id}/dashcard/{dashcard_id}/card/{card_id}/query"
            payload = {"parameters": parameters or []}
            print(f"[Metabase] Dashboard card request: card={card_id}, params={len(parameters or [])}")
            response = requests.post(url, headers=headers, json=payload, timeout=70, verify=VERIFY_SSL)
            print(f"[Metabase] Dashboard card response: card={card_id}, status={response.status_code}")
            if response.status_code in (200, 202):
                data = response.json()
                rows_data = data.get("data") or {}
                cols = rows_data.get("cols", [])
                rows = rows_data.get("rows", [])
                if not cols:
                    # True async job without data in body — not supported
                    print(f"[Metabase] dashcard {dashcard_id}/{card_id}: HTTP {response.status_code} no data in body, keys={list(data.keys())}")
                    return None
                col_names = [c.get("display_name") or c.get("name", f"col{i}") for i, c in enumerate(cols)]
                result = [dict(zip(col_names, row)) for row in rows]
                print(f"[Metabase] dashcard {dashcard_id}/{card_id}: OK ({len(result)} rows)")
                return result
            elif response.status_code == 401:
                self.session_token = None
                self.session_expires = None
                return self.execute_dashboard_card(dashboard_id, dashcard_id, card_id, parameters)
            else:
                print(f"[Metabase] dashcard {dashcard_id}/{card_id} HTTP {response.status_code}")
                try:
                    print(f"[Metabase] detail: {response.json()}")
                except Exception:
                    pass
                return None
        except requests.exceptions.Timeout:
            print(f"[Metabase] Таймаут dashcard {dashcard_id}/{card_id}")
            return None
        except Exception as e:
            print(f"[Metabase] Ошибка dashcard {dashcard_id}/{card_id}: {e}")
            return None

    def execute_question(self, question_id: int, parameters: Dict = None) -> Optional[List[Dict]]:
        """Выполнить question и получить данные"""
        headers = self._headers()
        if not headers:
            print(f"[Metabase] Нет авторизации для question {question_id}")
            return None

        try:
            url = f"{self.base_url}/api/card/{question_id}/query/json"
            payload = parameters or {}
            if question_id in [177, 178, 179, 180, 181, 182, 183, 191]:
                print(f"[Metabase] Question {question_id} request with {len(payload.get('parameters', []))} params")
            response = requests.post(url, headers=headers, json=payload, timeout=70, verify=VERIFY_SSL)

            if response.status_code == 200:
                data = response.json()
                if question_id in [177, 178, 179, 180, 181, 182, 183, 191]:
                    print(f"[Metabase] Question {question_id} response: {type(data)}, len={len(data) if isinstance(data, list) else '?'}")
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "error" in data:
                    print(f"[Metabase] Ошибка в ответе question {question_id}: {data.get('error')}")
                    return None
                return [data] if data else []
            elif response.status_code == 401:
                # Токен истёк, сбрасываем и пробуем снова
                self.session_token = None
                self.session_expires = None
                print(f"[Metabase] Токен истёк, переавторизация...")
                return self.execute_question(question_id, parameters)
            else:
                print(f"[Metabase] Ошибка question {question_id}: HTTP {response.status_code}")
                try:
                    error_detail = response.json()
                    err_msg = error_detail.get('message') or error_detail.get('error') or str(error_detail)[:200]
                    print(f"[Metabase] Question {question_id} error: {err_msg}")
                except:
                    print(f"[Metabase] Question {question_id} raw: {response.text[:200]}")
                return None

        except requests.exceptions.SSLError as e:
            print(f"[Metabase] SSL ошибка: {e}. Попробуйте установить VERIFY_SSL=false")
            return None
        except requests.exceptions.Timeout:
            print(f"[Metabase] Таймаут запроса question {question_id}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"[Metabase] Ошибка подключения: {e}")
            return None
        except Exception as e:
            print(f"[Metabase] Неожиданная ошибка: {e}")
            return None

    def execute_question_raw_sql(self, sql: str, db_id: int = 2) -> Optional[List[Dict]]:
        """Выполнить произвольный SQL через /api/dataset (PostgreSQL DB)."""
        headers = self._headers()
        if not headers:
            return None
        try:
            response = requests.post(
                f"{self.base_url}/api/dataset",
                headers=headers,
                json={"database": db_id, "type": "native", "native": {"query": sql}},
                timeout=60,
                verify=VERIFY_SSL,
            )
            if response.status_code in (200, 202):
                data = response.json()
                cols = [c["name"] for c in data.get("data", {}).get("cols", [])]
                rows = data.get("data", {}).get("rows", [])
                if not cols:
                    print(f"[Metabase] raw_sql HTTP {response.status_code} — no data in response (async job)")
                    return None
                return [dict(zip(cols, row)) for row in rows]
            elif response.status_code == 401:
                self.session_token = None
                self.session_expires = None
                return self.execute_question_raw_sql(sql, db_id)
            else:
                print(f"[Metabase] raw_sql HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"[Metabase] raw_sql error: {e}")
            return None

    def get_question_info(self, question_id: int) -> Optional[Dict]:
        """Получить информацию о question"""
        headers = self._headers()
        if not headers:
            return None

        try:
            response = requests.get(
                f"{self.base_url}/api/card/{question_id}",
                headers=headers,
                timeout=30,
                verify=VERIFY_SSL
            )

            if response.status_code == 200:
                return response.json()
            return None

        except Exception as e:
            print(f"[Metabase] Ошибка: {e}")
            return None


# Глобальный клиент
_client = None


def get_client() -> MetabaseClient:
    """Получить синглтон клиента"""
    global _client
    if _client is None:
        _client = MetabaseClient()
    return _client


# ============ ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ============

def get_merchants_report() -> List[Dict]:
    """
    Получить отчёт по мерчантам (#69)

    Возвращает:
    - Merchant Name: название
    - Сумма Amount: общая сумма
    - Количество: кол-во транзакций
    - Конверсия: конверсия в реквизиты
    - Конверсия в оплату: конверсия в оплату
    """
    qid = METABASE_QUESTIONS.get("merchants_report", 69)
    data = get_client().execute_question(qid)
    return data or []


def get_rates_by_method() -> List[Dict]:
    """
    Получить ставки по методам (#72)

    Возвращает:
    - name: название мерчанта
    - payment_type: метод оплаты
    - fee: комиссия
    - margin_buy: маржа
    - amount_gt/amount_lt: лимиты
    """
    qid = METABASE_QUESTIONS.get("rates_by_method", 72)
    data = get_client().execute_question(qid)
    return data or []


def get_conversion_requisites() -> Dict:
    """
    Получить общую конверсию в реквизиты (#55)

    Возвращает:
    - Конверсия в Реквизиты: процент
    """
    qid = METABASE_QUESTIONS.get("conversion_requisites", 55)
    data = get_client().execute_question(qid)
    if data and len(data) > 0:
        return data[0]
    return {}


def get_conversion_payment() -> Dict:
    """
    Получить конверсию в оплату (#56)

    Возвращает:
    - Всего: общее количество
    - Конверсия в оплату: процент
    - Успешных: количество успешных
    - Сумма заявок: сумма
    - Сумма успешных: сумма
    - Не выдано реквизитов: количество
    """
    qid = METABASE_QUESTIONS.get("conversion_payment", 56)
    data = get_client().execute_question(qid)
    if data and len(data) > 0:
        return data[0]
    return {}


def get_volumes_by_method() -> List[Dict]:
    """
    Получить объёмы по методам (#43)

    Возвращает:
    - Метод: название метода
    - Объем, упущенный (RUB): сумма
    - Объем, обработанный (RUB): сумма
    """
    qid = METABASE_QUESTIONS.get("volumes_by_method", 43)
    data = get_client().execute_question(qid)
    return data or []


def get_conversion_today() -> List[Dict]:
    """
    Получить конверсию за сегодня по мерчантам (#76)

    Возвращает список с данными по каждому мерчанту + строка ИТОГО:
    - Мерчант: название
    - Всего: количество ордеров
    - Успешных: количество успешных
    - Сумма: сумма ордеров
    - Сумма успешных: сумма успешных ордеров
    - Конверсия %: процент конверсии
    """
    qid = METABASE_QUESTIONS.get("conversion_today", 76)
    data = get_client().execute_question(qid)
    return data or []


def get_unpaid_orders() -> Dict[str, List[Dict[str, str]]]:
    """
    Получить неоплаченные заявки по мерчантам (#95)

    Возвращает словарь где ключ - merchant_name, значение - список словарей:
    {
        "Merchant1": [
            {"external_id": "abc-123", "method": "sbp"},
            {"external_id": "def-456", "method": "c2c"},
        ],
        ...
    }
    """
    qid = METABASE_QUESTIONS.get("unpaid_orders", 95)
    data = get_client().execute_question(qid)

    result = {}
    for row in data or []:
        merchant_name = row.get("merchant_name", "")
        # Новый формат: "ext_id;;method|ext_id;;method|..."
        details = row.get("unpaid_details") or ""

        if merchant_name and details and isinstance(details, str):
            parsed = []
            for entry in details.split('|'):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split(';;')
                if len(parts) == 2:
                    parsed.append({"external_id": parts[0], "method": parts[1]})
                else:
                    # Fallback: старый формат (только external_id)
                    parsed.append({"external_id": entry, "method": ""})
            result[merchant_name] = parsed

    return result


def get_conv_by_merchant_method() -> Dict[str, List[Dict]]:
    """
    Конверсия по мерчант+метод за сегодня (#256, PG).
    Консистентно с основной конверсией (та же БД и формула).
    Возвращает: {"Merchant X": [{"method": "sbp", "total": 100, "with_req": 30, "successful": 5, "conv_pct": 16.7}, ...]}
    """
    qid = METABASE_QUESTIONS.get("conv_by_merchant_method", 256)
    data = get_client().execute_question(qid)
    result = {}
    for row in data or []:
        name = row.get("merchant_name", "")
        if name:
            result.setdefault(name, []).append({
                "method": row.get("method", "unknown"),
                "total": int(row.get("total", 0) or 0),
                "with_req": int(row.get("with_req", 0) or 0),
                "successful": int(row.get("successful", 0) or 0),
                "conv_pct": float(row.get("conv_pct", 0) or 0),
            })
    return result


def get_hourly_by_merchant() -> Dict[str, Dict[str, List[Dict]]]:
    """
    Получить почасовую конверсию по мерчантам и методам за сегодня (#255).
    Возвращает:
    {
        "Merchant X": {
            "sbp": [{"hour": 0, "total": 10, "successful": 5, "conv_pct": 50.0}, ...],
            "c2c": [...]
        }
    }
    """
    qid = METABASE_QUESTIONS.get("hourly_by_merchant", 255)
    data = get_client().execute_question(qid)
    result = {}
    for row in data or []:
        name = row.get("merchant_name", "")
        method = row.get("payment_type", "unknown")
        if name:
            result.setdefault(name, {}).setdefault(method, []).append({
                "hour": int(row.get("hour", 0)),
                "total": int(row.get("total", 0)),
                "successful": int(row.get("successful", 0)),
                "conv_pct": float(row.get("conv_pct", 0)),
            })
    return result


def get_bad_clients() -> List[Dict]:
    """
    Получить список плохих пользователей по client_id (#97)

    Возвращает список записей с типами проблем:
    - bad_user: пользователи с низкой конверсией (<30%)
    - stub_client_id: мерчанты использующие заглушки (>90% одинаковый client_id)
    - random_client_id: мерчанты с рандомными client_id (>95% уникальных)

    Каждая запись содержит:
    {
        "merchant_name": "Merchant X",
        "client_id": "user_123" или "ЗАГЛУШКА" или "РАНДОМ",
        "total_orders": 20,
        "completed_orders": 3,
        "failed_orders": 17,
        "conversion_pct": 15.0,
        "issue_type": "bad_user" | "stub_client_id" | "random_client_id"
    }
    """
    qid = METABASE_QUESTIONS.get("bad_clients", 97)
    data = get_client().execute_question(qid)
    return data or []


def get_today_summary() -> Dict:
    """
    Получить сводку за сегодня из question #76

    Returns:
        Словарь с итоговыми метриками за день
    """
    data = get_conversion_today()

    # Ищем строку ИТОГО
    for row in data:
        merchant = row.get("Мерчант", "")
        if "ИТОГО" in merchant or merchant == "📊 ИТОГО":
            return {
                "total_orders": row.get("Всего", 0) or 0,
                "successful_orders": row.get("Успешных", 0) or 0,
                "total_amount": row.get("Сумма", 0) or 0,
                "successful_amount": row.get("Сумма успешных", 0) or 0,
                "conversion": row.get("Конверсия %", 0) or 0,
            }

    # Если строки ИТОГО нет, считаем сами
    total_orders = sum(r.get("Всего", 0) or 0 for r in data)
    successful = sum(r.get("Успешных", 0) or 0 for r in data)
    total_amount = sum(r.get("Сумма", 0) or 0 for r in data)
    successful_amount = sum(r.get("Сумма успешных", 0) or 0 for r in data)
    conversion = (successful / total_orders * 100) if total_orders > 0 else 0

    return {
        "total_orders": total_orders,
        "successful_orders": successful,
        "total_amount": total_amount,
        "successful_amount": successful_amount,
        "conversion": round(conversion, 2),
    }


def get_merchants_today() -> List[Dict]:
    """
    Получить данные по мерчантам за сегодня (без строки ИТОГО)
    """
    data = get_conversion_today()
    # Фильтруем строку ИТОГО
    return [r for r in data if "ИТОГО" not in r.get("Мерчант", "")]


def get_conversion_by_method() -> List[Dict]:
    """
    Получить конверсию по методам оплаты (#77)

    Возвращает:
    - Метод: название метода
    - Всего: количество ордеров
    - Успешных: количество успешных
    - Сумма: сумма ордеров
    - Конверсия %: процент конверсии
    """
    qid = METABASE_QUESTIONS.get("conversion_by_method", 77)
    data = get_client().execute_question(qid)
    return data or []


def get_hourly_stats() -> List[Dict]:
    """
    Получить почасовую статистику (#78)

    Возвращает:
    - Час: час (0-23)
    - Ордеров: количество
    - Успешных: количество успешных
    - Сумма: сумма
    - Конверсия %: процент
    """
    qid = METABASE_QUESTIONS.get("hourly_stats", 78)
    data = get_client().execute_question(qid)
    return data or []


def get_stats_by_bank() -> List[Dict]:
    """
    Получить статистику по банкам (#79)

    Возвращает:
    - Банк: название банка
    - Ордеров: количество
    - Успешных: количество успешных
    - Сумма: сумма
    - Конверсия %: процент
    """
    qid = METABASE_QUESTIONS.get("stats_by_bank", 79)
    data = get_client().execute_question(qid)
    return data or []


def get_compare_yesterday() -> List[Dict]:
    """
    Получить сравнение с вчера (#80)

    Возвращает:
    - День: "Сегодня" или "Вчера"
    - Ордеров: количество
    - Успешных: количество успешных
    - Сумма: сумма
    - Конверсия %: процент
    """
    qid = METABASE_QUESTIONS.get("compare_yesterday", 80)
    data = get_client().execute_question(qid)
    return data or []


def get_canceled_analysis() -> List[Dict]:
    """
    Получить анализ отмен (#81)

    Возвращает:
    - Причина: причина отмены
    - Количество: количество отмен
    - Сумма: сумма отменённых
    """
    qid = METABASE_QUESTIONS.get("canceled_analysis", 81)
    data = get_client().execute_question(qid)
    return data or []


def get_main_dashboard() -> Dict:
    """
    Получить данные главного дашборда (#82)

    Возвращает:
    - Всего заявок
    - Успешных заявок
    - Невыдано реквизитов
    - Конверсия в реквизиты %
    - Конверсия в оплату %
    - Сумма успешных
    """
    qid = METABASE_QUESTIONS.get("main_dashboard", 82)
    data = get_client().execute_question(qid)
    if data and len(data) > 0:
        return data[0]
    return {}


# ============ АГРЕГИРОВАННЫЕ ДАННЫЕ ============

def get_merchant_stats(merchant_name: str) -> Dict:
    """
    Получить статистику по конкретному мерчанту

    Args:
        merchant_name: название мерчанта

    Returns:
        Словарь со всеми данными мерчанта
    """
    result = {
        "name": merchant_name,
        "report": None,
        "rates": [],
    }

    # Данные из отчёта по мерчантам
    merchants = get_merchants_report()
    for m in merchants:
        if m.get("Merchant Name", "").lower() == merchant_name.lower():
            result["report"] = m
            break

    # Ставки по методам
    rates = get_rates_by_method()
    for r in rates:
        if r.get("name", "").lower() == merchant_name.lower():
            result["rates"].append(r)

    return result


def get_all_merchants_from_metabase() -> List[str]:
    """Получить список всех мерчантов из Metabase"""
    merchants = set()

    # Из отчёта
    report = get_merchants_report()
    for m in report:
        name = m.get("Merchant Name")
        if name:
            merchants.add(name)

    # Из ставок
    rates = get_rates_by_method()
    for r in rates:
        name = r.get("name")
        if name:
            merchants.add(name)

    return sorted(list(merchants))


def get_dashboard_summary() -> Dict:
    """
    Получить сводку для дашборда (данные за СЕГОДНЯ)

    Returns:
        Словарь с ключевыми метриками
    """
    # Данные за сегодня из question #76
    today = get_today_summary()
    merchants_today = get_merchants_today()

    # Ставки
    rates = get_rates_by_method()

    return {
        "merchants_count": len(merchants_today),
        "total_orders": today.get("total_orders", 0),
        "successful_orders": today.get("successful_orders", 0),
        "total_amount": today.get("total_amount", 0),
        "successful_amount": today.get("successful_amount", 0),
        "conversion": today.get("conversion", 0),
        "rates_count": len(rates),
    }


def test_connection() -> bool:
    """Проверить подключение к Metabase"""
    client = get_client()
    token = client._get_session()
    return token is not None


# ============ ПОИСК МЕРЧАНТА ============

def search_merchant(query: str) -> List[Dict]:
    """
    Поиск мерчанта по имени

    Args:
        query: строка поиска

    Returns:
        Список найденных мерчантов с их статистикой
    """
    query_lower = query.lower().strip()
    results = []

    # Ищем в данных за сегодня
    merchants = get_conversion_today()
    for m in merchants:
        name = m.get("Мерчант", "")
        if query_lower in name.lower() and "ИТОГО" not in name:
            results.append(m)

    return results


def get_merchant_detailed(merchant_name: str) -> Dict:
    """
    Получить детальную информацию по мерчанту
    """
    result = {
        "name": merchant_name,
        "today": None,
        "rates": [],
    }

    # Данные за сегодня
    merchants = get_conversion_today()
    for m in merchants:
        if m.get("Мерчант", "").lower() == merchant_name.lower():
            result["today"] = m
            break

    # Ставки
    rates = get_rates_by_method()
    for r in rates:
        if r.get("name", "").lower() == merchant_name.lower():
            result["rates"].append(r)

    return result


# ============ НЕДЕЛЬНАЯ/МЕСЯЧНАЯ СТАТИСТИКА ============

def get_weekly_stats() -> Dict:
    """
    Получить статистику за неделю (#83)
    """
    qid = METABASE_QUESTIONS.get("weekly_stats", 83)
    data = get_client().execute_question(qid)
    if data and len(data) > 0:
        return data[0]
    return {}


def get_monthly_stats() -> Dict:
    """
    Получить статистику за месяц (#85)
    """
    qid = METABASE_QUESTIONS.get("monthly_stats", 85)
    data = get_client().execute_question(qid)
    if data and len(data) > 0:
        return data[0]
    return {}


def get_weekly_by_day() -> List[Dict]:
    """
    Получить статистику по дням за неделю (#84)
    """
    qid = METABASE_QUESTIONS.get("weekly_by_day", 84)
    data = get_client().execute_question(qid)
    return data or []


# ============ АЛЕРТЫ ============

def check_alerts() -> List[Dict]:
    """
    Проверить условия для алертов

    Returns:
        Список активных алертов
    """
    alerts = []

    try:
        # Получаем текущие данные
        dashboard = get_main_dashboard()
        compare = get_compare_yesterday()
        canceled = get_canceled_analysis()

        # 1. Проверка конверсии
        conv_today = dashboard.get('Конверсия в оплату %', 0) or 0

        # Находим вчерашнюю конверсию
        conv_yesterday = 0
        for row in compare:
            if row.get("День") == "Вчера":
                conv_yesterday = row.get("Конверсия %", 0) or 0
                break

        # Алерт если конверсия упала более чем на 20%
        if conv_yesterday > 0 and conv_today < conv_yesterday * 0.8:
            drop = ((conv_yesterday - conv_today) / conv_yesterday) * 100
            alerts.append({
                "type": "conversion_drop",
                "severity": "high",
                "title": "📉 Падение конверсии",
                "message": f"Конверсия упала на {drop:.1f}% (было {conv_yesterday:.2f}%, стало {conv_today:.2f}%)"
            })

        # 2. Проверка отмен
        total_canceled = sum(c.get("Количество", 0) or 0 for c in canceled)
        total_orders = dashboard.get('Всего заявок', 0) or 0

        if total_orders > 0:
            cancel_rate = (total_canceled / total_orders) * 100
            # Алерт если отмен больше 30%
            if cancel_rate > 30:
                alerts.append({
                    "type": "high_cancellation",
                    "severity": "medium",
                    "title": "❌ Много отмен",
                    "message": f"Отменено {cancel_rate:.1f}% заявок ({total_canceled:,} из {total_orders:,})"
                })

        # 3. Проверка успешных - если 0 за последний час
        hourly = get_hourly_stats()
        if hourly:
            last_hour = hourly[-1] if hourly else {}
            if last_hour.get("Успешных", 0) == 0 and last_hour.get("Ордеров", 0) > 10:
                alerts.append({
                    "type": "no_success",
                    "severity": "high",
                    "title": "🚨 Нет успешных",
                    "message": f"За последний час 0 успешных из {last_hour.get('Ордеров', 0)} заявок"
                })

    except Exception as e:
        alerts.append({
            "type": "error",
            "severity": "low",
            "title": "⚠️ Ошибка проверки",
            "message": str(e)[:100]
        })

    return alerts


# ============ PAYOUT (PaycrowOUT) ============

PAYOUT_STATS_SQL = """
SELECT
    m.name                           AS merchant,
    COUNT(*)                         AS total,
    COUNT(*) FILTER (WHERE o.status = 'closed')
                                     AS closed,
    ROUND(COUNT(*) FILTER (WHERE o.status = 'closed') * 100.0
          / NULLIF(COUNT(*), 0), 2)  AS conv_pct,
    ROUND(SUM(CASE WHEN o.status = 'closed'
              THEN o.amount ELSE 0 END)::numeric, 2)
                                     AS closed_amount
FROM orders o
JOIN merchants m ON o.merchant_id = m.id
WHERE o.type = 'credit'
  AND o.status != 'deleted'
  AND (o.created_at AT TIME ZONE 'Europe/Moscow')::date = CURRENT_DATE
GROUP BY m.name
ORDER BY total DESC
"""

PAYOUT_CHECK_RANGES_SQL = """
SELECT
    CASE
        WHEN o.amount >= 1000  AND o.amount < 5000   THEN '1-5K'
        WHEN o.amount >= 5000  AND o.amount < 10000   THEN '5-10K'
        WHEN o.amount >= 10000 AND o.amount < 20000   THEN '10-20K'
        WHEN o.amount >= 20000 AND o.amount < 40000   THEN '20-40K'
        WHEN o.amount >= 40000 AND o.amount <= 100000  THEN '40-100K'
        ELSE 'Other'
    END                              AS check_range,
    COUNT(*)                         AS total,
    COUNT(*) FILTER (WHERE o.status = 'closed')
                                     AS closed,
    ROUND(COUNT(*) * 100.0
          / NULLIF(SUM(COUNT(*)) OVER(), 0), 1)
                                     AS pct_of_total,
    ROUND(COUNT(*) FILTER (WHERE o.status = 'closed') * 100.0
          / NULLIF(COUNT(*), 0), 1)  AS conv_pct,
    ROUND(SUM(CASE WHEN o.status = 'closed'
              THEN o.amount ELSE 0 END)::numeric, 2)
                                     AS closed_amount
FROM orders o
JOIN merchants m ON o.merchant_id = m.id
WHERE o.type = 'credit'
  AND o.status != 'deleted'
  AND (o.created_at AT TIME ZONE 'Europe/Moscow')::date = CURRENT_DATE
GROUP BY 1
ORDER BY MIN(o.amount)
"""


def get_payout_stats() -> dict:
    """Получить статистику пейаута: мерчанты + разбивка чеков."""
    from concurrent.futures import ThreadPoolExecutor

    def _q(sql):
        return get_client().execute_question_raw_sql(sql)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_merchants = ex.submit(_q, PAYOUT_STATS_SQL)
        f_ranges = ex.submit(_q, PAYOUT_CHECK_RANGES_SQL)
        try:
            merchants = f_merchants.result(timeout=30) or []
        except Exception:
            merchants = []
        try:
            ranges = f_ranges.result(timeout=30) or []
        except Exception:
            ranges = []

    return {"merchants": merchants, "ranges": ranges}


# ============ ДАШБОРД #6 — ПОЛНАЯ КОПИЯ ============
# Маппинг: card_id → dashcard_id для дашборда #6
DASHBOARD_6_ID = 6
DASHCARD_MAP = {
    118: 91,   # Прибыль
    119: 92,   # Оборот
    120: 93,   # Конверсия %
    121: 94,   # Конверсия реквизиты %
    122: 95,   # Всего транзакций
    123: 96,   # (дополнительная карта)
    124: 97,   # Успешных
    125: 98,
    126: 99,   # Топ провайдеров по обороту
    127: 100,  # Топ мерчантов по обороту
    128: 101,
    129: 102,
    130: 103,
    131: 104,
    132: 105,
    133: 106,
    134: 107,
    144: 112,
    152: 116,
}

DASHBOARD_13_ID = 13
DASHBOARD_13_DASHCARD_MAP = {
    177: 129,  # Всего payin заявок
    178: 130,  # Сумма payin заявок
    179: 131,  # Сумма успешных payin
    180: 132,  # Кол-во успешных payin
    181: 133,  # Не успешных принятых трейдеров
    182: 134,  # Конверсия в успех %
    183: 135,  # Конверсия в выдачу %
    184: 136,  # По методам
    186: 138,  # По банкам
    187: 139,  # Банк × Метод
    222: 231,  # Реквизиты сегодня
}

PERIOD_PARAM_ID = "ada20461-4d68-5819-8657-6eccfd53168c"
MERCHANT_PARAM_ID = "385f2c43-017e-58c2-a4b7-7c58d0395840"
PROVIDER_PARAM_ID = "6d5c321f-86f8-54d8-adc9-bbd2afad0066"
METHOD_PARAM_ID = "f73c9982-259f-44ee-8748-3a16f3bdff61"
BANK_PARAM_ID = "8559edaf-a54e-5b9c-820a-1561eb8ba8bc"
OP_TYPE_PARAM_ID = "5fcaf754-5e54-5766-9633-965ddb5a72f7"

# Dashboard #13 parameter IDs (from Metabase dashboard)
TRADER_PERIOD_PARAM_ID = "dcbf42a6-bce3-4bee-b2dd-65483117533a"
TRADER_METHOD_PARAM_ID = "32941394-06ae-4f92-97b4-7a00f70b6218"
TRADER_BANK_PARAM_ID = "e4a69a1f-5720-487e-8988-b7c5ba2cdb90"
TRADER_TRADER_PARAM_ID = "f421bda1-cf63-4555-befc-06d5c1902860"
TRADER_TLA_PARAM_ID = "17915e7d-5bef-4714-8231-195ad4d7da81"
TRADER_HTL_PARAM_ID = "c8ec3138-3731-4fc2-bfe5-7a257a2b2a09"
TRADER_AGENT_PARAM_ID = "2d55dc9d-5afb-4f3d-a1db-dfbbc117209b"
TRADER_MERCHANT_PARAM_ID = "a1b2c3d4-e5f6-7890-abcd-merchant00001"


from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed


def _build_params(
    date_range: Optional[str] = None,
    merchant: Optional[str] = None,
    provider: Optional[str] = None,
    method: Optional[str] = None,
    bank: Optional[str] = None,
    op_type: Optional[str] = None,
) -> List[Dict]:
    params = []
    if date_range:
        params.append({
            "id": PERIOD_PARAM_ID,
            "type": "date/all-options",
            "value": date_range,
            "target": ["dimension", ["template-tag", "created_at"]],
        })
    if merchant:
        params.append({
            "id": MERCHANT_PARAM_ID,
            "type": "text",
            "value": [merchant],
            "target": ["dimension", ["template-tag", "merchant"]],
        })
    if provider:
        params.append({
            "id": PROVIDER_PARAM_ID,
            "type": "text",
            "value": [provider],
            "target": ["dimension", ["template-tag", "provider"]],
        })
    if method:
        params.append({
            "id": METHOD_PARAM_ID,
            "type": "text",
            "value": [method],
            "target": ["dimension", ["template-tag", "method"]],
        })
    if bank:
        params.append({
            "id": BANK_PARAM_ID,
            "type": "text",
            "value": [bank],
            "target": ["dimension", ["template-tag", "bank"]],
        })
    if op_type:
        params.append({
            "id": OP_TYPE_PARAM_ID,
            "type": "text",
            "value": [op_type],
            "target": ["dimension", ["template-tag", "op_type"]],
        })
    return params


def _dc(card_id: int, params: List[Dict]) -> Optional[List[Dict]]:
    dc_id = DASHCARD_MAP.get(card_id)
    if dc_id is None:
        return None
    return get_client().execute_dashboard_card(DASHBOARD_6_ID, dc_id, card_id, params)


def _build_trader_params(
    period: Optional[str] = None,
    trader: Optional[str] = None,
    method: Optional[str] = None,
    bank: Optional[str] = None,
    tla: Optional[str] = None,
    htl: Optional[str] = None,
    agent: Optional[str] = None,
    merchant: Optional[str] = None,
) -> List[Dict]:
    """Build parameters for Dashboard #13 (Trader dashboard) - exact Metabase format."""
    params = []
    if period:
        params.append({
            "type": "date/all-options",
            "value": period,
            "id": TRADER_PERIOD_PARAM_ID,
            "target": ["variable", ["template-tag", "period"]],
        })
    if trader:
        params.append({
            "type": "string/=",
            "value": trader,
            "id": TRADER_TRADER_PARAM_ID,
            "target": ["variable", ["template-tag", "trader"]],
        })
    if method:
        params.append({
            "type": "string/=",
            "value": method,
            "id": TRADER_METHOD_PARAM_ID,
            "target": ["variable", ["template-tag", "method"]],
        })
    if bank:
        params.append({
            "type": "string/=",
            "value": bank,
            "id": TRADER_BANK_PARAM_ID,
            "target": ["variable", ["template-tag", "bank"]],
        })
    if tla:
        params.append({
            "type": "string/=",
            "value": tla,
            "id": TRADER_TLA_PARAM_ID,
            "target": ["variable", ["template-tag", "tla"]],
        })
    if htl:
        params.append({
            "type": "string/=",
            "value": htl,
            "id": TRADER_HTL_PARAM_ID,
            "target": ["variable", ["template-tag", "htl"]],
        })
    if agent:
        params.append({
            "type": "string/=",
            "value": agent,
            "id": TRADER_AGENT_PARAM_ID,
            "target": ["variable", ["template-tag", "agent"]],
        })
    if merchant:
        params.append({
            "type": "string/=",
            "value": merchant,
            "id": TRADER_MERCHANT_PARAM_ID,
            "target": ["variable", ["template-tag", "merchant"]],
        })
    return params


def _dc13(card_id: int, params: List[Dict]) -> Optional[List[Dict]]:
    """Execute dashboard card for Dashboard #13 (Trader dashboard)."""
    dc_id = DASHBOARD_13_DASHCARD_MAP.get(card_id)
    if dc_id is None:
        return None
    return get_client().execute_dashboard_card(DASHBOARD_13_ID, dc_id, card_id, params)


def _today_range() -> str:
    """Return today's date range in Metabase format (Moscow time UTC+3)."""
    from datetime import timezone, timedelta
    msk = timezone(timedelta(hours=3))
    today = datetime.now(msk).strftime("%Y-%m-%d")
    return f"{today}~{today}"


def _scalar(rows: Optional[List[Dict]]) -> Optional[float]:
    """Extract first value from first row of a scalar card."""
    if not rows:
        return None
    first = rows[0]
    values = list(first.values())
    return values[0] if values else None


def _kpi_from_questions(date_range: Optional[str] = None) -> Dict:
    """
    Получить скалярные KPI из вопросов #82 + #76 + cards 120/121 параллельно.
    Конверсии берём из cards 120/121 для точности формул.

    Args:
        date_range: период в формате "YYYY-MM-DD~YYYY-MM-DD" или None
    """
    # Questions #82/#76 have hardcoded CURRENT_DATE — no template tags.
    # We skip them when period != today and rely on dashboard card API instead.
    params = {}

    print(f"[Metabase] _kpi_from_questions date_range={date_range}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        f82 = ex.submit(lambda: get_client().execute_question(82, params))
        f76 = ex.submit(lambda: get_client().execute_question(76, params))
        try:
            data82 = f82.result(timeout=25) or []
            data76 = f76.result(timeout=25) or []
        except Exception as e:
            print(f"[Metabase] _kpi_from_questions error: {e}")
            data82, data76 = [], []

    row82 = data82[0] if data82 else {}

    # Точные имена полей question #82:
    # "Всего заявок", "Успешных заявок", "Невыдано реквизитов",
    # "Конверсия в реквизиты %", "Конверсия в оплату %", "Сумма успешных"
    total         = row82.get("Всего заявок")
    successful    = row82.get("Успешных заявок")
    not_issued    = row82.get("Невыдано реквизитов")

    # Используем готовые поля конверсии из question #82
    # ВАЖНО: нужно проверить правильный ли маппинг
    # Card 120 "Конверсия в выдачу %" = (issued / total)
    # Card 121 "Конверсия в успех %" = (successful / issued)
    # Question #82 возвращает:
    # - "Конверсия в реквизиты %" = вероятно (issued / total)
    # - "Конверсия в оплату %" = вероятно (successful / issued)
    conv_pct = row82.get("Конверсия в реквизиты %")   # Конверсия в выдачу
    conv_req = row82.get("Конверсия в оплату %")       # Конверсия в успех

    # Вычисляем issued_req для отображения
    issued_req = None
    if total is not None and not_issued is not None:
        issued_req = total - not_issued

    print(f"[Metabase] Conversions from Q82: total={total}, successful={successful}, not_issued={not_issued}, issued={issued_req}, conv_pct={conv_pct}, conv_req={conv_req}")

    # Оборот = сумма всех "Сумма" по мерчантам из #76
    merchants_list = [r for r in data76 if "ИТОГО" not in r.get("Мерчант", "")]
    turnover = sum(float(r.get("Сумма") or 0) for r in merchants_list)
    # Если есть строка ИТОГО — берём из неё
    for r in data76:
        if "ИТОГО" in r.get("Мерчант", ""):
            turnover = float(r.get("Сумма") or 0) or turnover
            break

    merchants_list.sort(key=lambda r: float(r.get("Сумма") or 0), reverse=True)

    print(
        f"[Metabase] kpi_from_questions: total={total}, successful={successful}, "
        f"conv_pct={conv_pct}, conv_req={conv_req}, turnover={turnover:.0f}, merchants={len(merchants_list)}"
    )

    kpi = {
        "total":              float(total) if total is not None else None,
        "successful":         float(successful) if successful is not None else None,
        "turnover":           float(turnover) if turnover else None,
        "profit":             None,  # Only from card 118 (real profit), NOT Q82 "Сумма успешных"
        "conversion_pct":     float(conv_pct) if conv_pct is not None else None,
        "conversion_req_pct": float(conv_req) if conv_req is not None else None,
        "issued_req":         float(issued_req) if issued_req is not None else None,
        "avg_check":          None,
        "decline_pct":        None,
    }
    top_merchants = [
        {
            "Мерчант":     r.get("Мерчант"),
            "Всего":       r.get("Всего"),
            "Успешных":    r.get("Успешных"),
            "Сумма":       r.get("Сумма"),
            "Конверсия %": r.get("Конверсия %"),
        }
        for r in merchants_list[:15]
    ]
    return kpi, top_merchants


def _fallback_dashboard_parallel(date_range: Optional[str] = None) -> Dict:
    """Полный фолбек через вопросы (без dashboard card API)."""
    kpi, top_merchants = _kpi_from_questions(date_range)
    return {
        "kpi":               kpi,
        "top_merchants":     top_merchants,
        "top_providers":     [],
        "top_methods":       [],
        "top_providers_conv": [],
    }


def get_full_dashboard(
    date_range: Optional[str] = None,
    merchant: Optional[str] = None,
    provider: Optional[str] = None,
    method: Optional[str] = None,
    bank: Optional[str] = None,
    op_type: Optional[str] = None,
) -> Dict:
    """
    Получить полные данные дашборда #6 с опциональной фильтрацией.
    Все запросы к Metabase выполняются параллельно.
    Если dashboard card endpoint недоступен — фолбек на старые функции.
    """
    params = _build_params(date_range, merchant, provider, method, bank, op_type)

    # Задаём что запрашивать: name → card_id
    scalar_cards = {
        "total":              122,  # Всего транзакций
        "successful":         124,  # Успешных транзакций
        "turnover":           119,  # Оборот
        "profit":             118,  # Прибыль
        "conversion_pct":     120,  # Конверсия в выдачу %
        "conversion_req_pct": 121,  # Конверсия в успех %
        "issued_req":         123,  # Выдано реквизитов
        "avg_check":          128,  # Средний чек
        "decline_pct":        130,  # Процент отказов %
        "avg_profit_per_order": 129,  # Средняя прибыль на транзакцию
        "total_amount_all":   144,  # Сумма ордеров (все статусы)
    }
    table_cards = {
        # 127 (top_merchants) убран — всегда тайм-аутится, используем #76
        "top_providers": 126,  # Топ провайдеров (работает стабильно)
        "top_methods":   134,  # Топ-10 методов оплаты (работает стабильно)
        "top_providers_conv": 131,  # Топ-5 провайдеров по конверсии
        "hourly_transactions": 125,  # Транзакции по часам
        "funnel_statuses": 132,  # Воронка статусов
        "week_dynamics": 133,  # Динамика по дням недели
        "hourly_profit": 152,  # Почасовая прибыль
        "_profit":       118,  # Прибыль — скаляр из дашборда (точное значение)
    }

    all_cards = {**scalar_cards, **table_cards}
    results: Dict[str, Any] = {}

    # Предавторизация — одна сессия до параллельных вызовов
    get_client()._get_session()

    table_card_ids = list(table_cards.items())  # [(name, card_id), ...]

    # Determine if we can use questions (only valid for "today" since Q82/Q76 use CURRENT_DATE)
    # BUT: Questions use CURRENT_DATE in Metabase's UTC timezone.
    # Between 00:00-02:59 MSK, UTC date != MSK date, so questions return yesterday's data.
    # In that case, force card API with explicit date_range.
    from datetime import timezone as _tz
    _msk = _tz(timedelta(hours=3))
    _msk_date = datetime.now(_msk).date()
    _utc_date = datetime.now(_tz.utc).date()
    _dates_match = (_msk_date == _utc_date)
    is_today = _dates_match and ((date_range is None) or (date_range == _today_range()))

    if is_today:
        # For "today" — questions (fast) + table cards in parallel
        def _fetch_tables():
            t_results = {}
            with ThreadPoolExecutor(max_workers=len(table_card_ids)) as ex:
                fs = {ex.submit(_dc, cid, params): nm for nm, cid in table_card_ids}
                try:
                    for fut in _as_completed(fs, timeout=35):
                        nm = fs[fut]
                        try:
                            t_results[nm] = fut.result()
                        except Exception:
                            t_results[nm] = None
                except Exception:
                    for fut, nm in fs.items():
                        if nm not in t_results:
                            t_results[nm] = None
            return t_results

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_kpi    = ex.submit(_kpi_from_questions, date_range)
            f_tables = ex.submit(_fetch_tables)
            question_kpi, top_merchants = f_kpi.result(timeout=40)
            table_results               = f_tables.result(timeout=40)
        kpi_data = question_kpi
        print(f"[Metabase] tables ok: { {k: len(v) for k, v in table_results.items() if v} }")
        print(f"[Metabase] KPI source: questions (today)")
    else:
        # For other periods (or MSK/UTC mismatch) — ALL via dashboard card API
        scalar_items = list(scalar_cards.items())
        all_card_ids = scalar_items + table_card_ids  # scalars + tables together
        table_results = {}
        kpi_data = {}

        # Fetch ALL cards via dashboard card API in parallel
        with ThreadPoolExecutor(max_workers=min(len(all_card_ids), 10)) as ex:
            fs = {ex.submit(_dc, cid, params): (kind, nm)
                  for kind, items in [("scalar", scalar_items), ("table", table_card_ids)]
                  for nm, cid in items}
            try:
                for fut in _as_completed(fs, timeout=80):
                    kind, nm = fs[fut]
                    try:
                        rows = fut.result()
                        if kind == "scalar":
                            val = _scalar(rows)
                            if val is not None:
                                kpi_data[nm] = float(val)
                        else:
                            table_results[nm] = rows
                    except Exception:
                        if kind == "table":
                            table_results[nm] = None
            except Exception:
                pass

        # Fill missing scalars with None
        for key in scalar_cards:
            if key not in kpi_data:
                kpi_data[key] = None
        filled = sum(1 for v in kpi_data.values() if v is not None)
        top_merchants = []
        print(f"[Metabase] tables ok: { {k: len(v) for k, v in table_results.items() if v} }")
        print(f"[Metabase] KPI source: dashboard card API ({filled}/{len(scalar_cards)} loaded)")

    # Profit ALWAYS from card 118 (real margin)
    profit_rows = table_results.get("_profit")
    if profit_rows:
        real_profit = _scalar(profit_rows)
        if real_profit is not None:
            kpi_data["profit"] = float(real_profit)
            print(f"[Metabase] Profit from card 118: {real_profit}")
    else:
        print(f"[Metabase] Card 118 (profit) not available, showing —")

    return {
        "kpi": kpi_data,
        "top_merchants":      table_results.get("top_merchants") or top_merchants,
        "top_providers":      table_results.get("top_providers") or [],
        "top_methods":        table_results.get("top_methods") or [],
        "top_providers_conv": table_results.get("top_providers_conv") or [],
        "hourly_transactions": table_results.get("hourly_transactions") or [],
        "funnel_statuses":    table_results.get("funnel_statuses") or [],
        "week_dynamics":      table_results.get("week_dynamics") or [],
        "hourly_profit":      table_results.get("hourly_profit") or [],
    }


def get_trader_dashboard(
    date_range: Optional[str] = None,
    trader: Optional[str] = None,
    method: Optional[str] = None,
    bank: Optional[str] = None,
    tla: Optional[str] = None,
    htl: Optional[str] = None,
    agent: Optional[str] = None,
    merchant: Optional[str] = None,
) -> Dict:
    """
    Получить полные данные дашборда #13 (Аналитика трейдерки) с опциональной фильтрацией.
    Скалярные KPI — из Dashboard Card API (#13).
    Конверсии — из Dashboard #13 (cards 182/183) — с учётом фильтров трейдера.
    Норма конверсии — из новых карточек 208-214.
    """
    params13 = _build_trader_params(date_range, trader, method, bank, tla, htl, agent, merchant)

    print(f"[Metabase] Fetching trader dashboard for period={date_range}")

    # Pre-authorize
    get_client()._get_session()

    # ── helpers ─────────────────────────────────────────────────

    def _fetch_d13_scalar(card_id: int):
        try:
            data = _dc13(card_id, params13)
            if data and len(data) > 0:
                val = list(data[0].values())[0]
                print(f"[Metabase] Trader DC13 scalar {card_id} → {val}")
                return val
            print(f"[Metabase] Trader DC13 scalar {card_id} → empty")
        except Exception as e:
            print(f"[Metabase] Trader DC13 scalar {card_id} error: {e}")
        return None

    def _fetch_d13_table(card_id: int):
        try:
            data = _dc13(card_id, params13)
            if data:
                print(f"[Metabase] Trader DC13 table {card_id} → {len(data)} rows")
                return data
        except Exception as e:
            print(f"[Metabase] Trader DC13 table {card_id} error: {e}")
        return []

    def _fetch_d6_scalar(card_id: int, label: str):
        """Fetch scalar from Dashboard #6 (admin source)."""
        try:
            data = _dc(card_id, params6)
            if data and len(data) > 0:
                val = list(data[0].values())[0]
                print(f"[Metabase] Trader D6 {label} (card {card_id}) → {val}")
                return val
            print(f"[Metabase] Trader D6 {label} (card {card_id}) → empty")
        except Exception as e:
            print(f"[Metabase] Trader D6 {label} (card {card_id}) error: {e}")
        return None

    # ── parallel fetch ──────────────────────────────────────────

    kpi_data = {}
    table_data = {}

    # All tasks: (future, type, key)
    with ThreadPoolExecutor(max_workers=6) as ex:
        tasks = {}

        # Scalars from Dashboard #13
        for cid, kpi_name in {177: "total_payin", 178: "amount_payin", 179: "amount_successful",
                               180: "count_successful", 181: "count_failed"}.items():
            tasks[ex.submit(_fetch_d13_scalar, cid)] = ("scalar", kpi_name)

        # Conversion scalars from Dashboard #13 (trader-specific, respects all filters)
        tasks[ex.submit(_fetch_d13_scalar, 182)] = ("scalar", "conversion_success")
        tasks[ex.submit(_fetch_d13_scalar, 183)] = ("scalar", "conversion_issued")

        # Tables from Dashboard #13
        for tbl_name, cid in {"by_methods": 184, "by_banks": 186, "bank_method": 187}.items():
            tasks[ex.submit(_fetch_d13_table, cid)] = ("table", tbl_name)


        try:
            for fut in _as_completed(tasks, timeout=70):
                kind, name = tasks[fut]
                try:
                    val = fut.result()
                    if kind == "scalar":
                        kpi_data[name] = val
                    else:
                        table_data[name] = val if val else []
                except Exception as e:
                    print(f"[Metabase] Future error ({kind}/{name}): {e}")
                    if kind == "table":
                        table_data[name] = []
        except Exception as e:
            print(f"[Metabase] Trader dashboard timeout: {sum(1 for f in tasks if not f.done())} (of {len(tasks)}) futures unfinished")

    print(f"[Metabase] Trader dashboard ready, KPI: {kpi_data}")

    return {
        "kpi": kpi_data,
        "by_methods": table_data.get("by_methods", []),
        "by_banks": table_data.get("by_banks", []),
        "bank_method": table_data.get("bank_method", []),
    }


def _fetch_question_values(card_id: int) -> List[str]:
    """Fetch unique values from a single-column Metabase question."""
    try:
        data = get_client().execute_question(card_id, {})
        if not data:
            print(f"[Metabase] Filter card {card_id} → None/empty response")
            return []
        print(f"[Metabase] Filter card {card_id} → {len(data)} rows, cols: {list(data[0].keys()) if data else '?'}")
        values = []
        for row in data:
            if row:
                val = list(row.values())[0]
                if val and str(val).strip():
                    values.append(str(val).strip())
        return sorted(set(values))
    except Exception as e:
        print(f"[Metabase] Filter card {card_id} error: {e}")
        return []


def get_trader_filter_options() -> Dict:
    """
    Получить списки значений для фильтров Dashboard #13 (Трейдерка).
    Методы/банки — из таблиц Dashboard Card API (184/186).
    Трейдеры/ТЛ/ХТЛ/агенты — из отдельных question cards (202/205/206/207).
    """
    try:
        get_client()._get_session()

        results = {}

        with ThreadPoolExecutor(max_workers=6) as ex:
            # Methods — from Dashboard Card API card 184 with today's date (fast)
            def _extract_methods():
                try:
                    from datetime import datetime, timezone, timedelta
                    msk = timezone(timedelta(hours=3))
                    today = datetime.now(msk).strftime("%Y-%m-%d")
                    today_params = _build_trader_params(today)
                    data = _dc13(184, today_params)
                    if data:
                        cols = list(data[0].keys())
                        method_col = cols[0]  # "Метод" or similar
                        vals = sorted(set(
                            str(row.get(method_col, "")).strip()
                            for row in data if row.get(method_col)
                        ))
                        print(f"[Metabase] Filter methods (DC13/184, col={method_col}) → {len(vals)}: {vals[:5]}")
                        return vals
                    print(f"[Metabase] Filter methods (DC13/184) → empty")
                except Exception as e:
                    print(f"[Metabase] Filter methods error: {e}")
                return []

            # Banks — from Dashboard Card API card 186 (column "Банк")
            def _extract_banks():
                try:
                    data = _dc13(186, [])
                    if data:
                        vals = sorted(set(
                            str(row.get("Банк", "")).strip()
                            for row in data if row.get("Банк")
                        ))
                        print(f"[Metabase] Filter banks (DC13/186) → {len(vals)}")
                        return vals
                except Exception as e:
                    print(f"[Metabase] Filter banks error: {e}")
                return []

            f_methods = ex.submit(_extract_methods)
            f_banks = ex.submit(_extract_banks)

            # Merchants — from dedicated question card
            # Card ID set after running create_tl_dashboards.py (see tl_dashboards_result.json)
            MERCHANTS_FILTER_CARD_ID = 223
            def _extract_merchants():
                try:
                    if MERCHANTS_FILTER_CARD_ID:
                        return _fetch_question_values(MERCHANTS_FILTER_CARD_ID)
                    # Fallback: extract from methods table (card 184)
                    print("[Metabase] MERCHANTS_FILTER_CARD_ID not set, trying merchants from orders")
                    data = get_client().execute_question(69)  # merchants_report
                    if data:
                        vals = sorted(set(
                            str(row.get("Мерчант", row.get("merchant_name", ""))).strip()
                            for row in data if row.get("Мерчант") or row.get("merchant_name")
                        ))
                        print(f"[Metabase] Filter merchants (Q#69 fallback) → {len(vals)}")
                        return vals
                except Exception as e:
                    print(f"[Metabase] Filter merchants error: {e}")
                return []

            f_merchants = ex.submit(_extract_merchants)

            # Traders/TLs/HTLs/agents — from dedicated question cards
            filter_cards = {
                "traders": 202,
                "agents": 205,
                "tlas": 206,
                "htls": 207,
            }
            filter_futures = {
                ex.submit(_fetch_question_values, cid): name
                for name, cid in filter_cards.items()
            }

            # Traders/TLs/HTLs/agents from questions (fast)
            for fut in _as_completed(filter_futures, timeout=30):
                name = filter_futures[fut]
                try:
                    results[name] = fut.result()
                except Exception as e:
                    print(f"[Metabase] Filter {name} error: {e}")
                    results[name] = []

            # Methods/banks (may take longer due to Dashboard Card API)
            try:
                results["banks"] = f_banks.result(timeout=30)
            except Exception as e:
                print(f"[Metabase] Filter banks timeout: {e}")
                results["banks"] = []

            try:
                results["methods"] = f_methods.result(timeout=60)
            except Exception as e:
                print(f"[Metabase] Filter methods timeout: {e}")
                results["methods"] = []

            try:
                results["merchants"] = f_merchants.result(timeout=30)
            except Exception as e:
                print(f"[Metabase] Filter merchants timeout: {e}")
                results["merchants"] = []

        print(f"[Metabase] Trader filter options: " +
              ", ".join(f"{len(results.get(k, []))} {k}" for k in ["methods", "banks", "traders", "tlas", "htls", "agents", "merchants"]))

        return {
            "methods": results.get("methods", []),
            "banks": results.get("banks", []),
            "traders": results.get("traders", []),
            "tlas": results.get("tlas", []),
            "htls": results.get("htls", []),
            "agents": results.get("agents", []),
            "merchants": results.get("merchants", []),
        }
    except Exception as e:
        print(f"[Metabase] Error fetching trader filter options: {e}")
        return {
            "methods": [],
            "banks": [],
            "traders": [],
            "tlas": [],
            "htls": [],
            "agents": [],
            "merchants": [],
        }


def get_bizdev_dashboard(date_range: Optional[str] = None) -> Dict:
    """
    Получить данные дашборда для биздевов.

    Dashboard #14 - Аналитика для биздевов:
    - Общая обработка (card 191)
    - Общая прибыль (card 192)
    - Количество провайдеров (card 193)
    - Выданные реки по часам (card 194) - bar chart
    - Методы: количество реков (card 195) - pie chart
    - Методы: прибыль (card 196) - pie chart
    - Таблица провайдеров (card 197)

    Args:
        date_range: период в формате "YYYY-MM-DD" или None для сегодня
    """
    # Build parameters - convert to text type for Question API
    params = []
    if date_range:
        params.append({
            "type": "text",
            "value": date_range,
            "id": "f208220c-70fa-5ee5-b32f-d836942cb9e3",
            "target": ["variable", ["template-tag", "created_at"]],
        })

    payload = {"parameters": params}

    print(f"[Metabase] Fetching bizdev dashboard for period={date_range}")

    # Pre-authorize
    get_client()._get_session()

    # Fetch scalars
    def fetch_scalar(card_id: int):
        try:
            data = get_client().execute_question(card_id, payload)
            if data and len(data) > 0:
                row = data[0]
                # Get first value from dict
                if isinstance(row, dict):
                    val = list(row.values())[0] if row.values() else None
                else:
                    val = row
                print(f"[Metabase] BizDev card {card_id} → {val}")
                return val
            return None
        except Exception as e:
            print(f"[Metabase] BizDev card {card_id} error: {e}")
            return None

    # Fetch tables
    def fetch_table(card_id: int):
        try:
            data = get_client().execute_question(card_id, payload)
            if data:
                print(f"[Metabase] BizDev table {card_id} → {len(data)} rows")
            return data if data else []
        except Exception as e:
            print(f"[Metabase] BizDev table {card_id} error: {e}")
            return []

    # Fetch ALL cards in parallel (7 workers = no queuing)
    with ThreadPoolExecutor(max_workers=7) as ex:
        f_processed = ex.submit(fetch_scalar, 191)
        f_profit = ex.submit(fetch_scalar, 192)
        f_providers_cnt = ex.submit(fetch_scalar, 193)
        f_hourly = ex.submit(fetch_table, 194)
        f_methods_count = ex.submit(fetch_table, 195)
        f_methods_profit = ex.submit(fetch_table, 196)
        f_providers_table = ex.submit(fetch_table, 197)

        # Get results with timeout (40 sec = matches HTTP timeout)
        try:
            total_processed = f_processed.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev card 191 timeout/error: {e}")
            total_processed = None

        try:
            total_profit = f_profit.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev card 192 timeout/error: {e}")
            total_profit = None

        try:
            providers_count = f_providers_cnt.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev card 193 timeout/error: {e}")
            providers_count = None

        try:
            hourly = f_hourly.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev hourly timeout/error: {e}")
            hourly = []

        try:
            methods_count = f_methods_count.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev methods_count timeout/error: {e}")
            methods_count = []

        try:
            methods_profit = f_methods_profit.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev methods_profit timeout/error: {e}")
            methods_profit = []

        try:
            providers_table = f_providers_table.result(timeout=40)
        except Exception as e:
            print(f"[Metabase] BizDev providers_table timeout/error: {e}")
            providers_table = []

    # Build KPI object
    kpi = {
        "total_processed": float(total_processed) if total_processed is not None else None,
        "total_profit": float(total_profit) if total_profit is not None else None,
        "providers_count": float(providers_count) if providers_count is not None else None,
    }

    print(f"[Metabase] BizDev dashboard OK: processed={total_processed}, profit={total_profit}, providers={providers_count}")

    return {
        "kpi": kpi,
        "hourly_issued": hourly,
        "methods_pie_count": methods_count,
        "methods_pie_profit": methods_profit,
        "providers_table": providers_table,
    }


# ============ ТЕСТ ============

if __name__ == "__main__":
    print("Тестирование подключения к Metabase...")

    if test_connection():
        print("✅ Подключение успешно!")

        print("\n=== Сводка за сегодня ===")
        summary = get_dashboard_summary()
        print(f"Мерчантов: {summary['merchants_count']}")
        print(f"Всего ордеров: {summary['total_orders']:,}")
        print(f"Успешных: {summary['successful_orders']:,}")
        print(f"Сумма ордеров: {summary['total_amount']:,.0f} RUB")
        print(f"Сумма успешных: {summary['successful_amount']:,.0f} RUB")
        print(f"Конверсия: {summary['conversion']:.2f}%")

        print("\n=== Мерчанты за сегодня ===")
        merchants = get_merchants_today()
        print(f"Всего: {len(merchants)}")
        for m in merchants[:10]:
            name = m.get("Мерчант", "?")
            total = m.get("Всего", 0)
            success = m.get("Успешных", 0)
            conv = m.get("Конверсия %", 0)
            print(f"  - {name}: {total} ордеров, {success} успешных ({conv}%)")
    else:
        print("❌ Не удалось подключиться")
