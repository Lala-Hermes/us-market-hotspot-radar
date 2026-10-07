"""Read-only, bounded Jin10 MCP adapter; no browser or embedded credentials."""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from radar_news import _date, _state_path


def validate_page_records(records, previous_oldest, seen):
    """Check newest-first order, forward pagination, and exact entry uniqueness."""
    times = [_date(row['published_at']) for row in records]
    if any(times[i] < times[i + 1] for i in range(len(times) - 1)):
        return False
    if previous_oldest is not None and times and times[0] > _date(previous_oldest):
        return False
    keys = [(row['published_at'], row['url']) for row in records]
    if len(keys) != len(set(keys)) or any(key in seen for key in keys):
        return False
    seen.update(keys)
    return True


def coverage_complete(oldest, newest, window_start, window_end, exhausted):
    if oldest is None or newest is None:
        return False
    return _date(oldest) <= _date(window_start) - timedelta(minutes=60) and (
        _date(newest) >= _date(window_end) or exhausted)


def write_json_atomic(output, payload, state):
    output, state = Path(output), Path(state).resolve()
    if output.is_symlink():
        raise ValueError('refusing symlink output')
    if output.parent.resolve() != state or output.parent != state:
        raise ValueError('output must be directly under .state')
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=state,
                                         prefix='.news-input-', suffix='.tmp',
                                         delete=False) as temp:
            temp_name = temp.name
            json.dump(payload, temp, ensure_ascii=False, indent=2)
            temp.flush()
            os.fsync(temp.fileno())
        if output.is_symlink():
            raise ValueError('refusing symlink output')
        os.replace(temp_name, output)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def parse_page(payload, received_at):
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get('items'), list) or not isinstance(data.get('has_more'), bool):
        raise ValueError('malformed MCP flash page')
    if len(data['items']) > 500:
        raise ValueError('oversized flash page')
    records = []
    for row in data['items']:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ('content', 'time', 'url')):
            raise ValueError('malformed MCP flash record')
        _date(row['time'])
        link = urlsplit(row['url'])
        if link.scheme != 'https' or not link.hostname or link.username or link.password:
            raise ValueError('unsafe flash URL')
        records.append({'source': 'jin10_mcp', 'url': row['url'], 'text': row['content'],
                        'published_at': row['time'], 'received_at': received_at,
                        'timestamp_precision': 'second', 'timestamp_evidence': 'Jin10 MCP list_flash.time aware ISO-8601'})
    cursor = data.get('next_cursor')
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError('invalid cursor')
    return records, cursor, data['has_more']


async def collect(snapshot):
    # Canonical Hermes resolver expands credential references without exposing them.
    home = Path(os.environ['HERMES_HOME']).resolve()
    sys.path.insert(0, str(home / 'hermes-agent'))
    from hermes_cli.config import load_config
    from hermes_cli.mcp_config import _resolve_mcp_server_config
    import httpx
    server = _resolve_mcp_server_config(load_config()['mcp_servers']['jin10'])
    records, seen, cursor, covered, page_count = [], set(), None, False, 0
    previous_oldest = None
    reason = 'pagination_budget_exhausted'
    try:
        async with asyncio.timeout(60):
            headers = dict(server.get('headers', {}))
            headers.update({'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
            async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=False) as client:
                seq = 0

                async def rpc(method, params, notify=False):
                    nonlocal seq
                    seq += 1
                    request_id = seq
                    request = {'jsonrpc': '2.0', 'method': method, 'params': params}
                    if not notify:
                        request['id'] = request_id
                    async with client.stream('POST', server['url'], json=request) as response:
                        response.raise_for_status()
                        if response.headers.get('mcp-session-id'):
                            client.headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
                        if notify:
                            return None
                        if 'text/event-stream' in response.headers.get('content-type', ''):
                            parts, message = [], None
                            async for line in response.aiter_lines():
                                if line.startswith('data:'):
                                    parts.append(line[5:].lstrip())
                                elif not line and parts:
                                    candidate = json.loads('\n'.join(parts))
                                    parts = []
                                    if candidate.get('id') == request_id:
                                        message = candidate
                                        break
                            if message is None:
                                raise ValueError('missing matching MCP response')
                        else:
                            message = json.loads(await response.aread())
                    if message.get('id') != request_id or 'error' in message or not isinstance(message.get('result'), dict):
                        raise ValueError('MCP protocol error')
                    return message['result']

                initialized = await rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'radar-news', 'version': '1.0'}})
                if initialized.get('protocolVersion') != '2025-11-25':
                    raise ValueError('unsupported MCP protocol')
                client.headers['MCP-Protocol-Version'] = initialized['protocolVersion']
                await rpc('notifications/initialized', {}, notify=True)
                for _ in range(3):
                    async with asyncio.timeout(15):
                        result = await rpc('tools/call', {'name': 'list_flash', 'arguments': {'cursor': cursor} if cursor else {}})
                    page_count += 1
                    if result.get('isError'):
                        reason = 'mcp_tool_error'
                        break
                    # Preserve wire structuredContent; never parse supplementary text.
                    page, next_cursor, more = parse_page(result.get('structuredContent'), datetime.now(timezone.utc).isoformat())
                    if not validate_page_records(page, previous_oldest, seen):
                        reason = 'pagination_integrity_failure'
                        break
                    records.extend(page)
                    oldest = min((_date(r['published_at']) for r in page), default=None)
                    newest = max((_date(r['published_at']) for r in records), default=None)
                    if coverage_complete(oldest, newest, snapshot['window_start'], snapshot['window_end'], not more):
                        covered = True
                        reason = ''
                        break
                    if not more:
                        reason = 'source_exhausted_before_cutoff'
                        break
                    if oldest is not None:
                        previous_oldest = oldest.isoformat()
                    if not next_cursor or next_cursor in seen or not page:
                        reason = 'pagination_incomplete'
                        break
                    seen.add(next_cursor)
                    cursor = next_cursor
    except Exception:
        # Do not emit exception messages that might contain resolved credentials.
        reason = 'mcp_request_failed_or_timeout'
    return {'items': records, 'sources': [{'source': 'jin10_mcp', 'status': 'ok' if covered else ('partial' if records else 'blocked'),
             'received_at': datetime.now(timezone.utc).isoformat(), 'url': 'https://mcp.jin10.com/mcp',
             'reason': reason, 'pages': page_count, 'context_coverage_reached': covered}]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        from radar_news import STATE
        raw_output = Path(args.output)
        if raw_output.is_symlink():
            raise ValueError('refusing symlink output')
        snap, output = map(_state_path, (args.snapshot, args.output))
        if output.parent != STATE or not output.name.startswith('news-input-') or output.suffix != '.json' or output == snap:
            raise ValueError('output must be a distinct news-input-*.json sidecar')
        snapshot = json.loads(snap.read_text(encoding='utf-8'))
        try:
            payload = asyncio.run(collect(snapshot))
        except Exception:
            payload = {'items': [], 'sources': [{'source': 'jin10_mcp', 'status': 'blocked', 'reason': 'mcp_configuration_or_runtime_unavailable', 'url': 'https://mcp.jin10.com/mcp', 'received_at': datetime.now(timezone.utc).isoformat()}]}
        write_json_atomic(output, payload, STATE)
        print(json.dumps({'output': str(output), 'status': payload['sources'][0]['status'], 'item_count': len(payload['items'])}))
        return 0
    except Exception as exc:
        print('radar_jin10: ' + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
