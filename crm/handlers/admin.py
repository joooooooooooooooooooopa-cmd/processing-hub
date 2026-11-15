import logging
from telegram import Update
from telegram.ext import ContextTypes

import keys
import storage
from handlers.utils import is_admin
from handlers.keyboards import kb_main

logger = logging.getLogger(__name__)


async def cmd_newkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать новый ключ: /newkey [описание]"""
    if not is_admin(update):
        return

    name = " ".join(context.args) if context.args else ""
    uid = update.effective_user.id

    key = keys.generate_key(name=name, created_by=uid)

    await update.message.reply_text(
        f"🔑 <b>Новый ключ доступа</b>\n\n"
        f"<code>{key}</code>\n\n"
        f"Для: {name or 'не указано'}\n\n"
        f"<i>Ключ одноразовый. Отправьте его пользователю.</i>",
        parse_mode="HTML"
    )


async def cmd_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список ключей: /keys"""
    if not is_admin(update):
        return

    stats = keys.get_stats()
    all_keys = keys.get_all_keys()

    lines = [
        "🔑 <b>Управление ключами</b>",
        "",
        f"Всего: {stats['total_keys']}",
        f"Активных: {stats['active_keys']}",
        f"Использовано: {stats['used_keys']}",
        "",
    ]

    for k in all_keys[-10:]:
        status = "✅" if k["active"] else "❌"
        used = f"👤" if k["used_by"] else "🆓"
        lines.append(f"{status}{used} <code>{k['key'][:12]}...</code>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Авторизованные: /users"""
    if not is_admin(update):
        return

    users = keys.get_authorized_users()
    if not users:
        await update.message.reply_text("Нет авторизованных")
        return

    lines = ["👥 <b>Авторизованные</b>", ""]
    for u in users:
        lines.append(f"• <code>{u['user_id']}</code> — {u.get('name', '?')}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отозвать ключ: /revoke [ключ]"""
    if not is_admin(update):
        return

    if not context.args:
        await update.message.reply_text("Использование: /revoke PC-XXXX-XXXX-XXXX")
        return

    if keys.revoke_key(context.args[0]):
        storage.log_audit(update.effective_user.id, "key_revoked", f"bot: revoked key {context.args[0][:8]}...")
        await update.message.reply_text("✅ Ключ отозван")
    else:
        await update.message.reply_text("❌ Ключ не найден")


async def cmd_kickuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кикнуть пользователя: /kickuser [id]"""
    if not is_admin(update):
        return

    if not context.args:
        await update.message.reply_text("Использование: /kickuser 123456789")
        return

    try:
        user_id = int(context.args[0])
        if keys.revoke_user(user_id):
            storage.log_audit(update.effective_user.id, "user_kicked", f"bot: kicked user {user_id}")
            await update.message.reply_text(f"✅ Доступ отозван у {user_id}")
        else:
            await update.message.reply_text("❌ Пользователь не найден")
    except:
        await update.message.reply_text("❌ Неверный ID")
