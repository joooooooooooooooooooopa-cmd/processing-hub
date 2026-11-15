"""
Форматирование экранов и экспорт CSV.
Extracted from bot.py — format_* and export_*_csv functions.
"""

import csv
import io
from datetime import datetime

import database
from handlers.utils import escape, format_money, format_number, progress_bar, trend_icon, conv_status, MSK


# ============ ФОРМАТИРОВАНИЕ ЭКРАНОВ ============

def format_today(data: dict) -> str:
    """Сводка за сегодня — главный экран"""
    total = data.get('Всего заявок', 0) or 0
    successful = data.get('Успешных заявок', 0) or 0
    no_req = data.get('Невыдано реквизитов', 0) or 0
    conv_req = data.get('Конверсия в реквизиты %', 0) or 0
    conv_pay = data.get('Конверсия в оплату %', 0) or 0
    amount = data.get('Сумма успешных', 0) or 0

    status = conv_status(conv_pay)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊  <b>СВОДКА ЗА СЕГОДНЯ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📋 <b>Заявки:</b>",
        f"   Всего получено:  <code>{total:,}</code>",
        f"   Успешно оплачено:  <code>{successful:,}</code>",
        f"   Без реквизитов:  <code>{no_req:,}</code>",
        "",
        "📈 <b>Конверсия:</b>",
        f"   В реквизиты:  <code>{conv_req:.2f}%</code>",
        f"   В оплату:  <code>{conv_pay:.2f}%</code>  {status}",
        "",
        "💰 <b>Финансы:</b>",
        f"   Успешный оборот:  <code>{format_money(amount)}</code>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 <i>Данные на {datetime.now(MSK).strftime('%H:%M')}</i>",
    ]
    return "\n".join(lines)


def format_canceled(canceled: list) -> str:
    """Анализ отменённых заявок"""
    total = sum(c.get("Количество", 0) or 0 for c in canceled)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "❌  <b>АНАЛИЗ ОТМЕНЁННЫХ ЗАЯВОК</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Всего отменено сегодня: <b>{total:,}</b>",
        "",
        "<b>Причины отмен:</b>",
        "",
    ]

    if not canceled:
        lines.append("Нет данных об отменах")
        return "\n".join(lines)

    for c in canceled[:10]:
        reason = escape((c.get("Причина") or "Не указана")[:30])
        count = c.get("Количество", 0) or 0
        amount = c.get("Сумма", 0) or 0
        pct = (count / total * 100) if total > 0 else 0

        bar = progress_bar(count, total, 8)

        lines.append(f"{bar} <b>{pct:.1f}%</b>")
        lines.append(f"   {reason}")
        lines.append(f"   {count:,} заявок на {format_money(amount)}")
        lines.append("")

    return "\n".join(lines)


def format_alerts(alerts: list) -> str:
    """Проверка проблем (алерты)"""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🚨  <b>ПРОВЕРКА ПРОБЛЕМ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if not alerts:
        lines.extend([
            "✅ <b>Всё в порядке!</b>",
            "",
            "Проблем не обнаружено:",
            "• Конверсия в норме",
            "• Количество отмен в пределах нормы",
            "• Все системы работают",
        ])
        return "\n".join(lines)

    lines.append(f"⚠️ Обнаружено проблем: <b>{len(alerts)}</b>")
    lines.append("")

    severity_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}

    for alert in alerts:
        icon = severity_icons.get(alert.get("severity", "low"), "⚪")
        lines.append(f"{icon} <b>{alert.get('title', 'Проблема')}</b>")
        lines.append(f"   {alert.get('message', '')}")
        lines.append("")

    return "\n".join(lines)


def format_bad_clients(bad_clients: list) -> str:
    """Форматирует список плохих пользователей по client_id"""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🚫  <b>ПЛОХИЕ ПОЛЬЗОВАТЕЛИ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Анализ за последние 30 дней",
        "",
    ]

    if not bad_clients:
        lines.extend([
            "✅ <b>Проблем не обнаружено!</b>",
            "",
            "Все пользователи имеют нормальную конверсию",
        ])
        return "\n".join(lines)

    # Группируем по типам проблем
    bad_users = [c for c in bad_clients if c.get("issue_type") == "bad_user"]
    stub_merchants = [c for c in bad_clients if c.get("issue_type") == "stub_client_id"]
    random_merchants = [c for c in bad_clients if c.get("issue_type") == "random_client_id"]

    lines.append(f"📊 Всего проблем: <b>{len(bad_clients)}</b>")
    lines.append("")

    # Плохие пользователи
    if bad_users:
        lines.append(f"🚨 <b>СПАМ-ЮЗЕРЫ (конверсия &lt;30%)</b>")
        lines.append(f"Найдено: {len(bad_users)}")
        lines.append("")

        for user in bad_users[:10]:  # Топ-10
            client_id = escape(str(user.get("client_id", ""))[:30])
            merchant = escape(str(user.get("merchant_name", ""))[:25])
            total = user.get("total_orders", 0)
            completed = user.get("completed_orders", 0)
            failed = user.get("failed_orders", 0)
            conv = user.get("conversion_pct", 0)

            # Примеры заказов для поиска в админке
            example_orders = user.get("example_order_ids", [])
            if isinstance(example_orders, str):
                example_orders = [example_orders]

            lines.append(f"👤 <code>{client_id}</code>")
            lines.append(f"   🏪 {merchant}")
            lines.append(f"   📊 {total} заказов | ✅ {completed} | ❌ {failed}")
            lines.append(f"   📉 Конверсия: <b>{conv:.1f}%</b>")

            # Показываем примеры заказов для поиска в админке
            if example_orders and len(example_orders) > 0:
                orders_str = ", ".join([str(o) for o in example_orders[:3] if o])
                if orders_str:
                    lines.append(f"   📝 Примеры заказов: <code>{escape(orders_str)}</code>")

            lines.append(f"   💡 <i>Найди заказ в админке чтобы увидеть client_id</i>")
            lines.append("")

    # Мерчанты с заглушками
    if stub_merchants:
        lines.append("⚠️ <b>МЕРЧАНТЫ С ЗАГЛУШКАМИ</b>")
        lines.append(f"Найдено: {len(stub_merchants)}")
        lines.append("Один client_id используется в &gt;90% заказов")
        lines.append("")

        for stub in stub_merchants[:5]:
            merchant = escape(str(stub.get("merchant_name", ""))[:30])
            total = stub.get("total_orders", 0)

            lines.append(f"🏪 <b>{merchant}</b>")
            lines.append(f"   📊 {total} заказов за 30 дней")
            lines.append(f"   💡 <i>Рекомендация: Попросить передавать настоящий client_id</i>")
            lines.append("")

    # Мерчанты с рандомом
    if random_merchants:
        lines.append("⚠️ <b>МЕРЧАНТЫ С РАНДОМНЫМИ ID</b>")
        lines.append(f"Найдено: {len(random_merchants)}")
        lines.append("Почти все client_id уникальные (&gt;95%)")
        lines.append("")

        for rand in random_merchants[:5]:
            merchant = escape(str(rand.get("merchant_name", ""))[:30])
            total = rand.get("total_orders", 0)

            lines.append(f"🏪 <b>{merchant}</b>")
            lines.append(f"   📊 {total} заказов за 30 дней")
            lines.append(f"   💡 <i>Рекомендация: Попросить передавать постоянный client_id</i>")
            lines.append("")

    return "\n".join(lines)


def format_conversion_detailed(merchants: list) -> str:
    """Детальная конверсия по мерчантам — ВСЕ активные мерчанты"""
    # Получаем итого
    itogo = None
    for m in merchants:
        if "ИТОГО" in (m.get("Мерчант") or ""):
            itogo = m
            break

    # Фильтруем только ИТОГО, показываем всех мерчантов
    filtered = [m for m in merchants if "ИТОГО" not in (m.get("Мерчант") or "")]

    # Сортируем по количеству заявок с реквизитами (от большего к меньшему)
    sorted_m = sorted(filtered, key=lambda x: x.get("С реквизитами") or 0, reverse=True)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📈  <b>КОНВЕРСИЯ ПО МЕРЧАНТАМ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Общая статистика
    if itogo:
        total = itogo.get("Всего") or 0
        with_req = itogo.get("С реквизитами") or 0
        success = itogo.get("Успешных") or 0
        conv_req = itogo.get("Конверсия в реквизиты %") or 0
        conv_pay = itogo.get("Конверсия в оплату %") or 0

        status = "🟢" if conv_pay >= 40 else "🟡" if conv_pay >= 25 else "🟠" if conv_pay >= 15 else "🔴"

        lines.extend([
            "📊 <b>ОБЩАЯ КОНВЕРСИЯ:</b>",
            "",
            f"   📥 Всего заявок: <code>{total:,}</code>",
            f"   📋 С реквизитами: <code>{with_req:,}</code> ({conv_req:.1f}%)",
            f"   ✅ Оплачено: <code>{success:,}</code>",
            "",
            f"   {status} <b>Конверсия в оплату: {conv_pay:.1f}%</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ])

    # Показываем ВСЕХ мерчантов с реквизитами, сгруппированных по конверсии
    merchants_with_req = [m for m in sorted_m if (m.get("С реквизитами") or 0) > 0]
    merchants_no_req = [m for m in sorted_m if (m.get("С реквизитами") or 0) == 0 and (m.get("Всего") or 0) > 0]

    # Проблемные мерчанты (конверсия < 20%)
    problem_merchants = [m for m in merchants_with_req if (m.get("Конверсия в оплату %") or 0) < 20]
    if problem_merchants:
        lines.append(f"🔴 <b>НИЗКАЯ КОНВЕРСИЯ (&lt; 20%) — {len(problem_merchants)} мерч.</b>")
        lines.append("")
        for m in problem_merchants:
            name = escape((m.get("Мерчант") or "?")[:20])
            with_req = m.get("С реквизитами") or 0
            success = m.get("Успешных") or 0
            conv = m.get("Конверсия в оплату %") or 0
            lines.append(f"   🔴 <b>{name}</b>: {conv:.1f}% ({success}/{with_req})")
        lines.append("")

    # Средние мерчанты (20-40%)
    medium_merchants = [m for m in merchants_with_req if 20 <= (m.get("Конверсия в оплату %") or 0) < 40]
    if medium_merchants:
        lines.append(f"🟡 <b>СРЕДНЯЯ (20-40%) — {len(medium_merchants)} мерч.</b>")
        lines.append("")
        for m in medium_merchants:
            name = escape((m.get("Мерчант") or "?")[:20])
            with_req = m.get("С реквизитами") or 0
            success = m.get("Успешных") or 0
            conv = m.get("Конверсия в оплату %") or 0
            lines.append(f"   🟡 <b>{name}</b>: {conv:.1f}% ({success}/{with_req})")
        lines.append("")

    # Хорошие мерчанты (>= 40%)
    good_merchants = [m for m in merchants_with_req if (m.get("Конверсия в оплату %") or 0) >= 40]
    if good_merchants:
        lines.append(f"🟢 <b>ХОРОШАЯ (≥ 40%) — {len(good_merchants)} мерч.</b>")
        lines.append("")
        for m in good_merchants:
            name = escape((m.get("Мерчант") or "?")[:20])
            with_req = m.get("С реквизитами") or 0
            success = m.get("Успешных") or 0
            conv = m.get("Конверсия в оплату %") or 0
            lines.append(f"   🟢 <b>{name}</b>: {conv:.1f}% ({success}/{with_req})")
        lines.append("")

    # Мерчанты без реквизитов (есть заявки, но нет выданных реквизитов)
    if merchants_no_req:
        lines.append(f"⚪ <b>БЕЗ РЕКВИЗИТОВ — {len(merchants_no_req)} мерч.</b>")
        lines.append("")
        for m in merchants_no_req[:10]:
            name = escape((m.get("Мерчант") or "?")[:20])
            total = m.get("Всего") or 0
            lines.append(f"   ⚪ {name}: {total} заявок")
        if len(merchants_no_req) > 10:
            lines.append(f"   <i>... и ещё {len(merchants_no_req) - 10}</i>")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Всего мерчантов: <b>{len(filtered)}</b>")
    lines.append(f"🕐 <i>Обновлено: {datetime.now(MSK).strftime('%H:%M:%S')}</i>")

    return "\n".join(lines)


def format_rates(rates: list) -> str:
    """Ставки и комиссии мерчантов"""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💰  <b>СТАВКИ И КОМИССИИ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if not rates:
        lines.append("Нет данных о ставках")
        return "\n".join(lines)

    merchants = {}
    for r in rates:
        name = r.get("name") or "Неизвестный"
        if name not in merchants:
            merchants[name] = []
        merchants[name].append(r)

    for name, items in list(merchants.items())[:10]:
        methods = [str(i.get("payment_type") or "?") for i in items]
        methods = list(set(methods))[:3]
        fees = [float(i.get("fee") or 0) for i in items]
        avg_fee = sum(fees) / len(fees) if fees else 0
        min_fee = min(fees) if fees else 0
        max_fee = max(fees) if fees else 0

        lines.append(f"🏪 <b>{escape(name)}</b>")
        lines.append(f"   Методы: {', '.join(methods)}")
        if min_fee == max_fee:
            lines.append(f"   Комиссия: {avg_fee:.2f}%")
        else:
            lines.append(f"   Комиссия: {min_fee:.2f}% — {max_fee:.2f}%")
        lines.append("")

    return "\n".join(lines)


# ============ ЭКСПОРТ ============

def export_merchants_csv(merchants: list) -> io.BytesIO:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Мерчант", "Всего заявок", "Успешных", "Сумма", "Сумма успешных", "Конверсия %"])
    for m in merchants:
        merchant_name = m.get("Мерчант") or ""
        if "ИТОГО" not in merchant_name:
            writer.writerow([
                merchant_name,
                m.get("Всего") or 0,
                m.get("Успешных") or 0,
                m.get("Сумма") or 0,
                m.get("Сумма успешных") or 0,
                m.get("Конверсия %") or 0,
            ])
    output.seek(0)
    return io.BytesIO(output.getvalue().encode('utf-8-sig'))


def export_methods_csv(methods: list) -> io.BytesIO:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Метод", "Всего", "Успешных", "Сумма", "Конверсия %"])
    for m in methods:
        writer.writerow([
            m.get("Метод") or "",
            m.get("Всего") or 0,
            m.get("Успешных") or 0,
            m.get("Сумма") or 0,
            m.get("Конверсия %") or 0,
        ])
    output.seek(0)
    return io.BytesIO(output.getvalue().encode('utf-8-sig'))


def export_hourly_csv(hours: list) -> io.BytesIO:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Час", "Заявок", "Успешных", "Сумма", "Конверсия %"])
    for h in hours:
        hour_val = h.get('Час') or 0
        writer.writerow([
            f"{hour_val:02d}:00",
            h.get("Ордеров") or 0,
            h.get("Успешных") or 0,
            h.get("Сумма") or 0,
            h.get("Конверсия %") or 0,
        ])
    output.seek(0)
    return io.BytesIO(output.getvalue().encode('utf-8-sig'))


def export_conv_history_csv(days: int = 7) -> io.BytesIO:
    """Экспорт истории конверсии за N дней"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Мерчант", "Дата", "Конверсия %", "Всего заявок", "Успешных"])
    # Get all merchants and their conversion history
    merchants = database.get_all_merchants()
    for m in merchants:
        history = database.get_conversion_history(m['name'], days=days)
        for h in history:
            writer.writerow([
                m['name'],
                h.get('date', ''),
                h.get('conversion_pct', 0),
                h.get('total_orders', 0),
                h.get('success_orders', 0),
            ])
    output.seek(0)
    return io.BytesIO(output.getvalue().encode('utf-8-sig'))


def export_incidents_csv(days: int = 30) -> io.BytesIO:
    """Экспорт инцидентов за N дней"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Мерчант", "Тип", "Приоритет", "Статус", "Назначен", "Дедлайн", "Создан", "Закрыт"])
    incidents = database.get_incidents_for_export(days=days)
    for inc in incidents:
        writer.writerow([
            inc.get('id', ''),
            inc.get('merchant_name', ''),
            inc.get('incident_type', ''),
            inc.get('priority', ''),
            inc.get('status', ''),
            inc.get('assigned_user_name', ''),
            str(inc.get('due_at', '') or ''),
            str(inc.get('created_at', ''))[:16],
            str(inc.get('resolved_at', '') or ''),
        ])
    output.seek(0)
    return io.BytesIO(output.getvalue().encode('utf-8-sig'))


# ============ PAYOUT (PaycrowOUT) ============

# Порядок отображения диапазонов чеков
_CHECK_RANGE_ORDER = ['1-5K', '5-10K', '10-20K', '20-40K', '40-100K', 'Other']


def format_payout(data: dict) -> str:
    """Форматирование статистики пейаута (PaycrowOUT)."""
    merchants = data.get("merchants") or []
    ranges = data.get("ranges") or []

    now = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📤  <b>PAYOUT — PaycrowOUT</b>",
        f"🕐 {now} МСК",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # --- Мерчанты ---
    if merchants:
        total_all = sum(int(m.get("total", 0) or 0) for m in merchants)
        closed_all = sum(int(m.get("closed", 0) or 0) for m in merchants)
        amount_all = sum(float(m.get("closed_amount", 0) or 0) for m in merchants)
        conv_all = round(closed_all * 100.0 / total_all, 2) if total_all else 0

        lines.append("")
        lines.append(f"📊 <b>Итого:</b> {total_all} заявок → {closed_all} закрыто ({conv_all}%)")
        lines.append(f"💰 <b>Сумма:</b> {format_money(amount_all)}")
        lines.append("")
        lines.append("<b>По мерчантам:</b>")

        for m in merchants:
            name = escape(str(m.get("merchant", ""))[:30])
            total = int(m.get("total", 0) or 0)
            closed = int(m.get("closed", 0) or 0)
            conv = float(m.get("conv_pct", 0) or 0)
            amount = float(m.get("closed_amount", 0) or 0)
            status = conv_status(conv)
            lines.append(f"  🏪 <b>{name}</b>")
            lines.append(f"     {total} → {closed} ({conv}%) {status}")
            if amount > 0:
                lines.append(f"     💰 {format_money(amount)}")
    else:
        lines.append("")
        lines.append("ℹ️ Сегодня пейаут-заявок пока нет")

    # --- Разбивка по чекам ---
    if ranges:
        lines.append("")
        lines.append("<b>Разбивка по чекам:</b>")

        range_map = {r.get("check_range"): r for r in ranges}

        for rng in _CHECK_RANGE_ORDER:
            r = range_map.get(rng)
            if not r:
                continue
            total = int(r.get("total", 0) or 0)
            closed = int(r.get("closed", 0) or 0)
            pct = float(r.get("pct_of_total", 0) or 0)
            conv = float(r.get("conv_pct", 0) or 0)
            lines.append(f"  {rng}: {total} заявок ({pct}%) → {closed} забрали ({conv}%)")

    return "\n".join(lines)
