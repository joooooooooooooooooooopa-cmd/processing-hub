#!/usr/bin/env python3
"""
Message processing & alerts for Merchant CRM
- Idempotent message processing (used by bot file-upload and API)
- Incident-based notifications
"""
import asyncio
import json
from datetime import datetime, timedelta
from telegram import Bot

import database as db
import analyzer
from analyzer import AnalysisResult
from config import BOT_TOKEN, ADMIN_IDS

NOTIFICATION_COOLDOWN = 30 * 60    # 30 minutes between same notifications

# Last notification times (for deduplication)
last_notifications = {}


def is_business_chat(name: str) -> bool:
    """Check if chat is a business/integration chat"""
    n = name.lower()
    if 'processinghub' not in n:
        return False
    if 'tech' in n:
        return False
    return any(x in n for x in ['business', 'buisness', 'integration', ' x ', ' | ', ' & '])


async def send_notification(bot: Bot, message: str, priority: str = 'P2'):
    """Send notification to all admins"""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=message, parse_mode="HTML")
        except Exception as e:
            print(f"[Notify] Failed to send to {admin_id}: {e}")


async def check_alerts(bot: Bot):
    """Check for pending alerts and send notifications"""
    alerts = db.get_pending_alerts()

    for alert in alerts:
        key = f"{alert['merchant_id']}_{alert['alert_type']}_{alert['title'][:30]}"
        now = datetime.now()

        # Check cooldown (deduplication)
        if key in last_notifications:
            if (now - last_notifications[key]).total_seconds() < NOTIFICATION_COOLDOWN:
                db.mark_alert_notified(alert['id'])
                continue

        # Format message based on priority
        priority = alert.get('priority', 'P2')
        if priority == 'P0':
            emoji = "P0"
        elif priority == 'P1':
            emoji = "P1"
        else:
            emoji = "P2"

        message = (
            f"<b>[{emoji}] {alert['title']}</b>\n"
            f"---\n"
            f"{alert.get('message', '')[:200]}\n"
            f"\n#{alert['id']} | {alert['created_at'][:16]}"
        )

        await send_notification(bot, message, priority)
        db.mark_alert_notified(alert['id'])
        last_notifications[key] = now


async def process_message(text: str, chat_name: str, group_id: int,
                          telegram_msg_id: int, sender_id: int, sender_name: str) -> int:
    """
    Process a single message with full deduplication and analysis.
    Returns: 1 if merchant updated, 0 otherwise
    """
    # Log message (returns None if duplicate)
    msg_id = db.log_message(
        group_id=group_id,
        telegram_msg_id=telegram_msg_id,
        group_name=chat_name,
        sender_id=sender_id,
        sender_name=sender_name,
        text=text
    )

    if msg_id is None:
        # Duplicate message, skip
        return 0

    # Quick filter
    quick = analyzer.quick_analyze(text)
    if not quick['has_merchant_info']:
        db.mark_message_processed(msg_id, "no_merchant_info")
        return 0

    # Full analysis
    result = analyzer.analyze_message(
        text=text,
        chat_name=chat_name,
        group_id=group_id
    )

    if not result.merchant_name:
        db.mark_message_processed(msg_id, "no_merchant_name")
        return 0

    # Skip if it's ProcessingHub itself
    if result.merchant_name.lower() == 'processinghub':
        db.mark_message_processed(msg_id, "processinghub_skip")
        return 0

    # Update merchant with explainability
    merchant_id = db.create_or_update_merchant(
        name=result.merchant_name,
        name_source=result.name_source,
        status=result.status,
        integration_status=result.integration_status,
        mood=result.mood,
        rate_flexibility=result.rate_flexibility,
        current_rate=result.current_rate,
        min_rate=result.min_rate,
        conversion=result.conversion,
        payment_methods=json.dumps(result.payment_methods) if result.payment_methods else None,
        group_id=group_id,
        group_name=chat_name,
        notes=result.notes,
        reason=result.reason,
        confidence=result.confidence,
        source_message_id=msg_id,
        decided_by=result.decided_by
    )

    # Link message to merchant for chat history
    if merchant_id and msg_id:
        db.link_message_to_merchant(msg_id, merchant_id)

    db.mark_message_processed(msg_id, f"updated_merchant_{merchant_id}")
    return 1


