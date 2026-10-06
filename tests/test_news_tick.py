import json
from datetime import datetime

import radar


def test_healthy_quiet_tick_requests_agent_news_collection(monkeypatch, capsys):
    info = {'slot': '2026-10-07T00:10:00+08:00', 'window_start': '2026-10-06T12:00:00-04:00', 'window_end': '2026-10-06T12:10:00-04:00'}
    monkeypatch.setattr(radar, 'gate', lambda _now: info)
    monkeypatch.setattr(radar, 'scan', lambda _info: {'status': 'ok', 'candidates': [], 'cross_signals': [], 'snapshot_path': 'immutable.json'})
    monkeypatch.setattr(radar, 'STATE', radar.ROOT / '.state')
    monkeypatch.setattr(radar, 'publish', lambda *_args: {'verified': True})
    monkeypatch.setattr(radar, '_atomic_bytes', lambda *_args: None)
    assert radar.tick(datetime.fromisoformat(info['window_end'])) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['wakeAgent'] is True
    assert payload['news_required'] is True
    assert payload['news_window_start'] == info['window_start']
    assert payload['news_window_end'] == info['window_end']


def test_partial_quiet_tick_requests_news_agent(monkeypatch, capsys):
    info = {'slot': '2026-10-07T00:10:00+08:00', 'window_start': '2026-10-06T12:00:00-04:00', 'window_end': '2026-10-06T12:10:00-04:00'}
    monkeypatch.setattr(radar, 'gate', lambda _now: info)
    monkeypatch.setattr(radar, 'scan', lambda _info: {'status': 'partial', 'candidates': [], 'cross_signals': [], 'snapshot_path': 'immutable.json'})
    monkeypatch.setattr(radar, 'publish', lambda *_args: {'verified': True})
    monkeypatch.setattr(radar, '_atomic_bytes', lambda *_args: None)
    assert radar.tick(datetime.fromisoformat(info['window_end'])) == 0
    assert json.loads(capsys.readouterr().out)['news_required'] is True
