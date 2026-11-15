"""
Веб-сервер для ProcessingHub Mini App
================================
Запуск: python webapp_server.py
Для Telegram нужен HTTPS - используй ngrok:
  ngrok http 5001
"""

from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
import pandas as pd
import numpy as np
import os
import math
import requests as req
from datetime import datetime
from openai import OpenAI
from config import EXCEL_PATH, OPENAI_API_KEY

try:
    from config import METABASE_URL, METABASE_EMAIL, METABASE_PASSWORD, METABASE_CARD_ID
except ImportError:
    METABASE_URL = None
    METABASE_EMAIL = None
    METABASE_PASSWORD = None
    METABASE_CARD_ID = None

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RATES_FILE = os.path.join(BASE_DIR, EXCEL_PATH)
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")

# OpenAI клиент
ai_client = OpenAI(api_key=OPENAI_API_KEY)

# Metabase session
_metabase_session = None
_last_update = None


def parse_number(x):
    """Парсит числа с пробелами и запятыми"""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    if not s or s.lower() in ['nan', 'none', '']:
        return None
    s = s.replace('\u00a0', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except:
        return None


def load_rates_data():
    """Загружает данные из CSV и форматирует для API"""
    global _last_update

    try:
        df = pd.read_csv(RATES_FILE, encoding='utf-8-sig')
    except Exception as e:
        return {'error': str(e), 'merchants': []}

    # Переименовываем колонки если нужно
    if 'margin_buy' in df.columns:
        df = df.rename(columns={'margin_buy': 'basefee'})

    # Парсим числа
    for col in ['basefee', 'fee', 'amount_gt', 'amount_lt']:
        if col in df.columns:
            df[col] = df[col].apply(parse_number)

    # Группируем по мерчам
    merchants = {}
    for _, row in df.iterrows():
        name = str(row.get('name', '')).strip()
        if not name or name.lower() in ['nan', 'none', '']:
            continue

        if name not in merchants:
            merchants[name] = {
                'name': name,
                'basefee': parse_number(row.get('basefee')),
                'methods': {}
            }

        # Обновляем basefee если есть
        bf = parse_number(row.get('basefee'))
        if bf is not None:
            merchants[name]['basefee'] = bf

        # Добавляем метод
        method = str(row.get('payment_type', '')).strip().lower()
        if method and method not in ['nan', 'none', '']:
            if method not in merchants[name]['methods']:
                merchants[name]['methods'][method] = []

            fee = parse_number(row.get('fee'))
            if fee is not None:
                merchants[name]['methods'][method].append({
                    'gt': parse_number(row.get('amount_gt')),
                    'lt': parse_number(row.get('amount_lt')),
                    'fee': fee
                })

    # Конвертируем в список
    result = []
    all_fees = []
    methods_set = set()

    for name, data in sorted(merchants.items()):
        methods_list = []
        for method_name, ranges in data['methods'].items():
            methods_set.add(method_name)
            methods_list.append({
                'name': method_name,
                'ranges': sorted(ranges, key=lambda x: (x['gt'] or 0, x['lt'] or float('inf')))
            })
            for r in ranges:
                if r['fee']:
                    all_fees.append(r['fee'])

        result.append({
            'name': data['name'],
            'basefee': data['basefee'],
            'methods': methods_list
        })
        if data['basefee']:
            all_fees.append(data['basefee'])

    # Статистика
    avg_rate = sum(all_fees) / len(all_fees) if all_fees else 0

    # Время обновления файла
    try:
        mtime = os.path.getmtime(RATES_FILE)
        _last_update = datetime.fromtimestamp(mtime).strftime('%d.%m.%Y %H:%M')
    except:
        _last_update = None

    return {
        'merchants': result,
        'methods_count': len(methods_set),
        'avg_rate': round(avg_rate, 1),
        'last_update': _last_update
    }


def metabase_sync():
    """Синхронизация с Metabase"""
    global _metabase_session

    if not METABASE_URL or not METABASE_EMAIL or not METABASE_PASSWORD:
        return {'success': False, 'error': 'Metabase не настроен'}

    try:
        # Логин
        resp = req.post(
            f"{METABASE_URL}/api/session",
            json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
            timeout=30
        )
        if resp.status_code != 200:
            return {'success': False, 'error': 'Ошибка авторизации'}

        _metabase_session = resp.json().get('id')

        # Загружаем CSV
        headers = {"X-Metabase-Session": _metabase_session}
        resp = req.post(
            f"{METABASE_URL}/api/card/{METABASE_CARD_ID}/query/csv",
            headers=headers,
            timeout=60
        )

        if resp.status_code != 200:
            return {'success': False, 'error': f'Ошибка загрузки: {resp.status_code}'}

        # Сохраняем
        with open(RATES_FILE, 'w', encoding='utf-8-sig') as f:
            f.write(resp.text)

        return {'success': True, 'message': 'Данные обновлены'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


# ============ STATIC FILES ============
@app.route("/")
def index():
    return send_from_directory(WEBAPP_DIR, "index.html")


@app.route("/logo.png")
def logo():
    return send_from_directory(WEBAPP_DIR, "logo.png")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(WEBAPP_DIR, path)


# ============ API ============
@app.route("/api/rates")
def api_rates():
    data = load_rates_data()
    return jsonify(data)


@app.route("/api/sync", methods=["POST"])
def api_sync():
    result = metabase_sync()
    return jsonify(result)


@app.route("/api/status")
def api_status():
    return jsonify({
        'status': 'ok',
        'metabase_configured': bool(METABASE_URL),
        'last_update': _last_update
    })


# ============ AI CHAT ============
@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        user_message = data.get("message", "")

        # Получаем данные о ставках для контекста
        rates_data = load_rates_data()
        rates_info = "\n".join([
            f"{m['name']}: basefee={m['basefee']}%, methods={[mt['name'] for mt in m['methods']]}"
            for m in rates_data.get('merchants', [])[:50]
        ])

        system_prompt = f"""Ты AI-помощник ProcessingHub для работы со ставками.
Данные о ставках (первые 50 мерчей):

{rates_info}

Отвечай кратко, на русском."""

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500
        )

        return jsonify({"response": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print("=" * 40)
    print("  ProcessingHub Mini App Server")
    print("=" * 40)
    print(f"  Local:  http://localhost:{port}")
    print(f"  Metabase: {'OK' if METABASE_URL else 'Не настроен'}")
    print("=" * 40)
    print("  Для Telegram нужен HTTPS!")
    print("  Запусти: ngrok http 5001")
    print("=" * 40)
    app.run(host="0.0.0.0", port=port, debug=False)
