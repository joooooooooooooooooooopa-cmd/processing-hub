"""Unit tests for analyzer.py - rule-based analysis (no OpenAI dependency)"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_openai():
    """Prevent OpenAI client initialization."""
    with patch("analyzer.client", None):
        with patch("analyzer.init_client"):
            yield


class TestExtractMerchantNameFromChat:
    def test_merchant_x_processinghub(self):
        from analyzer import extract_merchant_name_from_chat
        name, conf = extract_merchant_name_from_chat("AcmePay x ProcessingHub")
        assert name == "AcmePay"
        assert conf >= 0.8

    def test_merchant_pipe_processinghub(self):
        from analyzer import extract_merchant_name_from_chat
        name, conf = extract_merchant_name_from_chat("TestMerch | ProcessingHub")
        assert name == "TestMerch"
        assert conf >= 0.8

    def test_processinghub_x_merchant(self):
        from analyzer import extract_merchant_name_from_chat
        name, conf = extract_merchant_name_from_chat("ProcessingHub x AcmePay")
        assert name == "AcmePay"
        assert conf >= 0.8

    def test_empty_chat_name(self):
        from analyzer import extract_merchant_name_from_chat
        name, conf = extract_merchant_name_from_chat("")
        assert name is None
        assert conf == 0.0

    def test_no_pattern_match(self):
        from analyzer import extract_merchant_name_from_chat
        name, conf = extract_merchant_name_from_chat("Random chat name")
        assert name is None


class TestExtractMerchantNameFromText:
    def test_merchant_keyword(self):
        from analyzer import extract_merchant_name_from_text
        name, conf = extract_merchant_name_from_text("мерчант TestPay подключен")
        assert name == "TestPay"
        assert conf > 0

    def test_no_merchant(self):
        from analyzer import extract_merchant_name_from_text
        name, conf = extract_merchant_name_from_text("просто обычное сообщение")
        assert name is None


class TestDetectStatusByRules:
    def test_disconnected(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("мерчант отключен с утра")
        assert status == "disconnected"
        assert conf >= 0.9

    def test_problem(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("у них проблемы с API")
        assert status == "problem"
        assert conf >= 0.8

    def test_active(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("сеттлмент прошёл, всё работает")
        assert status == "active"
        assert conf >= 0.8

    def test_testing(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("сейчас тестируем подключение")
        assert status == "testing"
        assert conf >= 0.8

    def test_integration(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("подключаем мерчанта к api")
        assert status == "integration"
        assert conf >= 0.8

    def test_paused(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("мерч на паузе пока")
        assert status == "paused"
        assert conf >= 0.8

    def test_negotiation(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("обсуждаем условия работы")
        assert status == "negotiation"
        assert conf >= 0.5

    def test_no_status(self):
        from analyzer import detect_status_by_rules
        status, conf, reason = detect_status_by_rules("привет, как дела")
        assert status is None


class TestExtractRates:
    def test_rate_with_keyword(self):
        from analyzer import extract_rates
        rates = extract_rates("ставка 5.5%")
        assert rates["current_rate"] == 5.5

    def test_rate_before_keyword(self):
        from analyzer import extract_rates
        rates = extract_rates("6% ставка")
        assert rates["current_rate"] == 6.0

    def test_min_rate(self):
        from analyzer import extract_rates
        rates = extract_rates("минимум 3.5%")
        assert rates["min_rate"] == 3.5

    def test_no_rates(self):
        from analyzer import extract_rates
        rates = extract_rates("без ставок вообще")
        assert rates["current_rate"] is None
        assert rates["min_rate"] is None

    def test_unreasonable_rate_ignored(self):
        from analyzer import extract_rates
        rates = extract_rates("ставка 75%")
        assert rates["current_rate"] is None


class TestExtractConversion:
    def test_conversion_keyword(self):
        from analyzer import extract_conversion
        assert extract_conversion("конверсия 45%") == 45.0

    def test_conversion_approve(self):
        from analyzer import extract_conversion
        assert extract_conversion("апрув 30.5%") == 30.5

    def test_no_conversion(self):
        from analyzer import extract_conversion
        assert extract_conversion("ничего тут нет") is None


class TestExtractPaymentMethods:
    def test_sbp(self):
        from analyzer import extract_payment_methods
        methods = extract_payment_methods("принимаем через сбп")
        assert "sbp" in methods

    def test_c2c(self):
        from analyzer import extract_payment_methods
        methods = extract_payment_methods("карта-карта и p2p")
        assert "c2c" in methods

    def test_multiple(self):
        from analyzer import extract_payment_methods
        methods = extract_payment_methods("сбп и тинькофф работают")
        assert "sbp" in methods
        assert "tinkoff" in methods

    def test_none(self):
        from analyzer import extract_payment_methods
        methods = extract_payment_methods("просто текст")
        assert methods == []


class TestRuleBasedAnalyze:
    def test_full_analysis(self):
        from analyzer import rule_based_analyze
        result = rule_based_analyze(
            "ставка 5% конверсия 40% через сбп",
            chat_name="AcmePay x ProcessingHub"
        )
        assert result.merchant_name == "AcmePay"
        assert result.current_rate == 5.0
        assert result.conversion == 40.0
        assert "sbp" in result.payment_methods
        assert result.decided_by == "rule"
        assert result.confidence >= 0.8

    def test_status_detection(self):
        from analyzer import rule_based_analyze
        result = rule_based_analyze("мерчант отключили вчера")
        assert result.status == "disconnected"

    def test_empty_text(self):
        from analyzer import rule_based_analyze
        result = rule_based_analyze("")
        assert result.status is None
        assert result.confidence == 0.0


class TestQuickAnalyze:
    def test_merchant_info_detected(self):
        from analyzer import quick_analyze
        result = quick_analyze("ставка 5% у мерчанта")
        assert result["has_merchant_info"] is True

    def test_too_short(self):
        from analyzer import quick_analyze
        result = quick_analyze("hi")
        assert result["has_merchant_info"] is False
        assert result["type"] == "too_short"

    def test_no_merchant_info(self):
        from analyzer import quick_analyze
        result = quick_analyze("давайте обсудим погоду завтра")
        assert result["has_merchant_info"] is False


class TestAnalysisResult:
    def test_to_dict(self):
        from analyzer import AnalysisResult
        r = AnalysisResult(merchant_name="Test", status="active", confidence=0.9)
        d = r.to_dict()
        assert d["merchant_name"] == "Test"
        assert d["status"] == "active"
        assert d["confidence"] == 0.9


class TestLegacyCompat:
    def test_classify_message_type(self):
        from analyzer import classify_message_type
        assert classify_message_type("проблемы с оплатой") == "status_problem"
        assert classify_message_type("привет") == "general"

    def test_extract_numbers(self):
        from analyzer import extract_numbers
        result = extract_numbers("ставка 5% конверсия 40%")
        assert result["rate"] == 5.0
        assert result["conversion"] == 40.0
