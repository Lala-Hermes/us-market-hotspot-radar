from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_news_first_without_price_gate_and_mcp_primary():
    prompt = (ROOT / 'prompts/radar.md').read_text(encoding='utf-8')
    assert prompt.index('## 新聞優先') < prompt.index('## 行情核對')
    for requirement in ('list_flash', 'next_cursor', '整體市場', '板塊', '個股', '未出現價格反應', '不能因價格未達門檻而刪除新聞'):
        assert requirement in prompt


def test_jin10_mcp_page_maps_source_timestamps_and_more_flag():
    from radar_jin10 import parse_page
    items, cursor, more = parse_page({'data': {'has_more': True, 'next_cursor': 'opaque', 'items': [{'content': 'A flash', 'time': '2026-10-07T23:55:54+08:00', 'url': 'https://flash.jin10.com/detail/1'}]}}, '2026-10-08T00:01:00+08:00')
    assert items[0]['published_at'] == '2026-10-07T23:55:54+08:00'
    assert items[0]['source'] == 'jin10_mcp'
    assert cursor == 'opaque' and more


@pytest.mark.parametrize('payload', [{}, {'data': {'items': []}}, {'data': {'items': 'bad', 'has_more': False}}])
def test_malformed_page_never_means_no_news(payload):
    from radar_jin10 import parse_page
    with pytest.raises(ValueError):
        parse_page(payload, '2026-10-08T00:01:00+08:00')


def _row(second, url=None):
    return {'content': 'flash', 'time': f'2026-10-08T10:00:{second:02d}+08:00',
            'url': url or f'https://flash.jin10.com/detail/{second}'}


def test_validate_pages_enforces_order_forward_progress_and_exact_uniqueness():
    from radar_jin10 import validate_page_records
    newer = [{'published_at': '2026-10-08T10:00:02+08:00', 'url': 'https://x.test/2'}]
    older = [{'published_at': '2026-10-08T10:00:01+08:00', 'url': 'https://x.test/1'}]
    assert validate_page_records(newer, None, set())
    seen = {('2026-10-08T10:00:02+08:00', 'https://x.test/2')}
    assert validate_page_records(older, '2026-10-08T10:00:02+08:00', seen)
    newer_again = [{'published_at': '2026-10-08T10:00:03+08:00', 'url': 'https://x.test/3'}]
    assert not validate_page_records(newer_again, '2026-10-08T10:00:02+08:00', seen)
    assert not validate_page_records(list(reversed(newer + older)), None, set())
    assert not validate_page_records(newer, None, set(newer and [(newer[0]['published_at'], newer[0]['url'])]))


def test_safe_atomic_writer_rejects_symlinks_and_cleans_temporary_files(tmp_path):
    import json
    from radar_jin10 import write_json_atomic
    state = tmp_path / '.state'
    state.mkdir()
    target = state / 'news-input-a.json'
    write_json_atomic(target, {'ok': True}, state)
    assert json.loads(target.read_text(encoding='utf-8')) == {'ok': True}
    assert list(state.iterdir()) == [target]
    link = state / 'news-input-link.json'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError):
        write_json_atomic(link, {'bad': True}, state)
    assert json.loads(target.read_text(encoding='utf-8')) == {'ok': True}
    assert sorted(p.name for p in state.iterdir()) == ['news-input-a.json', 'news-input-link.json']


def test_coverage_uses_actual_snapshot_start_not_assumed_ten_minutes():
    from radar_jin10 import coverage_complete
    assert coverage_complete('2026-10-08T09:05:00+08:00', '2026-10-08T10:10:00+08:00',
                             '2026-10-08T10:05:00+08:00', '2026-10-08T10:10:00+08:00', False)


def test_coverage_requires_cutoff_and_newest_window_or_exhaustion():
    from radar_jin10 import coverage_complete
    cutoff, start, end = '2026-10-08T09:00:00+08:00', '2026-10-08T10:00:00+08:00', '2026-10-08T10:10:00+08:00'
    assert coverage_complete('2026-10-08T09:00:00+08:00', end, start, end, False)
    assert coverage_complete('2026-10-08T08:00:00+08:00', '2026-10-08T10:00:00+08:00', start, end, True)
    assert not coverage_complete(cutoff, '2026-10-08T10:00:00+08:00', start, end, False)
    assert not coverage_complete('2026-10-08T09:01:00+08:00', end, start, end, True)


def test_pagecap_and_exhaustion_reasons_are_not_complete_coverage():
    from radar_jin10 import coverage_complete
    assert not coverage_complete('2026-10-08T09:30:00+08:00', '2026-10-08T10:00:00+08:00',
                                 '2026-10-08T10:00:00+08:00', '2026-10-08T10:10:00+08:00', False)
    assert not coverage_complete('2026-10-08T09:30:00+08:00', '2026-10-08T10:00:00+08:00',
                                 '2026-10-08T10:00:00+08:00', '2026-10-08T10:10:00+08:00', True)
