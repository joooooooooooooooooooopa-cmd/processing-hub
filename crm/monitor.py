"""
Telegram Chat Monitor using Telethon (userbot)
Reads messages from groups and analyzes them
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

from config import API_ID, API_HASH, PHONE_NUMBER, SCAN_INTERVAL, MAX_MESSAGES_PER_SCAN, get_session_path
import database as db
import analyzer

# Telethon client
client: Optional[TelegramClient] = None


async def init_client():
    """Initialize Telethon client"""
    global client

    if not API_ID or not API_HASH:
        print("[Monitor] Error: API_ID and API_HASH required")
        print("[Monitor] Get them from https://my.telegram.org")
        return False

    client = TelegramClient(get_session_path(), API_ID, API_HASH)

    await client.start(phone=PHONE_NUMBER)

    me = await client.get_me()
    print(f"[Monitor] Logged in as {me.first_name} (@{me.username})")

    return True


def is_business_or_integration_chat(name: str) -> bool:
    """Check if chat is a business or integration chat (not tech)"""
    name_lower = name.lower()

    # Must contain processinghub
    if 'processinghub' not in name_lower:
        return False

    # Filter: Business, Integration, or just "x ProcessingHub" without tech
    # Exclude: Tech chats
    if 'tech' in name_lower:
        return False

    # Include: Business, Integration, or merchant chats with "x processinghub"
    if any(x in name_lower for x in ['business', 'buisness', 'integration', 'интеграция']):
        return True

    # Include chats with "x processinghub" pattern (merchant partnerships)
    if ' x ' in name_lower or ' | ' in name_lower or ' & ' in name_lower:
        return True

    return False


async def get_dialogs(filter_business_only: bool = False):
    """Get all dialogs (chats, groups, channels)"""
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity

        if isinstance(entity, (Channel, Chat)):
            # Apply filter if requested
            if filter_business_only and not is_business_or_integration_chat(dialog.name):
                continue

            dialogs.append({
                "id": dialog.id,
                "name": dialog.name,
                "type": "channel" if isinstance(entity, Channel) else "chat",
                "unread": dialog.unread_count
            })

    return dialogs


async def list_groups():
    """List all available groups"""
    dialogs = await get_dialogs()

    print("\n[Monitor] Available groups:")
    print("-" * 60)

    for d in dialogs:
        print(f"  {d['id']:>15} | {d['type']:<8} | {d['name']}")

    print("-" * 60)
    print(f"Total: {len(dialogs)} groups/channels")

    return dialogs


async def add_group_to_monitor(group_id: int, group_type: str = "merchant"):
    """Add a group to monitoring list"""
    try:
        entity = await client.get_entity(group_id)
        name = getattr(entity, 'title', str(group_id))

        db.add_group(group_id, name, group_type)
        print(f"[Monitor] Added group: {name} ({group_id}) as {group_type}")
        return True
    except Exception as e:
        print(f"[Monitor] Error adding group {group_id}: {e}")
        return False


async def scan_group_history(group_id: int, limit: int = 100):
    """Scan message history of a group"""
    try:
        entity = await client.get_entity(group_id)
        group_name = getattr(entity, 'title', str(group_id))

        print(f"[Monitor] Scanning {group_name}...")

        messages = []
        async for message in client.iter_messages(entity, limit=limit):
            if message.text:
                sender_name = "Unknown"
                if message.sender:
                    sender_name = getattr(message.sender, 'first_name', '') or \
                                  getattr(message.sender, 'title', 'Unknown')

                messages.append({
                    "id": message.id,
                    "text": message.text,
                    "sender_id": message.sender_id,
                    "sender_name": sender_name,
                    "date": message.date
                })

        print(f"[Monitor] Found {len(messages)} messages in {group_name}")

        # Analyze messages
        analyzed = 0
        for msg in reversed(messages):  # Process oldest first
            # Quick analysis first
            quick = analyzer.quick_analyze(msg["text"])

            if quick["has_merchant_info"] or quick["type"] != "general":
                # Full AI analysis for relevant messages
                result = analyzer.analyze_message(msg["text"], chat_name=group_name)

                if result and result.merchant_name:
                    # Save or update merchant using AnalysisResult fields directly
                    db.create_or_update_merchant(
                        name=result.merchant_name,
                        status=result.status,
                        integration_status=result.integration_status,
                        mood=result.mood,
                        rate_flexibility=result.rate_flexibility,
                        current_rate=result.current_rate,
                        min_rate=result.min_rate,
                        conversion=result.conversion,
                        payment_methods=json.dumps(result.payment_methods) if result.payment_methods else None,
                        group_id=group_id,
                        group_name=group_name,
                        notes=result.notes
                    )
                    analyzed += 1

                # Save message
                db.save_message(
                    telegram_msg_id=msg["id"],
                    group_id=group_id,
                    group_name=group_name,
                    sender_id=msg["sender_id"],
                    sender_name=msg["sender_name"],
                    text=msg["text"][:1000],  # Truncate long messages
                    analysis=json.dumps(result.to_dict()) if result else None,
                    merchants_mentioned=result.merchant_name if result and result.merchant_name else None
                )

        print(f"[Monitor] Analyzed {analyzed} merchant mentions")
        return analyzed

    except Exception as e:
        print(f"[Monitor] Error scanning group {group_id}: {e}")
        return 0


async def scan_all_groups():
    """Scan all monitored groups for new messages"""
    groups = db.get_groups()

    if not groups:
        print("[Monitor] No groups to monitor. Add groups first.")
        return

    total_analyzed = 0
    for group in groups:
        analyzed = await scan_group_history(group["id"], limit=MAX_MESSAGES_PER_SCAN)
        total_analyzed += analyzed
        await asyncio.sleep(1)  # Rate limiting

    print(f"[Monitor] Total analyzed: {total_analyzed} merchant mentions")
    return total_analyzed


async def start_realtime_monitor():
    """Start real-time monitoring of new messages"""
    groups = db.get_groups()
    group_ids = [g["id"] for g in groups]

    if not group_ids:
        print("[Monitor] No groups to monitor")
        return

    print(f"[Monitor] Starting real-time monitor for {len(group_ids)} groups")

    @client.on(events.NewMessage(chats=group_ids))
    async def handler(event):
        message = event.message

        if not message.text:
            return

        # Get sender info
        sender_name = "Unknown"
        if message.sender:
            sender_name = getattr(message.sender, 'first_name', '') or \
                          getattr(message.sender, 'title', 'Unknown')

        # Get chat info
        chat = await event.get_chat()
        group_name = getattr(chat, 'title', str(event.chat_id))

        print(f"[Monitor] New message in {group_name}: {message.text[:50]}...")

        # Quick analysis
        quick = analyzer.quick_analyze(message.text)

        if quick["has_merchant_info"] or quick["type"] != "general":
            # Full AI analysis
            result = analyzer.analyze_message(message.text, chat_name=group_name)

            if result and result.merchant_name:
                db.create_or_update_merchant(
                    name=result.merchant_name,
                    status=result.status,
                    integration_status=result.integration_status,
                    mood=result.mood,
                    rate_flexibility=result.rate_flexibility,
                    current_rate=result.current_rate,
                    min_rate=result.min_rate,
                    conversion=result.conversion,
                    payment_methods=json.dumps(result.payment_methods) if result.payment_methods else None,
                    group_id=event.chat_id,
                    group_name=group_name,
                    notes=result.notes
                )
                print(f"[Monitor] Updated merchant: {result.merchant_name}")

            # Save message
            db.save_message(
                telegram_msg_id=message.id,
                group_id=event.chat_id,
                group_name=group_name,
                sender_id=message.sender_id,
                sender_name=sender_name,
                text=message.text[:1000],
                analysis=json.dumps(result.to_dict()) if result else None,
                merchants_mentioned=result.merchant_name if result and result.merchant_name else None
            )

    print("[Monitor] Real-time monitoring started. Press Ctrl+C to stop.")
    await client.run_until_disconnected()


async def main():
    """Main function for standalone monitor"""
    import sys

    if not await init_client():
        return

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "list":
            await list_groups()

        elif command == "add" and len(sys.argv) > 2:
            group_id = int(sys.argv[2])
            group_type = sys.argv[3] if len(sys.argv) > 3 else "merchant"
            await add_group_to_monitor(group_id, group_type)

        elif command == "scan":
            await scan_all_groups()

        elif command == "realtime":
            await start_realtime_monitor()

        else:
            print("Usage:")
            print("  python monitor.py list              - List all groups")
            print("  python monitor.py add <id> [type]   - Add group to monitor")
            print("  python monitor.py scan              - Scan all monitored groups")
            print("  python monitor.py realtime          - Start real-time monitoring")

    else:
        # Default: scan all groups
        await scan_all_groups()

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
