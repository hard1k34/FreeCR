import os
import ssl
import json
import shutil
import zipfile
import urllib.request
from config import ZAPRET_AUTO_DIR, TG_AUTO_DIR, SSL_CONTEXT, is_clean_ascii_path

ssl._create_default_https_context = ssl._create_unverified_context

ZAPRET_API = "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest"
TG_PROXY_API = "https://api.github.com/repos/Flowseal/tg-ws-proxy/releases/latest"


class AutoInstaller:
    def __init__(self, config, status_callback=None):
        self.config = config
        self.status = status_callback or (lambda msg: None)

    def _fetch_json(self, url):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "FreeCR/3.9",
                "Accept": "application/vnd.github+json"
            }
        )
        with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _download_file(self, url, dest_path, label):
        self.status(f"Скачивание {label}...")
        req = urllib.request.Request(url, headers={"User-Agent": "FreeCR/3.9"})
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp, open(dest_path, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            last_pct = -1
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    if pct != last_pct and pct % 10 == 0:
                        last_pct = pct
                        self.status(f"Загрузка {label}: {pct}%")

    def check_zapret_update(self):
        try:
            release = self._fetch_json(ZAPRET_API)
            latest_tag = release.get("tag_name", "").strip()
            current_tag = self.config.get("zapret_version", "").strip()
            existing_root = self._find_zapret_root(self.config.get("zapret_dir", "")) or self._find_zapret_root(ZAPRET_AUTO_DIR)

            if not existing_root:
                return True, latest_tag, release
            if latest_tag and current_tag and latest_tag != current_tag:
                return True, latest_tag, release
            if latest_tag and not current_tag:
                self.config.set("zapret_version", latest_tag)
            return False, latest_tag, release
        except Exception:
            return False, "", None

    def ensure_zapret(self, custom_dir="", force_update=False) -> str:
        if not force_update:
            if custom_dir and is_clean_ascii_path(custom_dir) and os.path.isdir(custom_dir) and self._has_zapret_files(custom_dir):
                return custom_dir
            found = self._find_zapret_root(ZAPRET_AUTO_DIR)
            if found:
                return found

        self.status("Получение релиза Zapret...")
        release = self._fetch_json(ZAPRET_API)
        tag = release.get("tag_name", "latest")

        zip_url = None
        for asset in release.get("assets", []):
            name = asset.get("name", "").lower()
            if name.endswith(".zip"):
                zip_url = asset.get("browser_download_url")
                break
        if not zip_url:
            zip_url = release.get("zipball_url")

        if force_update and os.path.isdir(ZAPRET_AUTO_DIR):
            shutil.rmtree(ZAPRET_AUTO_DIR, ignore_errors=True)
        os.makedirs(ZAPRET_AUTO_DIR, exist_ok=True)

        archive_path = os.path.join(ZAPRET_AUTO_DIR, "zapret_latest.zip")
        self._download_file(zip_url, archive_path, f"Zapret {tag}")

        self.status(f"Распаковка Zapret {tag}...")
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(ZAPRET_AUTO_DIR)
        try:
            os.remove(archive_path)
        except OSError:
            pass

        root = self._find_zapret_root(ZAPRET_AUTO_DIR)
        if not root:
            raise RuntimeError("Не найдены файлы general*.bat и winws.exe")

        self.config.set("zapret_version", tag)
        self.config.set("zapret_dir", root)
        self.status(f"Zapret {tag} установлен.")
        return root

    def ensure_tg_proxy(self, custom_path="", force_update=False) -> str:
        if not force_update:
            if custom_path and os.path.isfile(custom_path):
                return custom_path
            existing = self._find_tg_executable(TG_AUTO_DIR)
            if existing:
                return existing

        self.status("Получение релиза TG WS Proxy...")
        release = self._fetch_json(TG_PROXY_API)
        tag = release.get("tag_name", "latest")

        exe_asset = None
        zip_asset = None
        for asset in release.get("assets", []):
            name = asset.get("name", "").lower()
            if name.endswith(".exe"):
                exe_asset = asset
                break
            elif name.endswith(".zip"):
                zip_asset = asset

        os.makedirs(TG_AUTO_DIR, exist_ok=True)

        if exe_asset:
            dest = os.path.join(TG_AUTO_DIR, exe_asset["name"])
            self._download_file(exe_asset["browser_download_url"], dest, f"TG Proxy {tag}")
            self.config.set("tg_proxy_version", tag)
            self.config.set("tg_proxy_path", dest)
            self.status(f"TG Proxy {tag} готов.")
            return dest

        if zip_asset:
            archive = os.path.join(TG_AUTO_DIR, "tg_proxy.zip")
            self._download_file(zip_asset["browser_download_url"], archive, f"TG Proxy {tag}")
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(TG_AUTO_DIR)
            try:
                os.remove(archive)
            except OSError:
                pass
            found = self._find_tg_executable(TG_AUTO_DIR)
            if found:
                self.config.set("tg_proxy_version", tag)
                self.config.set("tg_proxy_path", found)
                self.status(f"TG Proxy {tag} готов.")
                return found

        raise RuntimeError("Не найден .exe файл в релизе TG WS Proxy")

    def _has_zapret_files(self, folder):
        if not folder or not os.path.isdir(folder):
            return False
        try:
            files = [f.lower() for f in os.listdir(folder)]
            return any(f.startswith(("general", "discord")) and f.endswith(".bat") for f in files)
        except Exception:
            return False

    def _find_zapret_root(self, base_folder):
        if not base_folder or not os.path.isdir(base_folder):
            return None
        if self._has_zapret_files(base_folder):
            return base_folder
        for root, _, files in os.walk(base_folder):
            if any(f.lower().startswith(("general", "discord")) and f.lower().endswith(".bat") for f in files):
                return root
        return None

    def _find_tg_executable(self, base_folder):
        if not base_folder or not os.path.isdir(base_folder):
            return None
        for root, _, files in os.walk(base_folder):
            for f in files:
                if f.lower().endswith(".exe"):
                    return os.path.join(root, f)
        return None
