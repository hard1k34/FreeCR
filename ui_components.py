import tkinter as tk


def draw_rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
        x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
        x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
        x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class IncyPowerOrb(tk.Canvas):
    def __init__(self, parent, on_click, **kwargs):
        super().__init__(parent, width=360, height=190, highlightthickness=0, bd=0, **kwargs)
        self.on_click = on_click
        self.theme = None
        self.state = "idle"
        self.subtitle = "Нажмите для запуска"
        self.ping = None
        self.hovered = False
        self.pulse_step = 0
        self._anim_job = None

        self.bind("<Button-1>", lambda e: self.on_click())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        self.hovered = True
        self.config(cursor="hand2")
        self.render()

    def _on_leave(self, _):
        self.hovered = False
        self.render()

    def set_status(self, state, subtitle="", ping=None):
        self.state = state
        self.subtitle = subtitle
        self.ping = ping
        if self.state == "scanning":
            self._start_pulse()
        else:
            self._stop_pulse()
        self.render()

    def _start_pulse(self):
        if self._anim_job is None:
            self._animate()

    def _stop_pulse(self):
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        self.pulse_step = 0

    def _animate(self):
        if self.state != "scanning":
            self._anim_job = None
            return
        self.pulse_step = (self.pulse_step + 1) % 12
        self.render()
        self._anim_job = self.after(90, self._animate)

    def render(self, theme=None):
        if theme:
            self.theme = theme
        if not self.theme:
            return

        t = self.theme
        self.configure(bg=t["bg"])
        self.delete("all")

        cx, cy = 180, 74

        if self.state == "active":
            ring_color = t["success"]
            core_fill = t["surface_hover"]
            status_text = "CONNECTED"
        elif self.state == "scanning":
            ring_color = t["warning"]
            core_fill = t["surface"]
            status_text = "SCANNING..."
        else:
            ring_color = t["accent"] if self.hovered else t["border"]
            core_fill = t["surface_hover"] if self.hovered else t["surface"]
            status_text = "DISCONNECTED"

        grid_col = t["border"]
        self.create_line(cx - 90, cy, cx - 66, cy, fill=grid_col, width=1)
        self.create_line(cx + 66, cy, cx + 90, cy, fill=grid_col, width=1)

        extra = (self.pulse_step % 6) if self.state == "scanning" else (3 if self.hovered else 0)
        r_outer = 53 + extra
        self.create_oval(
            cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
            outline=ring_color, width=1.5
        )

        r_inner = 44
        self.create_oval(
            cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
            fill=core_fill, outline=ring_color, width=2
        )

        icon_col = ring_color if (self.state != "idle" or self.hovered) else t["subtext"]
        self.create_arc(
            cx - 13, cy - 13, cx + 13, cy + 13,
            start=125, extent=290, style="arc", outline=icon_col, width=2.5
        )
        self.create_line(cx, cy - 15, cx, cy - 2, fill=icon_col, width=2.5, capstyle="round")

        self.create_text(
            cx, 146, text=status_text,
            fill=ring_color if self.state != "idle" else t["text"],
            font=("Segoe UI Semibold", 11)
        )

        sub = self.subtitle
        if self.ping is not None and self.state == "active":
            sub = f"{self.subtitle}  •  {self.ping} ms"

        self.create_text(
            cx, 169, text=sub,
            fill=t["subtext"],
            font=("Segoe UI", 9)
        )


class IncyModuleCard(tk.Canvas):
    def __init__(self, parent, title, subtitle, on_toggle, **kwargs):
        super().__init__(parent, width=360, height=76, highlightthickness=0, bd=0, **kwargs)
        self.title = title
        self.subtitle = subtitle
        self.on_toggle = on_toggle

        self.checked = False
        self.hovered = False
        self.theme = None

        self.bind("<Button-1>", self._handle_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        self.hovered = True
        self.config(cursor="hand2")
        self.render()

    def _on_leave(self, _):
        self.hovered = False
        self.render()

    def _handle_click(self, _event):
        self.checked = not self.checked
        self.render()
        self.on_toggle(self.checked)

    def set_checked(self, state: bool):
        if self.checked != bool(state):
            self.checked = bool(state)
            self.render()

    def set_subtitle(self, text: str):
        if self.subtitle != text:
            self.subtitle = text
            self.render()

    def render(self, theme=None):
        if theme:
            self.theme = theme
        if not self.theme:
            return

        t = self.theme
        self.configure(bg=t["bg"])
        self.delete("all")

        card_bg = t["surface_hover"] if self.hovered else t["surface"]
        border_col = t["border_active"] if self.checked else t["border"]

        draw_rounded_rect(self, 2, 2, 358, 74, 16, fill=card_bg, outline=border_col, width=1.2)

        dot_col = t["success"] if self.checked else t["subtext"]
        self.create_oval(18, 22, 26, 30, fill=dot_col, outline=dot_col)

        self.create_text(
            35, 25, text=self.title, fill=t["text"],
            font=("Segoe UI Semibold", 11), anchor="w"
        )
        self.create_text(
            35, 49, text=self.subtitle, fill=t["subtext"],
            font=("Segoe UI", 9), anchor="w"
        )

        sw_x1, sw_y1, sw_x2, sw_y2 = 294, 25, 340, 51
        sw_fill = t["accent"] if self.checked else t["switch_off"]
        draw_rounded_rect(self, sw_x1, sw_y1, sw_x2, sw_y2, 13, fill=sw_fill, outline=sw_fill)

        knob_x = 327 if self.checked else 307
        self.create_oval(knob_x - 9, 29, knob_x + 9, 47, fill=t["knob"], outline=t["knob"])


class IncySettingsDrawer(tk.Frame):
    def __init__(self, parent, cfg, themes_dict, on_theme_change, on_repick, on_update, on_save_port, on_state_change=None):
        super().__init__(parent, bd=0, highlightthickness=0)
        self.parent = parent
        self.cfg = cfg
        self.themes = themes_dict
        self.on_theme_change = on_theme_change
        self.on_repick = on_repick
        self.on_update = on_update
        self.on_save_port = on_save_port
        self.on_state_change = on_state_change or (lambda is_open: None)

        self.is_open = False
        self._animating = False
        self._anim_job = None

        self.open_y = 64
        self.closed_y = 605
        self.drawer_h = 600 - self.open_y
        self.current_y = self.closed_y

        self._build_ui()

    def _build_ui(self):
        self.top_line = tk.Frame(self, height=2)
        self.top_line.pack(fill="x")

        self.header = tk.Frame(self)
        self.header.pack(fill="x", padx=22, pady=(14, 6))

        self.title_lbl = tk.Label(
            self.header, text="НАСТРОЙКИ", font=("Segoe UI Semibold", 11)
        )
        self.title_lbl.pack(side="left")

        self.close_btn = tk.Button(
            self.header,
            text="✕",
            font=("Segoe UI Semibold", 10),
            relief="flat",
            bd=0,
            padx=8,
            pady=1,
            cursor="hand2",
            command=self.close
        )
        self.close_btn.pack(side="right")

        self.lbl_theme = tk.Label(self, text="ТЕМА ОФОРМЛЕНИЯ", font=("Consolas", 8, "bold"), anchor="w")
        self.lbl_theme.pack(fill="x", padx=22, pady=(8, 6))

        self.theme_grid = tk.Frame(self)
        self.theme_grid.pack(fill="x", padx=22)
        self.theme_grid.columnconfigure(0, weight=1, uniform="tcol")
        self.theme_grid.columnconfigure(1, weight=1, uniform="tcol")

        self.theme_buttons = {}
        for idx, name in enumerate(self.themes.keys()):
            r, c = divmod(idx, 2)
            btn = tk.Button(
                self.theme_grid,
                text=name,
                font=("Segoe UI", 9),
                relief="flat",
                bd=0,
                padx=8,
                pady=8,
                cursor="hand2",
                command=lambda n=name: self._select_theme(n)
            )
            btn.grid(row=r, column=c, sticky="ew", padx=(0 if c == 0 else 4, 4 if c == 0 else 0), pady=3)
            self.theme_buttons[name] = btn

        self.lbl_zap = tk.Label(self, text="ПРОФИЛЬ ZAPRET И ОБНОВЛЕНИЯ", font=("Consolas", 8, "bold"), anchor="w")
        self.lbl_zap.pack(fill="x", padx=22, pady=(16, 4))

        self.prof_info = tk.Label(self, text="", font=("Segoe UI", 9), anchor="w")
        self.prof_info.pack(fill="x", padx=22, pady=(0, 8))

        self.repick_btn = tk.Button(
            self,
            text="⚡ Перепроверить все профили заново",
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            pady=8,
            cursor="hand2",
            command=self._handle_repick
        )
        self.repick_btn.pack(fill="x", padx=22, pady=3)

        self.upd_btn = tk.Button(
            self,
            text="↻ Проверить и скачать обновление Zapret",
            font=("Segoe UI Semibold", 9),
            relief="flat",
            bd=0,
            pady=8,
            cursor="hand2",
            command=self._handle_update
        )
        self.upd_btn.pack(fill="x", padx=22, pady=3)

        self.lbl_port = tk.Label(self, text="ПОРТ TG WS PROXY (ПО УМОЛЧАНИЮ 1080)", font=("Consolas", 8, "bold"), anchor="w")
        self.lbl_port.pack(fill="x", padx=22, pady=(16, 6))

        self.port_entry = tk.Entry(self, relief="flat", font=("Consolas", 10), bd=0)
        self.port_entry.pack(fill="x", padx=22, ipady=7)

        self.save_btn = tk.Button(
            self,
            text="Сохранить и закрыть",
            font=("Segoe UI Semibold", 10),
            relief="flat",
            bd=0,
            pady=10,
            cursor="hand2",
            command=self._handle_save
        )
        self.save_btn.pack(side="bottom", fill="x", padx=22, pady=(12, 22))

    def refresh_data(self):
        cur_prof = self.cfg.get("best_profile", "").replace(".bat", "") or "Не подобран"
        cur_ping = self.cfg.get("best_ping", None)
        ping_txt = f" ({cur_ping} ms)" if cur_ping is not None else ""
        self.prof_info.configure(text=f"Профиль: {cur_prof}{ping_txt} • GameFilter: TCP+UDP • ipset: any")

        self.port_entry.delete(0, "end")
        self.port_entry.insert(0, str(self.cfg.get("tg_proxy_port", "1080")))
        self.apply_theme(self.cfg.theme)

    def apply_theme(self, t):
        self.configure(bg=t["bg"])
        self.top_line.configure(bg=t["accent"])
        self.header.configure(bg=t["bg"])
        self.title_lbl.configure(bg=t["bg"], fg=t["text"])
        self.close_btn.configure(
            bg=t["surface"], fg=t["subtext"],
            activebackground=t["surface_hover"], activeforeground=t["text"]
        )

        self.lbl_theme.configure(bg=t["bg"], fg=t["subtext"])
        self.theme_grid.configure(bg=t["bg"])

        cur_theme = self.cfg.get("theme", "Obsidian Dark")
        for name, btn in self.theme_buttons.items():
            is_cur = (name == cur_theme)
            btn.configure(
                text=f"● {name}" if is_cur else name,
                font=("Segoe UI Semibold" if is_cur else "Segoe UI", 9),
                bg=t["surface_hover"] if is_cur else t["surface"],
                fg=t["accent"] if is_cur else t["text"],
                activebackground=t["surface_hover"],
                activeforeground=t["accent"]
            )

        self.lbl_zap.configure(bg=t["bg"], fg=t["subtext"])
        self.prof_info.configure(bg=t["bg"], fg=t["text"])

        self.repick_btn.configure(
            bg=t["surface"], fg=t["text"],
            activebackground=t["surface_hover"], activeforeground=t["text"]
        )
        self.upd_btn.configure(
            bg=t["surface"], fg=t["accent"],
            activebackground=t["surface_hover"], activeforeground=t["accent"]
        )

        self.lbl_port.configure(bg=t["bg"], fg=t["subtext"])
        self.port_entry.configure(
            bg=t["surface"], fg=t["text"], insertbackground=t["text"]
        )

        self.save_btn.configure(
            bg=t["accent"], fg=t["knob"],
            activebackground=t["border_active"], activeforeground=t["knob"]
        )

    def _select_theme(self, name):
        self.on_theme_change(name)
        self.apply_theme(self.cfg.theme)

    def _handle_repick(self):
        self.close()
        self.on_repick()

    def _handle_update(self):
        self.close()
        self.on_update()

    def _handle_save(self):
        port = self.port_entry.get().strip() or "1080"
        self.on_save_port(port)
        self.close()

    def toggle(self):
        if self.is_open:
            self.close()
        else:
            self.open()

    def open(self):
        if self.is_open and not self._animating:
            return
        self.refresh_data()
        self.is_open = True
        self.on_state_change(True)
        self.lift()
        self._animate_to(self.open_y, duration_ms=230, opening=True)

    def close(self):
        if not self.is_open and not self._animating:
            return
        self.is_open = False
        self.on_state_change(False)
        self._animate_to(self.closed_y, duration_ms=190, opening=False)

    def _animate_to(self, target_y: int, duration_ms: int = 220, opening: bool = True):
        if self._anim_job is not None:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

        start_y = self.current_y
        delta = target_y - start_y
        if delta == 0:
            if not opening:
                self.place_forget()
            return

        self._animating = True
        fps_interval = 12
        steps = max(1, duration_ms // fps_interval)
        step_idx = 0

        def tick():
            nonlocal step_idx
            step_idx += 1
            t = min(1.0, step_idx / steps)
            if opening:
                eased = 1.0 - (1.0 - t) ** 3
            else:
                eased = t * t * (3.0 - 2.0 * t)

            self.current_y = int(round(start_y + delta * eased))
            self.place(x=0, y=self.current_y, width=400, height=self.drawer_h)

            if t < 1.0:
                self._anim_job = self.after(fps_interval, tick)
            else:
                self._anim_job = None
                self._animating = False
                self.current_y = target_y
                if not opening:
                    self.place_forget()

        tick()
