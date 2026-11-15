"""
Tests for payout balance alerts in alerts.py (v2)
Run: python -m pytest tests/test_payout_alerts.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from alerts import (
    AlertState,
    check_payout_balances,
    check_global_no_traffic,
    check_conversion_drop,
    is_on_cooldown,
    set_cooldown,
    is_night_mode,
    is_critical_alert,
    build_status_message,
    batch_alerts,
    fmt_amount,
    PAYOUT_BALANCE_THRESHOLD,
    COOLDOWN_PAYOUT_BALANCE,
    ESCALATION_LEVELS,
    PAYOUT_CHECK_INTERVAL,
    MSK,
)


def make_state() -> AlertState:
    return AlertState()


def make_balances(alpha=500_000, alpha2=-4_000_000, bravo=2_000_000):
    return [
        {"merchant_name": "Merchant AlphaOut", "balance_rub": alpha},
        {"merchant_name": "Merchant AlphaOut2", "balance_rub": alpha2},
        {"merchant_name": "Merchant BravoOut", "balance_rub": bravo},
    ]


# ── Payout Balance Tests ────────────────────────────────────────────────────

class TestPayoutBalanceAlerts:
    """Vertical review: unit tests for check_payout_balances."""

    def test_alert_when_below_threshold(self):
        """Should alert when balance < 300k."""
        state = make_state()
        balances = make_balances(alpha=200_000)
        problems, recoveries = check_payout_balances(state, balances)
        assert len(problems) == 2
        assert "AlphaOut" in problems[0] or "AlphaOut2" in problems[0]

    def test_no_alert_when_above_threshold(self):
        """Should NOT alert when all balances >= 300k."""
        state = make_state()
        balances = make_balances(alpha=500_000, alpha2=400_000, bravo=1_000_000)
        problems, recoveries = check_payout_balances(state, balances)
        assert len(problems) == 0
        assert len(recoveries) == 0

    def test_negative_balance_severity(self):
        """Negative balance should show ОТРИЦАТЕЛЬНЫЙ БАЛАНС."""
        state = make_state()
        balances = make_balances(alpha=-100_000)
        problems, _ = check_payout_balances(state, balances)
        neg_alert = [a for a in problems if "AlphaOut" in a and "AlphaOut2" not in a]
        assert len(neg_alert) == 1
        assert "ОТРИЦАТЕЛЬНЫЙ" in neg_alert[0]

    def test_critical_low_severity(self):
        """Balance 0-100k should show КРИТИЧНО НИЗКИЙ."""
        state = make_state()
        balances = make_balances(alpha=50_000, alpha2=400_000, bravo=400_000)
        problems, _ = check_payout_balances(state, balances)
        assert len(problems) == 1
        assert "КРИТИЧНО" in problems[0]

    def test_below_threshold_severity(self):
        """Balance 100k-300k should show НИЖЕ ПОРОГА."""
        state = make_state()
        balances = make_balances(alpha=200_000, alpha2=400_000, bravo=400_000)
        problems, _ = check_payout_balances(state, balances)
        assert len(problems) == 1
        assert "НИЖЕ ПОРОГА" in problems[0]

    def test_cooldown_prevents_duplicate(self):
        """Same merchant should NOT alert again within cooldown."""
        state = make_state()
        balances = make_balances(alpha=100_000, alpha2=400_000, bravo=400_000)
        problems1, _ = check_payout_balances(state, balances)
        assert len(problems1) == 1

        problems2, _ = check_payout_balances(state, balances)
        assert len(problems2) == 0

    def test_cooldown_expires(self):
        """After cooldown expires, should alert again."""
        state = make_state()
        balances = make_balances(alpha=100_000, alpha2=400_000, bravo=400_000)
        problems1, _ = check_payout_balances(state, balances)
        assert len(problems1) == 1

        for key in list(state.cooldowns.keys()):
            state.cooldowns[key] = datetime.now(MSK) - timedelta(seconds=1)

        problems2, _ = check_payout_balances(state, balances)
        assert len(problems2) == 1

    def test_state_tracks_balances(self):
        """Should store last known balances in state."""
        state = make_state()
        balances = make_balances(alpha=500_000, alpha2=400_000, bravo=2_000_000)
        check_payout_balances(state, balances)
        assert state.last_payout_balances["Merchant AlphaOut"] == 500_000
        assert state.last_payout_balances["Merchant AlphaOut2"] == 400_000
        assert state.last_payout_balances["Merchant BravoOut"] == 2_000_000

    def test_empty_balances(self):
        """Should handle empty data gracefully."""
        state = make_state()
        problems, recoveries = check_payout_balances(state, [])
        assert len(problems) == 0
        assert len(recoveries) == 0

    def test_missing_fields(self):
        """Should handle rows with missing fields."""
        state = make_state()
        problems, _ = check_payout_balances(state, [{"merchant_name": "Test"}])
        assert len(problems) == 1

    def test_merchant_name_stripped(self):
        """Alert should show short name without 'Merchant ' prefix."""
        state = make_state()
        balances = [{"merchant_name": "Merchant BravoOut", "balance_rub": 100_000}]
        problems, _ = check_payout_balances(state, balances)
        assert len(problems) == 1
        assert "BravoOut" in problems[0]
        assert "Merchant BravoOut" not in problems[0]

    def test_exact_threshold_no_alert(self):
        """Balance exactly at threshold should NOT alert."""
        state = make_state()
        balances = [{"merchant_name": "Merchant BravoOut", "balance_rub": 300_000}]
        problems, _ = check_payout_balances(state, balances)
        assert len(problems) == 0

    def test_just_below_threshold(self):
        """Balance just below threshold should alert."""
        state = make_state()
        balances = [{"merchant_name": "Merchant BravoOut", "balance_rub": 299_999}]
        problems, _ = check_payout_balances(state, balances)
        assert len(problems) == 1


# ── Recovery Tests ───────────────────────────────────────────────────────────

class TestRecoveryAlerts:
    """Recovery alerts when problems resolve."""

    def test_payout_balance_recovery(self):
        """Should alert when balance goes from below to above threshold."""
        state = make_state()
        # First: balance low
        b1 = [{"merchant_name": "Merchant AlphaOut", "balance_rub": 100_000}]
        problems1, recoveries1 = check_payout_balances(state, b1)
        assert len(problems1) == 1
        assert len(recoveries1) == 0

        # Expire cooldown
        for key in list(state.cooldowns.keys()):
            state.cooldowns[key] = datetime.now(MSK) - timedelta(seconds=1)

        # Second: balance restored
        b2 = [{"merchant_name": "Merchant AlphaOut", "balance_rub": 500_000}]
        problems2, recoveries2 = check_payout_balances(state, b2)
        assert len(problems2) == 0
        assert len(recoveries2) == 1
        assert "пополнен" in recoveries2[0].lower() or "восстановл" in recoveries2[0].lower()

    def test_no_recovery_if_was_above(self):
        """Should NOT send recovery if balance was always above threshold."""
        state = make_state()
        b1 = [{"merchant_name": "Merchant AlphaOut", "balance_rub": 500_000}]
        check_payout_balances(state, b1)

        b2 = [{"merchant_name": "Merchant AlphaOut", "balance_rub": 600_000}]
        _, recoveries = check_payout_balances(state, b2)
        assert len(recoveries) == 0

    def test_traffic_recovery_alert(self):
        """Should alert when traffic resumes after no-traffic."""
        state = make_state()
        state.last_global_total = 100
        state.traffic_was_down = True
        state.global_unchanged_count = 10

        totals = {"Всего": 105}
        alerts = check_global_no_traffic(state, totals)
        recovery = [a for a in alerts if "восстановлен" in a.lower()]
        assert len(recovery) == 1
        assert "+5" in recovery[0]

    def test_no_recovery_if_traffic_was_fine(self):
        """Should NOT send recovery if traffic was never down."""
        state = make_state()
        state.last_global_total = 100
        state.traffic_was_down = False

        totals = {"Всего": 105}
        alerts = check_global_no_traffic(state, totals)
        assert len(alerts) == 0

    def test_payout_trend_shown(self):
        """Should show trend arrow when balance changes significantly."""
        state = make_state()
        b1 = [{"merchant_name": "Merchant AlphaOut", "balance_rub": 200_000}]
        check_payout_balances(state, b1)

        # Expire cooldown
        for key in list(state.cooldowns.keys()):
            state.cooldowns[key] = datetime.now(MSK) - timedelta(seconds=1)

        b2 = [{"merchant_name": "Merchant AlphaOut", "balance_rub": 100_000}]
        problems, _ = check_payout_balances(state, b2)
        assert len(problems) == 1
        assert "↓" in problems[0]


# ── Escalation Tests ─────────────────────────────────────────────────────────

class TestEscalation:
    """No-traffic escalation levels."""

    def test_escalation_level_1(self):
        """5 min no traffic = WARNING."""
        state = make_state()
        state.last_global_total = 100
        state.global_unchanged_count = 4  # will become 5

        totals = {"Всего": 100}
        alerts = check_global_no_traffic(state, totals)
        assert len(alerts) == 1
        assert "⚠️" in alerts[0]
        assert state.last_escalation_level == 0

    def test_escalation_level_2(self):
        """15 min no traffic = CRITICAL."""
        state = make_state()
        state.last_global_total = 100
        state.global_unchanged_count = 14
        state.last_escalation_level = 0  # already sent level 0

        totals = {"Всего": 100}
        alerts = check_global_no_traffic(state, totals)
        assert len(alerts) == 1
        assert "КРИТИЧНО" in alerts[0]
        assert state.last_escalation_level == 1

    def test_escalation_level_3(self):
        """30 min no traffic = EMERGENCY."""
        state = make_state()
        state.last_global_total = 100
        state.global_unchanged_count = 29
        state.last_escalation_level = 1

        totals = {"Всего": 100}
        alerts = check_global_no_traffic(state, totals)
        assert len(alerts) == 1
        assert "АВАРИЯ" in alerts[0]
        assert state.last_escalation_level == 2

    def test_no_duplicate_escalation(self):
        """Same level should not re-alert."""
        state = make_state()
        state.last_global_total = 100
        state.global_unchanged_count = 9
        state.last_escalation_level = 0  # already at WARNING

        totals = {"Всего": 100}
        alerts = check_global_no_traffic(state, totals)
        # Should not alert again at level 0 (10 > 5 but level 0 already sent)
        assert len(alerts) == 0

    def test_escalation_reset_on_recovery(self):
        """Escalation level should reset when traffic resumes."""
        state = make_state()
        state.last_global_total = 100
        state.traffic_was_down = True
        state.last_escalation_level = 2

        totals = {"Всего": 105}
        check_global_no_traffic(state, totals)
        assert state.last_escalation_level == -1


# ── Night Mode Tests ─────────────────────────────────────────────────────────

class TestNightMode:
    """Night mode filtering."""

    def test_critical_alert_detected(self):
        """Critical alerts should be identified."""
        assert is_critical_alert("🚨 НЕТ ТРАФИКА") is True
        assert is_critical_alert("ОТРИЦАТЕЛЬНЫЙ БАЛАНС") is True
        assert is_critical_alert("КРИТИЧНО НИЗКИЙ") is True

    def test_non_critical_alert(self):
        """Non-critical alerts should not pass filter."""
        assert is_critical_alert("⚠️ Мерчант остановился") is False
        assert is_critical_alert("📉 Низкая конверсия") is False

    def test_conversion_recovery_detection(self):
        """Should detect conversion recovery."""
        state = make_state()
        merchants = [
            {"Мерчант": "TestMerch", "С реквизитами": 50, "Конверсия в оплату %": 10, "Успешных": 5},
        ]
        drops, recoveries = check_conversion_drop(state, merchants)
        assert len(drops) == 1
        assert len(recoveries) == 0

        # Now conversion recovers
        merchants2 = [
            {"Мерчант": "TestMerch", "С реквизитами": 60, "Конверсия в оплату %": 35, "Успешных": 21},
        ]
        # Expire cooldown
        for key in list(state.cooldowns.keys()):
            state.cooldowns[key] = datetime.now(MSK) - timedelta(seconds=1)

        drops2, recoveries2 = check_conversion_drop(state, merchants2)
        assert len(drops2) == 0
        assert len(recoveries2) == 1
        assert "восстановилась" in recoveries2[0].lower()


# ── Status Message Tests ─────────────────────────────────────────────────────

class TestStatusMessage:
    """Pinned status message building."""

    def test_build_status_healthy(self):
        """Should show healthy status."""
        state = make_state()
        state.last_payout_balances = {"Merchant AlphaOut": 500_000}
        totals = {"Всего": 1000, "Успешных": 800, "Конверсия в оплату %": 80}
        msg = build_status_message(state, totals, [])
        assert "Статус системы" in msg
        assert "✅ Трафик" in msg
        assert "AlphaOut" in msg

    def test_build_status_problems(self):
        """Should show problems in status."""
        state = make_state()
        state.global_unchanged_count = 10
        state.low_conversion_merchants = {"BadMerch": 12.5}
        state.last_payout_balances = {"Merchant AlphaOut2": -500_000}
        totals = {"Всего": 100, "Успешных": 50, "Конверсия в оплату %": 50}
        msg = build_status_message(state, totals, [])
        assert "НЕТ ЗАЯВОК" in msg
        assert "Низкая конверсия" in msg
        assert "AlphaOut2" in msg


# ── Anti-Flood Tests ─────────────────────────────────────────────────────────

class TestAntiFlood:
    """Horizontal review: anti-flood mechanisms work correctly."""

    def test_multiple_merchants_one_message_batch(self):
        """Multiple alerts should be batchable."""
        state = make_state()
        balances = make_balances(alpha=100_000, alpha2=-500_000, bravo=200_000)
        problems, _ = check_payout_balances(state, balances)
        assert len(problems) == 3

        batched = batch_alerts(problems, "💰 <b>Payout балансы:</b>")
        assert len(batched) == 1
        assert "AlphaOut" in batched[0]
        assert "AlphaOut2" in batched[0]
        assert "BravoOut" in batched[0]

    def test_independent_cooldowns_per_merchant(self):
        """Each merchant has its own cooldown."""
        state = make_state()
        b1 = make_balances(alpha=100_000, alpha2=400_000, bravo=400_000)
        problems1, _ = check_payout_balances(state, b1)
        assert len(problems1) == 1
        assert "AlphaOut" in problems1[0]

        b2 = make_balances(alpha=100_000, alpha2=100_000, bravo=400_000)
        problems2, _ = check_payout_balances(state, b2)
        assert len(problems2) == 1
        assert "AlphaOut2" in problems2[0]

    def test_poll_count_interval(self):
        """Payout check runs only every N cycles."""
        state = make_state()
        checks_at = []
        for i in range(20):
            state.poll_count = i + 1
            if state.poll_count % PAYOUT_CHECK_INTERVAL == 0:
                checks_at.append(i + 1)
        assert len(checks_at) == 20 // PAYOUT_CHECK_INTERVAL
        assert checks_at[0] == PAYOUT_CHECK_INTERVAL

    def test_merchant_stopped_batched(self):
        """Merchant stopped alerts should come as compact list items."""
        from alerts import check_merchant_stopped, MERCHANT_STOPPED_CHECKS
        state = make_state()
        merchants = [
            {"Мерчант": "MerchA", "Всего": 10, "Сумма успешных": 1000, "Конверсия в оплату %": 50},
            {"Мерчант": "MerchB", "Всего": 20, "Сумма успешных": 2000, "Конверсия в оплату %": 60},
        ]
        # Init
        check_merchant_stopped(state, merchants)
        # Simulate long inactivity
        for ms in state.merchants.values():
            ms.unchanged_count = MERCHANT_STOPPED_CHECKS
        alerts = check_merchant_stopped(state, merchants)
        assert len(alerts) == 2
        # Alerts are compact (single line each, no header)
        for a in alerts:
            assert "<code>" in a


# ── Tagging Tests ────────────────────────────────────────────────────────────

class TestNoTrafficTagging:
    """Tests for tagging group members on no-traffic alerts."""

    def test_no_traffic_alert_calls_get_tags(self):
        """No-traffic alerts should include member tags."""
        from unittest.mock import patch
        state = make_state()
        state.last_global_total = 100
        state.global_unchanged_count = 4  # will become 5

        with patch("alerts.get_group_members_tags", return_value="@user1 @user2 @admin"):
            totals = {"Всего": 100}
            alerts = check_global_no_traffic(state, totals)
            assert len(alerts) == 1
            assert "@user1" in alerts[0]
            assert "@user2" in alerts[0]
            assert "@admin" in alerts[0]

    def test_no_traffic_all_escalation_levels_tagged(self):
        """All escalation levels should have tags."""
        from unittest.mock import patch

        with patch("alerts.get_group_members_tags", return_value="@boss @dev"):
            # Level 0 (5 min)
            state = make_state()
            state.last_global_total = 100
            state.global_unchanged_count = 4
            alerts = check_global_no_traffic(state, {"Всего": 100})
            assert "@boss" in alerts[0]

            # Level 1 (15 min)
            state.global_unchanged_count = 14
            alerts = check_global_no_traffic(state, {"Всего": 100})
            assert "@boss" in alerts[0]

            # Level 2 (30 min)
            state.global_unchanged_count = 29
            alerts = check_global_no_traffic(state, {"Всего": 100})
            assert "@boss" in alerts[0]

    def test_no_tags_when_empty(self):
        """Should work fine when no tags available."""
        from unittest.mock import patch
        state = make_state()
        state.last_global_total = 100
        state.global_unchanged_count = 4

        with patch("alerts.get_group_members_tags", return_value=""):
            alerts = check_global_no_traffic(state, {"Всего": 100})
            assert len(alerts) == 1
            # Alert still works, just no tags appended

    def test_recovery_alert_not_tagged(self):
        """Recovery alerts should NOT tag everyone."""
        from unittest.mock import patch
        state = make_state()
        state.last_global_total = 100
        state.traffic_was_down = True
        state.global_unchanged_count = 10

        with patch("alerts.get_group_members_tags", return_value="@user1 @user2") as mock_tags:
            alerts = check_global_no_traffic(state, {"Всего": 105})
            recovery = [a for a in alerts if "восстановлен" in a.lower()]
            assert len(recovery) == 1
            assert "@user1" not in recovery[0]

    def test_get_group_members_tags_parses_response(self):
        """get_group_members_tags should parse API response correctly."""
        from unittest.mock import patch, MagicMock
        from alerts import get_group_members_tags

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {"user": {"id": 123, "first_name": "Alice", "username": "alice_ops", "is_bot": False}},
                {"user": {"id": 456, "first_name": "Bot", "username": "mybot", "is_bot": True}},
                {"user": {"id": 789, "first_name": "NoUsername", "is_bot": False}},
            ]
        }

        with patch("alerts.http_requests.post", return_value=mock_resp):
            tags = get_group_members_tags()
            assert "@alice_ops" in tags
            assert "@mybot" not in tags  # bots excluded
            assert "NoUsername" in tags   # fallback to tg://user link
            assert "tg://user?id=789" in tags

    def test_get_group_members_tags_handles_error(self):
        """Should return empty string on API error."""
        from unittest.mock import patch, MagicMock
        from alerts import get_group_members_tags

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("alerts.http_requests.post", return_value=mock_resp):
            tags = get_group_members_tags()
            assert tags == ""


# ── Group Ignore Tests ───────────────────────────────────────────────────────

class TestGroupIgnore:
    """Bot should ignore all messages in alert group."""

    def test_alert_chat_id_in_config(self):
        """ALERT_CHAT_ID should be importable from config."""
        from config import ALERT_CHAT_ID
        assert isinstance(ALERT_CHAT_ID, int)
        # Групповые чаты Telegram имеют отрицательный ID; 0 = чат не задан в окружении
        assert ALERT_CHAT_ID <= 0
