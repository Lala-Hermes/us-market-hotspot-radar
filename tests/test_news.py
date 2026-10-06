import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'


def record(text='Fed signals policy shift', published='2026-10-06T10:03:00-04:00', received='2026-10-06T10:04:00-04:00', source='jin10', precision='second', url='https://example.test/a'):
    return {'source': source, 'url': url, 'text': text, 'published_at': published,
            'received_at': received, 'timestamp_precision': precision}


def test_classifies_exact_window_and_prior_context():
    import radar_news
    payload = {'status': 'ok', 'items': [record(), record('Older context', '2026-10-06T09:30:00-04:00')]}
    result = radar_news.normalize(payload, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert [x['text'] for x in result['window_items']] == ['Fed signals policy shift']
    assert [x['text'] for x in result['context_items']] == ['Older context']


def test_rejects_bad_timing_and_minute_boundary_ambiguity():
    import radar_news
    items = [record('naive', '2026-10-06T10:03:00'),
             record('future', '2026-10-06T10:11:00-04:00'),
             record('late retrieval', '2026-10-06T10:03:00-04:00', '2026-10-06T10:02:00-04:00'),
             record('edge minute', '2026-10-06T10:00:00-04:00', precision='minute')]
    result = radar_news.normalize({'status': 'ok', 'items': items}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert result['window_items'] == []
    assert len(result['rejected']) == 4


def test_duplicate_text_merges_provenance_not_confirmation():
    import radar_news
    one = record()
    one['timestamp_evidence'] = 'visible DOM time + date attribute'
    two = record(source='futu', url='https://example.test/b')
    result = radar_news.normalize({'status': 'ok', 'items': [one, two]}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert len(result['window_items']) == 1
    assert result['window_items'][0]['timestamp_evidence'] == 'visible DOM time + date attribute'
    assert result['window_items'][0]['provenance_sources'] == ['jin10', 'futu']
    assert result['window_items'][0]['independent_confirmations'] == 1


def test_source_outage_is_partial_without_dropping_visible_source_records():
    import radar_news
    payload = {'items': [record()], 'sources': [{'source': 'futu', 'status': 'ok'}, {'source': 'jin10', 'status': 'partial', 'reason': 'login_required'}]}
    result = radar_news.normalize(payload, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert result['status'] == 'partial'
    assert result['window_items'][0]['source'] == 'jin10'
    assert result['sources'][1]['reason'] == 'login_required'


def test_cli_cannot_overwrite_any_saved_snapshot(tmp_path, monkeypatch):
    import radar_news
    monkeypatch.setattr(radar_news, 'STATE', tmp_path.resolve())
    snapshot = tmp_path / 'scans' / 'slot.json'
    snapshot.parent.mkdir()
    original = '{"slot":"x","window_start":"2026-10-06T10:00:00-04:00","window_end":"2026-10-06T10:10:00-04:00"}'
    snapshot.write_text(original, encoding='utf-8')
    target = snapshot.parent / 'other.json'
    target.write_text('immutable evidence', encoding='utf-8')
    inp = tmp_path / 'input.json'
    inp.write_text(json.dumps({'status':'ok','items':[]}), encoding='utf-8')
    assert radar_news.main(['--snapshot',str(snapshot),'--input',str(inp),'--output',str(target)]) == 2
    assert target.read_text(encoding='utf-8') == 'immutable evidence'


def test_cli_requires_state_paths_preserves_snapshot_and_records_slot(tmp_path, monkeypatch):
    import radar_news
    monkeypatch.setattr(radar_news, 'STATE', tmp_path.resolve())
    state = tmp_path
    snap = state / 'test-news-snapshot.json'
    inp = state / 'test-news-input.json'
    out = state / 'news-output-test.json'
    original = {'slot': '2026-10-06T10:10:00-04:00', 'window_start': '2026-10-06T10:00:00-04:00', 'window_end': '2026-10-06T10:10:00-04:00'}
    try:
        snap.write_text(json.dumps(original), encoding='utf-8')
        inp.write_text(json.dumps({'status': 'partial', 'items': [record()]}), encoding='utf-8')
        assert radar_news.main(['--snapshot', str(snap), '--input', str(inp), '--output', str(out)]) == 0
        result = json.loads(out.read_text(encoding='utf-8'))
        assert result['snapshot_slot'] == original['slot']
        assert result['status'] == 'partial'
        assert json.loads(snap.read_text(encoding='utf-8')) == original
    finally:
        for path in (snap, inp, out):
            path.unlink(missing_ok=True)


def test_missing_items_is_not_successful_zero_news():
    import radar_news
    with pytest.raises(ValueError, match='items'):
        radar_news.normalize({'status': 'ok', 'sources': [{'source': 'futu', 'status': 'ok'}]}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')


def test_malformed_evidence_is_not_successful_zero_news():
    import radar_news
    result = radar_news.normalize({'status': 'ok', 'items': [record(published='bad')]}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert result['status'] != 'ok'


def test_explicit_ok_cannot_hide_source_failure():
    import radar_news
    result = radar_news.normalize({'status': 'ok', 'items': [], 'sources': [{'source': 'jin10', 'status': 'blocked'}]}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert result['status'] == 'blocked'
    with pytest.raises(ValueError):
        radar_news.normalize({'status': 'ok', 'items': [], 'sources': ['bad']}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')


def test_unsafe_links_are_rejected():
    import radar_news
    result = radar_news.normalize({'status': 'ok', 'items': [record(url='javascript:alert(1)')]}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert result['window_items'] == []
    assert result['status'] != 'ok'


def test_context_duplicates_merge_but_repeated_text_later_remains():
    import radar_news
    items = [record('Older context', '2026-10-06T09:30:00-04:00'), record('Older context', '2026-10-06T09:30:00-04:00', source='futu'), record(), record(published='2026-10-06T10:06:00-04:00', received='2026-10-06T10:07:00-04:00')]
    result = radar_news.normalize({'status': 'ok', 'items': items}, '2026-10-06T10:00:00-04:00', '2026-10-06T10:10:00-04:00')
    assert len(result['context_items']) == 1
    assert len(result['window_items']) == 2
