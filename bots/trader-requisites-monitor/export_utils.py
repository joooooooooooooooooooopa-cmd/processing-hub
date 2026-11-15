"""
Утилиты для экспорта отчётов в CSV
"""
import csv
import io
from datetime import datetime, timedelta
from typing import Dict, List
import database
from metabase import MSK


def get_export_stats(hours: int = 24) -> Dict:
    """
    Получает статистику для экспорта

    Args:
        hours: Количество часов для выборки

    Returns:
        Словарь со статистикой
    """
    alerts = database.get_alerts_for_export(hours)

    if not alerts:
        return {
            'total_alerts': 0,
            'unique_requisites': 0,
            'critical_count': 0,
            'urgent_count': 0,
            'warning_count': 0
        }

    unique_requisites = set(alert['gate_name'] for alert in alerts)

    critical_count = sum(1 for alert in alerts if alert['conversion_pct'] == 0)
    urgent_count = sum(1 for alert in alerts if 0 < alert['conversion_pct'] < 10)
    warning_count = sum(1 for alert in alerts if 10 <= alert['conversion_pct'] < 20)

    return {
        'total_alerts': len(alerts),
        'unique_requisites': len(unique_requisites),
        'critical_count': critical_count,
        'urgent_count': urgent_count,
        'warning_count': warning_count,
        'period_hours': hours
    }


def generate_csv_report(hours: int = 24) -> io.BytesIO:
    """
    Генерирует CSV отчёт по алертам за последние N часов

    Args:
        hours: Количество часов для выборки (24 = сутки, 168 = неделя)

    Returns:
        BytesIO объект с CSV данными
    """
    # Получаем данные из БД
    alerts = database.get_alerts_for_export(hours)

    # Получаем игнорируемые реквизиты с комментариями
    ignored_with_comments = database.get_all_ignored_with_comments()
    ignored_map = {item['gate_name']: item for item in ignored_with_comments}

    # Создаём CSV в памяти через StringIO, потом конвертируем
    import io as io_module
    string_output = io_module.StringIO()

    writer = csv.writer(string_output, delimiter=';')

    # Заголовок
    writer.writerow([
        'Время алерта',
        'Реквизит',
        'Конверсия (%)',
        'Всего заказов',
        'Успешных заказов',
        'Тип алерта',
        'Статус',
        'Комментарии'
    ])

    # Данные
    for alert in alerts:
        gate_name = alert['gate_name']
        alerted_at = alert['alerted_at']
        conversion_pct = alert['conversion_pct']
        total_orders = alert['total_orders']
        success_orders = alert['success_orders']
        alert_type = alert['alert_type']

        # Форматируем время
        time_str = alerted_at.strftime('%d.%m.%Y %H:%M')

        # Определяем статус
        if gate_name in ignored_map:
            status = 'Игнорируется'
            ignored_item = ignored_map[gate_name]
            comments_list = ignored_item.get('comments', [])
            if comments_list:
                # Берём последний комментарий
                last_comment = comments_list[-1]['comment']
                comments = last_comment[:100]  # Ограничиваем длину
            else:
                comments = ''
        else:
            status = 'Активен'
            comments = ''

        # Переводим тип алерта на русский
        alert_type_map = {
            'recurring': 'Постоянная проблема',
            'critical_drop': 'Резкое падение',
            'new': 'Новая проблема',
            'normal': 'Обычный'
        }
        alert_type_ru = alert_type_map.get(alert_type, alert_type)

        writer.writerow([
            time_str,
            gate_name,
            f"{conversion_pct:.1f}",
            total_orders,
            success_orders,
            alert_type_ru,
            status,
            comments
        ])

    # Получаем строку и конвертируем в байты с BOM для Excel
    csv_string = string_output.getvalue()

    # Создаём BytesIO с правильной кодировкой (utf-8-sig добавляет BOM)
    output = io.BytesIO()
    output.write('\ufeff'.encode('utf-8'))  # BOM для UTF-8
    output.write(csv_string.encode('utf-8'))
    output.seek(0)

    return output


def format_export_summary(stats: Dict) -> str:
    """
    Форматирует сводку по экспорту

    Args:
        stats: Статистика из get_export_stats()

    Returns:
        Отформатированное сообщение
    """
    period = stats['period_hours']
    if period == 24:
        period_text = "за последние сутки"
    elif period == 168:
        period_text = "за последнюю неделю"
    else:
        period_text = f"за последние {period} часов"

    message = f"""
📊 <b>Статистика {period_text}:</b>

• Всего алертов: {stats['total_alerts']}
• Уникальных реквизитов: {stats['unique_requisites']}

<b>По критичности:</b>
🔴 Критичные (0%): {stats['critical_count']}
🟠 Срочные (&lt;10%): {stats['urgent_count']}
🟡 Внимание (10-20%): {stats['warning_count']}
"""

    return message.strip()
