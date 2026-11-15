"""
Alert Engine - проверка алертов и создание инцидентов
Phase 1: Incidents & Alerts MVP
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import ops_db
import metabase

logger = logging.getLogger(__name__)


# ============ METRIC FETCHERS ============

def fetch_metric_data(metric: str, scope: str, dimensions: Dict, window_minutes: int) -> Tuple[Optional[float], Optional[float]]:
    """
    Получить текущее и baseline значение метрики из Metabase.

    Args:
        metric: название метрики (conversion_success, profit_total, decline_rate)
        scope: область (global, merchant, method, bank, trader, etc.)
        dimensions: фильтры для запроса (merchant_name, method, bank, trader, etc.)
        window_minutes: окно сравнения в минутах

    Returns:
        (current_value, baseline_value) или (None, None) если данных нет
    """
    try:
        # Определяем период для текущего значения (последний час)
        now = datetime.utcnow()
        current_period_start = now - timedelta(minutes=60)

        # Baseline период (тот же час, но window_minutes назад)
        baseline_period_start = current_period_start - timedelta(minutes=window_minutes)
        baseline_period_end = baseline_period_start + timedelta(minutes=60)

        # Получаем данные из главного дашборда (cards 118-124, 128-130)
        # Для MVP используем агрегированные метрики

        if metric == "conversion_success":
            # Card 120: Конверсия в успех %
            # Получаем текущую конверсию
            current_data = metabase.get_client().execute_question(120, {})
            if current_data and len(current_data) > 0:
                current_value = float(current_data[0].get("Конверсия в успех", 0) or 0)
            else:
                current_value = None

            # Для baseline используем исторические данные (упрощённо - берём вчерашний период)
            # В реальности нужно запрашивать с параметром period
            # Пока используем текущее значение - 10% для демо
            baseline_value = current_value * 1.1 if current_value else None

            return current_value, baseline_value

        elif metric == "profit_total":
            # Card 122: Прибыль (сумма)
            current_data = metabase.get_client().execute_question(122, {})
            if current_data and len(current_data) > 0:
                current_value = float(current_data[0].get("Прибыль", 0) or 0)
            else:
                current_value = None

            baseline_value = current_value * 1.2 if current_value else None
            return current_value, baseline_value

        elif metric == "decline_rate":
            # Card 124: Declined %
            current_data = metabase.get_client().execute_question(124, {})
            if current_data and len(current_data) > 0:
                current_value = float(current_data[0].get("Declined %", 0) or 0)
            else:
                current_value = None

            baseline_value = current_value * 0.8 if current_value else None
            return current_value, baseline_value

        else:
            logger.warning(f"[Alert Engine] Unknown metric: {metric}")
            return None, None

    except Exception as e:
        logger.error(f"[Alert Engine] Error fetching metric {metric}: {e}")
        return None, None


# ============ CONDITION EVALUATORS ============

def evaluate_condition(condition: Dict, current_value: float, baseline_value: Optional[float]) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Проверить условие алерта.

    Args:
        condition: словарь с op и threshold
        current_value: текущее значение метрики
        baseline_value: baseline значение для сравнения

    Returns:
        (is_breached, delta_value, delta_pct)
    """
    op = condition.get("op")
    threshold = condition.get("threshold")

    if op == "delta_pct":
        # Процентное изменение относительно baseline
        if baseline_value is None or baseline_value == 0:
            return False, None, None

        delta_value = current_value - baseline_value
        delta_pct = (delta_value / baseline_value) * 100

        # threshold отрицательный для падения (например -20%)
        is_breached = delta_pct <= threshold

        return is_breached, delta_value, delta_pct

    elif op == "absolute":
        # Абсолютное значение превысило порог
        is_breached = current_value >= threshold
        return is_breached, None, None

    elif op == "below":
        # Значение упало ниже порога
        is_breached = current_value <= threshold
        return is_breached, None, None

    else:
        logger.warning(f"[Alert Engine] Unknown condition op: {op}")
        return False, None, None


# ============ ALERT PROCESSOR ============

def check_alert(alert: Dict) -> Optional[str]:
    """
    Проверить один алерт и создать инцидент если условие сработало.

    Args:
        alert: словарь с данными алерта из БД

    Returns:
        incident_id если инцидент создан, иначе None
    """
    alert_id = alert["id"]
    alert_name = alert["name"]
    metric = alert["metric"]
    severity = alert["severity"]
    scope = alert["scope"]
    condition = alert["condition"]
    time_window = alert["time_window"]
    filters = alert.get("filters", {})
    cooldown_minutes = alert.get("cooldown_minutes", 15)

    logger.info(f"[Alert Engine] Checking alert {alert_id}: {alert_name}")

    try:
        # 1. Проверить cooldown
        last_fire = ops_db.get_last_alert_fire(alert_id)
        if last_fire:
            last_fire_time = last_fire["fired_at"]
            cooldown_end = last_fire_time + timedelta(minutes=cooldown_minutes)
            if datetime.utcnow() < cooldown_end:
                logger.info(f"[Alert Engine] Alert {alert_id} in cooldown until {cooldown_end}")
                return None

        # 2. Получить данные метрики
        window_minutes = time_window.get("minutes", 60)
        dimensions = filters.get("dimensions", {})

        current_value, baseline_value = fetch_metric_data(metric, scope, dimensions, window_minutes)

        if current_value is None:
            logger.warning(f"[Alert Engine] No data for metric {metric}, skipping")
            return None

        # 3. Проверить условие
        is_breached, delta_value, delta_pct = evaluate_condition(condition, current_value, baseline_value)

        if not is_breached:
            logger.info(f"[Alert Engine] Alert {alert_id} condition not breached (current={current_value}, baseline={baseline_value})")
            return None

        logger.warning(f"[Alert Engine] ⚠️ Alert {alert_id} BREACHED! current={current_value}, baseline={baseline_value}, delta_pct={delta_pct}")

        # 4. Создать dedupe key
        # Формат: alert_id:metric:scope:dimensions_hash
        dimensions_str = ":".join(f"{k}={v}" for k, v in sorted(dimensions.items()))
        dedupe_key = f"alert:{alert_id}:{metric}:{scope}:{dimensions_str}"

        # 5. Проверить дубликат
        existing_incident = ops_db.find_incident_by_dedupe_key(dedupe_key)
        if existing_incident:
            logger.info(f"[Alert Engine] Incident already exists for dedupe_key={dedupe_key}, incident_id={existing_incident['id']}")
            # Записать alert fire
            ops_db.create_alert_fire(
                alert_id=alert_id,
                context={
                    "current_value": current_value,
                    "baseline_value": baseline_value,
                    "delta_pct": delta_pct,
                    "duplicate": True,
                },
                incident_id=existing_incident["id"],
            )
            return None

        # 6. Создать инцидент
        now = datetime.utcnow()
        period_from = now - timedelta(minutes=60)
        period_to = now

        # Определить тип инцидента по метрике
        incident_type_map = {
            "conversion_success": "conversion_drop",
            "profit_total": "profit_drop",
            "decline_rate": "decline_spike",
        }
        incident_type = incident_type_map.get(metric, "metric_breach")

        # Сформировать title
        if delta_pct is not None:
            title = f"{alert_name}: {metric} упала на {abs(delta_pct):.1f}%"
        else:
            title = f"{alert_name}: {metric} = {current_value}"

        incident_id = ops_db.create_incident(
            type=incident_type,
            severity=severity,
            scope=scope,
            metric=metric,
            current_value=current_value,
            baseline_value=baseline_value,
            delta_value=delta_value,
            delta_pct=delta_pct,
            period_from=period_from,
            period_to=period_to,
            dimensions=dimensions,
            title=title,
            description=f"Alert '{alert_name}' triggered. Condition: {condition}",
            dedupe_key=dedupe_key,
            rule_id=alert_id,
        )

        logger.info(f"[Alert Engine] ✅ Created incident {incident_id} for alert {alert_id}")

        # 7. Записать alert fire
        ops_db.create_alert_fire(
            alert_id=alert_id,
            context={
                "current_value": current_value,
                "baseline_value": baseline_value,
                "delta_value": delta_value,
                "delta_pct": delta_pct,
                "duplicate": False,
            },
            incident_id=incident_id,
        )

        return incident_id

    except Exception as e:
        logger.error(f"[Alert Engine] Error checking alert {alert_id}: {e}", exc_info=True)
        return None


def run_alert_check_cycle():
    """
    Запустить один цикл проверки всех активных алертов.
    Вызывается scheduler'ом каждые N минут.
    """
    logger.info("[Alert Engine] Starting alert check cycle")

    try:
        # Получить все включенные алерты
        alerts = ops_db.get_enabled_alerts()
        logger.info(f"[Alert Engine] Found {len(alerts)} enabled alerts")

        incidents_created = 0

        for alert in alerts:
            try:
                incident_id = check_alert(alert)
                if incident_id:
                    incidents_created += 1
            except Exception as e:
                logger.error(f"[Alert Engine] Error processing alert {alert['id']}: {e}", exc_info=True)

        logger.info(f"[Alert Engine] Alert check cycle complete. Created {incidents_created} incidents")

        return {
            "alerts_checked": len(alerts),
            "incidents_created": incidents_created,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"[Alert Engine] Error in alert check cycle: {e}", exc_info=True)
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


# ============ MANUAL TRIGGER (for testing) ============

def trigger_alert_check_now():
    """
    Ручной запуск проверки алертов (для тестирования).
    """
    logger.info("[Alert Engine] Manual trigger requested")
    return run_alert_check_cycle()
