"""
Merchant CRM - Main Launcher
"""
import asyncio
import sys
import threading

def run_bot():
    """Run the Telegram bot"""
    from bot import main as bot_main
    bot_main()

def run_monitor():
    """Run the chat monitor"""
    from monitor import main as monitor_main
    asyncio.run(monitor_main())

def print_usage():
    print("""
╔══════════════════════════════════════════╗
║         MERCHANT CRM SYSTEM              ║
╠══════════════════════════════════════════╣
║                                          ║
║  Использование:                          ║
║                                          ║
║  python main.py bot      - Запуск бота   ║
║  python main.py monitor  - Монитор чатов ║
║  python main.py list     - Список групп  ║
║  python main.py scan     - Сканирование  ║
║  python main.py realtime - Реалтайм      ║
║                                          ║
╚══════════════════════════════════════════╝

Первый запуск:
1. Получи API_ID и API_HASH на https://my.telegram.org
2. Создай бота через @BotFather и получи BOT_TOKEN
3. Получи OPENAI_API_KEY на https://platform.openai.com
4. Установи переменные окружения или создай .env файл

Порядок настройки:
1. python main.py list     - Посмотреть список групп
2. python main.py add <id> - Добавить группу в мониторинг
3. python main.py scan     - Просканировать историю
4. python main.py bot      - Запустить бота для просмотра данных
5. python main.py realtime - Запустить мониторинг в реальном времени
""")

def main():
    if len(sys.argv) < 2:
        print_usage()
        return

    command = sys.argv[1].lower()

    if command == "bot":
        print("[Main] Starting Telegram Bot...")
        run_bot()

    elif command == "monitor":
        print("[Main] Starting Monitor (default: scan all)...")
        run_monitor()

    elif command in ["list", "scan", "realtime", "add"]:
        # Pass to monitor with appropriate arguments
        sys.argv = ["monitor.py"] + sys.argv[1:]
        run_monitor()

    else:
        print(f"Unknown command: {command}")
        print_usage()

if __name__ == "__main__":
    main()
