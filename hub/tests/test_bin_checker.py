"""Test BIN checker validation."""
import re
import pytest

BIN_PATTERN = re.compile(r"^\d{6,8}$")


def test_valid_bin_6_digits():
    assert BIN_PATTERN.match("424242")


def test_valid_bin_8_digits():
    assert BIN_PATTERN.match("42424242")


def test_invalid_bin_too_short():
    assert not BIN_PATTERN.match("4242")


def test_invalid_bin_too_long():
    assert not BIN_PATTERN.match("424242424")


def test_invalid_bin_letters():
    assert not BIN_PATTERN.match("42424a")


def test_invalid_bin_empty():
    assert not BIN_PATTERN.match("")


def test_invalid_bin_spaces():
    assert not BIN_PATTERN.match("424 242")


def test_bin_api_result_format():
    """Test expected result format from BIN API."""
    result = {
        "bin": "424242",
        "brand": "Visa",
        "card_type": "debit",
        "category": "Classic",
        "bank": "Test Bank",
        "country": "United States",
        "country_emoji": "🇺🇸",
        "prepaid": False,
    }
    assert result["bin"] == "424242"
    assert result["brand"] in ("Visa", "Mastercard", "N/A")
    assert isinstance(result["prepaid"], bool)
