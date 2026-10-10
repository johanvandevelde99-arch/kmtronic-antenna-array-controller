#!/usr/bin/env python3
"""
9 Circle Array - KMTronic 8-Relay Controller (standalone desktop app)

A native, standalone version of the browser-based 9CA controller. Talks to
the KMTronic web-relay board directly over HTTP from Python, so there is no
browser, no CORS/mixed-content/login restriction to work around.

Requires only the Python standard library (tkinter + urllib), so it runs
with a plain `python 9CA_KMTronic_Controller.py`, and can be frozen into a
single .exe with PyInstaller:

    pip install pyinstaller
    pyinstaller --onefile --windowed --name "9CA Controller" 9CA_KMTronic_Controller.py

The .exe will be in the dist/ folder. --windowed hides the console window.

73 ON4IQ
"""

import base64
import json
import math
import os
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

APP_TITLE = "9 Circle Array · KMTronic 8-Relay · 73 ON4IQ"

# ── Config location (next to the exe/script, so settings travel with it) ──
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(APP_DIR, '9ca_cfg.json')

DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
ANGLES = {'N': 0, 'NE': 45, 'E': 90, 'SE': 135, 'S': 180, 'SW': 225, 'W': 270, 'NW': 315}
BEAM_HALF = 22.5

DEFAULT_PATTERNS = {
    'N':  [1, 0, 0, 0],
    'NE': [0, 1, 0, 0],
    'E':  [1, 1, 0, 0],
    'SE': [0, 0, 1, 0],
    'S':  [1, 0, 1, 0],
    'SW': [0, 1, 1, 0],
    'W':  [1, 1, 1, 0],
    'NW': [0, 0, 0, 1],
}
DEFAULT_AUX_LABELS = ['BPF 1', 'BPF 2', 'AUX 3', 'AUX 4']

# Default color each direction's button/arrow/wedge use when it's the active
# direction. One shared blue by default; customisable per-direction in Settings.
DEFAULT_DIR_COLORS = {d: '#0055cc' for d in DIRS}
DEFAULT_AUX_COLORS = ['#006600', '#006600', '#006600', '#006600']  # relays 5-8, when ON
DEFAULT_OFF_COLOR = '#cc0000'  # ALL OFF button

DEFAULT_THEME = {
    'appBg': '#f0f0f0',       # window background
    'canvasBg': '#ffffff',    # compass background
    'ringColor': '#cccccc',   # compass outer ring
    'wedgeColor': '#dbe8fa',  # shaded triangular beam behind the arrow
}

DEFAULT_CFG = {
    'transport': 'udp',    # 'udp' (port 12345, no login) or 'http' (web interface)
    'host': '192.168.2.190',
    'port': 12345,         # UDP default; 80 is typical for HTTP
    'user': 'admin',
    'password': 'admin',
    'mode': 'ff',          # HTTP only: 'ff' = /FF0101 direct on/off, 'toggle' = /relays.cgi?relay=N
    'demo': True,
    'offset': 0,
    'dirPatterns': DEFAULT_PATTERNS,
    'auxLabels': DEFAULT_AUX_LABELS,
    'dirColors': DEFAULT_DIR_COLORS,
    'auxColors': DEFAULT_AUX_COLORS,
    'offColor': DEFAULT_OFF_COLOR,
    'theme': DEFAULT_THEME,
}


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULT_CFG))  # deep copy
    try:
        with open(CFG_PATH, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        cfg.update(saved)
        if 'dirPatterns' not in saved:
            cfg['dirPatterns'] = DEFAULT_PATTERNS
        if 'dirColors' not in saved:
            cfg['dirColors'] = dict(DEFAULT_DIR_COLORS)
        else:
            # fill in any direction missing a saved color (e.g. older config file)
            for d in DIRS:
                cfg['dirColors'].setdefault(d, DEFAULT_DIR_COLORS[d])
        if 'auxColors' not in saved or len(cfg.get('auxColors', [])) < 4:
            cfg['auxColors'] = list(DEFAULT_AUX_COLORS)
        if 'offColor' not in saved:
            cfg['offColor'] = DEFAULT_OFF_COLOR
        if 'theme' not in saved:
            cfg['theme'] = dict(DEFAULT_THEME)
        else:
            for k, v in DEFAULT_THEME.items():
                cfg['theme'].setdefault(k, v)
        if 'auxLabels' not in saved:
            cfg['auxLabels'] = DEFAULT_AUX_LABELS
    except (OSError, ValueError):
        pass
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────────
# KMTronic comms (runs in a background thread, never blocks the UI)
# Supports two transports:
#   - UDP (the original KMTronic UDP boards): send the ASCII command
#     ("FF0101" etc) as raw bytes in one UDP packet to the board's UDP port
#     (12345 by default). No login. Status is read by sending "FF0000" and
#     parsing the ASCII reply the board sends back.
#   - HTTP (KMTronic WEB boards): GET requests to the board's web server,
#     optionally with Basic auth.
# ──────────────────────────────────────────────────────────────────────────
class KMTronic:
    def __init__(self, cfg_getter, log):
        self.cfg_getter = cfg_getter
        self.log = log

    # ---------- HTTP ----------
    def _base_url(self):
        cfg = self.cfg_getter()
        port = cfg.get('port') or 80
        p = '' if port in (80, '', None) else f':{port}'
        return f"http://{cfg['host']}{p}"

    def _auth_header(self):
        cfg = self.cfg_getter()
        user = cfg.get('user', '')
        pw = cfg.get('password', '')
        token = base64.b64encode(f'{user}:{pw}'.encode()).decode()
        return f'Basic {token}'

    def _http_get(self, path):
        cfg = self.cfg_getter()
        url = f"{self._base_url()}/{path}"
        if cfg.get('demo'):
            self.log(f"[DEMO] GET {url}")
            time.sleep(0.05)
            return True, None
        req = urllib.request.Request(url, headers={'Authorization': self._auth_header()})
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                return True, r.read()
        except urllib.error.HTTPError as e:
            # Some KMTronic firmware answers /FF0101 with 404 even though the
            # relay switches fine, so any HTTP response counts as reaching
            # the board.
            self.log(f"GET {url} -> HTTP {e.code} (command still applied)")
            return True, e.read()
        except Exception as e:
            self.log(f"ERROR reaching board: {e}")
            return False, None

    # ---------- UDP ----------
    def _udp_send(self, command, expect_reply=False, reply_size=64, timeout=1.5):
        """Send an ASCII command (e.g. 'FF0101') as raw bytes in one UDP
        packet. Optionally wait briefly for a reply (used for status reads).
        Returns (ok, reply_bytes_or_None)."""
        cfg = self.cfg_getter()
        host = cfg['host']
        port = int(cfg.get('port') or 12345)
        if cfg.get('demo'):
            self.log(f"[DEMO] UDP -> {host}:{port}  {command}")
            time.sleep(0.05)
            return True, None
        try:
            sock_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock_.settimeout(timeout)
            sock_.sendto(command.encode('ascii'), (host, port))
            reply = None
            if expect_reply:
                try:
                    reply, _ = sock_.recvfrom(reply_size)
                except socket.timeout:
                    self.log(f"UDP {command} sent, no reply within {timeout}s "
                              f"(command may still have been applied)")
            sock_.close()
            self.log(f"UDP -> {host}:{port}  {command}")
            return True, reply
        except Exception as e:
            self.log(f"ERROR sending UDP to {host}:{port}: {e}")
            return False, None

    # ---------- transport-agnostic ----------
    @staticmethod
    def relay_command(relay_num, state):
        return f"FF{relay_num:02X}{'01' if state else '00'}"

    def send_relay(self, relay_num, state, relay_state):
        cfg = self.cfg_getter()
        transport = cfg.get('transport', 'udp')
        if transport == 'udp':
            ok, _ = self._udp_send(self.relay_command(relay_num, state))
        else:
            if cfg.get('mode') == 'toggle':
                if relay_state[relay_num - 1] == state:
                    return True
                ok, _ = self._http_get(f"relays.cgi?relay={relay_num}")
            else:
                ok, _ = self._http_get(self.relay_command(relay_num, state))
        if ok:
            relay_state[relay_num - 1] = state
        return ok

    def all_off(self, relay_state):
        cfg = self.cfg_getter()
        if cfg.get('transport', 'udp') == 'udp':
            ok, _ = self._udp_send('FFE000')
            if ok:
                for i in range(8):
                    relay_state[i] = False
            return ok
        for i in range(1, 9):
            if not self.send_relay(i, False, relay_state):
                return False
        return True

    def read_status(self):
        """Returns a list of 8 booleans, or None if unreadable/demo."""
        cfg = self.cfg_getter()
        if cfg.get('demo'):
            return None
        if cfg.get('transport', 'udp') == 'udp':
            ok, reply = self._udp_send('FF0000', expect_reply=True)
            if not ok or not reply:
                return None
            # Boards reply with an ASCII string of 8 '0'/'1' digits (relay 1..8),
            # sometimes with extra framing bytes around it; pull out the digits.
            text = ''.join(ch for ch in reply.decode('ascii', errors='ignore') if ch in '01')
            if len(text) < 8:
                return None
            return [c == '1' for c in text[:8]]
        ok, body = self._http_get('status.xml')
        if not ok or not body:
            return None
        try:
            root = ET.fromstring(body)
            st = []
            for i in range(8):
                node = root.find(f'relay{i}')
                st.append(bool(node is not None and node.text and node.text.strip() == '1'))
            return st
        except ET.ParseError:
            return None


# ──────────────────────────────────────────────────────────────────────────
# Main application
# ──────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(False, False)
        self.configure(bg='#f0f0f0')

        self.cfg = load_cfg()
        self.active_dir = None
        self.relay_state = [False] * 8
        self.conn_ok = None  # None = not tried yet, True = last command succeeded, False = failed
        self.km = KMTronic(lambda: self.cfg, self.log_line)
        self._busy = False

        self._build_ui()
        self._apply_cfg_to_widgets()
        self._update_ui()
        self._shrink_to_fit()
        self._poll_status()

    # ── logging to the small status line ──
    def log_line(self, msg):
        print(msg)

    def _build_menu(self):
        menubar = tk.Menu(self)
        view_menu = tk.Menu(menubar, tearoff=0)
        # Independent on/off toggles rather than mutually-exclusive radio
        # choices, so any combination (e.g. matrix + aux, no compass) works.
        self.view_compass_var = tk.BooleanVar(value=True)
        self.view_matrix_var = tk.BooleanVar(value=True)
        self.view_aux_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label='Compass', variable=self.view_compass_var,
                                   command=self._apply_view_mode)
        view_menu.add_checkbutton(label='Matrix', variable=self.view_matrix_var,
                                   command=self._apply_view_mode)
        view_menu.add_checkbutton(label='Aux Relays', variable=self.view_aux_var,
                                   command=self._apply_view_mode)
        menubar.add_cascade(label='View', menu=view_menu)
        self.config(menu=menubar)

    def _apply_view_mode(self):
        # Relay dots travel with the matrix (same info, same spot).
        (self.canvas.grid() if self.view_compass_var.get() else self.canvas.grid_remove())
        if self.view_matrix_var.get():
            self.matrix_frame.grid()
            self.dotrow.grid()
        else:
            self.matrix_frame.grid_remove()
            self.dotrow.grid_remove()
        (self.aux_frame.grid() if self.view_aux_var.get() else self.aux_frame.grid_remove())
        self._shrink_to_fit()

    def _shrink_to_fit(self):
        """Resize the whole window down to whatever space the now-visible
        widgets actually need, instead of leaving blank space behind.

        Tk otherwise silently treats a window's first displayed size as its
        minimum size, which blocks any later shrink — so that minimum is
        cleared every time before asking Tk to recompute the natural size.
        """
        self.minsize(1, 1)
        self.update_idletasks()
        self.geometry('')  # drop any fixed size, let Tk recompute from content

    # ── layout ──
    def _build_ui(self):
        self._build_menu()

        # A plain Frame swap instead of ttk.Notebook: a Notebook always sizes
        # itself to the LARGEST of all its tabs (even hidden ones), so the
        # window would stay oversized to fit Settings even while only the
        # smaller Control tab is shown and shrunk. With a manual swap, only
        # the currently-visible tab's frame is ever gridded, so the window's
        # natural size reflects just that one tab.
        tabbar = ttk.Frame(self)
        tabbar.pack(fill='x', padx=8, pady=(8, 0))
        self.tab_btn_control = tk.Button(tabbar, text='Control', relief='sunken',
                                          command=lambda: self._show_tab('control'))
        self.tab_btn_settings = tk.Button(tabbar, text='Settings', relief='raised',
                                           command=lambda: self._show_tab('settings'))
        self.tab_btn_control.pack(side='left', padx=(0, 4))
        self.tab_btn_settings.pack(side='left')

        container = ttk.Frame(self)
        container.pack(fill='both', expand=True, padx=8, pady=8)
        self.tab_main = ttk.Frame(container)
        self.tab_settings = ttk.Frame(container)

        self._build_main_tab(self.tab_main)
        self._build_settings_tab(self.tab_settings)

        self.tab_main.grid(row=0, column=0, sticky='n')
        self._current_tab = 'control'

        # status / toast bar
        self.status_var = tk.StringVar(value='Ready')
        bar = ttk.Label(self, textvariable=self.status_var, anchor='w',
                         relief='sunken', padding=(6, 3))
        bar.pack(fill='x', side='bottom')

    def _show_tab(self, which):
        if which == self._current_tab:
            return
        self._current_tab = which
        if which == 'control':
            self.tab_settings.grid_forget()
            self.tab_main.grid(row=0, column=0, sticky='n')
            self.tab_btn_control.config(relief='sunken')
            self.tab_btn_settings.config(relief='raised')
        else:
            self.tab_main.grid_forget()
            self.tab_settings.grid(row=0, column=0, sticky='n')
            self.tab_btn_control.config(relief='raised')
            self.tab_btn_settings.config(relief='sunken')
        self._shrink_to_fit()

    def _build_main_tab(self, root):
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky='n')

        # Compass canvas — gridded (not packed) so it can be shown/hidden
        # independently of the matrix below via the View menu, without
        # disturbing the vertical order of the other widgets.
        self.canvas = tk.Canvas(left, width=150, height=150, bg='white',
                                 highlightthickness=1, highlightbackground='#cccccc')
        self.canvas.grid(row=0, column=0)
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        # Mouse wheel over the compass steps through the 8 directions.
        # Windows/Mac fire <MouseWheel> with event.delta; Linux fires
        # <Button-4>/<Button-5> instead — both are bound so it works
        # wherever the app runs.
        self.canvas.bind('<MouseWheel>', self._on_canvas_scroll)
        self.canvas.bind('<Button-4>', self._on_canvas_scroll)
        self.canvas.bind('<Button-5>', self._on_canvas_scroll)

        # 3x3 direction grid ("the matrix")
        self.matrix_frame = ttk.Frame(left)
        self.matrix_frame.grid(row=1, column=0, pady=(10, 0))
        layout = ['NW', 'N', 'NE', 'W', 'OFF', 'E', 'SW', 'S', 'SE']
        self.dir_buttons = {}
        for idx, d in enumerate(layout):
            r, c = divmod(idx, 3)
            if d == 'OFF':
                self.off_btn = tk.Button(self.matrix_frame, text='ALL\nOFF', width=3, height=1,
                                          fg=self.cfg['offColor'], font=('Courier New', 6, 'bold'),
                                          command=self.all_off)
                self.off_btn.grid(row=r, column=c, padx=2, pady=2)
                continue
            b = tk.Button(self.matrix_frame, text=d, width=3, height=1,
                          font=('Courier New', 9, 'bold'),
                          command=lambda dd=d: self.select_dir(dd))
            b.grid(row=r, column=c, padx=2, pady=2)
            self.dir_buttons[d] = b

        # Relay 1-4 indicator dots (half size), grouped with the matrix since
        # they sit right under it and show the same relay info
        self.dotrow = ttk.Frame(left)
        self.dotrow.grid(row=2, column=0, pady=(8, 0))
        self.relay_dots = []
        for i in range(4):
            col = ttk.Frame(self.dotrow)
            col.grid(row=0, column=i, padx=2)
            dot = tk.Canvas(col, width=14, height=14, highlightthickness=0, bg='#f0f0f0')
            circle = dot.create_oval(1, 1, 13, 13, fill='#e0e0e0', outline='#cccccc')
            dot.pack()
            ttk.Label(col, text=f'R{i+1}', font=('Courier New', 6)).pack()
            self.relay_dots.append((dot, circle))

        # Aux relay box — stacked below the matrix/dots in the same column,
        # shown/hidden independently via the View menu.
        self.aux_frame = ttk.LabelFrame(left, text='AUX RELAYS (5–8)')
        self.aux_frame.grid(row=3, column=0, pady=(10, 0))
        self.aux_buttons = []
        for i in range(4):
            colf = ttk.Frame(self.aux_frame)
            colf.grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky='ew')
            b = tk.Button(colf, text=self.cfg['auxLabels'][i], width=7,
                          font=('Courier New', 8, 'bold'),
                          command=lambda ii=i: self.toggle_aux(ii))
            b.pack()
            ttk.Label(colf, text=f'R{i+5}', font=('Courier New', 7)).pack()
            self.aux_buttons.append(b)

    def _build_settings_tab(self, root):
        pad = {'padx': 6, 'pady': 4}

        conn = ttk.LabelFrame(root, text='Connection')
        conn.pack(fill='x', padx=4, pady=6)

        self.var_transport = tk.StringVar()
        self.var_host = tk.StringVar()
        self.var_port = tk.StringVar()
        self.var_user = tk.StringVar()
        self.var_pass = tk.StringVar()
        self.var_mode = tk.StringVar()
        self.var_demo = tk.BooleanVar()
        self.var_offset = tk.StringVar()

        def row(parent, r, label, widget):
            ttk.Label(parent, text=label, width=10).grid(row=r, column=0, sticky='w', **pad)
            widget.grid(row=r, column=1, sticky='ew', **pad)

        conn.columnconfigure(1, weight=1)
        transport_combo = ttk.Combobox(conn, textvariable=self.var_transport, state='readonly',
                                        values=['udp', 'http'])
        transport_combo.bind('<<ComboboxSelected>>', lambda e: self._update_transport_visibility())
        row(conn, 0, 'Transport', transport_combo)
        ttk.Label(conn, text='  udp = classic KMTronic UDP board (port 12345, no login)\n'
                              '  http = KMTronic WEB board (web interface, login)',
                  font=('Courier New', 7), foreground='#666666', justify='left').grid(
            row=1, column=0, columnspan=2, sticky='w', padx=6)
        row(conn, 2, 'Host / IP', ttk.Entry(conn, textvariable=self.var_host))
        row(conn, 3, 'Port', ttk.Entry(conn, textvariable=self.var_port))

        self.lbl_user = ttk.Label(conn, text='Username', width=10)
        self.ent_user = ttk.Entry(conn, textvariable=self.var_user)
        self.lbl_pass = ttk.Label(conn, text='Password', width=10)
        self.ent_pass = ttk.Entry(conn, textvariable=self.var_pass, show='*')
        self.lbl_user.grid(row=4, column=0, sticky='w', **pad)
        self.ent_user.grid(row=4, column=1, sticky='ew', **pad)
        self.lbl_pass.grid(row=5, column=0, sticky='w', **pad)
        self.ent_pass.grid(row=5, column=1, sticky='ew', **pad)

        self.lbl_mode = ttk.Label(conn, text='Mode', width=10)
        self.mode_combo = ttk.Combobox(conn, textvariable=self.var_mode, state='readonly',
                                        values=['ff', 'toggle'])
        self.lbl_mode.grid(row=6, column=0, sticky='w', **pad)
        self.mode_combo.grid(row=6, column=1, sticky='ew', **pad)
        self.lbl_mode_hint = ttk.Label(
            conn, text='  ff = /FF0101 direct on/off   ·   toggle = /relays.cgi?relay=N',
            font=('Courier New', 7), foreground='#666666')
        self.lbl_mode_hint.grid(row=7, column=0, columnspan=2, sticky='w', padx=6)

        ttk.Checkbutton(conn, text='Demo mode (no hardware)', variable=self.var_demo).grid(
            row=8, column=0, columnspan=2, sticky='w', padx=6, pady=(6, 2))
        row(conn, 9, 'Offset °', ttk.Entry(conn, textvariable=self.var_offset))

        # Direction pattern matrix
        pat = ttk.LabelFrame(root, text='Direction → Relay (1-4) pattern')
        pat.pack(fill='x', padx=4, pady=6)
        ttk.Label(pat, text='Dir', font=('Courier New', 8, 'bold')).grid(row=0, column=0)
        for i in range(4):
            ttk.Label(pat, text=f'R{i+1}', font=('Courier New', 8, 'bold')).grid(row=0, column=i + 1)
        ttk.Label(pat, text='Color', font=('Courier New', 8, 'bold')).grid(row=0, column=5)
        self.pattern_vars = {}
        self.dir_color_vars = {}
        self.dir_color_swatches = {}
        for r, d in enumerate(DIRS, start=1):
            ttk.Label(pat, text=d, font=('Courier New', 9, 'bold'), foreground='#0055cc').grid(
                row=r, column=0, padx=4, pady=2, sticky='w')
            vars4 = []
            for i in range(4):
                v = tk.BooleanVar()
                ttk.Checkbutton(pat, variable=v).grid(row=r, column=i + 1, padx=4)
                vars4.append(v)
            self.pattern_vars[d] = vars4

            self.dir_color_vars[d] = tk.StringVar(value=self.cfg['dirColors'][d])
            swatch = tk.Button(pat, width=3, relief='raised',
                                command=lambda dd=d: self._pick_dir_color(dd))
            swatch.grid(row=r, column=5, padx=4, pady=2)
            self.dir_color_swatches[d] = swatch

        # Aux labels + ON color
        auxf = ttk.LabelFrame(root, text='Aux relays (5-8): label and ON color')
        auxf.pack(fill='x', padx=4, pady=6)
        self.aux_label_vars = []
        self.aux_color_vars = []
        self.aux_color_swatches = []
        for i in range(4):
            ttk.Label(auxf, text=f'R{i+5}', font=('Courier New', 8, 'bold'),
                      foreground='#0055cc').grid(row=i, column=0, padx=4, pady=3, sticky='w')
            v = tk.StringVar()
            ttk.Entry(auxf, textvariable=v, width=14).grid(row=i, column=1, padx=4, pady=3)
            self.aux_label_vars.append(v)

            cv = tk.StringVar(value=self.cfg['auxColors'][i])
            swatch = tk.Button(auxf, width=3, relief='raised',
                                command=lambda ii=i: self._pick_aux_color(ii))
            swatch.grid(row=i, column=2, padx=4, pady=3)
            self.aux_color_vars.append(cv)
            self.aux_color_swatches.append(swatch)

        # ALL OFF button color
        offf = ttk.LabelFrame(root, text='ALL OFF button color')
        offf.pack(fill='x', padx=4, pady=6)
        self.off_color_var = tk.StringVar(value=self.cfg['offColor'])
        self.off_color_swatch = tk.Button(offf, width=3, relief='raised',
                                           command=self._pick_off_color)
        ttk.Label(offf, text='Color', font=('Courier New', 8, 'bold')).grid(
            row=0, column=0, padx=4, pady=3, sticky='w')
        self.off_color_swatch.grid(row=0, column=1, padx=4, pady=3)

        # Theme (window / compass background, ring, wedge)
        themef = ttk.LabelFrame(root, text='Theme')
        themef.pack(fill='x', padx=4, pady=6)
        theme_items = [
            ('appBg', 'App background'),
            ('canvasBg', 'Compass background'),
            ('ringColor', 'Compass ring'),
            ('wedgeColor', 'Shaded wedge'),
        ]
        self.theme_vars = {}
        self.theme_swatches = {}
        for r, (key, label) in enumerate(theme_items):
            ttk.Label(themef, text=label, font=('Courier New', 8)).grid(
                row=r, column=0, padx=4, pady=3, sticky='w')
            v = tk.StringVar(value=self.cfg['theme'][key])
            swatch = tk.Button(themef, width=3, relief='raised',
                                command=lambda k=key: self._pick_theme_color(k))
            swatch.grid(row=r, column=1, padx=4, pady=3)
            self.theme_vars[key] = v
            self.theme_swatches[key] = swatch

        apply_btn = tk.Button(root, text='Apply & Save', bg='#0055cc', fg='white',
                               font=('Courier New', 9, 'bold'), command=self.apply_settings)
        apply_btn.pack(fill='x', padx=4, pady=10)

    # ── sync widgets from self.cfg ──
    def _apply_cfg_to_widgets(self):
        c = self.cfg
        self.var_transport.set(c.get('transport', 'udp'))
        self.var_host.set(c['host'])
        self.var_port.set(str(c['port']))
        self.var_user.set(c.get('user', 'admin'))
        self.var_pass.set(c.get('password', 'admin'))
        self.var_mode.set(c.get('mode', 'ff'))
        self.var_demo.set(bool(c['demo']))
        self.var_offset.set(str(c.get('offset', 0)))
        for d in DIRS:
            pat = c['dirPatterns'].get(d, [0, 0, 0, 0])
            for i, v in enumerate(self.pattern_vars[d]):
                v.set(bool(pat[i]))
            color = c['dirColors'].get(d, DEFAULT_DIR_COLORS[d])
            self.dir_color_vars[d].set(color)
            self.dir_color_swatches[d].config(bg=color)
        for i, v in enumerate(self.aux_label_vars):
            v.set(c['auxLabels'][i])
        for i in range(4):
            color = c['auxColors'][i]
            self.aux_color_vars[i].set(color)
            self.aux_color_swatches[i].config(bg=color)
        self.off_color_var.set(c['offColor'])
        self.off_color_swatch.config(bg=c['offColor'])
        for key, v in self.theme_vars.items():
            color = c['theme'][key]
            v.set(color)
            self.theme_swatches[key].config(bg=color)
        self._update_badge()
        self._update_transport_visibility()

    def _pick_dir_color(self, d):
        current = self.dir_color_vars[d].get()
        _, hex_color = colorchooser.askcolor(color=current, title=f'Color for {d}')
        if hex_color:
            self.dir_color_vars[d].set(hex_color)
            self.dir_color_swatches[d].config(bg=hex_color)

    def _pick_aux_color(self, i):
        current = self.aux_color_vars[i].get()
        _, hex_color = colorchooser.askcolor(color=current, title=f'ON color for R{i+5}')
        if hex_color:
            self.aux_color_vars[i].set(hex_color)
            self.aux_color_swatches[i].config(bg=hex_color)

    def _pick_off_color(self):
        current = self.off_color_var.get()
        _, hex_color = colorchooser.askcolor(color=current, title='ALL OFF button color')
        if hex_color:
            self.off_color_var.set(hex_color)
            self.off_color_swatch.config(bg=hex_color)

    def _pick_theme_color(self, key):
        current = self.theme_vars[key].get()
        _, hex_color = colorchooser.askcolor(color=current, title=key)
        if hex_color:
            self.theme_vars[key].set(hex_color)
            self.theme_swatches[key].config(bg=hex_color)

    def _update_transport_visibility(self):
        is_http = self.var_transport.get() == 'http'
        widgets = [self.lbl_user, self.ent_user, self.lbl_pass, self.ent_pass,
                   self.lbl_mode, self.mode_combo, self.lbl_mode_hint]
        for w in widgets:
            if is_http:
                w.grid()
            else:
                w.grid_remove()
        # sensible default port per transport, only if the user hasn't customised it
        if is_http and self.var_port.get() in ('', '12345'):
            self.var_port.set('80')
        elif not is_http and self.var_port.get() in ('', '80'):
            self.var_port.set('12345')

    def apply_settings(self):
        host = self.var_host.get().strip()
        try:
            port = int(self.var_port.get().strip())
        except ValueError:
            messagebox.showerror('Invalid', 'Port must be a number.')
            return
        try:
            offset = float(self.var_offset.get().strip() or 0)
        except ValueError:
            messagebox.showerror('Invalid', 'Offset must be a number.')
            return
        if not host:
            messagebox.showerror('Invalid', 'Host / IP is required.')
            return
        if not (-180 <= offset <= 180):
            messagebox.showerror('Invalid', 'Offset must be between -180 and 180.')
            return

        dir_patterns = {}
        dir_colors = {}
        for d in DIRS:
            dir_patterns[d] = [1 if v.get() else 0 for v in self.pattern_vars[d]]
            dir_colors[d] = self.dir_color_vars[d].get()
        aux_labels = [v.get().strip() or f'AUX {i+1}' for i, v in enumerate(self.aux_label_vars)]

        self.cfg = {
            'transport': self.var_transport.get() or 'udp',
            'host': host, 'port': port,
            'user': self.var_user.get(), 'password': self.var_pass.get(),
            'mode': self.var_mode.get() or 'ff',
            'demo': bool(self.var_demo.get()),
            'offset': offset,
            'dirPatterns': dir_patterns,
            'auxLabels': aux_labels,
            'dirColors': dir_colors,
            'auxColors': [v.get() for v in self.aux_color_vars],
            'offColor': self.off_color_var.get(),
            'theme': {k: v.get() for k, v in self.theme_vars.items()},
        }
        save_cfg(self.cfg)
        self.conn_ok = None  # settings changed (host/transport/etc) — status unknown again
        for i, b in enumerate(self.aux_buttons):
            b.config(text=aux_labels[i])
        self._update_ui()
        self.toast(f"Settings saved (offset {'+' if offset >= 0 else ''}{offset:g}°)")

    def _update_badge(self):
        # Status is now shown as a dot on the compass (see _draw_compass),
        # not as text. Kept as a no-op so existing call sites don't need
        # removing; _update_ui() (called separately) redraws the dot.
        pass

    # ── background worker helper ──
    def _run_async(self, fn, on_done=None):
        if self._busy:
            return
        self._busy = True

        def worker():
            try:
                result = fn()
            except Exception as e:
                # Never let an exception die silently in the background thread —
                # that used to leave the compass cleared (canvas.delete('all'))
                # with nothing redrawn, and the status text stuck from whatever
                # it was mid-update.
                import traceback
                traceback.print_exc()
                self.after(0, lambda: self._finish_async(None, on_done, error=str(e)))
                return
            self.after(0, lambda: self._finish_async(result, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_async(self, result, on_done, error=None):
        self._busy = False
        if error:
            self.toast(f'Internal error: {error}', err=True)
            return
        if on_done:
            on_done(result)

    # ── actions ──
    def select_dir(self, d):
        self.toast(f'Switching to {d}…')

        def work():
            pattern = self.cfg['dirPatterns'][d]
            for i, want in enumerate(pattern):
                if not self.km.send_relay(i + 1, want == 1, self.relay_state):
                    return False
            return True

        def done(ok):
            self.conn_ok = ok
            if ok:
                self.active_dir = d
                self._update_ui()
                tb = (ANGLES[d] + self.cfg.get('offset', 0)) % 360
                self.toast(f'▶ {d}  ·  {tb:.0f}° true')
            else:
                self._update_ui()  # redraw so the status dot reflects the failure
                self.toast('Connection failed — check settings', err=True)

        self._run_async(work, done)

    def toggle_aux(self, idx):
        relay_num = idx + 5
        new_state = not self.relay_state[relay_num - 1]

        def work():
            return self.km.send_relay(relay_num, new_state, self.relay_state)

        def done(ok):
            self.conn_ok = ok
            if ok:
                self._update_ui()
                label = self.cfg['auxLabels'][idx]
                self.toast(f"{label}  →  {'ON' if new_state else 'OFF'}")
            else:
                self._update_ui()
                self.toast('Connection failed', err=True)

        self._run_async(work, done)

    def all_off(self):
        self.toast('Turning all relays off…')
        self.off_btn.config(bg=self.cfg['offColor'], fg='white', relief='sunken')

        def work():
            return self.km.all_off(self.relay_state)

        def done(ok):
            self.off_btn.config(bg='SystemButtonFace', fg=self.cfg['offColor'], relief='raised')
            self.conn_ok = ok
            if ok:
                self.active_dir = None
                self._update_ui()
                self.toast('All relays OFF')
            else:
                self._update_ui()
                self.toast('Connection failed — check IP / network', err=True)

        self._run_async(work, done)

    def _on_canvas_click(self, event):
        cx, cy = 75, 75
        dx, dy = event.x - cx, event.y - cy
        if math.hypot(dx, dy) < 10:
            return
        angle = math.degrees(math.atan2(dy, dx)) + 90
        if angle < 0:
            angle += 360
        snap = round(angle / 45) * 45 % 360
        for d, a in ANGLES.items():
            if a == snap:
                self.select_dir(d)
                break

    def _on_canvas_scroll(self, event):
        if self._busy:
            return  # a command is still in flight — don't queue another
        # Linux sends Button-4 (up) / Button-5 (down) with no delta;
        # Windows/Mac send MouseWheel with event.delta (+120 / -120 per notch).
        if getattr(event, 'num', None) in (4, 5):
            step = 1 if event.num == 4 else -1
        else:
            step = 1 if event.delta > 0 else -1
        idx = DIRS.index(self.active_dir) if self.active_dir in DIRS else -1
        self.select_dir(DIRS[(idx + step) % len(DIRS)])

    # ── background status polling ──
    def _poll_status(self):
        def work():
            return self.km.read_status()

        def done(st):
            if st:
                self.conn_ok = True  # a successful status read confirms the board is reachable
                self.relay_state = st
                cur = ''.join('1' if v else '0' for v in st[:4])
                if cur == '0000':
                    # Relays 1-4 all off is ambiguous: it could mean "no
                    # direction selected" OR a direction whose own pattern is
                    # 0000 (e.g. NE on this array). The board can't tell us
                    # which — both look identical on the wire — so we don't
                    # guess here. Whatever the app already has as the active
                    # direction (set explicitly by select_dir() or all_off())
                    # is left alone instead of being silently overwritten.
                    pass
                else:
                    found = None
                    for d in DIRS:
                        pat = ''.join(str(x) for x in self.cfg['dirPatterns'][d])
                        if pat == cur:
                            found = d
                            break
                    self.active_dir = found
                self._update_ui()

        if not self._busy and not self.cfg.get('demo'):
            self._run_async(work, done)
        self.after(1500, self._poll_status)

    # ── UI refresh ──
    def _update_ui(self):
        theme = self.cfg['theme']
        self.configure(bg=theme['appBg'])
        self.canvas.config(bg=theme['canvasBg'])

        # Idle ALL OFF text color (its bg/fg flip to red/white only while a
        # command is actually in flight, handled separately in all_off()).
        self.off_btn.config(fg=self.cfg['offColor'])

        for d, b in self.dir_buttons.items():
            if d == self.active_dir:
                # relief + text marker, not just color: on some platforms
                # (notably macOS) native buttons ignore bg/fg entirely, which
                # would otherwise make the selected label invisible.
                color = self.cfg['dirColors'].get(d, DEFAULT_DIR_COLORS[d])
                b.config(bg=color, fg='white', relief='sunken', text=f'▶{d}')
            else:
                b.config(bg='SystemButtonFace', fg='black', relief='raised', text=d)

        for i, (dot, circle) in enumerate(self.relay_dots):
            on = self.relay_state[i]
            dot.itemconfig(circle, fill='#0055cc' if on else '#e0e0e0',
                            outline='#0055cc' if on else '#cccccc')

        for i, b in enumerate(self.aux_buttons):
            on = self.relay_state[i + 4]
            on_color = self.cfg['auxColors'][i]
            b.config(bg=on_color if on else 'SystemButtonFace',
                     fg='white' if on else 'black')

        self._draw_compass()

    @staticmethod
    def _lighten(hex_color, amount=0.82):
        """Blend a hex color toward white for the compass wedge fill."""
        hex_color = hex_color.lstrip('#')
        try:
            r0, g0, b0 = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return '#dbe8fa'
        r1 = int(r0 + (255 - r0) * amount)
        g1 = int(g0 + (255 - g0) * amount)
        b1 = int(b0 + (255 - b0) * amount)
        return f'#{r1:02x}{g1:02x}{b1:02x}'

    def _draw_compass(self):
        c = self.canvas
        c.delete('all')
        cx, cy, r = 75, 75, 64
        off = self.cfg.get('offset', 0)
        theme = self.cfg['theme']
        active_color = (self.cfg['dirColors'].get(self.active_dir, DEFAULT_DIR_COLORS.get(self.active_dir, '#0055cc'))
                         if self.active_dir else '#0055cc')

        def label_xy(deg, radius):
            a = math.radians(deg - 90)
            return cx + radius * math.cos(a), cy + radius * math.sin(a)

        if self.active_dir:
            a = math.radians(ANGLES[self.active_dir] + off - 90)
            half = math.radians(BEAM_HALF)
            pts = [cx, cy]
            steps = 12
            for i in range(steps + 1):
                ang = a - half + (2 * half) * i / steps
                pts += [cx + (r - 2) * math.cos(ang), cy + (r - 2) * math.sin(ang)]
            c.create_polygon(pts, fill=theme['wedgeColor'], outline='')

        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=theme['ringColor'])

        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=active_color, outline='')

        # Arrow is drawn BEFORE the direction labels, so the labels (N/NE/E/...)
        # always stay on top and never get painted over by the arrowhead,
        # which otherwise happens for the diagonal (2-letter) directions.
        if self.active_dir:
            a = math.radians(ANGLES[self.active_dir] + off - 90)
            arrow_len = r - 14   # stays inside the ring, well clear of the edge
            ex, ey = cx + arrow_len * math.cos(a), cy + arrow_len * math.sin(a)
            c.create_line(cx, cy, ex, ey, fill=active_color, width=3)
            hl, hw = 10, 5
            bx, by = ex - hl * math.cos(a), ey - hl * math.sin(a)
            p1 = (bx + hw * math.cos(a + math.pi / 2), by + hw * math.sin(a + math.pi / 2))
            p2 = (bx - hw * math.cos(a + math.pi / 2), by - hw * math.sin(a + math.pi / 2))
            c.create_polygon(ex, ey, *p1, *p2, fill=active_color, outline='')

        for d in DIRS:
            active = d == self.active_dir
            dcolor = self.cfg['dirColors'].get(d, DEFAULT_DIR_COLORS[d])
            x1, y1 = label_xy(ANGLES[d], r - 3)
            x2, y2 = label_xy(ANGLES[d], r - 10)
            c.create_line(x1, y1, x2, y2, fill=dcolor if active else '#cccccc',
                          width=2 if active else 1)
            lx, ly = label_xy(ANGLES[d], r - 20)
            c.create_text(lx, ly, text=d, fill=dcolor if active else '#888888',
                          font=('Courier New', 9, 'bold' if len(d) == 1 else 'normal'))

        if off:
            c.create_text(cx, cy + r - 6, text=f"offset {'+' if off >= 0 else ''}{off:g}°",
                          fill='#aaaaaa', font=('Courier New', 8))

        # Connection status dot, top-right corner of the canvas:
        #   gray   = demo mode (not actually talking to hardware)
        #   green  = live, and the last command/status read succeeded
        #   red    = live, and the last command/status read failed
        #   orange = live, but nothing sent/read yet (unknown)
        is_demo = self.cfg.get('demo', True)
        if is_demo:
            dot_color = '#888888'
        elif self.conn_ok is True:
            dot_color = '#009900'
        elif self.conn_ok is False:
            dot_color = '#cc0000'
        else:
            dot_color = '#cc8800'
        dot_x, dot_y, dot_r = 140, 10, 5
        c.create_oval(dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r,
                      fill=dot_color, outline='#666666')

    # ── toast / status bar ──
    def toast(self, msg, err=False):
        self.status_var.set(('⚠ ' if err else '') + msg)


if __name__ == '__main__':
    app = App()
    app.mainloop()
