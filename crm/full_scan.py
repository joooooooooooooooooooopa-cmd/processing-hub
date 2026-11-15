#!/usr/bin/env python3
"""Full scan of all business/integration groups"""
import asyncio
import sys
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
import database as db
import analyzer
import json
from config import API_ID, API_HASH, PHONE_NUMBER

# Flush output immediately
sys.stdout.reconfigure(line_buffering=True)

def is_biz(name):
    n = name.lower()
    if 'processinghub' not in n:
        return False
    if 'tech' in n:
        return False
    return any(x in n for x in ['business', 'buisness', 'integration', ' x ', ' | ', ' & '])

async def main():
    print('Starting full scan...', flush=True)
    client = TelegramClient('merchant_crm_session', API_ID, API_HASH)
    await client.start(phone=PHONE_NUMBER)
    print('Connected!', flush=True)

    groups = []
    async for d in client.iter_dialogs():
        if hasattr(d.entity, 'title') and is_biz(d.name):
            groups.append({'id': d.id, 'name': d.name})

    print(f'Scanning {len(groups)} groups...', flush=True)

    total = 0
    for i, g in enumerate(groups, 1):
        print(f'[{i}/{len(groups)}] {g["name"][:45]}', flush=True)
        try:
            ent = await client.get_entity(g['id'])
            msgs = []
            async for m in client.iter_messages(ent, limit=50):
                if m.text and len(m.text) > 15:
                    msgs.append(m.text)

            if not msgs:
                continue

            ctx = '\n'.join(msgs[:5])
            seen = set()

            for txt in msgs:
                q = analyzer.quick_analyze(txt)
                if q['has_merchant_info'] or q['type'] != 'general':
                    r = analyzer.analyze_message(txt, chat_name=g['name'])
                    if r and r.merchant_name:
                        nm = r.merchant_name
                        if nm and nm.lower() != 'processinghub' and nm not in seen:
                            seen.add(nm)
                            db.create_or_update_merchant(
                                name=nm,
                                status=r.status,
                                integration_status=r.integration_status,
                                mood=r.mood,
                                rate_flexibility=r.rate_flexibility,
                                current_rate=r.current_rate,
                                min_rate=r.min_rate,
                                conversion=r.conversion,
                                payment_methods=json.dumps(r.payment_methods) if r.payment_methods else None,
                                group_id=g['id'],
                                group_name=g['name'],
                                notes=r.notes
                            )
                            print(f'  + {nm} ({r.status or "?"})', flush=True)
                            total += 1
        except Exception as e:
            print(f'  ERR: {str(e)[:40]}', flush=True)

        await asyncio.sleep(0.3)

    print(f'\n=== DONE: {total} merchant updates ===', flush=True)
    s = db.get_stats()
    print(f'DB: {s["total_merchants"]} merchants', flush=True)
    print(f'Status: {s["by_status"]}', flush=True)

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
