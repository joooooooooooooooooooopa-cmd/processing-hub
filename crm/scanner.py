#!/usr/bin/env python3
"""
MerchantCRM Chat Scanner Service (crm-scanner)
Production entry point for Railway — 4th microservice.

SAFETY FIRST:
- FloodWait handling (respects Telegram rate limits)
- Gradual ramp-up (no aggressive initial scan)
- Throttled real-time processing
- Long delays between group scans
- Graceful shutdown on SIGINT/SIGTERM
"""
import asyncio
import signal
import sys
import logging
from datetime import datetime, timedelta

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError, SessionPasswordNeededError,
    AuthKeyUnregisteredError, UserDeactivatedBanError,
)
from telethon.tl.types import Channel, Chat
from telegram import Bot

from config import (
    API_ID, API_HASH, PHONE_NUMBER, BOT_TOKEN, ADMIN_IDS,
    get_session_path, MAX_MESSAGES_PER_SCAN
)
import database as db
from scheduler import (
    process_message, check_alerts, is_business_chat
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("scanner")

# Reduce noise from libraries
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Safety settings ──────────────────────────────────────────────────────────
# Delays between operations to avoid FloodWait / account restrictions
DELAY_BETWEEN_GROUPS = 5          # 5 seconds between scanning groups
DELAY_BETWEEN_MESSAGES = 0.3      # 300ms between processing messages
DELAY_AFTER_FLOODWAIT_EXTRA = 10  # Extra seconds after FloodWait recovery
MAX_MESSAGES_PER_GROUP = 15       # Read max 15 messages per group (conservative)
MAX_GROUPS_PER_SCAN = 30          # Don't scan more than 30 groups at once
REALTIME_THROTTLE = 2.0           # Min 2 seconds between real-time processing
STARTUP_DELAY = 10                # Wait 10 seconds after connecting before scanning

# Intervals (seconds)
FULL_SCAN_INTERVAL = 4 * 60 * 60     # 4 hours (conservative)
PROBLEM_SCAN_INTERVAL = 2 * 60 * 60  # 2 hours
ALERT_CHECK_INTERVAL = 5 * 60        # 5 minutes
GROUP_REFRESH_INTERVAL = 12 * 60 * 60 # 12 hours
LOOP_TICK = 60                        # Check every minute


async def safe_sleep(seconds: float):
    """Sleep with logging for long waits."""
    if seconds > 30:
        logger.info(f"Waiting {seconds:.0f} seconds (rate limit protection)...")
    await asyncio.sleep(seconds)


class ScannerService:
    def __init__(self):
        self.client: TelegramClient = None
        self.bot: Bot = None
        self.running = False
        self.last_full_scan = datetime.min
        self.last_problem_scan = datetime.min
        self.last_alert_check = datetime.min
        self.last_group_refresh = datetime.min
        self.last_realtime_process = datetime.min
        self.monitored_group_ids: list = []
        self.flood_wait_until: datetime = datetime.min

    async def start(self):
        """Initialize and start all scanning modes."""
        logger.info("=" * 60)
        logger.info("Starting Scanner Service (SAFE MODE)")
        logger.info("=" * 60)

        # Validate config
        if not API_ID or not API_HASH or not PHONE_NUMBER:
            logger.error("Missing Telethon credentials (API_ID, API_HASH, PHONE_NUMBER)")
            sys.exit(1)

        # 1. Initialize Telethon client
        session_path = get_session_path()
        logger.info(f"Connecting Telethon (session: {session_path})...")
        self.client = TelegramClient(session_path, API_ID, API_HASH)

        try:
            await self.client.start(phone=PHONE_NUMBER)
        except SessionPasswordNeededError:
            logger.error("2FA password required! Run locally first to set up session.")
            sys.exit(1)
        except AuthKeyUnregisteredError:
            logger.error("Session expired! Need to re-authenticate locally.")
            sys.exit(1)
        except UserDeactivatedBanError:
            logger.error("ACCOUNT BANNED! Cannot proceed.")
            sys.exit(1)

        me = await self.client.get_me()
        logger.info(f"Logged in as {me.first_name} (@{me.username})")
        logger.info(f"Phone: {me.phone}")

        # 2. Initialize bot for notifications
        if BOT_TOKEN and BOT_TOKEN != "YOUR_BOT_TOKEN":
            self.bot = Bot(token=BOT_TOKEN)
            logger.info("Notification bot initialized")
        else:
            logger.warning("BOT_TOKEN not set — notifications disabled")

        # 3. Wait before doing anything (let Telegram stabilize the session)
        logger.info(f"Waiting {STARTUP_DELAY}s for session to stabilize...")
        await safe_sleep(STARTUP_DELAY)

        # 4. Discover groups (slowly)
        await self._safe_discover_groups()

        # 5. Register real-time handler (throttled)
        self._register_realtime_handler()

        # 6. Update scanner state
        self._update_state("scanner_started", datetime.now().isoformat())
        self._update_state("scanner_status", "running")
        self._update_state("account", f"{me.first_name} (@{me.username})")

        # 7. DO NOT run aggressive initial scan — let periodic loop handle it gradually
        logger.info("Skipping initial full scan (will run in first periodic cycle)")
        # Force first scan after 5 minutes (not immediately)
        self.last_full_scan = datetime.now() - timedelta(hours=4) + timedelta(minutes=5)

        # 8. Start periodic loop
        self.running = True
        logger.info("Scanner ready — real-time (throttled) + periodic mode active")
        logger.info(f"Full scan: every {FULL_SCAN_INTERVAL // 3600}h | "
                     f"Problem scan: every {PROBLEM_SCAN_INTERVAL // 3600}h | "
                     f"Groups: {len(self.monitored_group_ids)}")
        await self._periodic_loop()

    async def _safe_discover_groups(self):
        """Discover ProcessingHub business groups with FloodWait protection."""
        logger.info("Discovering business groups...")
        groups_found = 0

        try:
            async for d in self.client.iter_dialogs():
                entity = d.entity
                if not isinstance(entity, (Channel, Chat)):
                    continue
                if not is_business_chat(d.name):
                    continue

                db.add_group(d.id, d.name, "merchant")
                groups_found += 1
                logger.info(f"  Group: {d.name} ({d.id})")

        except FloodWaitError as e:
            logger.warning(f"FloodWait during group discovery: wait {e.seconds}s")
            self.flood_wait_until = datetime.now() + timedelta(seconds=e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)
            await safe_sleep(e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)

        # Update monitored list
        groups = db.get_groups()
        self.monitored_group_ids = [g["id"] for g in groups]

        self._update_state("groups_monitored", str(groups_found))
        self.last_group_refresh = datetime.now()
        logger.info(f"Monitoring {groups_found} groups")

    def _register_realtime_handler(self):
        """Register THROTTLED real-time handler."""
        if not self.monitored_group_ids:
            logger.warning("No groups to monitor in real-time")
            return

        @self.client.on(events.NewMessage(chats=self.monitored_group_ids))
        async def on_new_message(event):
            # Throttle: skip if processing too fast
            now = datetime.now()
            elapsed = (now - self.last_realtime_process).total_seconds()
            if elapsed < REALTIME_THROTTLE:
                return  # Skip — too fast

            # Skip if in FloodWait cooldown
            if now < self.flood_wait_until:
                return

            message = event.message
            if not message.text or len(message.text) < 15:
                return

            try:
                sender_id = message.sender_id or 0
                sender_name = ""
                if message.sender:
                    sender_name = (
                        getattr(message.sender, "first_name", "")
                        or getattr(message.sender, "title", "")
                    )

                chat = await event.get_chat()
                group_name = getattr(chat, "title", str(event.chat_id))

                logger.info(f"[RT] {group_name}: {message.text[:50]}...")

                result = await process_message(
                    text=message.text,
                    chat_name=group_name,
                    group_id=event.chat_id,
                    telegram_msg_id=message.id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                )

                self.last_realtime_process = datetime.now()

                if result:
                    logger.info(f"[RT] Merchant updated from {group_name}")
                    self._update_state("last_realtime_update", datetime.now().isoformat())

            except FloodWaitError as e:
                logger.warning(f"[RT] FloodWait: waiting {e.seconds}s")
                self.flood_wait_until = datetime.now() + timedelta(seconds=e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)
            except Exception as e:
                logger.error(f"[RT] Error: {e}")

        logger.info(f"Real-time handler registered for {len(self.monitored_group_ids)} groups (throttle: {REALTIME_THROTTLE}s)")

    async def _safe_scan_groups(self, groups: list, message_limit: int = MAX_MESSAGES_PER_GROUP):
        """Scan groups with FloodWait protection and conservative delays."""
        total_updates = 0
        scanned = 0

        for group in groups[:MAX_GROUPS_PER_SCAN]:
            # Check FloodWait cooldown
            if datetime.now() < self.flood_wait_until:
                wait = (self.flood_wait_until - datetime.now()).total_seconds()
                logger.info(f"In FloodWait cooldown, waiting {wait:.0f}s...")
                await safe_sleep(wait)

            if not self.running:
                break

            try:
                entity = await self.client.get_entity(group["id"])
                group_name = getattr(entity, "title", str(group["id"]))

                async for msg in self.client.iter_messages(entity, limit=message_limit):
                    if not msg.text or len(msg.text) < 15:
                        continue

                    sender_id = msg.sender_id or 0
                    sender_name = ""
                    if msg.sender:
                        sender_name = getattr(msg.sender, "first_name", "") or getattr(msg.sender, "title", "")

                    result = await process_message(
                        text=msg.text,
                        chat_name=group_name,
                        group_id=group["id"],
                        telegram_msg_id=msg.id,
                        sender_id=sender_id,
                        sender_name=sender_name,
                    )
                    total_updates += result
                    await asyncio.sleep(DELAY_BETWEEN_MESSAGES)

                scanned += 1

            except FloodWaitError as e:
                logger.warning(f"FloodWait scanning {group.get('name', '?')}: wait {e.seconds}s")
                self.flood_wait_until = datetime.now() + timedelta(seconds=e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)
                await safe_sleep(e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)
            except Exception as e:
                logger.error(f"Error scanning {group.get('name', '?')}: {e}")

            # Conservative delay between groups
            await safe_sleep(DELAY_BETWEEN_GROUPS)

        logger.info(f"Scanned {scanned}/{len(groups)} groups, {total_updates} updates")
        return total_updates

    async def _periodic_loop(self):
        """Main loop for scheduled tasks."""
        while self.running:
            now = datetime.now()

            try:
                # Check alerts (every 5 min) — lightweight, no Telegram API calls
                if (now - self.last_alert_check).total_seconds() >= ALERT_CHECK_INTERVAL:
                    if self.bot:
                        await check_alerts(self.bot)
                    self.last_alert_check = now
                    self._update_state("last_alert_check", now.isoformat())

                # Full scan (every 4 hours)
                if (now - self.last_full_scan).total_seconds() >= FULL_SCAN_INTERVAL:
                    if now >= self.flood_wait_until:
                        logger.info("Starting periodic full scan (safe mode)...")
                        groups = db.get_groups()
                        await self._safe_scan_groups(groups)
                        self.last_full_scan = now
                        self._update_state("last_full_scan", now.isoformat())

                # Problem scan (every 2 hours, not right after full scan)
                elif (now - self.last_problem_scan).total_seconds() >= PROBLEM_SCAN_INTERVAL:
                    if now >= self.flood_wait_until:
                        logger.info("Starting periodic problem scan (safe mode)...")
                        problems = db.get_problem_merchants()
                        if problems:
                            group_ids = set()
                            for m in problems:
                                if m.get("group_id"):
                                    group_ids.add(m["group_id"])
                            groups = [{"id": gid, "name": str(gid)} for gid in group_ids]
                            await self._safe_scan_groups(groups, message_limit=10)
                        self.last_problem_scan = now
                        self._update_state("last_problem_scan", now.isoformat())

                # Refresh group list (every 12 hours)
                if (now - self.last_group_refresh).total_seconds() >= GROUP_REFRESH_INTERVAL:
                    await self._safe_discover_groups()

            except FloodWaitError as e:
                logger.warning(f"FloodWait in periodic loop: wait {e.seconds}s")
                self.flood_wait_until = datetime.now() + timedelta(seconds=e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)
                await safe_sleep(e.seconds + DELAY_AFTER_FLOODWAIT_EXTRA)
            except Exception as e:
                logger.error(f"Periodic loop error: {e}")
                self._update_state("last_error", f"{now.isoformat()}: {e}")

            await asyncio.sleep(LOOP_TICK)

    def _update_state(self, key: str, value: str):
        """Update scanner state in DB."""
        try:
            db.set_scanner_state(key, value)
        except Exception as e:
            logger.error(f"Failed to update state {key}: {e}")

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping scanner service...")
        self.running = False
        self._update_state("scanner_status", "stopped")
        self._update_state("scanner_stopped", datetime.now().isoformat())
        if self.client:
            await self.client.disconnect()
        logger.info("Scanner stopped.")


async def main():
    service = ScannerService()

    # Graceful shutdown on signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))

    try:
        await service.start()
    except FloodWaitError as e:
        logger.error(f"FloodWait at startup: need to wait {e.seconds}s. Exiting safely.")
        service._update_state("scanner_status", f"flood_wait_{e.seconds}s")
    except Exception as e:
        logger.error(f"Scanner crashed: {e}", exc_info=True)
        service._update_state("scanner_status", f"error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
