"""Normalize externally collected, timestamped macro-news evidence."""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = (ROOT / '.state').resolve()
MAX_INPUT_BYTES = 2_000_000
MAX_ITEMS = 500


def _date(value):
    if not isinstance(value, str):
        raise ValueError('timestamp missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timestamp must be timezone-aware ISO-8601')
    return parsed


def _normalize_text(text):
    text = unicodedata.normalize('NFKC', str(text)).casefold()
    return ' '.join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def normalize(payload, start, end):
    start, end = _date(start), _date(end)
    if end <= start:
        raise ValueError('snapshot window end must follow start')
    if not isinstance(payload, dict):
        raise ValueError('payload must be an object')
    status = payload.get('status')
    source_states = payload.get('sources', [])
    allowed = {'ok', 'partial', 'blocked', 'failed', 'unavailable'}
    if not isinstance(source_states, list) or any(not isinstance(s, dict) or not isinstance(s.get('source'), str) or not s.get('source') or s.get('status') not in allowed for s in source_states):
        raise ValueError('invalid source states')
    if source_states:
        states = {entry['status'] for entry in source_states}
        derived = 'ok' if states == {'ok'} else ('partial' if states & {'ok', 'partial'} else 'blocked')
        if status is None or status == 'ok':
            status = derived
        elif derived == 'blocked':
            status = 'blocked'
    if status not in {'ok', 'partial', 'blocked', 'failed', 'unavailable'}:
        raise ValueError('invalid collection status')
    items = payload.get('items')
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError('items must be a bounded list')
    groups, context, rejected = {}, {}, []
    integrity_failure = False
    for item in items:
        try:
            if not isinstance(item, dict) or not all(item.get(k) for k in ('source', 'url', 'text', 'published_at', 'received_at', 'timestamp_precision')):
                raise ValueError('required evidence field missing')
            if not all(isinstance(item[k], str) for k in ('source', 'url', 'text')):
                raise ValueError('source/url/text must be strings')
            link = urlsplit(item['url'])
            if link.scheme != 'https' or not link.hostname or link.username or link.password:
                raise ValueError('unsafe evidence URL')
            published, received = _date(item['published_at']), _date(item['received_at'])
            published_utc, received_utc = published.astimezone(start.tzinfo), received.astimezone(start.tzinfo)
            if received_utc < published_utc:
                raise ValueError('retrieved before source publication time')
            precision = item['timestamp_precision']
            if precision not in {'second', 'minute'}:
                raise ValueError('unsupported timestamp precision')
            lower, upper = published_utc, published_utc + (timedelta(minutes=1) if precision == 'minute' else timedelta(microseconds=1))
            if lower > end:
                raise ValueError('future or outside snapshot time')
            if precision == 'minute':
                if lower > start and upper <= end:
                    bucket = 'window_items'
                elif lower >= start - timedelta(minutes=60) and upper <= start:
                    bucket = 'context_items'
                else:
                    raise ValueError('minute interval crosses a strict window boundary')
            elif start < lower <= end:
                bucket = 'window_items'
            elif start - timedelta(minutes=60) <= lower <= start:
                bucket = 'context_items'
            else:
                raise ValueError('outside exact window and prior 60-minute context')
            clean = {key: value for key, value in item.items() if key in {'source', 'url', 'text', 'published_at', 'received_at', 'timestamp_precision', 'timestamp_evidence', 'source_time', 'source_timezone'}}
            # Only exact normalized text in the same UTC minute is merged.
            # Similar wording remains separate, never independent corroboration.
            minute = published.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
            key = hashlib.sha256((_normalize_text(item['text']) + '|' + minute).encode('utf-8')).hexdigest()
            target = context if bucket == 'context_items' else groups
            if key not in target:
                clean.update({'provenance': [], 'provenance_sources': [], 'independent_confirmations': 1})
                target[key] = clean
            group = target[key]
            provenance = {'source': item['source'], 'url': item['url'], 'published_at': item['published_at'], 'received_at': item['received_at'], 'timestamp_precision': precision}
            if provenance not in group['provenance']:
                group['provenance'].append(provenance)
            if item['source'] not in group['provenance_sources']:
                group['provenance_sources'].append(item['source'])
        except (ValueError, TypeError, OverflowError) as exc:
            reason = str(exc)
            if reason not in {'future or outside snapshot time', 'outside exact window and prior 60-minute context', 'minute interval crosses a strict window boundary'}:
                integrity_failure = True
            rejected.append({'reason': reason, 'source': item.get('source') if isinstance(item, dict) else None})
    if integrity_failure and status == 'ok':
        status = 'partial'
    return {'status': status, 'sources': source_states, 'errors': payload.get('errors', []), 'window_items': list(groups.values()), 'context_items': list(context.values()), 'rejected': rejected}


def _state_path(value):
    path = Path(value).resolve()
    if path != STATE and STATE not in path.parents:
        raise ValueError('all CLI paths must be under repository .state')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        snap, source, output = map(_state_path, (args.snapshot, args.input, args.output))
        if output.parent != STATE or not output.name.startswith('news-output-') or output.suffix != '.json':
            raise ValueError('output must be a news-output-*.json sidecar directly under .state')
        if snap == output or source == output:
            raise ValueError('output must be a distinct .state file')
        if source.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError('input exceeds size limit')
        snapshot = json.loads(snap.read_text(encoding='utf-8'))
        payload = json.loads(source.read_text(encoding='utf-8'))
        result = normalize(payload, snapshot['window_start'], snapshot['window_end'])
        result['snapshot_slot'] = snapshot['slot']
        result['window_start'] = snapshot['window_start']
        result['window_end'] = snapshot['window_end']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return 0
    except Exception as exc:
        print(f'radar_news: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
