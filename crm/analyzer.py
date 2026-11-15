"""
AI Analyzer v2.0 for Merchant CRM
- Rule-first, AI-second approach
- Explicit confidence levels
- No guessing - null when uncertain
- Canonical data only
- Context-aware analysis
"""
import json
import re
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass
from openai import OpenAI

from config import OPENAI_API_KEY, AI_MODEL
from database import (
    CANONICAL_STATUSES,
    CANONICAL_PAYMENT_METHODS,
    CANONICAL_MOODS,
    validate_status,
    validate_payment_method,
    get_recent_messages,
    get_merchant,
)

client = None


def init_client():
    global client
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
    else:
        print("[Analyzer] Warning: OPENAI_API_KEY not set")


init_client()


# ============ ANALYSIS RESULT ============

@dataclass
class AnalysisResult:
    """Structured analysis result with explainability"""
    merchant_name: Optional[str] = None
    name_source: str = 'unknown'  # chat_title, message, unknown
    status: Optional[str] = None
    integration_status: Optional[str] = None
    mood: Optional[str] = None
    rate_flexibility: Optional[str] = None
    current_rate: Optional[float] = None
    min_rate: Optional[float] = None
    conversion: Optional[float] = None
    payment_methods: Optional[List[str]] = None
    notes: Optional[str] = None

    # Explainability
    reason: str = ""
    confidence: float = 0.0  # 0.0 to 1.0
    decided_by: str = "rule"  # rule, ai, hybrid

    def to_dict(self) -> Dict:
        return {
            'merchant_name': self.merchant_name,
            'name_source': self.name_source,
            'status': self.status,
            'integration_status': self.integration_status,
            'mood': self.mood,
            'rate_flexibility': self.rate_flexibility,
            'current_rate': self.current_rate,
            'min_rate': self.min_rate,
            'conversion': self.conversion,
            'payment_methods': self.payment_methods,
            'notes': self.notes,
            'reason': self.reason,
            'confidence': self.confidence,
            'decided_by': self.decided_by,
        }


# ============ RULE-BASED ANALYSIS ============

# Status detection rules (ordered by priority)
STATUS_RULES = [
    # Disconnected (highest priority - clear signal)
    {
        'status': 'disconnected',
        'patterns': [
            r'\b(отключили|отключен|выключили|офф|стоп|stopped|disabled|off)\b',
            r'\b(мерч(ант)?\s+(офф|стоп|отключ))',
            r'\bвыводим\s+из\s+работы\b',
        ],
        'confidence': 0.95,
        'reason': 'Explicit disconnection mentioned'
    },
    # Problem (high priority - needs attention)
    {
        'status': 'problem',
        'patterns': [
            r'\b(проблем[аы]|ошибк[аи]|не работает|баг|fail|error|broken)\b',
            r'\b(упал[аи]?|сломал[аи]?|зависл[аи]?)\b',
            r'\b(конверсия\s+(упала|0|ноль|низкая))\b',
            r'\bне\s+(проходят?|идут?|работает?)\b',
        ],
        'confidence': 0.9,
        'reason': 'Problem indicators detected'
    },
    # Active (clear signals of working merchant)
    {
        'status': 'active',
        'patterns': [
            r'\b(сетл|сеттл|settlement|выплат[аы]?)\b',
            r'\b(льём|льем|гоним|трафик\s+идёт|трафик\s+идет)\b',
            r'\b(в\s+проде|работает|запустили|подключили)\b',
            r'\b(конверсия|конверт)\s*[:\s]*\d+',
            r'\bобъём[ы]?\s*[:\s]*\d+',
        ],
        'confidence': 0.85,
        'reason': 'Active traffic/operations detected'
    },
    # Testing
    {
        'status': 'testing',
        'patterns': [
            r'\b(тест(ируем|овый|им)?|testing|проверяем|проверка)\b',
            r'\bтестов(ый|ая|ые)?\s+(транзакц|платёж)',
        ],
        'confidence': 0.85,
        'reason': 'Testing phase mentioned'
    },
    # Integration
    {
        'status': 'integration',
        'patterns': [
            r'\b(интеграц|интегрируем|подключаем|настраиваем)\b',
            r'\b(апи|api|webhook)\s+(настро|подключ)',
            r'\bтехническ(ая|ое)\s+(интеграц|настройк)',
        ],
        'confidence': 0.85,
        'reason': 'Integration work mentioned'
    },
    # Paused
    {
        'status': 'paused',
        'patterns': [
            r'\b(на\s+паузе|приостановили|временно\s+(стоп|офф))\b',
            r'\b(пауза|pause)\b',
        ],
        'confidence': 0.9,
        'reason': 'Paused state mentioned'
    },
    # Negotiation
    {
        'status': 'negotiation',
        'patterns': [
            r'\b(обсуждаем|переговор|договарива|условия)\b',
            r'\b(какие?\s+ставк|предложи|готовы\s+работать)\b',
        ],
        'confidence': 0.7,
        'reason': 'Negotiation detected'
    },
]

# Rate patterns
RATE_PATTERNS = [
    (r'(?:ставка|rate|fee|комиссия)[:\s]*(\d+(?:[.,]\d+)?)\s*%?', 'current_rate'),
    (r'(\d+(?:[.,]\d+)?)\s*%\s*(?:ставка|rate|fee)', 'current_rate'),
    (r'(?:минимум|мин|min)[:\s]*(\d+(?:[.,]\d+)?)\s*%?', 'min_rate'),
    (r'(\d+(?:[.,]\d+)?)\s*%\s*(?:минимум|мин)', 'min_rate'),
]

# Conversion patterns
CONVERSION_PATTERNS = [
    r'(?:конверсия|конверт|апрув|approve)[:\s]*(\d+(?:[.,]\d+)?)\s*%?',
    r'(\d+(?:[.,]\d+)?)\s*%?\s*(?:конверсия|конверт|апрув)',
]

# Payment method patterns
PAYMENT_METHOD_PATTERNS = {
    'sbp': [r'\b(сбп|sbp|спб)\b'],
    'c2c': [r'\b(c2c|p2p|карт[аы]?\s*-?\s*карт[ау]?)\b'],
    'qr': [r'\b(qr|qr-code|нспк)\b'],
    'alfa': [r'\b(альфа|alfa|alphabank)\b'],
    'tinkoff': [r'\b(тинькофф|тиньков|tinkoff)\b'],
    'sber': [r'\b(сбер|sber|сбербанк)\b'],
    'vtb': [r'\b(втб|vtb)\b'],
}


def extract_merchant_name_from_chat(chat_name: str) -> Tuple[Optional[str], float]:
    """
    Extract merchant name from chat title.
    Returns (name, confidence)
    """
    if not chat_name:
        return None, 0.0

    # Pattern: "MerchantName x ProcessingHub" or "MerchantName | ProcessingHub"
    patterns = [
        r'^(.+?)\s*[x×|&]\s*(?:processinghub|ProcessingHub)',
        r'^(.+?)\s+(?:business|buisness|integration)',
        r'^(?:processinghub|ProcessingHub)\s*[x×|&]\s*(.+?)$',
    ]

    for pattern in patterns:
        match = re.search(pattern, chat_name, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Clean up
            name = re.sub(r'\s+', ' ', name)
            if len(name) > 2 and name.lower() != 'processinghub':
                return name, 0.9

    return None, 0.0


def extract_merchant_name_from_text(text: str) -> Tuple[Optional[str], float]:
    """
    Extract merchant name from message text.
    Returns (name, confidence) - lower confidence than chat title
    """
    patterns = [
        (r'(?:мерч(?:ант)?|merchant)\s+["\']?([A-Za-zА-Яа-я0-9_\-]+)["\']?', 0.7),
        (r'(?:у|от|с|на)\s+([A-Z][A-Za-z0-9]+(?:Pay|Coin|Cash|Money|Wallet)?)\b', 0.5),
    ]

    for pattern, conf in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if len(name) > 2 and name.lower() not in ('processinghub', 'merchant', 'мерчант'):
                return name, conf

    return None, 0.0


def detect_status_by_rules(text: str) -> Tuple[Optional[str], float, str]:
    """
    Detect status using rules.
    Returns (status, confidence, reason)
    """
    text_lower = text.lower()

    for rule in STATUS_RULES:
        for pattern in rule['patterns']:
            if re.search(pattern, text_lower):
                return rule['status'], rule['confidence'], rule['reason']

    return None, 0.0, ""


def extract_rates(text: str) -> Dict[str, Optional[float]]:
    """Extract rate information from text"""
    result = {'current_rate': None, 'min_rate': None}

    for pattern, field in RATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1).replace(',', '.'))
                if 0 < value < 50:  # Reasonable rate range
                    result[field] = value
            except ValueError:
                pass

    return result


def extract_conversion(text: str) -> Optional[float]:
    """Extract conversion rate from text"""
    for pattern in CONVERSION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1).replace(',', '.'))
                if 0 <= value <= 100:  # Valid percentage
                    return value
            except ValueError:
                pass
    return None


def extract_payment_methods(text: str) -> List[str]:
    """Extract payment methods from text"""
    found = []
    text_lower = text.lower()

    for method, patterns in PAYMENT_METHOD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                found.append(method)
                break

    return list(set(found))


def rule_based_analyze(text: str, chat_name: str = "") -> AnalysisResult:
    """
    Analyze message using rules only.
    Returns AnalysisResult with confidence indicating rule certainty.
    """
    result = AnalysisResult()
    result.decided_by = 'rule'

    # Extract merchant name (prefer chat title)
    name_from_chat, chat_conf = extract_merchant_name_from_chat(chat_name)
    name_from_text, text_conf = extract_merchant_name_from_text(text)

    if name_from_chat and chat_conf > text_conf:
        result.merchant_name = name_from_chat
        result.name_source = 'chat_title'
        result.confidence = max(result.confidence, chat_conf)
    elif name_from_text:
        result.merchant_name = name_from_text
        result.name_source = 'message'
        result.confidence = max(result.confidence, text_conf)

    # Detect status
    status, status_conf, status_reason = detect_status_by_rules(text)
    if status:
        result.status = status
        result.reason = status_reason
        result.confidence = max(result.confidence, status_conf)

    # Extract rates
    rates = extract_rates(text)
    if rates['current_rate']:
        result.current_rate = rates['current_rate']
        result.confidence = max(result.confidence, 0.8)
    if rates['min_rate']:
        result.min_rate = rates['min_rate']

    # Extract conversion
    conversion = extract_conversion(text)
    if conversion is not None:
        result.conversion = conversion
        result.confidence = max(result.confidence, 0.8)

    # Extract payment methods
    methods = extract_payment_methods(text)
    if methods:
        result.payment_methods = methods
        result.confidence = max(result.confidence, 0.75)

    return result


# ============ AI ANALYSIS (for complex cases) ============

AI_SYSTEM_PROMPT = """Ты аналитик CRM-системы для платёжных мерчантов. Анализируй сообщения СТРОГО по данным.

КРИТИЧЕСКИ ВАЖНО:
1. НЕ ДОДУМЫВАЙ - если данных нет, ставь null
2. НЕ УГАДЫВАЙ ставки, статусы, методы оплаты
3. Указывай confidence (0.0-1.0) - насколько уверен в каждом поле
4. Лучше null, чем неверные данные

КАНОНИЧЕСКИЕ СТАТУСЫ (только эти):
- new: первый контакт
- negotiation: переговоры
- integration: техническая интеграция
- testing: тестирование
- active: работает, идёт трафик
- paused: на паузе
- problem: есть проблемы
- disconnected: отключен

КАНОНИЧЕСКИЕ МЕТОДЫ ОПЛАТЫ:
sbp, c2c, qr, bank_transfer, alfa, tinkoff, sber, vtb, raiffeisen, other

Отвечай ТОЛЬКО JSON. Все поля обязательны (null если нет данных)."""

AI_EXTRACTION_PROMPT = """Проанализируй сообщение и КОНТЕКСТ. Извлеки ТОЛЬКО то, что ЯВНО указано.

НАЗВАНИЕ ЧАТА: {chat_name}
СООБЩЕНИЕ: {message}
КОНТЕКСТ (история): {context}
ИСТОРИЯ МЕРЧАНТА: {merchant_history}

Верни JSON:
{{
  "merchant_name": "имя или null",
  "name_source": "chat_title/message/unknown",
  "status": "canonical_status или null",
  "status_confidence": 0.0-1.0,
  "status_reason": "почему такой статус",
  "integration_status": "request/docs/tech/testing/completed или null",
  "mood": "loyal/neutral/difficult/aggressive или null",
  "current_rate": число или null,
  "min_rate": число или null,
  "conversion": число или null,
  "payment_methods": ["canonical_method", ...] или null,
  "notes": "ключевая информация",
  "overall_confidence": 0.0-1.0,
  "analysis_notes": "что понял из сообщения"
}}

ВАЖНО: Если информации недостаточно - ставь null и низкий confidence."""


def ai_analyze(text: str, chat_name: str = "", context: str = "",
               merchant_history: str = "") -> Optional[AnalysisResult]:
    """
    Use AI for complex analysis when rules are insufficient.
    Only called when rule-based analysis has low confidence.
    """
    if not client:
        return None

    if not text or len(text.strip()) < 15:
        return None

    import time as _time
    last_exc = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": AI_EXTRACTION_PROMPT.format(
                        message=text,
                        context=context or "Нет контекста",
                        chat_name=chat_name or "Неизвестно",
                        merchant_history=merchant_history or "Нет истории"
                    )}
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            break  # Success — exit retry loop
        except Exception as e:
            last_exc = e
            print(f"[Analyzer] AI error (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                _time.sleep(2 ** attempt)
    else:
        print(f"[Analyzer] AI failed after 3 attempts: {last_exc}")
        return None

    try:
        result_text = response.choices[0].message.content  # type: ignore[possibly-undefined]
        data = json.loads(result_text)

        # Build result with validation
        result = AnalysisResult()
        result.decided_by = 'ai'

        if data.get('merchant_name'):
            result.merchant_name = data['merchant_name']
            result.name_source = data.get('name_source', 'unknown')

        # Validate and set status
        if data.get('status'):
            validated = validate_status(data['status'])
            if validated:
                result.status = validated
                result.reason = data.get('status_reason', 'AI analysis')
                result.confidence = float(data.get('status_confidence', 0.5))

        # Set other fields only if present
        if data.get('current_rate') is not None:
            try:
                rate = float(data['current_rate'])
                if 0 < rate < 50:
                    result.current_rate = rate
            except (ValueError, TypeError):
                pass

        if data.get('min_rate') is not None:
            try:
                rate = float(data['min_rate'])
                if 0 < rate < 50:
                    result.min_rate = rate
            except (ValueError, TypeError):
                pass

        if data.get('conversion') is not None:
            try:
                conv = float(data['conversion'])
                if 0 <= conv <= 100:
                    result.conversion = conv
            except (ValueError, TypeError):
                pass

        if data.get('payment_methods'):
            methods = []
            for m in data['payment_methods']:
                validated = validate_payment_method(m)
                if validated and validated != 'other':
                    methods.append(validated)
            if methods:
                result.payment_methods = methods

        if data.get('notes'):
            result.notes = str(data['notes'])[:500]

        # Set overall confidence
        result.confidence = float(data.get('overall_confidence', 0.5))

        return result

    except (json.JSONDecodeError, Exception) as e:
        print(f"[Analyzer] AI parse/result error: {e}")
        return None


# ============ HYBRID ANALYSIS ============

def analyze_message(text: str, chat_name: str = "", group_id: int = None,
                    merchant_name: str = None) -> AnalysisResult:
    """
    Main analysis function using hybrid approach:
    1. First try rules
    2. If low confidence, use AI
    3. Merge results with preference for high-confidence data
    """
    # Step 1: Rule-based analysis
    rule_result = rule_based_analyze(text, chat_name)

    # If rules give high confidence, use them
    if rule_result.confidence >= 0.8 and rule_result.status:
        return rule_result

    # Step 2: Get context for AI
    context = ""
    merchant_history = ""

    if group_id:
        recent = get_recent_messages(group_id, limit=5)
        context = "\n".join([m['text'][:200] for m in recent if m.get('text')])

    if merchant_name or rule_result.merchant_name:
        name = merchant_name or rule_result.merchant_name
        merchant = get_merchant(name)
        if merchant:
            merchant_history = f"Current status: {merchant.get('status')}, " \
                             f"Rate: {merchant.get('current_rate')}, " \
                             f"Conversion: {merchant.get('conversion')}"

    # Step 3: AI analysis for complex/ambiguous cases
    ai_result = ai_analyze(text, chat_name, context, merchant_history)

    if not ai_result:
        return rule_result

    # Step 4: Merge results (prefer higher confidence)
    merged = AnalysisResult()
    merged.decided_by = 'hybrid'

    # Merchant name - prefer chat title source
    if rule_result.name_source == 'chat_title':
        merged.merchant_name = rule_result.merchant_name
        merged.name_source = 'chat_title'
    elif ai_result.merchant_name:
        merged.merchant_name = ai_result.merchant_name
        merged.name_source = ai_result.name_source
    else:
        merged.merchant_name = rule_result.merchant_name
        merged.name_source = rule_result.name_source

    # Status - prefer higher confidence
    if rule_result.status and rule_result.confidence >= ai_result.confidence:
        merged.status = rule_result.status
        merged.reason = rule_result.reason
    elif ai_result.status:
        merged.status = ai_result.status
        merged.reason = ai_result.reason

    # Rates - prefer rule-based (more precise)
    merged.current_rate = rule_result.current_rate or ai_result.current_rate
    merged.min_rate = rule_result.min_rate or ai_result.min_rate
    merged.conversion = rule_result.conversion if rule_result.conversion is not None else ai_result.conversion

    # Payment methods - merge
    methods = set()
    if rule_result.payment_methods:
        methods.update(rule_result.payment_methods)
    if ai_result.payment_methods:
        methods.update(ai_result.payment_methods)
    if methods:
        merged.payment_methods = list(methods)

    # Notes - prefer AI (more detailed)
    merged.notes = ai_result.notes or rule_result.notes

    # Confidence - weighted average
    merged.confidence = max(rule_result.confidence, ai_result.confidence)

    return merged


# ============ QUICK ANALYSIS (for filtering) ============

def quick_analyze(text: str) -> Dict[str, Any]:
    """
    Quick analysis for filtering messages before full analysis.
    Uses only rules, no AI.
    """
    if not text or len(text) < 10:
        return {'has_merchant_info': False, 'type': 'too_short'}

    text_lower = text.lower()

    # Check for merchant-related keywords
    merchant_keywords = [
        'мерч', 'merchant', 'ставка', 'rate', 'конверсия', 'трафик',
        'сетл', 'settlement', 'интеграц', 'подключ', 'тест',
        'проблем', 'ошибк', 'работает', 'отключ'
    ]

    has_merchant_info = any(kw in text_lower for kw in merchant_keywords)

    # Detect type
    status, _, _ = detect_status_by_rules(text)
    msg_type = status if status else 'general'

    # Check for rates
    rates = extract_rates(text)
    has_rates = rates['current_rate'] is not None or rates['min_rate'] is not None

    return {
        'has_merchant_info': has_merchant_info or has_rates,
        'type': msg_type,
        'has_rates': has_rates,
        'rates': rates,
    }


# ============ BATCH ANALYSIS ============

def analyze_batch(messages: List[Dict[str, str]], chat_name: str = "",
                  group_id: int = None) -> List[AnalysisResult]:
    """
    Analyze multiple messages with context.
    More efficient than individual calls.
    """
    results = []

    for i, msg in enumerate(messages):
        text = msg.get('text', '')

        # Quick filter first
        quick = quick_analyze(text)
        if not quick['has_merchant_info']:
            continue

        # Full analysis
        result = analyze_message(
            text=text,
            chat_name=chat_name,
            group_id=group_id
        )

        if result.merchant_name or result.status:
            results.append(result)

    return results


# ============ LEGACY COMPATIBILITY ============

def extract_merchant_names(text: str) -> List[str]:
    """Legacy function for compatibility"""
    name_chat, _ = extract_merchant_name_from_chat("")
    name_text, _ = extract_merchant_name_from_text(text)
    names = []
    if name_chat:
        names.append(name_chat)
    if name_text:
        names.append(name_text)
    return names


def classify_message_type(text: str) -> str:
    """Legacy function for compatibility"""
    status, _, _ = detect_status_by_rules(text)
    return f"status_{status}" if status else 'general'


def extract_numbers(text: str) -> Dict[str, Optional[float]]:
    """Legacy function for compatibility"""
    rates = extract_rates(text)
    conversion = extract_conversion(text)
    return {
        'rate': rates['current_rate'],
        'conversion': conversion,
        'min_amount': None,
        'max_amount': None,
    }
