"""Smoke tests — verify all handlers import without error."""
import pytest


def test_import_start():
    from bot.handlers import start
    assert hasattr(start, "router")


def test_import_glossary():
    from bot.handlers import glossary
    assert hasattr(glossary, "router")


def test_import_countries():
    from bot.handlers import countries
    assert hasattr(countries, "router")


def test_import_calendar():
    from bot.handlers import calendar_h
    assert hasattr(calendar_h, "router")


def test_import_acquirers():
    from bot.handlers import acquirers
    assert hasattr(acquirers, "router")


def test_import_bin_checker():
    from bot.handlers import bin_checker
    assert hasattr(bin_checker, "router")


def test_import_news():
    from bot.handlers import news
    assert hasattr(news, "router")


def test_import_platforms():
    from bot.handlers import platforms
    assert hasattr(platforms, "router")


def test_import_traffic():
    from bot.handlers import traffic
    assert hasattr(traffic, "router")


def test_import_aml():
    from bot.handlers import aml
    assert hasattr(aml, "router")


def test_import_subscription():
    from bot.handlers import subscription
    assert hasattr(subscription, "router")


def test_import_admin():
    from bot.handlers import admin
    assert hasattr(admin, "router")


def test_import_main():
    from bot.main import create_bot, create_dispatcher
    assert callable(create_bot)
    assert callable(create_dispatcher)


def test_keyboards():
    from bot.keyboards.inline import (
        main_menu_kb,
        glossary_categories_kb,
        calendar_month_kb,
        acquirer_filter_kb,
        platform_type_kb,
        traffic_vertical_kb,
        subscription_kb,
        back_to_menu_kb,
    )
    assert main_menu_kb() is not None
    assert calendar_month_kb() is not None
    assert acquirer_filter_kb() is not None
    assert platform_type_kb() is not None
    assert traffic_vertical_kb() is not None
    assert subscription_kb() is not None
    assert back_to_menu_kb() is not None


def test_cache():
    from bot.services.cache import TTLCache
    c = TTLCache(default_ttl=60)
    c.set("key", "value")
    assert c.get("key") == "value"
    c.delete("key")
    assert c.get("key") is None


def test_schemas():
    from bot.models.schemas import User, Subscription, GlossaryTerm
    u = User(user_id=123)
    assert u.user_id == 123
    t = GlossaryTerm(term="Test", term_ru="Тест", category="tech", definition="Def")
    assert t.term == "Test"
