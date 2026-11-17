import os
import sys
import ssl
import json
import shutil
import ctypes

ssl._create_default_https_context = ssl._create_unverified_context
SSL_CONTEXT = ssl._create_unverified_context()

IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if IS_FROZEN else __file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)

ASSETS_DIR = os.path.join(RESOURCE_DIR, "assets")
ICON_PNG = os.path.join(ASSETS_DIR, "icon.png")
ICON_ICO = os.path.join(ASSETS_DIR, "icon.ico")

_PROG_DATA = os.environ.get("ProgramData", r"C:\ProgramData")
if _PROG_DATA and _PROG_DATA.isascii() and " " not in _PROG_DATA:
    RUNTIME_DIR = os.path.join(_PROG_DATA, "FreeCR")
else:
    RUNTIME_DIR = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "FreeCR_runtime")

ZAPRET_AUTO_DIR = os.path.join(RUNTIME_DIR, "zapret")
TG_AUTO_DIR = os.path.join(RUNTIME_DIR, "tg_proxy")
RUNTIME_ASSETS_DIR = os.path.join(RUNTIME_DIR, "assets")
CONFIG_FILE = os.path.join(BASE_DIR, "settings.json")


def get_safe_icon_paths():
    os.makedirs(RUNTIME_ASSETS_DIR, exist_ok=True)
    safe_ico = os.path.join(RUNTIME_ASSETS_DIR, "icon.ico")
    safe_png = os.path.join(RUNTIME_ASSETS_DIR, "icon.png")

    for src, dst in ((ICON_ICO, safe_ico), (ICON_PNG, safe_png)):
        if os.path.isfile(src):
            try:
                if (not os.path.isfile(dst)) or (os.path.getsize(src) != os.path.getsize(dst)):
                    shutil.copy2(src, dst)
            except Exception:
                pass

    final_ico = safe_ico if os.path.isfile(safe_ico) else ICON_ICO
    final_png = safe_png if os.path.isfile(safe_png) else ICON_PNG
    return final_ico, final_png


PROFILE_SCHEMA_VER = 4

DEFAULT_CONFIG = {
    "theme": "Obsidian Dark",
    "zapret_dir": "",
    "zapret_version": "",
    "tg_proxy_path": "",
    "tg_proxy_version": "",
    "tg_proxy_port": "1080",
    "best_profile": "",
    "best_ping": None,
    "profile_ver": PROFILE_SCHEMA_VER,
    "game_filter_mode": "all",
    "ipset_mode": "any",
    "use_zapret": False,
    "use_tg_proxy": True,
    "auto_check_updates": False
}

THEMES = {
    "Obsidian Dark": {
        "bg": "#090A0D",
        "surface": "#111319",
        "surface_hover": "#161922",
        "border": "#1E222E",
        "border_active": "#6366F1",
        "text": "#F3F4F6",
        "subtext": "#7D8590",
        "accent": "#6366F1",
        "success": "#10B981",
        "warning": "#F59E0B",
        "danger": "#EF4444",
        "switch_off": "#232734",
        "knob": "#FFFFFF",
        "log_bg": "#060709",
        "is_dark": True
    },
    "Graphite Mono": {
        "bg": "#0E0E10",
        "surface": "#161618",
        "surface_hover": "#1E1E21",
        "border": "#27272B",
        "border_active": "#E4E4E7",
        "text": "#FAFAFA",
        "subtext": "#71717A",
        "accent": "#E4E4E7",
        "success": "#22C55E",
        "warning": "#EAB308",
        "danger": "#F43F5E",
        "switch_off": "#27272A",
        "knob": "#09090B",
        "log_bg": "#09090B",
        "is_dark": True
    },
    "Nordic Slate": {
        "bg": "#0B1017",
        "surface": "#121A24",
        "surface_hover": "#182230",
        "border": "#212E3F",
        "border_active": "#38BDF8",
        "text": "#F0F6FC",
        "subtext": "#7D8590",
        "accent": "#38BDF8",
        "success": "#2EA043",
        "warning": "#D29922",
        "danger": "#F85149",
        "switch_off": "#212E3F",
        "knob": "#FFFFFF",
        "log_bg": "#070A0F",
        "is_dark": True
    },
    "Alabaster Light": {
        "bg": "#F3F4F6",
        "surface": "#FFFFFF",
        "surface_hover": "#F9FAFB",
        "border": "#E5E7EB",
        "border_active": "#4F46E5",
        "text": "#111827",
        "subtext": "#6B7280",
        "accent": "#4F46E5",
        "success": "#059669",
        "warning": "#D97706",
        "danger": "#DC2626",
        "switch_off": "#D1D5DB",
        "knob": "#FFFFFF",
        "log_bg": "#E5E7EB",
        "is_dark": False
    }
}


def is_clean_ascii_path(path: str) -> bool:
    return bool(path) and path.isascii() and (" " not in path)


class ConfigManager:
    def __init__(self):
        os.makedirs(ZAPRET_AUTO_DIR, exist_ok=True)
        os.makedirs(TG_AUTO_DIR, exist_ok=True)
        os.makedirs(RUNTIME_ASSETS_DIR, exist_ok=True)
        self.data = self.load()
        changed = False

        old_zap = self.data.get("zapret_dir", "")
        if old_zap and not is_clean_ascii_path(old_zap):
            self.data["zapret_dir"] = ""
            changed = True

        if self.data.get("profile_ver", 1) < PROFILE_SCHEMA_VER:
            self.data["best_profile"] = ""
            self.data["best_ping"] = None
            self.data["game_filter_mode"] = "all"
            self.data["ipset_mode"] = "any"
            self.data["auto_check_updates"] = False
            self.data["profile_ver"] = PROFILE_SCHEMA_VER
            changed = True

        if changed:
            self.save()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if "profile_ver" not in raw:
                        raw["profile_ver"] = 1
                    return {**DEFAULT_CONFIG, **raw}
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save(self):
        try:
            tmp_file = CONFIG_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            os.replace(tmp_file, CONFIG_FILE)
        except Exception:
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=4)
            except Exception:
                pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    @property
    def theme(self):
        name = self.data.get("theme", "Obsidian Dark")
        return THEMES.get(name, THEMES["Obsidian Dark"])


def apply_win11_window_style(window, is_dark=True):
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        dark_val = ctypes.c_int(1 if is_dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_val), ctypes.sizeof(dark_val)
        )
        corner_val = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner_val), ctypes.sizeof(corner_val)
        )
    except Exception:
        pass


def apply_win32_window_icon(window, ico_path: str):
    if sys.platform != "win32" or not ico_path or not os.path.isfile(ico_path):
        return
    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCLP_HICON = -14
        GCLP_HICONSM = -34

        hicon_big = user32.LoadImageW(None, ico_path, IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
        hicon_small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        inner_hwnd = window.winfo_id()
        outer_hwnd = user32.GetParent(inner_hwnd)

        set_class_ptr = getattr(user32, "SetClassLongPtrW", None) or getattr(user32, "SetClassLongW", None)

        for hwnd in (outer_hwnd, inner_hwnd):
            if not hwnd:
                continue
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                if set_class_ptr:
                    set_class_ptr(hwnd, GCLP_HICON, hicon_big)
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                if set_class_ptr:
                    set_class_ptr(hwnd, GCLP_HICONSM, hicon_small)
    except Exception:
        pass
