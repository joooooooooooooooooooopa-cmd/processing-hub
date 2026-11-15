"""
Модуль для работы с базой данных PostgreSQL
Хранение игнорируемых реквизитов
"""
import psycopg2
from psycopg2 import pool
from datetime import datetime, timedelta, timezone
import os
from typing import Optional

MSK = timezone(timedelta(hours=3))

# Connection pool
connection_pool = None


def get_connection_pool():
    """Получает или создает connection pool"""
    global connection_pool

    if connection_pool is None:
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url:
            raise ValueError("DATABASE_URL не найден в переменных окружения")

        connection_pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            database_url
        )

    return connection_pool


def init_database():
    """
    Инициализирует все таблицы базы данных
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        # Создаем таблицу игнорируемых реквизитов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ignored_requisites (
                gate_name VARCHAR(255) PRIMARY KEY,
                ignored_at TIMESTAMP WITH TIME ZONE NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)

        # Создаем индекс на expires_at для быстрой очистки
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ignored_expires
            ON ignored_requisites(expires_at)
        """)

        conn.commit()
        cursor.close()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)

    # Создаем таблицу комментариев (зависит от ignored_requisites из-за FOREIGN KEY)
    init_ignore_comments_table()

    # Создаем таблицу истории алертов
    init_alert_history_table()


def add_ignored_requisite(gate_name: str, duration_hours: int = 24) -> None:
    """
    Добавляет реквизит в список игнорируемых

    Args:
        gate_name: Название реквизита
        duration_hours: Количество часов игнорирования (по умолчанию 24)
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)
        expires = now + timedelta(hours=duration_hours)

        # Используем UPSERT (INSERT ... ON CONFLICT)
        cursor.execute("""
            INSERT INTO ignored_requisites (gate_name, ignored_at, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (gate_name)
            DO UPDATE SET
                ignored_at = EXCLUDED.ignored_at,
                expires_at = EXCLUDED.expires_at
        """, (gate_name, now, expires))

        conn.commit()

        print(f"💾 Добавлен в игнор: {gate_name}")
        print(f"   Текущее время: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"   Истекает: {expires.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        cursor.close()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)


def is_requisite_ignored(gate_name: str) -> bool:
    """
    Проверяет, находится ли реквизит в игнор-листе

    Args:
        gate_name: Название реквизита

    Returns:
        True если реквизит игнорируется
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)

        # Получаем информацию о записи для отладки
        cursor.execute("""
            SELECT gate_name, ignored_at, expires_at
            FROM ignored_requisites
            WHERE gate_name = %s
        """, (gate_name,))

        record = cursor.fetchone()

        if record:
            _, ignored_at, expires_at = record
            is_active = expires_at > now
            print(f"🔍 Проверка игнорирования: {gate_name}")
            print(f"   Текущее время: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"   Истекает: {expires_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"   Активен: {is_active}")

        cursor.execute("""
            SELECT COUNT(*)
            FROM ignored_requisites
            WHERE gate_name = %s AND expires_at > %s
        """, (gate_name, now))

        result = cursor.fetchone()
        cursor.close()

        return result[0] > 0 if result else False

    except Exception as e:
        print(f"Ошибка проверки игнорирования: {e}")
        return False
    finally:
        pool.putconn(conn)


def clean_expired_requisites() -> int:
    """
    Удаляет просроченные записи из таблицы

    Returns:
        Количество удаленных записей
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)

        cursor.execute("""
            DELETE FROM ignored_requisites
            WHERE expires_at <= %s
        """, (now,))

        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()

        return deleted_count

    except Exception as e:
        conn.rollback()
        print(f"Ошибка очистки просроченных записей: {e}")
        return 0
    finally:
        pool.putconn(conn)


def get_ignore_time_left(gate_name: str) -> Optional[int]:
    """
    Возвращает сколько часов осталось до истечения игнорирования

    Args:
        gate_name: Название реквизита

    Returns:
        Количество часов или None если не игнорируется
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT expires_at
            FROM ignored_requisites
            WHERE gate_name = %s
        """, (gate_name,))

        result = cursor.fetchone()
        cursor.close()

        if not result:
            return None

        expires_at = result[0]
        now = datetime.now(MSK)

        if expires_at <= now:
            return 0

        hours_left = (expires_at - now).total_seconds() / 3600
        return int(hours_left)

    except Exception as e:
        print(f"Ошибка получения времени игнорирования: {e}")
        return None
    finally:
        pool.putconn(conn)


def get_all_ignored() -> list:
    """
    Возвращает список всех игнорируемых реквизитов

    Returns:
        Список словарей с информацией о реквизитах
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)

        cursor.execute("""
            SELECT gate_name, ignored_at, expires_at
            FROM ignored_requisites
            WHERE expires_at > %s
            ORDER BY expires_at DESC
        """, (now,))

        results = []
        for row in cursor.fetchall():
            results.append({
                'gate_name': row[0],
                'ignored_at': row[1],
                'expires_at': row[2],
                'hours_left': int((row[2] - now).total_seconds() / 3600)
            })

        cursor.close()
        return results

    except Exception as e:
        print(f"Ошибка получения списка игнорируемых: {e}")
        return []
    finally:
        pool.putconn(conn)


# ==================== НОВЫЕ ФУНКЦИИ ДЛЯ КОММЕНТАРИЕВ И ИСТОРИИ АЛЕРТОВ ====================


def init_ignore_comments_table() -> None:
    """
    Инициализирует таблицу для комментариев к игнорируемым реквизитам
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        # Создаем таблицу комментариев
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ignore_comments (
                id SERIAL PRIMARY KEY,
                gate_name VARCHAR(255) NOT NULL,
                user_id BIGINT NOT NULL,
                comment TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                FOREIGN KEY (gate_name) REFERENCES ignored_requisites(gate_name) ON DELETE CASCADE
            )
        """)

        # Создаем индекс для быстрого поиска по реквизиту
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ignore_comments_gate
            ON ignore_comments(gate_name)
        """)

        # Создаем индекс для сортировки по дате
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ignore_comments_created
            ON ignore_comments(created_at DESC)
        """)

        conn.commit()
        cursor.close()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)


def init_alert_history_table() -> None:
    """
    Инициализирует таблицу для истории алертов
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        # Создаем таблицу истории алертов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id SERIAL PRIMARY KEY,
                gate_name VARCHAR(255) NOT NULL,
                conversion_pct FLOAT NOT NULL,
                total_orders INT NOT NULL,
                success_orders INT NOT NULL,
                alerted_at TIMESTAMP WITH TIME ZONE NOT NULL,
                alert_type VARCHAR(50) NOT NULL
            )
        """)

        # Создаем индексы для быстрых запросов
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alert_history_gate
            ON alert_history(gate_name)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alert_history_date
            ON alert_history(alerted_at DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alert_history_gate_date
            ON alert_history(gate_name, alerted_at DESC)
        """)

        conn.commit()
        cursor.close()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)


def add_ignore_comment(gate_name: str, user_id: int, comment: str) -> None:
    """
    Добавляет комментарий к игнорированному реквизиту

    Args:
        gate_name: Название реквизита
        user_id: Telegram ID пользователя
        comment: Текст комментария
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)

        cursor.execute("""
            INSERT INTO ignore_comments (gate_name, user_id, comment, created_at)
            VALUES (%s, %s, %s, %s)
        """, (gate_name, user_id, comment, now))

        conn.commit()
        cursor.close()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)


def get_ignore_comments(gate_name: str) -> list:
    """
    Получает все комментарии для реквизита

    Args:
        gate_name: Название реквизита

    Returns:
        Список словарей с комментариями
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, comment, created_at
            FROM ignore_comments
            WHERE gate_name = %s
            ORDER BY created_at DESC
        """, (gate_name,))

        results = []
        for row in cursor.fetchall():
            results.append({
                'user_id': row[0],
                'comment': row[1],
                'created_at': row[2]
            })

        cursor.close()
        return results

    except Exception as e:
        print(f"Ошибка получения комментариев: {e}")
        return []
    finally:
        pool.putconn(conn)


def get_all_ignored_with_comments() -> list:
    """
    Возвращает список игнорируемых реквизитов с комментариями

    Returns:
        Список словарей с информацией о реквизитах и комментариях
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)

        # Получаем все активные игнорируемые реквизиты с комментариями
        cursor.execute("""
            SELECT
                ir.gate_name,
                ir.ignored_at,
                ir.expires_at,
                ic.user_id,
                ic.comment,
                ic.created_at as comment_created_at
            FROM ignored_requisites ir
            LEFT JOIN ignore_comments ic ON ir.gate_name = ic.gate_name
            WHERE ir.expires_at > %s
            ORDER BY ir.expires_at DESC, ic.created_at DESC
        """, (now,))

        # Группируем результаты по реквизитам
        requisites_dict = {}

        for row in cursor.fetchall():
            gate_name = row[0]

            if gate_name not in requisites_dict:
                requisites_dict[gate_name] = {
                    'gate_name': gate_name,
                    'ignored_at': row[1],
                    'expires_at': row[2],
                    'hours_left': int((row[2] - now).total_seconds() / 3600),
                    'comments': []
                }

            # Добавляем комментарий если есть
            if row[3] is not None:  # user_id
                requisites_dict[gate_name]['comments'].append({
                    'user_id': row[3],
                    'comment': row[4],
                    'created_at': row[5]
                })

        cursor.close()
        return list(requisites_dict.values())

    except Exception as e:
        print(f"Ошибка получения списка с комментариями: {e}")
        return []
    finally:
        pool.putconn(conn)


def save_alert(gate_name: str, conversion_pct: float, total_orders: int,
               success_orders: int, alert_type: str = 'normal') -> None:
    """
    Сохраняет информацию об алерте в истории

    Args:
        gate_name: Название реквизита
        conversion_pct: Конверсия в процентах
        total_orders: Всего заказов
        success_orders: Успешных заказов
        alert_type: Тип алерта ('normal', 'recurring', 'new', 'critical_drop')
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        now = datetime.now(MSK)

        cursor.execute("""
            INSERT INTO alert_history (gate_name, conversion_pct, total_orders, success_orders, alerted_at, alert_type)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (gate_name, conversion_pct, total_orders, success_orders, now, alert_type))

        conn.commit()
        cursor.close()

    except Exception as e:
        conn.rollback()
        print(f"Ошибка сохранения алерта: {e}")
        raise e
    finally:
        pool.putconn(conn)


def get_alert_count_today(gate_name: str) -> int:
    """
    Подсчитывает количество алертов за сегодня для реквизита

    Args:
        gate_name: Название реквизита

    Returns:
        Количество алертов
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        # Получаем начало дня в MSK
        cursor.execute("""
            SELECT COUNT(*)
            FROM alert_history
            WHERE gate_name = %s
            AND alerted_at >= date_trunc('day', now() AT TIME ZONE 'Europe/Moscow')
        """, (gate_name,))

        result = cursor.fetchone()
        cursor.close()

        return result[0] if result else 0

    except Exception as e:
        print(f"Ошибка подсчета алертов: {e}")
        return 0
    finally:
        pool.putconn(conn)


def get_average_conversion_last_week(gate_name: str) -> Optional[float]:
    """
    Получает среднюю конверсию за последние 7 дней для реквизита

    Args:
        gate_name: Название реквизита

    Returns:
        Средняя конверсия или None если нет данных
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT AVG(conversion_pct)
            FROM alert_history
            WHERE gate_name = %s
            AND alerted_at >= now() - INTERVAL '7 days'
        """, (gate_name,))

        result = cursor.fetchone()
        cursor.close()

        return result[0] if result and result[0] is not None else None

    except Exception as e:
        print(f"Ошибка получения средней конверсии: {e}")
        return None
    finally:
        pool.putconn(conn)


def is_new_problem_requisite(gate_name: str) -> bool:
    """
    Проверяет является ли реквизит новой проблемой (первый раз в алертах)

    Args:
        gate_name: Название реквизита

    Returns:
        True если реквизит впервые в алертах
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM alert_history
            WHERE gate_name = %s
        """, (gate_name,))

        result = cursor.fetchone()
        cursor.close()

        return result[0] == 0 if result else True

    except Exception as e:
        print(f"Ошибка проверки новой проблемы: {e}")
        return False
    finally:
        pool.putconn(conn)


def clean_old_alerts(days: int = 30) -> int:
    """
    Удаляет старые алерты для оптимизации БД

    Args:
        days: Удалить алерты старше N дней

    Returns:
        Количество удаленных записей
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM alert_history
            WHERE alerted_at < now() - INTERVAL '%s days'
        """, (days,))

        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()

        return deleted_count

    except Exception as e:
        conn.rollback()
        print(f"Ошибка очистки старых алертов: {e}")
        return 0
    finally:
        pool.putconn(conn)


def get_alerts_for_export(hours: int = 24) -> list:
    """
    Получает все алерты за последние N часов для экспорта

    Args:
        hours: Количество часов назад

    Returns:
        Список словарей с данными алертов
    """
    pool = get_connection_pool()
    conn = pool.getconn()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT gate_name, conversion_pct, total_orders, success_orders, alerted_at, alert_type
            FROM alert_history
            WHERE alerted_at >= now() - INTERVAL '%s hours'
            ORDER BY alerted_at DESC
        """, (hours,))

        results = []
        for row in cursor.fetchall():
            results.append({
                'gate_name': row[0],
                'conversion_pct': row[1],
                'total_orders': row[2],
                'success_orders': row[3],
                'alerted_at': row[4],
                'alert_type': row[5]
            })

        cursor.close()
        return results

    except Exception as e:
        print(f"Ошибка получения данных для экспорта: {e}")
        return []
    finally:
        pool.putconn(conn)
