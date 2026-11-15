"""
Простая система доступа по мастер-ключу
"""
import logging
import random
import string
from config import MASTER_KEY, ADMIN_IDS

logger = logging.getLogger(__name__)

# Хранилище авторизованных пользователей (в памяти)
authorized_users = set()

# Хранилище ключей доступа (в памяти)
access_keys = {MASTER_KEY: "Master"} if MASTER_KEY else {}


def validate_key(key: str, user_id: int) -> bool:
    """
    Проверяет мастер-ключ и авторизует пользователя

    Args:
        key: Введенный ключ
        user_id: Telegram ID пользователя

    Returns:
        True если ключ верный
    """
    logger.info(f"Попытка валидации ключа от пользователя {user_id}")
    logger.info(f"Введенный ключ: '{key}' (длина: {len(key)})")

    if key in access_keys:
        authorized_users.add(user_id)
        logger.info(f"✅ Пользователь {user_id} успешно авторизован ключом '{access_keys[key]}'")
        return True

    logger.warning(f"❌ Неверный ключ от пользователя {user_id}")
    return False


def is_user_authorized(user_id: int) -> bool:
    """
    Проверяет авторизован ли пользователь

    Args:
        user_id: Telegram ID пользователя

    Returns:
        True если пользователь авторизован или является админом
    """
    return user_id in ADMIN_IDS or user_id in authorized_users


def revoke_user(user_id: int) -> bool:
    """
    Отзывает доступ пользователя

    Args:
        user_id: Telegram ID пользователя

    Returns:
        True если пользователь был удален
    """
    if user_id in authorized_users:
        authorized_users.remove(user_id)
        return True
    return False


def get_authorized_users() -> list:
    """
    Возвращает список авторизованных пользователей

    Returns:
        Список user_id
    """
    return list(authorized_users)


def is_admin(user_id: int) -> bool:
    """
    Проверяет является ли пользователь админом

    Args:
        user_id: Telegram ID пользователя

    Returns:
        True если пользователь админ
    """
    return user_id in ADMIN_IDS


def generate_key(name: str = "User") -> str:
    """
    Генерирует новый ключ доступа

    Args:
        name: Название ключа

    Returns:
        Сгенерированный ключ
    """
    key = 'KEY-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    access_keys[key] = name
    logger.info(f"✅ Создан новый ключ: {key} ({name})")
    return key


def get_all_keys() -> dict:
    """
    Возвращает все ключи доступа

    Returns:
        Словарь {ключ: название}
    """
    return access_keys.copy()


def delete_key(key: str) -> bool:
    """
    Удаляет ключ доступа

    Args:
        key: Ключ для удаления

    Returns:
        True если ключ был удален
    """
    if key in access_keys and key != MASTER_KEY:
        del access_keys[key]
        logger.info(f"🗑️ Удален ключ: {key}")
        return True
    return False
