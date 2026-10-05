from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import urllib.parse
import urllib.request

MAX_AGE_SECONDS = 120
MIN_INTERVAL_SECONDS = 540
MAX_INTERVAL_SECONDS = 660


def yahoo_chart_quote(symbol, payload, received_at=None):
    try:
        result = payload['chart']['result'][0]
        meta = result['meta']
        expected_type = 'INDEX' if symbol in ('^VIX','^TNX') else None
        price = float(meta['regularMarketPrice'])
        stamp = int(meta['regularMarketTime'])
        if (meta.get('symbol') != symbol or (expected_type and meta.get('instrumentType') != expected_type)
            or not math.isfinite(price) or price <= 0 or stamp <= 0):
            return None
        return {'symbol':symbol, 'instrument':symbol, 'price':price,
                'source_time':datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                'received_at':received_at or datetime.now(timezone.utc).isoformat(),
                'source':'Yahoo Finance chart metadata (delay unspecified)',
                'unit':'percent' if symbol == '^TNX' else 'index_points'}
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, OSError):
        return None


def fetch_yahoo_quote(symbol, timeout=10):
    encoded = urllib.parse.quote(symbol, safe='')
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1d'
    request = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode('utf-8'))
    received = datetime.now(timezone.utc).isoformat()
    return yahoo_chart_quote(symbol, payload, received)


def _stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def validate_quote(quote, now=None):
    if not isinstance(quote, dict) or not quote.get('source') or not quote.get('symbol') or not quote.get('instrument'):
        return {'status': 'invalid', 'reason': 'missing source or instrument identity'}
    try:
        price = float(quote.get('price'))
    except (TypeError, ValueError, OverflowError):
        return {'status': 'invalid', 'reason': 'invalid price'}
    if not math.isfinite(price) or price <= 0:
        return {'status': 'invalid', 'reason': 'invalid price'}
    source_time, received = _stamp(quote.get('source_time')), _stamp(quote.get('received_at'))
    if source_time is None or received is None:
        return {'status': 'invalid', 'reason': 'source and receipt times must be timezone-aware'}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    current = now.astimezone(timezone.utc)
    age = (current - source_time).total_seconds()
    receipt_age = (current - received).total_seconds()
    if receipt_age < -30 or receipt_age > MAX_AGE_SECONDS or (source_time-received).total_seconds() > 30:
        return {'status': 'invalid', 'reason': 'receipt timestamp is not current or precedes quote time'}
    if age < -30 or age > MAX_AGE_SECONDS:
        return {'status': 'stale', 'reason': f'source quote age {age:.0f}s outside allowed range'}
    item = dict(quote)
    item['price'] = price
    item['source_time'] = source_time.isoformat()
    item['received_at'] = received.isoformat()
    item['status'] = 'usable'
    item['source_age_seconds'] = round(age, 1)
    return item


def observed_change(current, previous):
    if not previous:
        return None
    now, before = _stamp(current.get('source_time')), _stamp(previous.get('source_time'))
    received, prior_received = _stamp(current.get('received_at')), _stamp(previous.get('received_at'))
    if not all((now, before, received, prior_received)):
        return None
    elapsed, receipt_elapsed = (now-before).total_seconds(), (received-prior_received).total_seconds()
    if not MIN_INTERVAL_SECONDS <= elapsed <= MAX_INTERVAL_SECONDS or receipt_elapsed <= 0:
        return None
    if any(current.get(k) != previous.get(k) for k in ('symbol','instrument','source','unit')) or now.date() != before.date():
        return None
    if current.get('source_time') == previous.get('source_time'):
        return None
    a, b = float(current['price']), float(previous['price'])
    delta = a-b
    result = {'symbol':current['symbol'], 'instrument':current['instrument'], 'source':current['source'],
              'unit':current['unit'], 'previous_price':b, 'price':a,
              'source_time':now.isoformat(), 'previous_source_time':before.isoformat(),
              'received_at':received.isoformat(), 'previous_received_at':prior_received.isoformat(),
              'elapsed_seconds':elapsed, 'receipt_elapsed_seconds':receipt_elapsed,
              'change_absolute':round(delta, 8), 'change_pct':round(delta/b*100, 5),
              'confidence':'reduced; price-only observed quote change, not a forecast'}
    if result['unit'] == 'index_points': result['change_points'] = round(delta, 5)
    elif result['unit'] == 'percent': result['change_basis_points'] = round(delta*100, 5)
    return result


class QuoteBook:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS observations (
              id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, instrument TEXT NOT NULL,
              price REAL NOT NULL, source_time TEXT NOT NULL, received_at TEXT NOT NULL,
              source TEXT NOT NULL, unit TEXT NOT NULL, diagnostic INTEGER NOT NULL DEFAULT 0,
              payload TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS observations_lookup ON observations(symbol, diagnostic, id)')

    def previous(self, symbol):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload FROM observations WHERE symbol=? AND diagnostic=0 ORDER BY id DESC LIMIT 1', (symbol,)).fetchone()
        return json.loads(row[0]) if row else None

    def observe(self, quote, diagnostic=False, now=None):
        valid = validate_quote(quote, now)
        if valid['status'] != 'usable': return valid
        prior = None if diagnostic else self.previous(valid['symbol'])
        change = observed_change(valid, prior)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO observations(symbol,instrument,price,source_time,received_at,source,unit,diagnostic,payload) VALUES(?,?,?,?,?,?,?,?,?)',
                       (valid['symbol'], valid['instrument'], valid['price'], valid['source_time'], valid['received_at'], valid['source'], valid['unit'], int(diagnostic), json.dumps(valid)))
        return change
