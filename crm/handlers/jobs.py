"""
Scheduled jobs & low-conversion alerts.

Extracted from bot.py — constants, helpers and async job functions.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from telegram.ext import ContextTypes

import metabase as mb
import database
import storage
import keys
import visualization
from config import ADMIN_IDS, BOT_TOKEN

from handlers.utils import escape, format_money, format_number, MSK, is_admin, progress_bar
from handlers.formatters import format_today, format_conversion_detailed
from handlers.keyboards import kb_main, kb_alert

logger = logging.getLogger(__name__)

# ============ CONSTANTS ============

CONVERSION_THRESHOLD = 25
# Минимум заявок С РЕКВИЗИТАМИ для алерта (чтобы не спамить по мелким мерчам)
MIN_ORDERS_WITH_REQ_FOR_ALERT = 10
# Минимум реквизитов ПО МЕТОДУ для алерта по методу
MIN_METHOD_REQ_FOR_ALERT = 15
# Мерчанты, исключённые из алертов о низкой конверсии
# (список задаётся окружением, чтобы не хранить имена мерчантов в коде)
EXCLUDED_MERCHANTS = {x.strip() for x in os.getenv("EXCLUDED_MERCHANTS", "").split(",") if x.strip()}
# Интервал проверки (секунды) — 1 час
CHECK_INTERVAL = 3600

TREND_ICON = {'declining': '📉', 'improving': '📈', 'stable': ''}

# ============ HELPERS ============


def get_greeting_by_time():
    """Возвращает приветствие в зависимости от времени суток"""
    hour = datetime.now(MSK).hour

    if 6 <= hour < 12:
        return "Доброе утро"
    elif 12 <= hour < 18:
        return "Добрый день"
    elif 18 <= hour < 23:
        return "Добрый вечер"
    else:
        return "Доброго времени суток"


def get_merchants_status_map():
    """Возвращает словарь {имя_мерчанта: статус} из локальной БД"""
    try:
        merchants = database.get_all_merchants()
        return {m['name']: m.get('status', 'unknown') for m in merchants if m.get('name')}
    except Exception as e:
        logger.warning(f"Не удалось загрузить статусы мерчантов из БД: {e}")
        return {}


def get_template_variant(conv_level):
    """
    Возвращает вариант шаблона в зависимости от дня месяца
    conv_level: 'critical' (<10%), 'low' (10-20%), или 'warning' (20-25%)
    """
    day = datetime.now(MSK).day

    critical_templates = [
        (
            "🔴 <b>КРИТИЧЕСКИЙ УРОВЕНЬ КОНВЕРСИИ</b>\n"
            "При текущих показателях конверсии продолжение сотрудничества невозможно.\n"
            "Просим в срочном порядке проанализировать клиентов на предмет спама, мошенничества и иных факторов по неоплаченным заявкам ниже."
        ),
        (
            "🔴 <b>КРИТИЧЕСКАЯ СИТУАЦИЯ</b>\n"
            "Конверсия находится на критически низком уровне. Работа на таких условиях невозможна.\n"
            "Необходимо срочно выявить причины: проверьте клиентов на мошенничество, спам и другие факторы по примерам ниже."
        ),
        (
            "🔴 <b>КРИТИЧЕСКИЙ УРОВЕНЬ</b>\n"
            "Конверсия ниже минимально допустимого порога для продолжения сотрудничества.\n"
            "Просим немедленно провести анализ неоплаченных заявок ниже на предмет недобросовестных клиентов и технических проблем."
        ),
        (
            "🔴 <b>КРИТИЧЕСКАЯ КОНВЕРСИЯ</b>\n"
            "Текущий уровень конверсии делает невозможным дальнейшее сотрудничество.\n"
            "Требуется экстренная проверка качества трафика и клиентов по неоплаченным заявкам ниже."
        ),
    ]

    low_templates = [
        (
            "⚠️ <b>НИЗКАЯ КОНВЕРСИЯ</b>\n"
            "Предоставленные нами реквизиты не конвертируются в оплату. Ниже примеры таких заявок.\n"
            "Просим проанализировать клиентов на предмет спама, мошенничества и иных факторов, снижающих конверсию."
        ),
        (
            "⚠️ <b>НИЗКИЙ УРОВЕНЬ ОПЛАТ</b>\n"
            "Выданные реквизиты не приводят к оплатам. Примеры проблемных заявок ниже.\n"
            "Рекомендуем проверить качество трафика, исключить спам-заявки и мошеннические попытки."
        ),
        (
            "⚠️ <b>КОНВЕРСИЯ НИЖЕ НОРМЫ</b>\n"
            "Большинство клиентов получают реквизиты, но не совершают оплату. Ниже примеры.\n"
            "Просим оценить качество клиентской базы, выявить спам и проблемы на стороне приема платежей."
        ),
        (
            "⚠️ <b>НИЗКАЯ ОПЛАЧИВАЕМОСТЬ</b>\n"
            "Реквизиты выдаются, но конверсия в оплату значительно ниже нормы. Примеры ниже.\n"
            "Необходимо проверить клиентов на добросовестность и исключить технические проблемы с оплатой."
        ),
    ]

    warning_templates = [
        (
            "💛 <b>ЗОНА ВНИМАНИЯ</b>\n"
            "Конверсия немного ниже целевого уровня. Уверены, что сможете улучшить показатели!\n"
            "Проверьте примеры ниже — возможно, есть точки роста в обработке клиентов. Сможем показать лучшие результаты вместе."
        ),
        (
            "💛 <b>НЕБОЛЬШОЕ СНИЖЕНИЕ</b>\n"
            "Показатели чуть ниже обычного, но это поправимо. Вместе сможем улучшить результаты!\n"
            "Посмотрите примеры неоплат ниже — возможно, найдёте способы повысить качество обработки заявок."
        ),
        (
            "💛 <b>ЕСТЬ ПОТЕНЦИАЛ</b>\n"
            "Конверсия близка к норме, но можно лучше! Уверены в ваших возможностях.\n"
            "Ниже примеры заявок — проанализируйте их, и сможем вместе показать отличные результаты."
        ),
        (
            "💛 <b>МОЖНО УЛУЧШИТЬ</b>\n"
            "Показатели немного просели, но вы точно справитесь! Есть все возможности для роста.\n"
            "Изучите примеры ниже — оптимизация обработки поможет показать лучшую конверсию."
        ),
    ]

    if conv_level == 'critical':
        variant_index = day % len(critical_templates)
        return critical_templates[variant_index]
    elif conv_level == 'low':
        variant_index = day % len(low_templates)
        return low_templates[variant_index]
    else:  # warning
        variant_index = day % len(warning_templates)
        return warning_templates[variant_index]


def format_low_conversion_alert(merchants, unpaid_orders):
    """Форматирует алерт о мерчантах с низкой конверсией"""
    low_conv_merchants = []

    # Получаем статусы мерчантов из локальной БД
    merchant_statuses = get_merchants_status_map()

    for m in merchants:
        name = m.get("Мерчант") or ""
        if "ИТОГО" in name:
            continue

        # Пропускаем отключенных мерчантов
        if merchant_statuses.get(name) == 'disconnected':
            continue

        total = m.get("Всего") or 0
        with_req = m.get("С реквизитами") or 0
        conv = m.get("Конверсия в оплату %") or 0

        # Проверяем порог (минимум заявок с реквизитами)
        if with_req >= MIN_ORDERS_WITH_REQ_FOR_ALERT and conv < CONVERSION_THRESHOLD:
            low_conv_merchants.append({
                "name": name,
                "total": total,
                "with_req": with_req,
                "conv": conv,
                "successful": m.get("Успешных") or 0,
            })

    if not low_conv_merchants:
        return "✅ Все мерчанты имеют нормальную конверсию (≥25%)"

    # Получаем приветствие по времени суток
    greeting = get_greeting_by_time()

    lines = [
        "🚨 <b>АЛЕРТ: НИЗКАЯ КОНВЕРСИЯ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for m in low_conv_merchants[:10]:
        conv = m['conv']

        # Выбираем emoji и шаблон в зависимости от конверсии
        if conv < 10:
            emoji = "🔴"
            template_text = get_template_variant('critical')
            template = f"Коллеги, {greeting}!\n\n{template_text}"
        elif conv < 20:  # 10-20%
            emoji = "⚠️"
            template_text = get_template_variant('low')
            template = f"Коллеги, {greeting}!\n\n{template_text}"
        else:  # 20-25%
            emoji = "💛"
            template_text = get_template_variant('warning')
            template = f"Коллеги, {greeting}!\n\n{template_text}"

        lines.append(f"{emoji} <b>{escape(m['name'])}</b>")
        lines.append(f"   Конверсия в оплату: <code>{conv:.1f}%</code> (порог {CONVERSION_THRESHOLD}%)")
        lines.append(f"   С реквизитами: {m['with_req']} → Оплатили: {m['successful']}")
        lines.append("")
        lines.append(f"   {template}")
        lines.append("")

        # Добавляем примеры неоплаченных заявок
        merchant_unpaid = unpaid_orders.get(m['name'], [])
        if merchant_unpaid and isinstance(merchant_unpaid, list):
            lines.append("   📋 <b>Примеры неоплаченных заявок:</b>")
            for item in merchant_unpaid[:5]:  # Максимум 5 примеров
                if isinstance(item, dict):
                    ext = item.get('external_id', '?')
                    method = item.get('method', '')
                    method_str = f" · {method}" if method else ""
                    lines.append(f"   • <code>{ext}</code>{method_str}")
                else:
                    lines.append(f"   • <code>{item}</code>")
            lines.append("")

    lines.append(f"⏰ {datetime.now(MSK).strftime('%H:%M:%S')}")

    return "\n".join(lines)


def analyze_alert_patterns(merchant_name: str, current_conv: float) -> list:
    """Анализирует паттерны алертов и возвращает список бейджей"""
    badges = []
    try:
        if database.get_alert_count_today(merchant_name) >= 3:
            badges.append("🔥 Постоянная проблема")
        avg = database.get_avg_conversion_last_week(merchant_name)
        if avg and avg > 0 and current_conv < avg * 0.7:
            badges.append("⚠️ Резкое падение")
        if database.is_new_problem(merchant_name):
            badges.append("🆕 Новая проблема")
    except Exception:
        pass
    return badges


# ============ ASYNC JOBS ============


async def send_daily_digest(context):
    """Ежедневный дайджест в 09:00 МСК"""
    try:
        merchants_all = database.get_all_merchants()
        total_m = len(merchants_all)
        active_m = sum(1 for m in merchants_all if m.get('status') == 'active')
        problem_m = sum(1 for m in merchants_all if m.get('status') in ('problem', 'disconnected'))

        incidents_open = database.get_open_incidents()
        p0_open = sum(1 for i in incidents_open if i.get('priority') == 'P0')

        # Конверсия из Metabase
        try:
            conv_data = mb.get_conversion_today()
            convs = [m.get("Конверсия в оплату %") or 0 for m in conv_data if "ИТОГО" not in (m.get("Мерчант") or "")]
            avg_conv = sum(convs) / len(convs) if convs else 0
            low_conv = [m for m in conv_data if (m.get("Конверсия в оплату %") or 0) < CONVERSION_THRESHOLD and "ИТОГО" not in (m.get("Мерчант") or "")]
            top_conv = sorted([m for m in conv_data if "ИТОГО" not in (m.get("Мерчант") or "")], key=lambda x: x.get("Конверсия в оплату %") or 0, reverse=True)[:3]
        except Exception:
            avg_conv = 0
            low_conv = []
            top_conv = []

        now_str = datetime.now(MSK).strftime('%d.%m.%Y')
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊  <b>ДАЙДЖЕСТ {now_str}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🏪 Мерчантов: <b>{total_m}</b> (активных: {active_m}, проблемных: {problem_m})",
            f"📋 Открытых инцидентов: <b>{len(incidents_open)}</b>, P0: {p0_open}",
            f"📈 Средняя конверсия: <b>{avg_conv:.1f}%</b>",
        ]
        if low_conv:
            lines.append("")
            lines.append("🔴 <b>Проблемные мерчанты:</b>")
            for m in low_conv[:5]:
                name = escape(m.get("Мерчант") or "?")
                conv = m.get("Конверсия в оплату %") or 0
                lines.append(f"  • {name}: {conv:.1f}%")
        if top_conv:
            lines.append("")
            lines.append("🏆 <b>Лучшие:</b>")
            for m in top_conv[:3]:
                name = escape(m.get("Мерчант") or "?")
                conv = m.get("Конверсия в оплату %") or 0
                lines.append(f"  • {name}: {conv:.1f}%")

        # AI-сводка
        try:
            from analyzer import client as ai_client, AI_MODEL
            if ai_client and total_m > 0:
                summary_data = (
                    f"Мерчантов: {total_m}, активных: {active_m}, проблемных: {problem_m}. "
                    f"Открытых инцидентов: {len(incidents_open)}, P0: {p0_open}. "
                    f"Средняя конверсия: {avg_conv:.1f}%."
                )
                resp = ai_client.chat.completions.create(
                    model=AI_MODEL,
                    messages=[
                        {"role": "system", "content": "Ты аналитик платёжного агрегатора ProcessingHub. Пиши кратко и по делу, без воды."},
                        {"role": "user", "content": f"Дай 2-3 предложения аналитической сводки по состоянию на сегодня: {summary_data}"}
                    ],
                    max_tokens=180,
                )
                ai_text = resp.choices[0].message.content.strip()
                lines.append(f"\n🤖 <b>AI-анализ:</b>\n{escape(ai_text)}")
        except Exception:
            pass

        text = "\n".join(lines)
        recipients = set(ADMIN_IDS)
        authorized = keys.get_authorized_users()
        for u in authorized:
            recipients.add(u['user_id'])
        for uid in recipients:
            try:
                await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            except Exception:
                pass
        logger.info("Дайджест отправлен")
    except Exception as e:
        logger.error(f"Ошибка дайджеста: {e}")


async def save_daily_conversion_job(context):
    """Сохраняем конверсию за день в 23:50 МСК"""
    try:
        conv_data = mb.get_conversion_today()
        today = datetime.now(MSK).strftime('%Y-%m-%d')
        for m in conv_data:
            name = m.get("Мерчант") or ""
            if "ИТОГО" in name or not name:
                continue
            conv = m.get("Конверсия в оплату %") or 0
            total = m.get("Всего") or 0
            success = m.get("Успешных") or 0
            database.save_daily_conversion(name, today, conv, total, success)
        logger.info(f"Конверсия за {today} сохранена для {len(conv_data)} мерчантов")
    except Exception as e:
        logger.error(f"Ошибка сохранения конверсии: {e}")


async def check_overdue_incidents_job(context):
    """Проверка просроченных инцидентов каждые 30 минут"""
    try:
        overdue = database.get_overdue_incidents()
        if not overdue:
            return
        lines = ["⏰ <b>Просроченные инциденты!</b>", ""]
        for inc in overdue[:5]:
            pe = {'P0': '🔴', 'P1': '🟠', 'P2': '🟡', 'P3': '⚪'}.get(inc.get('priority', 'P2'), '⚪')
            lines.append(f"{pe} #{inc['id']} {escape(inc.get('merchant_name', ''))} — {inc.get('incident_type', '')}")
            assigned = inc.get('assigned_user_name') or 'Не назначен'
            lines.append(f"   Назначен: {escape(assigned)}")
        text = "\n".join(lines)
        for uid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Ошибка проверки дедлайнов: {e}")


async def cleanup_old_data_job(context):
    """Очистка старых данных в 03:00 МСК"""
    try:
        database.cleanup_old_data()
        storage.get_storage().cleanup_old_alerts(days=7)
        logger.info("Очистка старых данных выполнена")
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")


async def check_low_conversion(context):
    """Проверка мерчантов с низкой конверсией в оплату - отправляет отдельное сообщение на каждого мерчанта"""
    try:
        merchants = mb.get_conversion_today()

        if not merchants:
            logger.warning("Нет данных от Metabase, пропускаем проверку конверсии")
            return

        # Загружаем неоплаченные заявки по мерчантам
        unpaid_orders = mb.get_unpaid_orders()

        # Загружаем почасовую конверсию для графиков
        try:
            hourly_by_merchant = mb.get_hourly_by_merchant()
        except Exception as e:
            logger.warning(f"Не удалось загрузить почасовые данные: {e}")
            hourly_by_merchant = {}

        # Загружаем конверсию по мерчант+метод (PG, консистентно)
        try:
            conv_by_method = mb.get_conv_by_merchant_method()
        except Exception as e:
            logger.warning(f"Не удалось загрузить данные по методам: {e}")
            conv_by_method = {}

        # Загружаем отправленные алерты из хранилища (PostgreSQL или JSON)
        sent_alerts = storage.load_sent_alerts()

        # Получаем статусы мерчантов из локальной БД
        merchant_statuses = get_merchants_status_map()

        low_conv_merchants = []
        for m in merchants:
            name = m.get("Мерчант") or ""
            if "ИТОГО" in name:
                continue
            if merchant_statuses.get(name) == 'disconnected':
                continue
            if name in EXCLUDED_MERCHANTS:
                continue

            total = m.get("Всего") or 0
            with_req = m.get("С реквизитами") or 0
            conv = m.get("Конверсия в оплату %") or 0

            if with_req >= MIN_ORDERS_WITH_REQ_FOR_ALERT and conv < CONVERSION_THRESHOLD:
                alert_key = f"{name}_{datetime.now(MSK).strftime('%Y-%m-%d')}"
                if alert_key not in sent_alerts:
                    low_conv_merchants.append({
                        "name": name,
                        "total": total,
                        "with_req": with_req,
                        "conv": conv,
                        "successful": m.get("Успешных") or 0,
                    })
                    sent_alerts.add(alert_key)

        # Если есть мерчанты с низкой конверсией — отправляем алерты
        if low_conv_merchants:
            # Получаем приветствие по времени суток
            greeting = get_greeting_by_time()

            # Собираем всех получателей: админы + авторизованные пользователи
            recipients = set(ADMIN_IDS)
            authorized = keys.get_authorized_users()
            for u in authorized:
                recipients.add(u['user_id'])

            # При 3+ проблемных мерчантах — сначала сводное сообщение
            if len(low_conv_merchants) >= 3:
                p0_count = sum(1 for m in low_conv_merchants if m['conv'] < 10)
                p1_count = sum(1 for m in low_conv_merchants if 10 <= m['conv'] < 20)
                p2_count = len(low_conv_merchants) - p0_count - p1_count
                summary_lines = [
                    f"🚨 <b>Сводка алертов: {len(low_conv_merchants)} мерчантов с низкой конверсией</b>",
                    f"P0: {p0_count}  P1: {p1_count}  P2+: {p2_count}",
                    "",
                ]
                for m in low_conv_merchants[:8]:
                    badges = analyze_alert_patterns(m['name'], m['conv'])
                    badge_str = " ".join(badges[:1]) if badges else ""
                    e = "🔴" if m['conv'] < 10 else ("🟠" if m['conv'] < 20 else "🟡")
                    summary_lines.append(f"{e} {escape(m['name'])} — {m['conv']:.1f}% {badge_str}")
                summary_text = "\n".join(summary_lines)
                for uid in recipients:
                    try:
                        await context.bot.send_message(chat_id=uid, text=summary_text, parse_mode="HTML")
                    except Exception:
                        pass

            # Для КАЖДОГО мерчанта отправляем отдельное сообщение с картинкой
            for m in low_conv_merchants:
                conv = m['conv']
                name = m['name']
                total = m['total']
                with_req = m['with_req']
                successful = m['successful']

                # Выбираем шаблон в зависимости от конверсии
                if conv < 10:
                    emoji = "🔴"
                    template_text = get_template_variant('critical')
                elif conv < 20:
                    emoji = "⚠️"
                    template_text = get_template_variant('low')
                else:
                    emoji = "💛"
                    template_text = get_template_variant('warning')

                template = f"Коллеги, {greeting}!\n\n{template_text}"

                # Паттерн-анализ
                badges = analyze_alert_patterns(name, conv)
                try:
                    trend = database.get_conversion_trend(name, days=3)
                    if trend == 'declining':
                        badges.append("📉 3 дня падения")
                    elif trend == 'improving':
                        badges.append("📈 Восстанавливается")
                except Exception:
                    pass
                try:
                    database.save_alert_history(name, conv, 'low_conversion')
                except Exception:
                    pass

                # Формируем текст сообщения
                badge_str = "  ".join(badges) if badges else ""
                lines = [
                    f"{emoji} <b>{escape(name)}</b>{(' · ' + badge_str) if badge_str else ''}",
                    "",
                    f"📊 Конверсия в оплату: <b>{conv:.1f}%</b> (порог {CONVERSION_THRESHOLD}%)",
                    f"📋 С реквизитами: {with_req} → Оплатили: {successful}",
                ]

                # Разбивка по методам со статусом
                merchant_methods = conv_by_method.get(name, [])
                methods_with_req = [ms for ms in merchant_methods if (ms.get('with_req', 0) or 0) > 0]
                if methods_with_req:
                    lines.append("")
                    lines.append("💳 <b>По методам:</b>")
                    for ms in sorted(methods_with_req, key=lambda x: x.get('with_req', 0), reverse=True):
                        m_name = ms.get('method', '?')
                        m_conv = ms.get('conv_pct', 0) or 0
                        m_req = ms.get('with_req', 0)
                        m_succ = ms.get('successful', 0)
                        # Статус-иконка по методу
                        if m_conv >= 40:
                            m_icon = "🟢"
                        elif m_conv >= CONVERSION_THRESHOLD:
                            m_icon = "🟡"
                        elif m_conv >= 10:
                            m_icon = "🟠"
                        else:
                            m_icon = "🔴"
                        lines.append(f"   {m_icon} {m_name}: <b>{m_conv:.1f}%</b> ({m_succ}/{m_req})")

                lines.extend([
                    "",
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    "",
                    template,
                ])

                # Добавляем примеры неоплаченных заявок
                merchant_unpaid = unpaid_orders.get(name, [])
                if merchant_unpaid and isinstance(merchant_unpaid, list):
                    lines.append("")
                    lines.append("📋 <b>Примеры неоплаченных заявок:</b>")
                    for item in merchant_unpaid[:10]:  # Максимум 10 примеров
                        if isinstance(item, dict):
                            ext = item.get('external_id', '?')
                            method = item.get('method', '')
                            method_str = f" · {method}" if method else ""
                            lines.append(f"• <code>{ext}</code>{method_str}")
                        else:
                            lines.append(f"• <code>{item}</code>")

                lines.append("")
                lines.append(f"⏰ {datetime.now(MSK).strftime('%d.%m.%Y %H:%M:%S')}")

                text = "\n".join(lines)

                # Генерируем картинку с метриками
                try:
                    chart_image = visualization.generate_conversion_chart(
                        merchant_name=name,
                        total=total,
                        with_req=with_req,
                        successful=successful,
                        conv=conv,
                        hourly_data=hourly_by_merchant.get(name),
                        method_stats_pg=conv_by_method.get(name),
                    )
                except Exception as e:
                    logger.error(f"Ошибка генерации визуализации для {name}: {e}")
                    chart_image = None

                # Клавиатура с кнопками действий
                alert_kb = kb_alert(name)

                # Отправляем КАЖДОМУ получателю
                for user_id in recipients:
                    try:
                        if chart_image:
                            chart_image.seek(0)  # Сброс позиции в начало
                            await context.bot.send_photo(
                                chat_id=user_id,
                                photo=chart_image,
                                caption=text,
                                parse_mode="HTML",
                                reply_markup=alert_kb,
                            )
                        else:
                            # Если картинка не создалась - отправляем просто текст
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=text,
                                parse_mode="HTML",
                                reply_markup=alert_kb,
                            )
                    except Exception as e:
                        logger.error(f"Ошибка отправки алерта {name} пользователю {user_id}: {e}")

                logger.info(f"Отправлен алерт по мерчанту {name} ({conv:.1f}%) для {len(recipients)} пользователей")

            # Сохраняем отправленные алерты в хранилище
            storage.save_sent_alerts(sent_alerts)
            logger.info(f"Всего отправлено {len(low_conv_merchants)} алертов")

    except Exception as e:
        logger.error(f"Ошибка проверки конверсии: {e}")
