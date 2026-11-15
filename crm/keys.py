"""
Система управления ключами доступа

Обёртка над storage.py для обратной совместимости.
Поддерживает PostgreSQL (Railway) и JSON (локально).
"""
from storage import (
    generate_key,
    validate_key,
    is_user_authorized,
    get_all_keys,
    revoke_key,
    revoke_user,
    get_authorized_users,
    get_stats,
)

# Реэкспорт всех функций для совместимости
__all__ = [
    'generate_key',
    'validate_key',
    'is_user_authorized',
    'get_all_keys',
    'revoke_key',
    'revoke_user',
    'get_authorized_users',
    'get_stats',
]
