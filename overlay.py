#!/usr/bin/env python3
"""Codex Pulse v3 — widget de desktop, local, sem dependências além de Tkinter.

O valor em USD é uma *simulação equivalente à API*, não cobrança do ChatGPT.
Os snapshots de limite refletem a última execução registrada do Codex.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tkinter as tk
from tkinter import font, messagebox, simpledialog
from urllib.request import urlopen
import webbrowser

if __name__ == '__main__':
    from updater import check_and_apply
    if check_and_apply():
        os.execv(sys.executable, [sys.executable, *sys.argv])

from codex_pulse import BASE, PRICES_FILE, aggregate

BG = '#0c101a'
SURFACE = '#171f2d'
SURFACE_2 = '#1b2938'
EDGE = '#293746'
TEAL = '#74e7bd'
TEAL_SOFT = '#143831'
INK = '#edf6ff'
SUB = '#9caec2'
FAINT = '#6f839b'
AMBER = '#ffc87f'
RED = '#ff9494'
WIDTH = 426
HEIGHTS = {'full': 658, 'compact': 256, 'micro': 174}
MODES = ('full', 'compact', 'micro')
REFRESH_SECONDS = 6
PREFS = Path.home() / '.codex-pulse' / 'overlay.json'


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def number(value):
    n = int(value or 0)
    if n >= 1_000_000:
        return f'{n / 1e6:.2f}M'.replace('.', ',')
    if n >= 1_000:
        return f'{n / 1e3:.1f}k'.replace('.', ',')
    return f'{n:,}'.replace(',', '.')


# Preserve the names imported by v2 integrations and existing tests.
abbreviate = number


def money(value, partial=False):
    if value is None:
        return 'Sem tarifa'
    places = 4 if abs(value) < 1 else 2
    raw = f'{value:,.{places}f}'.replace(',', '@').replace('.', ',').replace('@', '.')
    return f'US$ {raw}' + ('*' if partial else '')


def project_name(path):
    return (str(path or '').replace('\\', '/').rstrip('/').split('/')[-1] or 'Sem projeto')


def as_datetime(timestamp):
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (TypeError, ValueError, OverflowError):
        return None


def local_time(timestamp):
    value = as_datetime(timestamp)
    return value.astimezone().strftime('%H:%M') if value else '--:--'


def age_text(dt, now):
    if not dt:
        return 'sem chamadas'
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 60:
        return 'agora'
    if seconds < 3600:
        return f'há {seconds // 60}min'
    if seconds < 86400:
        return f'há {seconds // 3600}h'
    return f'há {seconds // 86400}d'


def quota_info(limits, now=None):
    """No guessing: preserve age and explicitly mark expired/stale snapshots."""
    now = now or datetime.now().astimezone()
    limits = limits if isinstance(limits, dict) else {}
    candidate = limits.get('primary') or limits.get('secondary') or {}
    if not isinstance(candidate, dict):
        candidate = {}
    measured = as_datetime(limits.get('timestamp'))
    if not candidate or not measured:
        return {'percent': None, 'label': 'Sem registro de limite', 'age': None, 'stale': True, 'expired': False}
    age = max(0, (now - measured).total_seconds())
    reset = candidate.get('resets_at')
    if reset is None and candidate.get('resets_in_seconds') is not None:
        try:
            reset = measured.timestamp() + float(candidate['resets_in_seconds'])
        except (TypeError, ValueError):
            reset = None
    try:
        expired = reset is not None and now.timestamp() >= float(reset)
    except (TypeError, ValueError):
        expired = False
    try:
        percent = clamp(float(candidate['used_percent']), 0, 100)
        if not math.isfinite(percent):
            percent = None
    except (KeyError, TypeError, ValueError):
        percent = None
    stale = age > 900
    minutes = candidate.get('window_minutes')
    if isinstance(minutes, (float, int)) and minutes > 0:
        label = f'Janela {int(minutes / 60)}h' if minutes % 60 == 0 else f'Janela {int(minutes)}min'
    else:
        label = 'Limite registrado'
    return {'percent': percent if not expired else None, 'label': label, 'age': age,
            'stale': stale, 'expired': expired, 'measured': measured}


def summarize(data, now=None, scope='today'):
    """Pure function; dates are always interpreted in the user's local time zone."""
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    calls = data.get('calls') or []
    most_recent = calls[0] if calls else None
    last_dt = as_datetime(most_recent.get('timestamp')) if most_recent else None
    latest_sid = (most_recent or {}).get('session_id')
    entries = []
    for call in calls:
        dt = as_datetime(call.get('timestamp'))
        if dt is None:
            continue
        dt = dt.astimezone(now.tzinfo)
        if scope == 'hour':
            included = now - timedelta(hours=1) <= dt <= now
        elif scope == 'session':
            included = bool(latest_sid and call.get('session_id') == latest_sid)
        else:
            included = dt.date() == now.date()
        if included:
            entries.append(call)
    priced = [c for c in entries if c.get('cost') is not None]
    unpriced = len(entries) - len(priced)
    inp = sum(int(c.get('input') or 0) for c in entries)
    cache = sum(int(c.get('cached') or 0) for c in entries)
    latest_prompt = None
    if most_recent:
        latest_prompt = next((p for p in data.get('prompts') or [] if p.get('id') == most_recent.get('prompt_id')), None)
    return {'calls': len(entries), 'today_calls': len(entries), 'tokens': sum(int(c.get('total') or 0) for c in entries),
            'input': inp, 'cached': cache, 'cache_percent': clamp(100 * cache / inp, 0, 100) if inp else 0,
            'cost': sum(float(c['cost']) for c in priced), 'unknown_costs': unpriced,
            'latest': most_recent, 'last_dt': last_dt, 'prompt': latest_prompt, 'selected': entries,
            'scope': scope, 'quota': quota_info(data.get('limits'), now), 'demo': bool(data.get('demo')),
            'files': data.get('files', 0), 'scan_errors': data.get('scan_errors', 0),
            'source': data.get('source', ''), 'latest_sid': latest_sid}


def timeline(calls, now=None, scope='today', bins=18):
    """Return per-bin token totals, ignoring missing or future timestamps."""
    now = now or datetime.now().astimezone()
    values = [0] * bins
    times = [as_datetime(c.get('timestamp')) for c in calls]
    if scope == 'hour':
        start = now - timedelta(hours=1)
    elif scope == 'session':
        dated = [d for d in times if d and d <= now]
        start = min(dated, default=now - timedelta(minutes=1))
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    span = max(1, (now-start).total_seconds())
    for call, date in zip(calls, times):
        if date is None or not start <= date <= now:
            continue
        idx = min(bins-1, max(0, int((date-start).total_seconds() / span * bins)))
        values[idx] += max(0, int(call.get('total') or 0))
    return values


def prices_from_file():
    models = json.loads(PRICES_FILE.read_text(encoding='utf-8'))['models']
    if not isinstance(models, dict):
        raise ValueError('Modelos de preços inválidos')
    for p in models.values():
        if not isinstance(p, dict) or any(type(p.get(key)) not in (int, float) or not math.isfinite(p[key]) or p[key] < 0 for key in ('input','cached','output')):
            raise ValueError('Há valores inválidos em pricing.json')
    return models


class Overlay:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.home = Path(args.codex_home).expanduser()
        self.prices = prices_from_file()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.data = None
        self.error = None
        self.last_update = None
        self.drag_anchor = None
        self.dashboard_process = None
        self.dashboard_url = None
        self.closed = False
        self.prefs = self.load_prefs()
        self.mode = self.prefs.get('mode', 'micro') if self.prefs.get('discreet_layout') else 'micro'
        if self.mode not in MODES:
            self.mode = 'full'
        self.scope = self.prefs.get('scope', 'today')
        if self.scope not in ('today', 'hour', 'session'):
            self.scope = 'today'
        self.topmost = bool(self.prefs.get('topmost', True))
        self.opacity = clamp(float(self.prefs.get('opacity', args.opacity)), 0.72, 1.0)
        self.alert_cost = max(0, float(self.prefs.get('alert_cost', 0)))
        self.show_prompt = False  # Privacy: never persist a user's prompt visibility.
        self.c = tk.Canvas(root, bg=BG, bd=0, highlightthickness=0)
        self.c.pack(fill='both', expand=True)
        installed = set(font.families(root))
        self.font = next((x for x in ('Inter', 'Segoe UI', 'Arial', 'DejaVu Sans') if x in installed), 'TkDefaultFont')
        root.title('Codex Pulse · Overlay')
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes('-topmost', self.topmost)
        root.attributes('-alpha', self.opacity)
        root.protocol('WM_DELETE_WINDOW', self.quit)
        self.place(self.prefs.get('x'), self.prefs.get('y'))
        root.bind('<Escape>', lambda e: self.cycle_mode())
        root.bind('<Control-w>', lambda e: self.quit())
        root.bind('<Control-W>', lambda e: self.quit())
        root.bind('<Control-1>', lambda e: self.set_scope('today'))
        root.bind('<Control-2>', lambda e: self.set_scope('hour'))
        root.bind('<Control-3>', lambda e: self.set_scope('session'))
        root.bind('<Button-1>', lambda e: self.c.focus_set(), add='+')
        self.draw()
        self.refresh_loop()
        self.read_loop()

    @staticmethod
    def load_prefs():
        try:
            x = json.loads(PREFS.read_text(encoding='utf-8'))
            return x if isinstance(x, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_prefs(self):
        try:
            PREFS.parent.mkdir(parents=True, exist_ok=True)
            content = {'x': self.root.winfo_x(), 'y': self.root.winfo_y(), 'mode': self.mode,
                       'scope': self.scope, 'topmost': self.topmost, 'opacity': self.opacity,
                       'alert_cost': self.alert_cost, 'discreet_layout': True}
            temporary = PREFS.with_suffix('.tmp')
            temporary.write_text(json.dumps(content, indent=2), encoding='utf-8')
            temporary.replace(PREFS)
        except OSError:
            pass

    def place(self, x=None, y=None):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        h = HEIGHTS[self.mode]
        width = 310 if self.mode == 'micro' else WIDTH
        if x is None or y is None:
            x, y = max(0, sw-width-18), max(0, sh-h-70)
        x = clamp(int(x), 0, max(0, sw-100))
        y = clamp(int(y), 0, max(0, sh-60))
        self.root.geometry(f'{width}x{h}+{x}+{y}')
        self.c.configure(width=width, height=h)

    def save_drag(self, _event=None):
        self.drag_anchor = None
        self.save_prefs()

    def start_drag(self, event):
        self.drag_anchor = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def dragging(self, event):
        if self.drag_anchor:
            ax, ay, px, py = self.drag_anchor
            self.root.geometry(f'+{px+event.x_root-ax}+{py+event.y_root-ay}')

    def cycle_mode(self):
        self.mode = MODES[(MODES.index(self.mode)+1)%len(MODES)]
        self.place(self.root.winfo_x(), self.root.winfo_y())
        self.save_prefs()
        self.draw()

    def set_scope(self, scope):
        self.scope = scope
        self.save_prefs()
        self.draw()

    def toggle_pin(self):
        self.topmost = not self.topmost
        self.root.attributes('-topmost', self.topmost)
        self.save_prefs()
        self.draw()

    def opacity_by(self, delta):
        self.opacity = round(clamp(self.opacity+delta, .72, 1.0),2)
        self.root.attributes('-alpha', self.opacity)
        self.save_prefs()
        self.draw()

    def configure_alert(self):
        amount = simpledialog.askfloat('Codex Pulse — alerta',
            'Alertar quando o custo equivalente estimado da faixa ultrapassar quantos US$?\n'
            'Digite 0 para desativar o alerta.\n'
            '(Não é cobrança real.)', initialvalue=self.alert_cost, minvalue=0, parent=self.root)
        if amount is not None:
            self.alert_cost = round(amount,4)
            self.save_prefs()
            self.draw()

    def quit(self):
        self.closed = True
        self.save_prefs()
        if self.dashboard_process and self.dashboard_process.poll() is None:
            self.dashboard_process.terminate()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def refresh_loop(self):
        if self.closed:
            return
        if self.future is None:
            self.future = self.executor.submit(aggregate, self.home, self.prices, self.args.demo)
        self.root.after(round(self.args.interval*1000), self.refresh_loop)

    def read_loop(self):
        if self.closed:
            return
        if self.future is not None and self.future.done():
            try:
                self.data = self.future.result()
                self.error = None
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
            finally:
                self.future = None
                self.last_update = datetime.now().astimezone()
            self.draw()
        self.root.after(500, self.read_loop)

    def dashboard_at(self, url):
        try:
            with urlopen(url+'/api/data',timeout=.5) as res:
                payload=json.load(res)
                return isinstance(payload,dict) and 'calls' in payload and 'prompts' in payload
        except Exception:
            return False

    def open_dashboard(self):
        if self.dashboard_url:
            webbrowser.open(self.dashboard_url)
            return
        for port in range(4327,4338):
            url = f'http://127.0.0.1:{port}'
            if self.dashboard_at(url):
                self.dashboard_url = url
                webbrowser.open(url)
                return
            with socket.socket() as sock:
                try:
                    sock.bind(('127.0.0.1',port))
                except OSError:
                    continue
            argv = [sys.executable,str(BASE/'codex_pulse.py'),'--no-browser','--port',str(port),'--codex-home',str(self.home)]
            if self.args.demo:
                argv.append('--demo')
            try:
                flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if sys.platform=='win32' else 0
                self.dashboard_process=subprocess.Popen(argv,cwd=str(BASE),stdout=subprocess.DEVNULL,
                                                      stderr=subprocess.DEVNULL,creationflags=flags)
            except OSError as exc:
                messagebox.showerror('Codex Pulse',str(exc),parent=self.root)
                return
            self.dashboard_url=url
            self.root.after(850,lambda: webbrowser.open(url))
            return
        messagebox.showerror('Codex Pulse','Sem porta local disponível.',parent=self.root)

    def rect(self,x,y,x2,y2,r=12,fill=SURFACE,stroke=None,tag=()):
        r=min(r,(x2-x)/2,(y2-y)/2)
        coords=[x+r,y,x2-r,y,x2,y,x2,y+r,x2,y2-r,x2,y2,x2-r,y2,
                x+r,y2,x,y2,x,y2-r,x,y+r,x,y]
        return self.c.create_polygon(coords,fill=fill,outline=stroke or fill,width=1,
                                     smooth=True,splinesteps=14,tags=tag)

    def text(self,x,y,value,size=11,color=INK,bold=False,anchor='nw',tag=(),**kwargs):
        return self.c.create_text(x,y,text=str(value),font=(self.font,size,'bold' if bold else 'normal'),
                                  fill=color,anchor=anchor,tags=tag,**kwargs)

    def line(self,x1,y1,x2,y2,fill=EDGE,width=1):
        return self.c.create_line(x1,y1,x2,y2,fill=fill,width=width)

    def button(self,key,x,y,w,h,caption,action,fg=SUB,bg=SURFACE_2,size=11):
        tag='button-'+key
        self.rect(x,y,x+w,y+h,8,bg,tag=(tag,))
        self.text(x+w/2,y+h/2,caption,size,fg,True,'center',tag=(tag,))
        self.c.tag_bind(tag,'<Button-1>',lambda e: action())
        self.c.tag_bind(tag,'<Enter>',lambda e:self.c.configure(cursor='hand2'))
        self.c.tag_bind(tag,'<Leave>',lambda e:self.c.configure(cursor='arrow'))

    def drag_events(self):
        for event,callback in (('<ButtonPress-1>',self.start_drag),('<B1-Motion>',self.dragging),
                               ('<ButtonRelease-1>',self.save_drag)):
            self.c.tag_bind('drag',event,callback)
        self.c.tag_bind('drag','<Enter>',lambda e:self.c.configure(cursor='fleur'))
        self.c.tag_bind('drag','<Leave>',lambda e:self.c.configure(cursor='arrow'))

    def header(self):
        self.c.create_rectangle(0,0,WIDTH,62,fill=BG,outline=BG,tags=('drag',))
        self.rect(16,14,56,53,12,TEAL_SOFT,tag=('drag',))
        self.c.create_line(24,37,29,37,33,28,37,43,42,33,45,37,49,37,
                           fill=TEAL,width=2.1,capstyle='round',tags=('drag',))
        self.text(68,13,'codex',18,INK,True,tag=('drag',))
        self.text(144,13,'pulse',18,TEAL,True,tag=('drag',))
        self.text(69,38,'DESKTOP MONITOR   •   V3',8,FAINT,True,tag=('drag',))
        self.button('pin',302,16,33,32,'●' if self.topmost else '○',self.toggle_pin,
                    TEAL if self.topmost else SUB,TEAL_SOFT if self.topmost else SURFACE)
        self.button('size',339,16,33,32,{'full':'−','compact':'▱','micro':'+'}[self.mode],self.cycle_mode,INK,SURFACE)
        self.button('close',376,16,33,32,'×',self.quit,RED,'#332430',15)
        self.drag_events()

    def status(self,s):
        q=s['quota']
        caution=(q['percent'] is not None and not q['stale'] and q['percent']>=80)
        alert_cost=self.alert_cost>0 and s['cost']>=self.alert_cost and s['calls']>0
        alert=caution or alert_cost
        if s['demo']:
            name,clr='MODO DEMONSTRAÇÃO',AMBER
        elif not s['files']:
            name,clr='SEM REGISTROS ENCONTRADOS',AMBER
        elif self.error:
            name,clr='FALHA DE LEITURA',RED
        elif alert:
            name,clr='ATENÇÃO AO CONSUMO',AMBER
        else:
            name,clr='LEITURA LOCAL',TEAL
        self.c.create_oval(19,72,26,79,fill=clr,outline=clr)
        self.text(34,69,name,9,clr,True)
        self.text(407,69,age_text(s['last_dt'],datetime.now().astimezone()),9,FAINT,anchor='ne')

    def scope_tabs(self):
        entries=[('today','Hoje'),('hour','Última 1h'),('session','Sessão atual')]
        x=18
        for key,title in entries:
            w={'today':104,'hour':130,'session':142}[key]
            self.button('scope-'+key,x,93,w,33,title,lambda k=key:self.set_scope(k),
                        TEAL if self.scope==key else SUB,TEAL_SOFT if self.scope==key else SURFACE,10)
            x += w+6

    def main_card(self,s,top=137,bottom=232,compact=False):
        self.limits_card(s, top, bottom)

    def limits_card(self,s,top,bottom):
        self.rect(18,top,408,bottom,14,'#162735','#315259')
        self.text(31,top+9,'LIMITES DE USO · ÚLTIMO REGISTRO LOCAL',9,SUB,True)
        limits = self.data.get('limits') or {}
        for index, key in enumerate(('primary', 'secondary')):
            q = quota_info({'timestamp': limits.get('timestamp'), 'primary': limits.get(key)})
            y = top + 29 + index * 30
            value = 'Não informado' if q['percent'] is None else f"{q['percent']:.0f}% usado"
            state = ' · expirado' if q['expired'] else (' · antigo' if q['stale'] and q['percent'] is not None else '')
            color = AMBER if q['stale'] or q['expired'] else TEAL
            self.text(31,y,'Principal' if index == 0 else 'Secundário',10,SUB)
            self.text(393,y,value+state,10,color,True,'ne')
            self.rect(31,y+18,393,y+22,2,'#334252')
            if q['percent'] is not None and q['percent'] > 0:
                self.rect(31,y+18,31+362*q['percent']/100,y+22,2,AMBER if q['percent']>=80 else color)

    def cards(self,s):
        self.rect(18,242,209,338,12,SURFACE,EDGE)
        self.text(31,255,'CACHE DE ENTRADA',9,SUB,True)
        self.text(30,273,f"{s['cache_percent']:.1f}%".replace('.',','),25,INK,True)
        self.rect(31,317,195,324,3,'#344255')
        if s['cache_percent']>0:
            self.rect(31,317,31+164*s['cache_percent']/100,324,3,TEAL)
        self.rect(219,242,408,338,12,SURFACE,EDGE)
        self.text(231,255,'ÚLTIMA CHAMADA',9,SUB,True)
        last=s['latest']
        if last:
            value=money(last.get('cost'))
        else:
            value='—'
        self.text(230,274,value,18 if len(value)<17 else 14,INK,True)
        self.text(231,316,f"{number((last or {}).get('total'))} tokens · {local_time((last or {}).get('timestamp'))}",10,SUB)

    def chart(self,s):
        self.rect(18,349,408,434,12,SURFACE,EDGE)
        self.text(31,359,'CONSUMO DISTRIBUÍDO',9,SUB,True)
        self.text(393,359,'TOKENS',8,FAINT,True,'ne')
        series=timeline(s['selected'],datetime.now().astimezone(),self.scope,18)
        high=max(series) if series else 0
        x0,y0,step,barw=32,411,20.5,10
        for i,value in enumerate(series):
            h=round(39*value/high) if high and value else 3
            color=TEAL if value>0 else '#2a3c4e'
            self.rect(x0+i*step,y0-h,x0+i*step+barw,y0,3,color)
        title={'today':'00h → agora','hour':'60 minutos → agora','session':'início da sessão → agora'}[self.scope]
        self.text(32,415,title,8,FAINT)

    def prompt(self,s):
        self.rect(18,445,408,520,12,SURFACE,EDGE)
        self.text(31,455,'ÚLTIMO PROMPT',9,SUB,True)
        self.button('privacy',365,451,27,24,'◉' if self.show_prompt else '◌',self.toggle_prompt,
                    TEAL if self.show_prompt else SUB,SURFACE_2,11)
        last=s['latest']
        if last:
            group=s['prompt'] or {}
            raw=str(group.get('prompt') or '')
            if self.show_prompt and raw and raw!='(prompt não registrado)':
                summary=raw[:52]+('…' if len(raw)>52 else '')
            else:
                summary='Texto oculto · clique para revelar'
            self.text(31,480,summary,10,INK)
            self.text(31,503,f"{project_name(last.get('project'))[:22]} · {str(last.get('model') or '')[:22]}",9,TEAL)
        else:
            self.text(31,485,'Aguardando chamadas do Codex…',11,SUB)

    def toggle_prompt(self):
        self.show_prompt=not self.show_prompt
        self.draw()

    def quota_card(self,s):
        self.rect(18,532,408,584,12,SURFACE,EDGE)
        q=s['quota']
        self.text(31,543,q['label'].upper(),9,SUB,True)
        if q['expired']:
            desc='Registro expirado'
        elif q['percent'] is None:
            desc='Não informado'
        else:
            desc=f"{q['percent']:.0f}% registrado" + (' · antigo' if q['stale'] else '')
        self.text(392,542,desc,10,AMBER if q['stale'] or q['expired'] else INK,True,'ne')
        self.rect(32,568,393,576,4,'#334252')
        if q['percent'] is not None and q['percent']>0:
            width=361*q['percent']/100
            self.rect(32,568,32+width,576,4,AMBER if q['percent']>=80 else TEAL)

    def footer(self,top):
        self.line(18,top-5,408,top-5)
        self.text(20,top+10,'OPACIDADE',8,FAINT,True)
        self.button('fade-',102,top+5,25,28,'−',lambda:self.opacity_by(-.07),INK,SURFACE,12)
        self.text(143,top+19,f'{round(self.opacity*100)}%',9,SUB,anchor='center')
        self.button('fade+',172,top+5,25,28,'+',lambda:self.opacity_by(.07),INK,SURFACE,12)
        self.button('alert',205,top+5,28,28,'!',self.configure_alert,AMBER,SURFACE,12)
        self.button('dashboard',241,top+5,167,28,'Dashboard completo  ↗',self.open_dashboard,TEAL,TEAL_SOFT,10)
        self.text(19,top+42,'* Valores estimados; nunca fatura da assinatura · dados locais',8,FAINT)

    def compact_content(self,s):
        self.main_card(s,77,177,compact=True)
        self.line(18,187,408,187)
        self.text(21,195,'FAIXA:',8,FAINT,True)
        self.button('scope-short',72,192,99,29,{'today':'Hoje','hour':'Última 1h','session':'Sessão'}[self.scope],
                    lambda:self.set_scope({'today':'hour','hour':'session','session':'today'}[self.scope]),TEAL,TEAL_SOFT,10)
        self.button('alert-short',180,192,28,29,'!',self.configure_alert,AMBER,SURFACE,11)
        self.button('dash-short',217,192,190,29,'Dashboard completo ↗',self.open_dashboard,TEAL,TEAL_SOFT,10)
        self.text(19,221,'Custo equivalente à API, não cobrança real.',8,FAINT)

    def micro_content(self,s):
        if s['unknown_costs']==s['calls'] and s['calls']:
            cost='Sem tarifa'
        else:
            cost=money(s['cost'],s['unknown_costs']>0)
        q=s['quota']
        value='Limite indisponível' if q['percent'] is None else f"{q['percent']:.0f}% usado"
        if q['expired']:
            value += ' · expirado'
        elif q['stale'] and q['percent'] is not None:
            value += ' · antigo'
        self.text(19,77,value,13,AMBER if q['stale'] or q['expired'] else INK,True)
        self.text(407,80,f"{number(s['tokens'])} tok · {s['calls']} calls",10,TEAL,True,'ne')
        self.line(18,103,408,103,'#334251')

    def draw(self):
        if self.closed:
            return
        self.c.delete('all')
        if self.mode == 'micro':
            self.discreet_content()
            return
        self.header()
        if self.data is None:
            self.c.create_oval(19,73,26,80,fill=AMBER,outline=AMBER)
            self.text(34,69,'CARREGANDO REGISTROS LOCAIS',9,AMBER,True)
            if self.mode!='micro':
                self.text(23,114,'Nenhum dado é enviado para a internet.',10,SUB)
                if self.error:
                    self.text(23,135,self.error[:53],9,RED)
            return
        s=summarize(self.data,scope=self.scope)
        if self.mode=='micro':
            self.micro_content(s)
            return
        self.status(s)
        if self.mode=='compact':
            self.compact_content(s)
            return
        self.scope_tabs()
        self.main_card(s)
        self.cards(s)
        self.chart(s)
        self.prompt(s)
        self.quota_card(s)
        self.footer(593)

    def discreet_content(self):
        self.c.create_rectangle(0,0,310,33,fill=BG,outline=BG,tags=('drag',))
        self.text(12,10,'pulse',11,TEAL,True,tag=('drag',))
        self.button('pin',188,5,25,23,'●' if self.topmost else '○',self.toggle_pin,TEAL,SURFACE,9)
        self.button('expand',218,5,25,23,'+',self.cycle_mode,INK,SURFACE,10)
        self.button('dashboard',248,5,25,23,'↗',self.open_dashboard,TEAL,SURFACE,10)
        self.button('close',278,5,23,23,'×',self.quit,SUB,SURFACE,10)
        self.drag_events()
        if self.data is None:
            self.text(12,48,'Lendo registros locais…',10,SUB)
            if self.error:
                self.text(12,75,'Falha de leitura · tentando novamente',9,AMBER)
            return
        latest=max(self.data.get('calls') or [],key=lambda c:c.get('timestamp') or '',default={})
        model=latest.get('model') or 'Modelo não informado'
        self.text(12,38,model,10,INK,True,width=285)
        limits=self.data.get('limits') or {}
        for index,key in enumerate(('primary','secondary')):
            raw=limits.get(key) or {}
            q=quota_info({'timestamp':limits.get('timestamp'),'primary':raw})
            y=65+index*43
            label=q['label'] if raw else ('Principal' if index==0 else 'Secundário')
            value='Não informado' if q['percent'] is None else f"{q['percent']:.0f}% usado"
            if q['expired']: value='Registro expirado'
            elif q['stale'] and q['percent'] is not None: value+=' · antigo'
            color=AMBER if q['stale'] or q['expired'] or (q['percent'] or 0)>=80 else TEAL
            self.text(12,y,label,9,SUB)
            self.text(298,y,value,9,color,True,'ne')
            self.rect(12,y+17,298,y+20,1,EDGE)
            if q['percent']:
                self.rect(12,y+17,12+286*q['percent']/100,y+20,1,color)
            reset=raw.get('resets_at')
            try:
                if reset is None and raw.get('resets_in_seconds') is not None and q.get('measured'):
                    reset=q['measured'].timestamp()+float(raw['resets_in_seconds'])
                date=datetime.fromtimestamp(float(reset)).strftime('%d/%m %H:%M') if reset is not None else 'não informada'
            except (ValueError,TypeError,OverflowError,OSError):
                date='não informada'
            self.text(12,y+24,'Renova em '+date,8,FAINT)
        note='Dados fictícios' if self.data.get('demo') else 'Modelo da última chamada · limites registrados'
        if self.error: note='Falha de leitura · exibindo último registro'
        self.text(12,156,note,8,FAINT)


def run(argv=None):
    parser=argparse.ArgumentParser(description='Codex Pulse v3 — widget flutuante local')
    parser.add_argument('--demo',action='store_true',help='Dados fictícios para testar a interface')
    parser.add_argument('--codex-home',default=os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    parser.add_argument('--interval',type=float,default=REFRESH_SECONDS,help='Atualização em segundos; mínimo 2')
    parser.add_argument('--opacity',type=float,default=.97)
    args=parser.parse_args(argv)
    if not math.isfinite(args.interval) or args.interval<2:
        parser.error('--interval deve ser no mínimo 2 segundos')
    root=None
    try:
        root=tk.Tk()
        Overlay(root,args)
        root.mainloop()
    except Exception as exc:
        print(f'Falha ao executar a janela flutuante: {exc}',file=sys.stderr)
        if root:
            try: root.destroy()
            except tk.TclError: pass
        raise


if __name__=='__main__':
    run()
