"""
Alert Scheduler - периодическая проверка алертов
Phase 1: Incidents & Alerts MVP

Простой планировщик на asyncio без дополнительных зависимостей.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
import alert_engine

logger = logging.getLogger(__name__)


class AlertScheduler:
    """
    Простой планировщик для периодической проверки алертов.
    Работает в фоновом режиме как asyncio task.
    """

    def __init__(self, check_interval_minutes: int = 5):
        """
        Args:
            check_interval_minutes: интервал проверки алертов в минутах (по умолчанию 5)
        """
        self.check_interval_minutes = check_interval_minutes
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.last_run: Optional[datetime] = None
        self.last_result: Optional[dict] = None

    async def _run_check(self):
        """Запустить одну проверку алертов (в отдельном потоке)."""
        try:
            logger.info(f"[Alert Scheduler] Running alert check at {datetime.utcnow()}")

            # Запускаем в executor чтобы не блокировать event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, alert_engine.run_alert_check_cycle)

            self.last_run = datetime.utcnow()
            self.last_result = result

            logger.info(f"[Alert Scheduler] Alert check completed: {result}")

        except Exception as e:
            logger.error(f"[Alert Scheduler] Error running alert check: {e}", exc_info=True)
            self.last_result = {"error": str(e)}

    async def _schedule_loop(self):
        """Основной цикл планировщика."""
        logger.info(f"[Alert Scheduler] Started with interval={self.check_interval_minutes} min")

        while self.is_running:
            try:
                # Запустить проверку
                await self._run_check()

                # Подождать до следующей проверки
                await asyncio.sleep(self.check_interval_minutes * 60)

            except asyncio.CancelledError:
                logger.info("[Alert Scheduler] Scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"[Alert Scheduler] Error in schedule loop: {e}", exc_info=True)
                # Подождать немного перед повтором
                await asyncio.sleep(60)

        logger.info("[Alert Scheduler] Stopped")

    def start(self):
        """Запустить планировщик."""
        if self.is_running:
            logger.warning("[Alert Scheduler] Already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._schedule_loop())
        logger.info("[Alert Scheduler] Scheduler started")

    def stop(self):
        """Остановить планировщик."""
        if not self.is_running:
            logger.warning("[Alert Scheduler] Not running")
            return

        self.is_running = False
        if self.task:
            self.task.cancel()

        logger.info("[Alert Scheduler] Scheduler stopped")

    def get_status(self) -> dict:
        """Получить статус планировщика."""
        return {
            "is_running": self.is_running,
            "check_interval_minutes": self.check_interval_minutes,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_result": self.last_result,
        }

    async def trigger_now(self) -> dict:
        """Запустить проверку алертов немедленно (для тестирования)."""
        logger.info("[Alert Scheduler] Manual trigger requested")
        await self._run_check()
        return self.last_result or {}


# ============ ГЛОБАЛЬНЫЙ ИНСТАНС ============

# Создаём один глобальный scheduler который будет запущен при старте приложения
_global_scheduler: Optional[AlertScheduler] = None


def get_scheduler() -> AlertScheduler:
    """Получить глобальный инстанс планировщика."""
    global _global_scheduler
    if _global_scheduler is None:
        # Создаём с интервалом 5 минут (можно настроить через env)
        _global_scheduler = AlertScheduler(check_interval_minutes=5)
    return _global_scheduler


def start_scheduler():
    """Запустить глобальный планировщик."""
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("[Alert Scheduler] Global scheduler started")


def stop_scheduler():
    """Остановить глобальный планировщик."""
    scheduler = get_scheduler()
    scheduler.stop()
    logger.info("[Alert Scheduler] Global scheduler stopped")
