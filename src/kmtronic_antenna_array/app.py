"""Tkinter desktop app for the KMTronic 9CA antenna controller."""

from __future__ import annotations

import math
import threading
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from .config import DEFAULT_DIR_COLORS, DIRS, load_cfg, save_cfg
from .relay import KMTronicRelay

ANGLES = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
BEAM_HALF = 22.5


def config_getter():
    return load_cfg()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("9 Circle Array · KMTronic 8-Relay · 73 ON4IQ")
        self.resizable(False, False)
        self.configure(bg="#f0f0f0")

        self.cfg = load_cfg()
        self.active_dir = None
        self.relay_state = [False] * 8
        self.conn_ok = None
        self.km = KMTronicRelay(lambda: self.cfg, self.log_line)
        self._busy = False

        self._build_ui()
        self._apply_cfg_to_widgets()
        self._update_ui()
        self._shrink_to_fit()
        self._poll_status()

    def log_line(self, msg: str) -> None:
        print(msg)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        view_menu = tk.Menu(menubar, tearoff=0)
        self.view_compass_var = tk.BooleanVar(value=True)
        self.view_matrix_var = tk.BooleanVar(value=True)
        self.view_aux_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(label="Compass", variable=self.view_compass_var, command=self._apply_view_mode)
        view_menu.add_checkbutton(label="Matrix", variable=self.view_matrix_var, command=self._apply_view_mode)
        view_menu.add_checkbutton(label="Aux Relays", variable=self.view_aux_var, command=self._apply_view_mode)
        menubar.add_cascade(label="View", menu=view_menu)
        self.config(menu=menubar)

    def _apply_view_mode(self) -> None:
        self.canvas.grid() if self.view_compass_var.get() else self.canvas.grid_remove()
        if self.view_matrix_var.get():
            self.matrix_frame.grid()
            self.dotrow.grid()
        else:
            self.matrix_frame.grid_remove()
            self.dotrow.grid_remove()
        self.aux_frame.grid() if self.view_aux_var.get() else self.aux_frame.grid_remove()
        self._shrink_to_fit()

    def _shrink_to_fit(self) -> None:
        self.minsize(1, 1)
        self.update_idletasks()
        self.geometry("")

    def _build_ui(self) -> None:
        self._build_menu()

        tabbar = ttk.Frame(self)
        tabbar.pack(fill="x", padx=8, pady=(8, 0))
        self.tab_btn_control = tk.Button(tabbar, text="Control", relief="sunken", command=lambda: self._show_tab("control"))
        self.tab_btn_settings = tk.Button(tabbar, text="Settings", relief="raised", command=lambda: self._show_tab("settings"))
        self.tab_btn_control.pack(side="left", padx=(0, 4))
        self.tab_btn_settings.pack(side="left")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_main = ttk.Frame(container)
        self.tab_settings = ttk.Frame(container)

        self._build_main_tab(self.tab_main)
        self._build_settings_tab(self.tab_settings)

        self.tab_main.grid(row=0, column=0, sticky="n")
        self._current_tab = "control"

        self.status_var = tk.StringVar(value="Ready")
        bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(6, 3))
        bar.pack(fill="x", side="bottom")

    def _show_tab(self, which: str) -> None:
        if which == self._current_tab:
            return
        self._current_tab = which
        if which == "control":
            self.tab_settings.grid_forget()
            self.tab_main.grid(row=0, column=0, sticky="n")
            self.tab_btn_control.config(relief="sunken")
            self.tab_btn_settings.config(relief="raised")
        else:
            self.tab_main.grid_forget()
            self.tab_settings.grid(row=0, column=0, sticky="n")
            self.tab_btn_control.config(relief="raised")
            self.tab_btn_settings.config(relief="sunken")
        self._shrink_to_fit()

    def _build_main_tab(self, root) -> None:
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="n")

        self.canvas = tk.Canvas(left, width=150, height=150, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.canvas.grid(row=0, column=0)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<MouseWheel>", self._on_canvas_scroll)
        self.canvas.bind("<Button-4>", self._on_canvas_scroll)
        self.canvas.bind("<Button-5>", self._on_canvas_scroll)

        self.matrix_frame = ttk.Frame(left)
        self.matrix_frame.grid(row=1, column=0, pady=(10, 0))
        layout = ["NW", "N", "NE", "W", "OFF", "E", "SW", "S", "SE"]
        self.dir_buttons = {}
        for idx, direction in enumerate(layout):
            row_idx, col_idx = divmod(idx, 3)
            if direction == "OFF":
                self.off_btn = tk.Button(self.matrix_frame, text="ALL\nOFF", width=3, height=1, fg=self.cfg["offColor"], font=("Courier New", 6, "bold"), command=self.all_off)
                self.off_btn.grid(row=row_idx, column=col_idx, padx=2, pady=2)
                continue
            btn = tk.Button(self.matrix_frame, text=direction, width=3, height=1, font=("Courier New", 9, "bold"), command=lambda value=direction: self.select_dir(value))
            btn.grid(row=row_idx, column=col_idx, padx=2, pady=2)
            self.dir_buttons[direction] = btn

        self.dotrow = ttk.Frame(left)
        self.dotrow.grid(row=2, column=0, pady=(8, 0))
        self.relay_dots = []
        for idx in range(4):
            col = ttk.Frame(self.dotrow)
            col.grid(row=0, column=idx, padx=2)
            dot = tk.Canvas(col, width=14, height=14, highlightthickness=0, bg="#f0f0f0")
            circle = dot.create_oval(1, 1, 13, 13, fill="#e0e0e0", outline="#cccccc")
            dot.pack()
            ttk.Label(col, text=f"R{idx + 1}", font=("Courier New", 6)).pack()
            self.relay_dots.append((dot, circle))

        self.aux_frame = ttk.LabelFrame(left, text="AUX RELAYS (5–8)")
        self.aux_frame.grid(row=3, column=0, pady=(10, 0))
        self.aux_buttons = []
        for idx in range(4):
            colf = ttk.Frame(self.aux_frame)
            colf.grid(row=idx // 2, column=idx % 2, padx=3, pady=3, sticky="ew")
            btn = tk.Button(colf, text=self.cfg["auxLabels"][idx], width=7, font=("Courier New", 8, "bold"), command=lambda value=idx: self.toggle_aux(value))
            btn.pack()
            ttk.Label(colf, text=f"R{idx + 5}", font=("Courier New", 7)).pack()
            self.aux_buttons.append(btn)

    def _build_settings_tab(self, root) -> None:
        pad = {"padx": 6, "pady": 4}
        conn = ttk.LabelFrame(root, text="Connection")
        conn.pack(fill="x", padx=4, pady=6)

        self.var_transport = tk.StringVar()
        self.var_host = tk.StringVar()
        self.var_port = tk.StringVar()
        self.var_user = tk.StringVar()
        self.var_pass = tk.StringVar()
        self.var_mode = tk.StringVar()
        self.var_demo = tk.BooleanVar()
        self.var_offset = tk.StringVar()

        def row(parent, row_idx, label, widget):
            ttk.Label(parent, text=label, width=10).grid(row=row_idx, column=0, sticky="w", **pad)
            widget.grid(row=row_idx, column=1, sticky="ew", **pad)

        conn.columnconfigure(1, weight=1)
        transport_combo = ttk.Combobox(conn, textvariable=self.var_transport, state="readonly", values=["udp", "http"])
        transport_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_transport_visibility())
        row(conn, 0, "Transport", transport_combo)
        ttk.Label(conn, text="  udp = classic KMTronic UDP board\n  http = KMTronic WEB board", font=("Courier New", 7), foreground="#666666", justify="left").grid(row=1, column=0, columnspan=2, sticky="w", padx=6)
        row(conn, 2, "Host / IP", ttk.Entry(conn, textvariable=self.var_host))
        row(conn, 3, "Port", ttk.Entry(conn, textvariable=self.var_port))

        self.lbl_user = ttk.Label(conn, text="Username", width=10)
        self.ent_user = ttk.Entry(conn, textvariable=self.var_user)
        self.lbl_pass = ttk.Label(conn, text="Password", width=10)
        self.ent_pass = ttk.Entry(conn, textvariable=self.var_pass, show="*")
        self.lbl_user.grid(row=4, column=0, sticky="w", **pad)
        self.ent_user.grid(row=4, column=1, sticky="ew", **pad)
        self.lbl_pass.grid(row=5, column=0, sticky="w", **pad)
        self.ent_pass.grid(row=5, column=1, sticky="ew", **pad)

        self.lbl_mode = ttk.Label(conn, text="Mode", width=10)
        self.mode_combo = ttk.Combobox(conn, textvariable=self.var_mode, state="readonly", values=["ff", "toggle"])
        self.lbl_mode.grid(row=6, column=0, sticky="w", **pad)
        self.mode_combo.grid(row=6, column=1, sticky="ew", **pad)
        self.lbl_mode_hint = ttk.Label(conn, text="  ff = /FF0101 direct on/off · toggle = /relays.cgi?relay=N", font=("Courier New", 7), foreground="#666666")
        self.lbl_mode_hint.grid(row=7, column=0, columnspan=2, sticky="w", padx=6)

        ttk.Checkbutton(conn, text="Demo mode (no hardware)", variable=self.var_demo).grid(row=8, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 2))
        row(conn, 9, "Offset °", ttk.Entry(conn, textvariable=self.var_offset))

        pat = ttk.LabelFrame(root, text="Direction → Relay (1-4) pattern")
        pat.pack(fill="x", padx=4, pady=6)
        ttk.Label(pat, text="Dir", font=("Courier New", 8, "bold")).grid(row=0, column=0)
        for relay_idx in range(4):
            ttk.Label(pat, text=f"R{relay_idx + 1}", font=("Courier New", 8, "bold")).grid(row=0, column=relay_idx + 1)
        ttk.Label(pat, text="Color", font=("Courier New", 8, "bold")).grid(row=0, column=5)
        self.pattern_vars = {}
        self.dir_color_vars = {}
        self.dir_color_swatches = {}
        for row_idx, direction in enumerate(DIRS, start=1):
            ttk.Label(pat, text=direction, font=("Courier New", 9, "bold"), foreground="#0055cc").grid(row=row_idx, column=0, padx=4, pady=2, sticky="w")
            pattern_vars = []
            for relay_idx in range(4):
                var = tk.BooleanVar()
                ttk.Checkbutton(pat, variable=var).grid(row=row_idx, column=relay_idx + 1, padx=4)
                pattern_vars.append(var)
            self.pattern_vars[direction] = pattern_vars
            self.dir_color_vars[direction] = tk.StringVar(value=self.cfg["dirColors"][direction])
            swatch = tk.Button(pat, width=3, relief="raised", command=lambda value=direction: self._pick_dir_color(value))
            swatch.grid(row=row_idx, column=5, padx=4, pady=2)
            self.dir_color_swatches[direction] = swatch

        auxf = ttk.LabelFrame(root, text="Aux relays (5-8): label and ON color")
        auxf.pack(fill="x", padx=4, pady=6)
        self.aux_label_vars = []
        self.aux_color_vars = []
        self.aux_color_swatches = []
        for idx in range(4):
            ttk.Label(auxf, text=f"R{idx + 5}", font=("Courier New", 8, "bold"), foreground="#0055cc").grid(row=idx, column=0, padx=4, pady=3, sticky="w")
            label_var = tk.StringVar()
            ttk.Entry(auxf, textvariable=label_var, width=14).grid(row=idx, column=1, padx=4, pady=3)
            self.aux_label_vars.append(label_var)
            color_var = tk.StringVar(value=self.cfg["auxColors"][idx])
            swatch = tk.Button(auxf, width=3, relief="raised", command=lambda value=idx: self._pick_aux_color(value))
            swatch.grid(row=idx, column=2, padx=4, pady=3)
            self.aux_color_vars.append(color_var)
            self.aux_color_swatches.append(swatch)

        offf = ttk.LabelFrame(root, text="ALL OFF button color")
        offf.pack(fill="x", padx=4, pady=6)
        self.off_color_var = tk.StringVar(value=self.cfg["offColor"])
        self.off_color_swatch = tk.Button(offf, width=3, relief="raised", command=self._pick_off_color)
        ttk.Label(offf, text="Color", font=("Courier New", 8, "bold")).grid(row=0, column=0, padx=4, pady=3, sticky="w")
        self.off_color_swatch.grid(row=0, column=1, padx=4, pady=3)

        themef = ttk.LabelFrame(root, text="Theme")
        themef.pack(fill="x", padx=4, pady=6)
        theme_items = [("appBg", "App background"), ("canvasBg", "Compass background"), ("ringColor", "Compass ring"), ("wedgeColor", "Shaded wedge")]
        self.theme_vars = {}
        self.theme_swatches = {}
        for row_idx, (key, label) in enumerate(theme_items):
            ttk.Label(themef, text=label, font=("Courier New", 8)).grid(row=row_idx, column=0, padx=4, pady=3, sticky="w")
            value_var = tk.StringVar(value=self.cfg["theme"][key])
            swatch = tk.Button(themef, width=3, relief="raised", command=lambda key_name=key: self._pick_theme_color(key_name))
            swatch.grid(row=row_idx, column=1, padx=4, pady=3)
            self.theme_vars[key] = value_var
            self.theme_swatches[key] = swatch

        apply_btn = tk.Button(root, text="Apply & Save", bg="#0055cc", fg="white", font=("Courier New", 9, "bold"), command=self.apply_settings)
        apply_btn.pack(fill="x", padx=4, pady=10)

    def _apply_cfg_to_widgets(self) -> None:
        cfg = self.cfg
        self.var_transport.set(cfg.get("transport", "udp"))
        self.var_host.set(cfg["host"])
        self.var_port.set(str(cfg["port"]))
        self.var_user.set(cfg.get("user", "admin"))
        self.var_pass.set(cfg.get("password", "admin"))
        self.var_mode.set(cfg.get("mode", "ff"))
        self.var_demo.set(bool(cfg["demo"]))
        self.var_offset.set(str(cfg.get("offset", 0)))

        for direction in DIRS:
            pattern = cfg["dirPatterns"].get(direction, [0, 0, 0, 0])
            for relay_idx, variable in enumerate(self.pattern_vars[direction]):
                variable.set(bool(pattern[relay_idx]))
            color = cfg["dirColors"].get(direction, DEFAULT_DIR_COLORS[direction])
            self.dir_color_vars[direction].set(color)
            self.dir_color_swatches[direction].config(bg=color)

        for idx, label_var in enumerate(self.aux_label_vars):
            label_var.set(cfg["auxLabels"][idx])
        for idx, color_var in enumerate(self.aux_color_vars):
            color_value = cfg["auxColors"][idx]
            color_var.set(color_value)
            self.aux_color_swatches[idx].config(bg=color_value)

        self.off_color_var.set(cfg["offColor"])
        self.off_color_swatch.config(bg=cfg["offColor"])
        for key, value_var in self.theme_vars.items():
            color = cfg["theme"][key]
            value_var.set(color)
            self.theme_swatches[key].config(bg=color)
        self._update_transport_visibility()

    def _pick_dir_color(self, direction: str) -> None:
        current = self.dir_color_vars[direction].get()
        _, chosen = colorchooser.askcolor(color=current, title=f"Color for {direction}")
        if chosen:
            self.dir_color_vars[direction].set(chosen)
            self.dir_color_swatches[direction].config(bg=chosen)

    def _pick_aux_color(self, idx: int) -> None:
        current = self.aux_color_vars[idx].get()
        _, chosen = colorchooser.askcolor(color=current, title=f"ON color for R{idx + 5}")
        if chosen:
            self.aux_color_vars[idx].set(chosen)
            self.aux_color_swatches[idx].config(bg=chosen)

    def _pick_off_color(self) -> None:
        current = self.off_color_var.get()
        _, chosen = colorchooser.askcolor(color=current, title="ALL OFF button color")
        if chosen:
            self.off_color_var.set(chosen)
            self.off_color_swatch.config(bg=chosen)

    def _pick_theme_color(self, key: str) -> None:
        current = self.theme_vars[key].get()
        _, chosen = colorchooser.askcolor(color=current, title=key)
        if chosen:
            self.theme_vars[key].set(chosen)
            self.theme_swatches[key].config(bg=chosen)

    def _update_transport_visibility(self) -> None:
        is_http = self.var_transport.get() == "http"
        widgets = [self.lbl_user, self.ent_user, self.lbl_pass, self.ent_pass, self.lbl_mode, self.mode_combo, self.lbl_mode_hint]
        for widget in widgets:
            if is_http:
                widget.grid()
            else:
                widget.grid_remove()
        if is_http and self.var_port.get() in ("", "12345"):
            self.var_port.set("80")
        elif not is_http and self.var_port.get() in ("", "80"):
            self.var_port.set("12345")

    def apply_settings(self) -> None:
        host = self.var_host.get().strip()
        try:
            port = int(self.var_port.get().strip())
        except ValueError:
            messagebox.showerror("Invalid", "Port must be a number.")
            return
        try:
            offset = float(self.var_offset.get().strip() or 0)
        except ValueError:
            messagebox.showerror("Invalid", "Offset must be a number.")
            return
        if not host:
            messagebox.showerror("Invalid", "Host / IP is required.")
            return
        if not (-180 <= offset <= 180):
            messagebox.showerror("Invalid", "Offset must be between -180 and 180.")
            return

        dir_patterns = {}
        dir_colors = {}
        for direction in DIRS:
            dir_patterns[direction] = [1 if var.get() else 0 for var in self.pattern_vars[direction]]
            dir_colors[direction] = self.dir_color_vars[direction].get()
        aux_labels = [value.get().strip() or f"AUX {idx + 1}" for idx, value in enumerate(self.aux_label_vars)]

        self.cfg = {
            "transport": self.var_transport.get() or "udp",
            "host": host,
            "port": port,
            "user": self.var_user.get(),
            "password": self.var_pass.get(),
            "mode": self.var_mode.get() or "ff",
            "demo": bool(self.var_demo.get()),
            "offset": offset,
            "dirPatterns": dir_patterns,
            "auxLabels": aux_labels,
            "dirColors": dir_colors,
            "auxColors": [var.get() for var in self.aux_color_vars],
            "offColor": self.off_color_var.get(),
            "theme": {key: value.get() for key, value in self.theme_vars.items()},
        }
        save_cfg(self.cfg)
        self.conn_ok = None
        for idx, button in enumerate(self.aux_buttons):
            button.config(text=aux_labels[idx])
        self._update_ui()
        self.toast(f"Settings saved (offset {'+' if offset >= 0 else ''}{offset:g}°)")

    def _run_async(self, fn, on_done=None) -> None:
        if self._busy:
            return
        self._busy = True

        def worker() -> None:
            try:
                result = fn()
            except Exception as exc:  # pragma: no cover
                import traceback
                traceback.print_exc()
                self.after(0, lambda: self._finish_async(None, on_done, error=str(exc)))
                return
            self.after(0, lambda: self._finish_async(result, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_async(self, result, on_done, error=None) -> None:
        self._busy = False
        if error:
            self.toast(f"Internal error: {error}", err=True)
            return
        if on_done:
            on_done(result)

    def select_dir(self, direction: str) -> None:
        self.toast(f"Switching to {direction}…")

        def work():
            pattern = self.cfg["dirPatterns"][direction]
            for relay_idx, wanted in enumerate(pattern):
                if not self.km.send_relay(relay_idx + 1, wanted == 1, self.relay_state):
                    return False
            return True

        def done(ok: bool) -> None:
            self.conn_ok = ok
            if ok:
                self.active_dir = direction
                self._update_ui()
                true_bearing = (ANGLES[direction] + self.cfg.get("offset", 0)) % 360
                self.toast(f"▶ {direction} · {true_bearing:.0f}° true")
            else:
                self._update_ui()
                self.toast("Connection failed — check settings", err=True)

        self._run_async(work, done)

    def toggle_aux(self, idx: int) -> None:
        relay_num = idx + 5
        new_state = not self.relay_state[relay_num - 1]

        def work():
            return self.km.send_relay(relay_num, new_state, self.relay_state)

        def done(ok: bool) -> None:
            self.conn_ok = ok
            if ok:
                self._update_ui()
                label = self.cfg["auxLabels"][idx]
                self.toast(f"{label} → {'ON' if new_state else 'OFF'}")
            else:
                self._update_ui()
                self.toast("Connection failed", err=True)

        self._run_async(work, done)

    def all_off(self) -> None:
        self.toast("Turning all relays off…")
        self.off_btn.config(bg=self.cfg["offColor"], fg="white", relief="sunken")

        def work():
            return self.km.all_off(self.relay_state)

        def done(ok: bool) -> None:
            self.off_btn.config(bg="SystemButtonFace", fg=self.cfg["offColor"], relief="raised")
            self.conn_ok = ok
            if ok:
                self.active_dir = None
                self._update_ui()
                self.toast("All relays OFF")
            else:
                self._update_ui()
                self.toast("Connection failed — check IP / network", err=True)

        self._run_async(work, done)

    def _on_canvas_click(self, event) -> None:
        center_x, center_y = 75, 75
        dx = event.x - center_x
        dy = event.y - center_y
        if math.hypot(dx, dy) < 10:
            return
        angle = math.degrees(math.atan2(dy, dx)) + 90
        if angle < 0:
            angle += 360
        snapped = round(angle / 45) * 45 % 360
        for direction, value in ANGLES.items():
            if value == snapped:
                self.select_dir(direction)
                break

    def _on_canvas_scroll(self, event) -> None:
        if self._busy:
            return
        if getattr(event, "num", None) in (4, 5):
            step = 1 if event.num == 4 else -1
        else:
            step = 1 if event.delta > 0 else -1
        idx = DIRS.index(self.active_dir) if self.active_dir in DIRS else -1
        self.select_dir(DIRS[(idx + step) % len(DIRS)])

    def _poll_status(self) -> None:
        def work():
            return self.km.read_status()

        def done(status):
            if status:
                self.conn_ok = True
                self.relay_state = status
                current_combo = "".join("1" if value else "0" for value in status[:4])
                if current_combo != "0000":
                    found = None
                    for direction in DIRS:
                        pattern = "".join(str(value) for value in self.cfg["dirPatterns"][direction])
                        if pattern == current_combo:
                            found = direction
                            break
                    self.active_dir = found
                self._update_ui()

        if not self._busy and not self.cfg.get("demo"):
            self._run_async(work, done)
        self.after(1500, self._poll_status)

    def _update_ui(self) -> None:
        theme = self.cfg["theme"]
        self.configure(bg=theme["appBg"])
        self.canvas.config(bg=theme["canvasBg"])
        self.off_btn.config(fg=self.cfg["offColor"])

        for direction, button in self.dir_buttons.items():
            if direction == self.active_dir:
                color = self.cfg["dirColors"].get(direction, DEFAULT_DIR_COLORS[direction])
                button.config(bg=color, fg="white", relief="sunken", text=f"▶{direction}")
            else:
                button.config(bg="SystemButtonFace", fg="black", relief="raised", text=direction)

        for idx, (dot, circle) in enumerate(self.relay_dots):
            on = self.relay_state[idx]
            dot.itemconfig(circle, fill="#0055cc" if on else "#e0e0e0", outline="#0055cc" if on else "#cccccc")

        for idx, button in enumerate(self.aux_buttons):
            on = self.relay_state[idx + 4]
            color = self.cfg["auxColors"][idx]
            button.config(bg=color if on else "SystemButtonFace", fg="white" if on else "black")

        self._draw_compass()

    def _draw_compass(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        center_x, center_y, radius = 75, 75, 64
        offset = self.cfg.get("offset", 0)
        theme = self.cfg["theme"]
        active_color = self.cfg["dirColors"].get(self.active_dir, DEFAULT_DIR_COLORS.get(self.active_dir, "#0055cc")) if self.active_dir else "#0055cc"

        def label_xy(deg: float, distance: float):
            angle = math.radians(deg - 90)
            return center_x + distance * math.cos(angle), center_y + distance * math.sin(angle)

        if self.active_dir:
            a = math.radians(ANGLES[self.active_dir] + offset - 90)
            half = math.radians(BEAM_HALF)
            points = [center_x, center_y]
            for step in range(13):
                angle = a - half + (2 * half) * step / 12
                points.extend([center_x + (radius - 2) * math.cos(angle), center_y + (radius - 2) * math.sin(angle)])
            canvas.create_polygon(points, fill=theme["wedgeColor"], outline="")

        canvas.create_oval(center_x - radius, center_y - radius, center_x + radius, center_y + radius, outline=theme["ringColor"])
        canvas.create_oval(center_x - 4, center_y - 4, center_x + 4, center_y + 4, fill=active_color, outline="")

        if self.active_dir:
            a = math.radians(ANGLES[self.active_dir] + offset - 90)
            arrow_length = radius - 14
            ex = center_x + arrow_length * math.cos(a)
            ey = center_y + arrow_length * math.sin(a)
            canvas.create_line(center_x, center_y, ex, ey, fill=active_color, width=3)
            head_length, head_width = 10, 5
            bx = ex - head_length * math.cos(a)
            by = ey - head_length * math.sin(a)
            p1 = (bx + head_width * math.cos(a + math.pi / 2), by + head_width * math.sin(a + math.pi / 2))
            p2 = (bx - head_width * math.cos(a + math.pi / 2), by - head_width * math.sin(a + math.pi / 2))
            canvas.create_polygon(ex, ey, *p1, *p2, fill=active_color, outline="")

        for direction in DIRS:
            active = direction == self.active_dir
            color = self.cfg["dirColors"].get(direction, DEFAULT_DIR_COLORS[direction])
            x1, y1 = label_xy(ANGLES[direction], radius - 3)
            x2, y2 = label_xy(ANGLES[direction], radius - 10)
            canvas.create_line(x1, y1, x2, y2, fill=color if active else "#cccccc", width=2 if active else 1)
            lx, ly = label_xy(ANGLES[direction], radius - 20)
            canvas.create_text(lx, ly, text=direction, fill=color if active else "#888888", font=("Courier New", 9, "bold" if len(direction) == 1 else "normal"))

        if offset:
            canvas.create_text(center_x, center_y + radius - 6, text=f"offset {'+' if offset >= 0 else ''}{offset:g}°", fill="#aaaaaa", font=("Courier New", 8))

        is_demo = self.cfg.get("demo", True)
        if is_demo:
            dot_color = "#888888"
        elif self.conn_ok is True:
            dot_color = "#009900"
        elif self.conn_ok is False:
            dot_color = "#cc0000"
        else:
            dot_color = "#cc8800"
        canvas.create_oval(140 - 5, 10 - 5, 140 + 5, 10 + 5, fill=dot_color, outline="#666666")

    def toast(self, msg: str, err: bool = False) -> None:
        self.status_var.set(("⚠ " if err else "") + msg)


def main() -> None:
    app = App()
    app.mainloop()
