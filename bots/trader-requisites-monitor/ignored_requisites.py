"""
Управление списком игнорируемых реквизитов
Реквизиты хранятся в PostgreSQL базе данных (persistence across deployments)
Для обратной совместимости сохранены те же функции, но используется БД вместо JSON
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import database

MSK = timezone(timedelta(hours=3))
IGNORE_DURATION_HOURS = 24

# Постоянно игнорируемые — никогда не попадают в сводку
PERMANENT_IGNORE = {'example_trader', 'example_trader@example.com'}


def is_ignored(gate_name: str) -> bool:
    """
    Проверяет, находится ли реквизит в игнор-листе

    Args:
        gate_name: Название реквизита

    Returns:
        True если реквизит игнорируется
    """
    if gate_name in PERMANENT_IGNORE:
        return True
    try:
        # Автоматически очищаем просроченные записи
        database.clean_expired_requisites()

        return database.is_requisite_ignored(gate_name)
    except Exception as e:
        print(f"Ошибка проверки игнорирования: {e}")
        return False


def add_to_ignored(gate_name: str) -> None:
    """
    Добавляет реквизит в игнор-лист

    Args:
        gate_name: Название реквизита
    """
    try:
        database.add_ignored_requisite(gate_name, IGNORE_DURATION_HOURS)
    except Exception as e:
        print(f"Ошибка добавления в игнор-лист: {e}")


def get_ignore_time_left(gate_name: str) -> Optional[int]:
    """
    Возвращает сколько часов осталось до истечения игнорирования

    Args:
        gate_name: Название реквизита

    Returns:
        Количество часов или None если не игнорируется
    """
    try:
        return database.get_ignore_time_left(gate_name)
    except Exception as e:
        print(f"Ошибка получения времени: {e}")
        return None


def get_all_ignored() -> list:
    """
    Возвращает список всех игнорируемых реквизитов

    Returns:
        Список словарей с информацией о реквизитах
    """
    try:
        return database.get_all_ignored()
    except Exception as e:
        print(f"Ошибка получения списка: {e}")
        return []


# Deprecated functions - для обратной совместимости
def load_ignored():
    """DEPRECATED: Используется database.get_all_ignored()"""
    return {}


def save_ignored(ignored):
    """DEPRECATED: Больше не используется"""
    pass


def clean_expired(ignored):
    """DEPRECATED: Используется database.clean_expired_requisites()"""
    return ignored
