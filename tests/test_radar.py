from datetime import datetime
from zoneinfo import ZoneInfo

import radar

ET = ZoneInfo("America/New_York")


def test_gate_starts_at_fixed_taipei_2120_and_emits_slot():
    # Oct 5 21:20 Taipei = Oct 5 09:20 ET (DST)
    result = radar.gate(datetime.fromisoformat("2026-10-05T09:20:00-04:00"))
    assert result["active"] is True
    assert result["slot"] == "2026-10-05T21:20:00+08:00"


def test_gate_idle_on_weekend():
    assert radar.gate(datetime.fromisoformat("2026-10-03T10:00:00-04:00")) == "IDLE"


def test_gate_idle_on_holiday():
    assert radar.gate(datetime.fromisoformat("2026-11-26T21:30:00+08:00")) == "IDLE"


def test_gate_uses_previous_trade_date_after_taipei_midnight():
    result = radar.gate(datetime.fromisoformat("2026-10-06T01:20:00+08:00"))
    assert result["trading_date"] == "2026-10-05"
    assert result["slot"] == "2026-10-06T01:20:00+08:00"


def test_diagnostic_candles_exclude_unfinished_and_count_real_trades():
    candles = [
        {"time": "2026-10-05 09:31:00", "close": 10, "volume": 100},
        {"time": "2026-10-05 09:32:00", "close": 11, "volume": 100},
    ]
    result = radar.completed_window(candles, datetime.fromisoformat("2026-10-05T09:32:00-04:00"))
    assert len(result) == 1


def test_append_is_slot_idempotent():
    content = "# report\n"
    first = radar.append_slot(content, "09:30", "### item\n")
    assert radar.append_slot(first, "09:30", "### item\n") == first


def test_tick_offhours_skips_futu(monkeypatch, capsys):
    monkeypatch.setattr(radar, "scan", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("scan called")))
    assert radar.tick(datetime.fromisoformat("2026-10-05T08:00:00-04:00")) == 0
    assert '"wakeAgent":false' in capsys.readouterr().out
