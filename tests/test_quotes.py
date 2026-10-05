from datetime import datetime, timedelta, timezone

from radar_quotes import QuoteBook, observed_change, validate_quote


def q(symbol, price, stamp, received=None, source='Yahoo Finance'):
    return {'symbol': symbol, 'instrument': symbol, 'price': price, 'source_time': stamp,
            'received_at': received or stamp, 'source': source, 'unit': 'percent' if symbol == '^TNX' else 'index_points'}


def test_observed_change_requires_two_valid_distinct_observations():
    start = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    assert observed_change(q('^VIX', 15, start.isoformat()), None) is None
    prior = q('^VIX', 15, start.isoformat())
    current = q('^VIX', 16, (start + timedelta(minutes=10)).isoformat())
    change = observed_change(current, prior)
    assert change['change_points'] == 1
    assert change['change_pct'] == round(100 / 15, 5)
    assert change['elapsed_seconds'] == 600


def test_treasury_yield_change_is_reported_in_basis_points():
    start = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    prior = q('^TNX', 5.2, start.isoformat())
    current = q('^TNX', 5.277, (start + timedelta(minutes=10)).isoformat())
    assert observed_change(current, prior)['change_basis_points'] == 7.7


def test_rejects_stale_missing_bad_repeated_and_cross_source_quotes():
    start = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    prior = q('^VIX', 15, start.isoformat())
    assert validate_quote(q('^VIX', 15, start.isoformat(), (start+timedelta(minutes=3)).isoformat()), start+timedelta(minutes=3))['status'] == 'stale'
    assert observed_change(q('^VIX', 16, 'bad'), prior) is None
    assert observed_change(q('^VIX', 16, start.isoformat()), prior) is None
    assert observed_change(q('^VIX', 16, (start+timedelta(minutes=10)).isoformat(), source='other'), prior) is None
    assert observed_change(q('^VIX', 16, (start+timedelta(minutes=30)).isoformat()), prior) is None


def test_rejects_cross_utc_day_pair_and_missing_receipt_time():
    start = datetime(2026, 10, 2, 23, 55, tzinfo=timezone.utc)
    prior = q('^VIX', 15, start.isoformat())
    next_day = start+timedelta(minutes=10)
    assert observed_change(q('^VIX', 16, next_day.isoformat()), prior) is None
    current = q('^VIX', 16, (start+timedelta(minutes=10)).isoformat())
    current['received_at'] = None
    assert observed_change(current, prior) is None


def test_rejects_nonfinite_prices():
    start = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    for price in (0, -1, float('nan'), float('inf')):
        assert validate_quote(q('^VIX', price, start.isoformat()), start)['status'] == 'invalid'


def test_rejects_unverifiable_receipt_timestamp():
    start=datetime(2026,10,2,14,0,tzinfo=timezone.utc)
    quote=q('^VIX',15,start.isoformat())
    quote['received_at']=(start-timedelta(minutes=5)).isoformat()
    assert validate_quote(quote,start)['status']=='invalid'
    quote=q('^VIX',15,start.isoformat())
    quote['received_at']=(start-timedelta(seconds=60)).isoformat()
    assert validate_quote(quote,start)['status']=='invalid'


def test_quote_book_persists_baseline_but_diagnostic_does_not_seed_it(tmp_path):
    start = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    book = QuoteBook(tmp_path / 'quotes.sqlite')
    diagnostic = q('^VIX', 15, start.isoformat())
    assert book.observe(diagnostic, diagnostic=True, now=start) is None
    assert book.previous('^VIX') is None
    assert book.observe(diagnostic, now=start) is None
    current_time = start+timedelta(minutes=10)
    current = q('^VIX', 16, current_time.isoformat())
    assert book.observe(current, now=current_time)['change_points'] == 1
    assert book.previous('^VIX')['price'] == 16


def test_yahoo_chart_quote_uses_latest_snapshot_metadata_not_day_candle():
    from radar_quotes import yahoo_chart_quote
    payload = {'chart': {'result': [{'meta': {'symbol': '^TNX', 'regularMarketPrice': 5.277,
                'regularMarketTime': int(datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc).timestamp()), 'instrumentType': 'INDEX'},
                'indicators': {'quote': [{'close': [5.1]}]}}], 'error': None}}
    quote = yahoo_chart_quote('^TNX', payload, received_at='2026-10-02T14:00:01+00:00')
    assert quote['price'] == 5.277
    assert quote['unit'] == 'percent'
    assert quote['source_time'] == '2026-10-02T14:00:00+00:00'
    assert quote['source'] == 'Yahoo Finance chart metadata (delay unspecified)'


def test_yahoo_chart_quote_rejects_wrong_symbol_or_missing_snapshot_metadata():
    from radar_quotes import yahoo_chart_quote
    assert yahoo_chart_quote('^VIX', {'chart': {'result': [{'meta': {'symbol': '^TNX'}}]}},
                             received_at='2026-10-02T14:00:01+00:00') is None


def test_provider_receipt_timestamp_is_captured_after_response(monkeypatch):
    import json
    import radar_quotes
    before=datetime(2026,10,2,14,0,tzinfo=timezone.utc)
    after=before+timedelta(seconds=2)
    clock={'now':before}
    original_datetime=radar_quotes.datetime
    class Clock(original_datetime):
        @classmethod
        def now(cls,tz=None):
            value=clock['now']
            return value if tz is None else value.astimezone(tz)
    payload={'chart':{'result':[{'meta':{'symbol':'^VIX','instrumentType':'INDEX','regularMarketPrice':15,
        'regularMarketTime':int(before.timestamp())}}],'error':None}}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def read(self):
            clock['now']=after
            return json.dumps(payload).encode()
    monkeypatch.setattr(radar_quotes,'datetime',Clock)
    monkeypatch.setattr(radar_quotes.urllib.request,'urlopen',lambda *a,**k:Response())
    quote=radar_quotes.fetch_yahoo_quote('^VIX')
    assert quote['received_at']==after.isoformat()

