#!/usr/bin/env python3
"""Codex Pulse: observabilidade local e somente-leitura de logs Codex."""
from __future__ import annotations
import argparse
from bisect import bisect_right
import csv
from datetime import datetime, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
import webbrowser

if __name__ == '__main__':
    from updater import check_and_apply
    if check_and_apply():
        os.execv(sys.executable, [sys.executable, *sys.argv])

BASE = Path(__file__).resolve().parent
FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')
PRICES_FILE = BASE / 'pricing.json'


def stamp(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def duration_ms(start, end):
    if not start or not end:
        return None
    try:
        ms = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000
        return round(ms) if ms >= 0 else None
    except (TypeError, ValueError):
        return None


def tokens(raw):
    raw = raw if isinstance(raw, dict) else {}
    x = {}
    for field in FIELDS:
        try:
            x[field] = max(0, int(raw.get(field) or 0))
        except (TypeError, ValueError):
            x[field] = 0
    x['cached_input_tokens'] = min(x['cached_input_tokens'], x['input_tokens'])
    x['reasoning_output_tokens'] = min(x['reasoning_output_tokens'], x['output_tokens'])
    x['total_tokens'] = x['input_tokens'] + x['output_tokens']
    return x


def diff(now, previous):
    return tokens({k: max(0, now[k] - previous[k]) for k in FIELDS})


def message_text(payload):
    if not isinstance(payload, dict):
        return ''
    content = payload.get('message', payload.get('content', ''))
    if isinstance(content, dict):
        content = content.get('content', content.get('text', ''))
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get('text', '')
                if isinstance(value, dict):
                    value = value.get('value', '')
                if isinstance(value, str):
                    parts.append(value)
        content = ' '.join(parts)
    if isinstance(content, str):
        return ' '.join(content.split())[:240]
    return ''


def parse_rollout(path):
    """Returns one session + response records, tolerant to partially written JSONL."""
    meta = {'id': path.stem, 'cwd': '', 'client': '', 'started': None, 'path': str(path)}
    responses = []
    prompts = []
    tools = []
    limits = None
    latest_model = 'desconhecido'
    effort = '—'
    context_window = None
    seq = 0
    prev_cumulative = None
    legacy = []
    found_modern = False
    latest_prompt = None
    current_turn = None
    task_timings = {}
    try:
        fh = path.open('r', encoding='utf-8', errors='replace')
    except OSError:
        return None
    with fh:
        for line_no, line in enumerate(fh, 1):
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            typ = row.get('type')
            p = row.get('payload') or {}
            if not isinstance(p, dict):
                continue
            t = stamp(row.get('timestamp'))
            if typ == 'session_meta':
                meta.update({'id': str(p.get('id') or meta['id']), 'cwd': str(p.get('cwd') or ''), 'client': str(p.get('originator') or ''), 'started': t})
                continue
            if typ == 'turn_context':
                latest_model = str(p.get('model') or latest_model)
                effort = str(p.get('effort') or p.get('reasoning_effort') or (p.get('reasoning', {}).get('effort') if isinstance(p.get('reasoning'), dict) else None) or effort)
                current_turn = p.get('turn_id') or current_turn
                continue
            is_user = (typ == 'event_msg' and p.get('type') == 'user_message') or (typ == 'response_item' and p.get('role') == 'user' and p.get('type') in ('message', 'user_message'))
            if is_user:
                content = message_text(p)
                if content:
                    seq += 1
                    latest_prompt = {'key': str(p.get('turn_id') or f'p{seq}'), 'timestamp': t, 'preview': content}
                    prompts.append(latest_prompt)
                    current_turn = str(p.get('turn_id') or current_turn or '') or None
                continue
            if typ == 'response_item':
                if p.get('type') in ('function_call', 'custom_tool_call'):
                    name = str(p.get('name') or 'ferramenta')
                    tools.append({'turn_id': str(p.get('turn_id') or current_turn or ''), 'timestamp': t, 'name': name})
                continue
            if typ == 'event_msg':
                kind = p.get('type')
                if kind == 'task_complete':
                    turn = str(p.get('turn_id') or current_turn or '')
                    if turn:
                        task_timings[turn] = p.get('duration_ms')
                if kind != 'token_count':
                    continue
                if isinstance(p.get('rate_limits'), dict):
                    limits = {'timestamp': t, **p['rate_limits']}
                info = p.get('info') or {}
                if not isinstance(info, dict):
                    continue
                if isinstance(info.get('model_context_window'), (int, float)):
                    context_window = info['model_context_window']
                total_raw = info.get('total_token_usage')
                last_raw = info.get('last_token_usage')
                usage = None
                if isinstance(total_raw, dict):
                    cumul = tokens(total_raw)
                    usage = diff(cumul, prev_cumulative) if prev_cumulative else cumul
                    # Detect counter reset; treat new total as a fresh baseline.
                    if prev_cumulative and cumul['total_tokens'] < prev_cumulative['total_tokens']:
                        usage = cumul
                    prev_cumulative = cumul
                elif isinstance(last_raw, dict):
                    usage = tokens(last_raw)
                if usage and usage['total_tokens']:
                    legacy.append({'response_id': f'{meta["id"]}:legacy:{line_no}', 'turn_id': str(p.get('turn_id') or current_turn or ''), 'root_turn_id': None, 'timestamp': t, 'model': str(info.get('model') or latest_model), 'effort': effort, 'usage': usage, 'prompt': latest_prompt})
                continue
            if typ == 'token_usage_record':
                u = tokens(p.get('usage'))
                if not u['total_tokens']:
                    continue
                found_modern = True
                rid = str(p.get('response_id') or f'{meta["id"]}:{line_no}')
                responses.append({'response_id': rid, 'turn_id': str(p.get('turn_id') or current_turn or ''), 'root_turn_id': str(p.get('root_turn_id') or ''), 'timestamp': t, 'model': str(p.get('model') or latest_model), 'effort': effort, 'usage': u, 'prompt': latest_prompt})
    if not meta['started']:
        meta['started'] = (prompts[0]['timestamp'] if prompts else (responses[0]['timestamp'] if responses else None))
    meta['context_window'] = context_window
    meta['limits'] = limits
    meta['task_timings'] = task_timings
    meta['prompts'] = prompts
    meta['tools'] = tools
    return {'meta': meta, 'responses': responses if found_modern else legacy}


@lru_cache(maxsize=3072)
def cached_rollout(path_str, size, mtime_ns):
    return parse_rollout(Path(path_str))


def discover(home):
    paths = []
    for dirname in ('sessions', 'archived_sessions'):
        folder = home / dirname
        if folder.is_dir():
            paths.extend(folder.rglob('rollout-*.jsonl'))
    return sorted(set(paths))


def price_for(model, prices):
    return prices.get(model.lower())


def cost_breakdown(usage, model, prices):
    r = price_for(model, prices)
    if not r:
        return None
    fresh = usage['input_tokens'] - usage['cached_input_tokens']
    return {
        'fresh': fresh * r['input'] / 1_000_000,
        'cached': usage['cached_input_tokens'] * r['cached'] / 1_000_000,
        'output': usage['output_tokens'] * r['output'] / 1_000_000,
        'saved_by_cache': usage['cached_input_tokens'] * max(0, r['input'] - r['cached']) / 1_000_000,
    }

def estimated_cost(usage, model, prices):
    breakdown = cost_breakdown(usage, model, prices)
    return sum(breakdown[k] for k in ('fresh', 'cached', 'output')) if breakdown else None


def aggregate(home, prices, demo=False):
    if demo:
        return demo_data(prices)
    sessions, calls, seen = {}, [], set()
    all_prompts = {}
    last_limits = None
    latest_context = None
    scan_errors = 0
    files = discover(home)  # scan only once per refresh
    timings = {}
    for file in files:
        try:
            st = file.stat()
            result = cached_rollout(str(file), st.st_size, st.st_mtime_ns)
        except OSError:
            scan_errors += 1
            continue
        if not result:
            continue
        meta = result['meta']
        sid = meta['id']
        if sid not in sessions:
            sessions[sid] = {'id': sid, 'project': meta['cwd'] or 'Sem projeto', 'client': meta['client'], 'started': meta['started'], 'context_window': meta['context_window'], 'file': file.name}
        if meta.get('context_window'):
            latest_context = meta['context_window']
        if meta.get('limits') and (not last_limits or (meta['limits']['timestamp'] or '') > (last_limits['timestamp'] or '')):
            last_limits = meta['limits']
        all_prompts.setdefault(sid, []).extend(meta['prompts'])
        for tid, duration in meta['task_timings'].items():
            timings[f'{sid}:{tid}'] = duration
        for r in result['responses']:
            key = r['response_id']
            if key in seen:
                continue
            seen.add(key)
            u = r['usage']
            calls.append({'id': key, 'session_id': sid, 'project': sessions[sid]['project'], 'model': r['model'], 'effort': r['effort'], 'timestamp': r['timestamp'], 'turn_id': r['turn_id'], 'root_turn_id': r['root_turn_id'], 'prompt': None, 'prompt_id': '', 'input': u['input_tokens'], 'cached': u['cached_input_tokens'], 'fresh': u['input_tokens'] - u['cached_input_tokens'], 'output': u['output_tokens'], 'reasoning': u['reasoning_output_tokens'], 'total': u['total_tokens'], 'cost': estimated_cost(u, r['model'], prices), 'cost_breakdown': cost_breakdown(u, r['model'], prices), 'context_window': meta['context_window']})

    # Build a per-session timestamp index. A long project can have tens of
    # thousands of calls: avoid sorting and filtering every prompt for each one.
    prompt_index = {}
    for sid, messages in all_prompts.items():
        by_time = sorted((p for p in messages if p.get('timestamp')), key=lambda p: p['timestamp'])
        explicit = {p['key']: p for p in by_time if p.get('key')}
        prompt_index[sid] = ([p['timestamp'] for p in by_time], by_time, explicit)
    for c in calls:
        index = prompt_index.get(c['session_id'])
        match = None
        if index:
            stamps, prompts_by_time, by_id = index
            match = by_id.get(c['turn_id']) if c['turn_id'] else None
            if match is None and c['timestamp']:
                pos = bisect_right(stamps, c['timestamp']) - 1
                if pos >= 0:
                    match = prompts_by_time[pos]
        if match:
            c['prompt'] = match['preview']
            c['prompt_id'] = f"{c['session_id']}:{c['turn_id'] or match['key']}"
        else:
            c['prompt_id'] = f"{c['session_id']}:{c['turn_id'] or 'sem-prompt'}"
    calls.sort(key=lambda x: x['timestamp'] or '', reverse=True)
    prompt_groups = {}
    session_groups = {}
    def touch(obj, key, labels):
        if key not in obj:
            obj[key] = {**labels, 'calls': 0, 'input': 0, 'cached': 0, 'fresh': 0, 'output': 0, 'reasoning': 0, 'total': 0, 'cost': 0, 'unpriced_calls': 0, 'first': None, 'last': None, 'models': set()}
        return obj[key]
    for c in calls:
        gs = touch(session_groups, c['session_id'], {'id': c['session_id'], 'project': c['project'], 'prompt': ''})
        gp = touch(prompt_groups, c['prompt_id'], {'id': c['prompt_id'], 'session_id': c['session_id'], 'project': c['project'], 'prompt': c['prompt'] or '(prompt não registrado)', 'turn_id': c['turn_id']})
        for group in (gs, gp):
            group['calls'] += 1
            for x in ('input', 'cached', 'fresh', 'output', 'reasoning', 'total'):
                group[x] += c[x]
            group['models'].add(c['model'])
            if c['cost'] is None:
                group['unpriced_calls'] += 1
            else:
                group['cost'] += c['cost']
            ts = c['timestamp']
            if ts:
                group['first'] = min(group['first'] or ts, ts)
                group['last'] = max(group['last'] or ts, ts)

    for obj in (prompt_groups, session_groups):
        for g in obj.values():
            g['models'] = sorted(g['models'])
            g['cost'] = round(g['cost'], 8) if not g['unpriced_calls'] else None
            g['cache_pct'] = round(100 * g['cached'] / g['input'], 1) if g['input'] else 0
            g['duration_ms'] = None
    # Timing data was collected in the first pass; no need to re-open files.
    for key, pg in prompt_groups.items():
        if key in timings:
            pg['duration_ms'] = timings[key]
    return {'source': str(home), 'demo': False, 'calls': calls, 'prompts': sorted(prompt_groups.values(), key=lambda p: p['last'] or '', reverse=True), 'sessions': sorted(session_groups.values(), key=lambda p: p['last'] or '', reverse=True), 'limits': last_limits, 'context_window': latest_context, 'files': len(files), 'scan_errors': scan_errors}


def demo_data(prices):
    from datetime import timedelta
    base = datetime.now(timezone.utc)
    models = ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-5.3-codex', 'gpt-6.1-terra']
    projects = ['/workspace/banco-talentos', '/workspace/inventario', '/workspace/api-dotnet', '/workspace/portfolio']
    prompts = ['Implemente filtros combináveis para candidatos e vagas.', 'Corrija a consulta SQL e explique a causa.', 'Crie testes de regressão para os endpoints.', 'Refatore o serviço mantendo as regras de negócio.', 'Revise os índices e a performance do banco.', 'Implemente autenticação e autorização segura.']
    calls = []
    for i in range(140):
        m = models[(i // 7) % len(models)]
        project = projects[(i // 11) % len(projects)]
        inp = 2100 + (i * 271) % 35000
        cached = int(inp * (0.55 + (i % 6) * .06))
        out = 180 + (i * 59) % 2900
        usage = tokens({'input_tokens': inp, 'cached_input_tokens': cached, 'output_tokens': out, 'reasoning_output_tokens': out // 3})
        ts = (base - timedelta(hours=i*1.7)).isoformat()
        sid = f'demo-sess-{(i // 15):02}'
        calls.append({'id': f'demo-{i}', 'session_id': sid, 'project': project, 'model': m, 'effort': ['medium','high','xhigh'][i%3], 'timestamp': ts, 'turn_id': f'demo-turn-{i//3}', 'root_turn_id': '', 'prompt_id': f'demo-prompt-{i//3}', 'prompt': prompts[(i//3) % len(prompts)], 'input': inp, 'cached': cached, 'fresh': inp-cached, 'output': out, 'reasoning': out//3, 'total': inp+out, 'cost': estimated_cost(usage, m, prices), 'cost_breakdown': cost_breakdown(usage, m, prices), 'context_window': 258400})
    def grouped(field):
        buckets = {}
        for c in calls:
            key = c[field]
            if key not in buckets:
                buckets[key] = {'id': key, 'session_id': c['session_id'], 'project': c['project'], 'prompt': c['prompt'], 'calls': 0, 'input': 0, 'cached': 0, 'fresh': 0, 'output': 0, 'reasoning': 0, 'total': 0, 'cost': 0, 'unpriced_calls': 0, 'first': c['timestamp'], 'last': c['timestamp'], 'models': set(), 'duration_ms': None}
            b = buckets[key]
            b['calls'] += 1
            b['first'] = min(b['first'], c['timestamp'])
            b['last'] = max(b['last'], c['timestamp'])
            for k in ('input', 'cached', 'fresh', 'output', 'reasoning', 'total'):
                b[k] += c[k]
            b['models'].add(c['model'])
            if c['cost'] is None:
                b['unpriced_calls'] += 1
            else:
                b['cost'] += c['cost']
        for b in buckets.values():
            b['models'] = sorted(b['models'])
            b['cache_pct'] = round(100*b['cached']/b['input'], 1)
            if b['unpriced_calls']:
                b['cost'] = None
        return sorted(buckets.values(), key=lambda x: x['last'], reverse=True)
    return {'source': 'Demonstração — dados sintéticos', 'demo': True, 'calls': calls, 'prompts': grouped('prompt_id'), 'sessions': grouped('session_id'), 'limits': {'timestamp': base.isoformat(), 'primary': {'used_percent': 37, 'window_minutes': 300, 'resets_at': int(base.timestamp())+5300}, 'secondary': {'used_percent': 62, 'window_minutes': 10080, 'resets_at': int(base.timestamp())+324000}}, 'context_window': 258400, 'files': 10, 'scan_errors': 0}


def main():
    parser = argparse.ArgumentParser(description='Codex Pulse — monitor local para Codex')
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--port', type=int, default=4327)
    parser.add_argument('--demo', action='store_true', help='Exibe dados fictícios para testar o dashboard')
    parser.add_argument('--no-browser', action='store_true', help='Não abre o navegador automaticamente')
    args = parser.parse_args()
    if not (1 <= args.port <= 65535):
        parser.error('porta deve estar entre 1 e 65535')
    try:
        prices = json.loads(PRICES_FILE.read_text(encoding='utf-8'))['models']
        for value in prices.values():
            if not all(isinstance(value.get(k), (int, float)) and value[k] >= 0 for k in ('input', 'cached', 'output')):
                raise ValueError('Tabela de preços inválida')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f'Não foi possível ler pricing.json: {exc}')
    home = Path(args.codex_home).expanduser()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            uri = urlparse(self.path)
            if uri.path in ('/', '/index.html'):
                self.respond((BASE / 'dashboard.html').read_bytes(), 'text/html; charset=utf-8')
            elif uri.path == '/api/data':
                self.respond(json.dumps(aggregate(home, prices, args.demo), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            elif uri.path == '/api/pricing':
                self.respond(PRICES_FILE.read_bytes(), 'application/json; charset=utf-8')
            elif uri.path == '/api/export.csv':
                rows = aggregate(home, prices, args.demo)['calls']
                query = parse_qs(uri.query)
                include_prompt = query.get('prompts', ['0'])[0] == '1'
                buf = io.StringIO()
                cols = ['timestamp', 'id', 'session_id', 'project', 'model', 'effort', 'input', 'cached', 'fresh', 'output', 'reasoning', 'total', 'cost', 'prompt_id']
                if include_prompt:
                    cols.append('prompt')
                writer = csv.DictWriter(buf, fieldnames=cols, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
                self.respond(buf.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', disposition='attachment; filename="codex-pulse.csv"')
            else:
                self.send_error(404)
        def respond(self, body, content_type, disposition=None):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if disposition:
                self.send_header('Content-Disposition', disposition)
            self.end_headers()
            self.wfile.write(body)
    # Serve JavaScript/CSS separately to keep a strict script-src policy.
    old_get = Handler.do_GET
    def get(self):
        uri = urlparse(self.path)
        static = {'/app.js': ('app.js', 'application/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if uri.path in static:
            filename, mime = static[uri.path]
            self.respond((BASE / filename).read_bytes(), mime)
        else:
            old_get(self)
    Handler.do_GET = get
    url = f'http://127.0.0.1:{args.port}'
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Codex Pulse iniciado: {url}')
        print(f'Fonte: {"DEMO" if args.demo else home}')
        print('Somente localhost, sem envio de dados. Ctrl+C para encerrar.')
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            print('\nEncerrado.')


if __name__ == '__main__':
    main()
