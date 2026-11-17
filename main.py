import os
import sys
import ssl
import time
import ctypes
import threading
import tkinter as tk

ssl._create_default_https_context = ssl._create_unverified_context

from config import (
    ConfigManager,
    THEMES,
    BASE_DIR,
    get_safe_icon_paths,
    apply_win11_window_style,
    apply_win32_window_icon,
)
from engine import CoreEngine
from ui_components import IncyPowerOrb, IncyModuleCard, IncySettingsDrawer


def set_windows_app_id():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("hardovere.freecr.app")
        except Exception:
            pass


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_permissions():
    args_list = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    params = " ".join(f'"{arg}"' for arg in args_list)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, BASE_DIR, 1
    )
    sys.exit(0)


class FreeCRApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = ConfigManager()
        self.safe_ico, self.safe_png = get_safe_icon_paths()

        self.engine = CoreEngine(
            self.cfg,
            on_status_change=self.sync_ui_from_thread,
            on_log=self.append_log_from_thread
        )

        self.title("FreeCR // by hardovere")
        self.geometry("400x600")
        self.resizable(False, False)

        saved_prof = self.cfg.get("best_profile", "").replace(".bat", "")
        saved_ping = self.cfg.get("best_ping", None)
        ping_suffix = f" ({saved_ping} ms)" if saved_ping is not None else ""
        self.logs = [
            "FreeCR запущен.",
            f"Профиль: {saved_prof}{ping_suffix}" if saved_prof else "Профиль Zapret ещё не выбран."
        ]
        if not is_admin():
            self.logs.append("Запущено без прав Администратора!")

        self._build_layout()
        self.apply_theme()
        self._apply_app_icon()
        self._sync_ui()

        self.after(80, self._apply_app_icon)
        self.bind("<Escape>", lambda e: self.settings_drawer.close())

        if self.cfg.get("auto_check_updates", True):
            threading.Thread(target=self.engine.check_updates_background, daemon=True).start()

        self.after(500, self._watchdog_loop)
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    def _apply_app_icon(self):
        try:
            if os.path.isfile(self.safe_ico):
                self.iconbitmap(default=self.safe_ico)
        except Exception:
            pass
        apply_win32_window_icon(self, self.safe_ico)

    def _build_layout(self):
        self.top_bar = tk.Frame(self)
        self.top_bar.pack(fill="x", padx=22, pady=(18, 4))

        self.brand_lbl = tk.Label(
            self.top_bar, text="FreeCR", font=("Segoe UI Black", 17)
        )
        self.brand_lbl.pack(side="left")

        self.author_lbl = tk.Label(
            self.top_bar, text="  by hardovere", font=("Consolas", 9, "bold")
        )
        self.author_lbl.pack(side="left", pady=(5, 0))

        self.settings_btn = tk.Button(
            self.top_bar,
            text="⚙ Настройки",
            font=("Segoe UI Semibold", 9),
            relief="flat",
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.toggle_settings_drawer
        )
        self.settings_btn.pack(side="right")

        self.orb = IncyPowerOrb(self, on_click=self.on_master_orb_click)
        self.orb.pack(padx=20, pady=(4, 6))

        self.zapret_card = IncyModuleCard(
            self,
            title="Zapret (Discord & YouTube)",
            subtitle="Подбор профиля под провайдера",
            on_toggle=self.on_zapret_toggle
        )
        self.zapret_card.pack(padx=20, pady=6)

        self.tg_card = IncyModuleCard(
            self,
            title="Telegram WS Proxy",
            subtitle=f"Flowseal туннель • 127.0.0.1:{self.cfg.get('tg_proxy_port', '1080')}",
            on_toggle=self.on_tg_toggle
        )
        self.tg_card.pack(padx=20, pady=6)

        self.telemetry_header = tk.Frame(self)
        self.telemetry_header.pack(fill="x", padx=24, pady=(10, 2))

        self.telemetry_lbl = tk.Label(
            self.telemetry_header, text="ЖУРНАЛ", font=("Consolas", 8, "bold")
        )
        self.telemetry_lbl.pack(side="left")

        self.update_lbl = tk.Label(
            self.telemetry_header,
            text="↻ Обновить",
            font=("Segoe UI", 8, "underline"),
            cursor="hand2"
        )
        self.update_lbl.pack(side="right")
        self.update_lbl.bind(
            "<Button-1>",
            lambda e: threading.Thread(target=self.engine.update_zapret_now, daemon=True).start()
        )

        self.repick_lbl = tk.Label(
            self.telemetry_header,
            text="⚡ Подобрать лучший",
            font=("Segoe UI Semibold", 8, "underline"),
            cursor="hand2"
        )
        self.repick_lbl.pack(side="right", padx=(0, 10))
        self.repick_lbl.bind(
            "<Button-1>",
            lambda e: threading.Thread(target=self.engine.reset_and_repick_profile, daemon=True).start()
        )

        self.log_box = tk.Text(
            self,
            height=7,
            font=("Consolas", 8),
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            state="disabled"
        )
        self.log_box.pack(fill="both", expand=True, padx=22, pady=(2, 18))
        self._refresh_log_widget()

        self.settings_drawer = IncySettingsDrawer(
            self,
            cfg=self.cfg,
            themes_dict=THEMES,
            on_theme_change=self._on_theme_changed_from_drawer,
            on_repick=lambda: threading.Thread(target=self.engine.reset_and_repick_profile, daemon=True).start(),
            on_update=lambda: threading.Thread(target=self.engine.update_zapret_now, daemon=True).start(),
            on_save_port=self._on_port_saved_from_drawer,
            on_state_change=self._on_drawer_state_changed
        )

    def apply_theme(self):
        t = self.cfg.theme
        apply_win11_window_style(self, is_dark=t["is_dark"])

        self.configure(bg=t["bg"])
        self.top_bar.configure(bg=t["bg"])
        self.brand_lbl.configure(bg=t["bg"], fg=t["text"])
        self.author_lbl.configure(bg=t["bg"], fg=t["accent"])

        is_open = getattr(self, "settings_drawer", None) and self.settings_drawer.is_open
        self.settings_btn.configure(
            bg=t["surface_hover"] if is_open else t["surface"],
            fg=t["accent"] if is_open else t["text"],
            activebackground=t["surface_hover"],
            activeforeground=t["text"]
        )

        self.orb.render(t)
        self.zapret_card.render(t)
        self.tg_card.render(t)

        self.telemetry_header.configure(bg=t["bg"])
        self.telemetry_lbl.configure(bg=t["bg"], fg=t["subtext"])
        self.repick_lbl.configure(bg=t["bg"], fg=t["success"])
        self.update_lbl.configure(
            bg=t["bg"],
            fg=t["warning"] if self.engine.update_available_tag else t["accent"]
        )

        self.log_box.configure(
            bg=t["log_bg"],
            fg=t["subtext"],
            insertbackground=t["text"]
        )

        if hasattr(self, "settings_drawer"):
            self.settings_drawer.apply_theme(t)

    def toggle_settings_drawer(self):
        self.settings_drawer.toggle()

    def _on_drawer_state_changed(self, is_open: bool):
        t = self.cfg.theme
        if is_open:
            self.settings_btn.configure(text="✕ Закрыть", bg=t["surface_hover"], fg=t["accent"])
        else:
            self.settings_btn.configure(text="⚙ Настройки", bg=t["surface"], fg=t["text"])

    def _on_theme_changed_from_drawer(self, name: str):
        self.cfg.set("theme", name)
        self.apply_theme()

    def _on_port_saved_from_drawer(self, port: str):
        self.cfg.set("tg_proxy_port", port)
        self._sync_ui()
        self._append_log("Настройки сохранены.")

    def _watchdog_loop(self):
        try:
            self.engine.poll_external_state()
        except Exception:
            pass
        self.after(500, self._watchdog_loop)

    def on_master_orb_click(self):
        if self.engine.busy or self.engine.tg_busy:
            return
        if self.engine.zapret_active or self.engine.tg_active:
            threading.Thread(target=self._stop_active_worker, daemon=True).start()
        else:
            threading.Thread(target=self._start_selected_worker, daemon=True).start()

    def _start_selected_worker(self):
        use_tg = bool(self.cfg.get("use_tg_proxy", True))
        use_zap = bool(self.cfg.get("use_zapret", False))
        if not use_tg and not use_zap:
            use_tg = True
            self.cfg.set("use_tg_proxy", True)

        if use_tg:
            self.engine.start_tg_proxy()
        if use_zap:
            self.engine.start_zapret()

    def _stop_active_worker(self):
        if self.engine.zapret_active:
            self.engine.stop_zapret()
        if self.engine.tg_active:
            self.engine.stop_tg_proxy()

    def on_zapret_toggle(self, desired_state: bool):
        if self.engine.busy:
            self.zapret_card.set_checked(self.engine.zapret_active)
            return
        self.cfg.set("use_zapret", bool(desired_state))
        if desired_state:
            threading.Thread(target=self.engine.start_zapret, daemon=True).start()
        else:
            threading.Thread(target=self.engine.stop_zapret, daemon=True).start()

    def on_tg_toggle(self, desired_state: bool):
        if self.engine.tg_busy:
            self.tg_card.set_checked(self.engine.tg_active)
            return
        self.cfg.set("use_tg_proxy", bool(desired_state))
        if desired_state:
            threading.Thread(target=self.engine.start_tg_proxy, daemon=True).start()
        else:
            threading.Thread(target=self.engine.stop_tg_proxy, daemon=True).start()

    def sync_ui_from_thread(self):
        self.after(0, self._sync_ui)

    def _sync_ui(self):
        t = self.cfg.theme
        self.zapret_card.set_checked(self.engine.zapret_active)
        self.tg_card.set_checked(self.engine.tg_active)

        if self.engine.update_available_tag:
            self.update_lbl.configure(
                text=f"⬆ Zapret {self.engine.update_available_tag}",
                fg=t["warning"]
            )
        else:
            ver = self.cfg.get("zapret_version", "")
            self.update_lbl.configure(
                text=f"↻ {ver}" if ver else "↻ Обновить",
                fg=t["accent"]
            )

        port = self.cfg.get("tg_proxy_port", "1080")
        if self.engine.tg_busy:
            self.tg_card.set_subtitle("Запуск TG Proxy...")
        elif self.engine.tg_active:
            self.tg_card.set_subtitle(f"Работает в трее • 127.0.0.1:{port}")
        else:
            self.tg_card.set_subtitle(f"Flowseal туннель • 127.0.0.1:{port}")

        saved_prof = self.cfg.get("best_profile", "").replace(".bat", "")
        live_ping = self.engine.ping_ms if self.engine.ping_ms is not None else self.cfg.get("best_ping", None)
        ping_str = f" • {live_ping} ms" if live_ping is not None else ""

        route_str = ""
        if self.engine.local_ip and self.engine.target_ip and self.engine.local_ip != "0.0.0.0":
            route_str = f"{self.engine.local_ip} → {self.engine.target_ip}"

        if self.engine.busy:
            self.zapret_card.set_subtitle(self.engine.active_profile)
        elif self.engine.zapret_active:
            if route_str:
                self.zapret_card.set_subtitle(f"{route_str}{ping_str}")
            else:
                self.zapret_card.set_subtitle(f"Профиль: {self.engine.active_profile}{ping_str}")
        elif saved_prof:
            self.zapret_card.set_subtitle(f"Лучший профиль: {saved_prof}{ping_str}")
        else:
            self.zapret_card.set_subtitle("Включите для подбора профиля")

        if self.engine.busy:
            self.orb.set_status("scanning", subtitle=self.engine.active_profile)
        elif self.engine.zapret_active or self.engine.tg_active:
            parts = []
            if self.engine.tg_active:
                parts.append("TG Proxy")
            if self.engine.zapret_active:
                parts.append(self.engine.active_profile)
            self.orb.set_status("active", subtitle=" + ".join(parts), ping=self.engine.ping_ms)
        else:
            targets = []
            if self.cfg.get("use_tg_proxy", True):
                targets.append("TG Proxy")
            if self.cfg.get("use_zapret", False):
                targets.append(saved_prof if saved_prof else "Zapret")
            target_str = " + ".join(targets) if targets else "TG Proxy"
            self.orb.set_status("idle", subtitle=f"Запуск: {target_str}")

    def append_log_from_thread(self, msg: str):
        self.after(0, lambda: self._append_log(msg))

    def _append_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] {msg}")
        if len(self.logs) > 80:
            self.logs = self.logs[-80:]
        self._refresh_log_widget()

    def _refresh_log_widget(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", "\n".join(self.logs))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def on_exit(self):
        self.engine.shutdown_all()
        self.destroy()


if __name__ == "__main__":
    set_windows_app_id()
    if sys.platform == "win32" and not is_admin():
        elevate_permissions()
    app = FreeCRApp()
    app.mainloop()
