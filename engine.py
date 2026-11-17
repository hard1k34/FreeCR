import os
import re
import ssl
import sys
import glob
import json
import time
import shlex
import shutil
import socket
import ctypes
import ipaddress
import threading
import subprocess
import http.client
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from config import SSL_CONTEXT, PROFILE_SCHEMA_VER
from updater import AutoInstaller

ssl._create_default_https_context = ssl._create_unverified_context

if sys.platform == "win32":
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    _kernel32 = ctypes.windll.kernel32
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


def is_process_running(exe_name: str) -> bool:
    if not exe_name or sys.platform != "win32":
        return False
    target = os.path.basename(exe_name).lower()
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE or not snap:
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return False
        while True:
            if entry.szExeFile.lower() == target:
                return True
            if not _kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
        return False
    finally:
        _kernel32.CloseHandle(snap)


def is_valid_public_ipv4(ip_str: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip_str)
        return not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        )
    except Exception:
        return False


def get_local_outbound_ip() -> str:
    for probe_dst in (("1.1.1.1", 80), ("8.8.8.8", 80), ("77.88.8.8", 80)):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(probe_dst)
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "0.0.0.0"


PROBE_ENDPOINTS = [
    ("YouTube Web", "https://www.youtube.com/watch?v=jNQXAC9IVRw", ("youtube.com", "google.com"), 32768, 65536),
    ("YouTube Media", "https://i.ytimg.com/vi/aqz-KE-bpKQ/maxresdefault.jpg", ("ytimg.com", "google.com"), 32768, 49152),
    ("YouTube Video", "https://redirector.googlevideo.com/report_mapping", ("googlevideo.com", "google.com"), 0, 4096),
    ("Discord API", "https://discord.com/api/v9/experiments", ("discord.com",), 16384, 49152),
    ("Epic Games", "https://www.epicgames.com/id/api/location", ("epicgames.com",), 0, 4096),
]

ZAPRET_TARGET_HOSTS = [
    "www.youtube.com",
    "i.ytimg.com",
    "discord.com",
    "gateway.discord.gg",
    "www.epicgames.com",
]

TG_TARGET_HOSTS = [
    "kws1.web.telegram.org",
    "kws2.web.telegram.org",
]


class BoundHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port=443, source_ip="0.0.0.0", target_ip=None, timeout=3.0, context=None):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._source_ip = source_ip
        self._target_ip = target_ip or host

    def connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        if self._source_ip and self._source_ip != "0.0.0.0":
            try:
                sock.bind((self._source_ip, 0))
            except Exception:
                pass
        sock.connect((self._target_ip, self.port))
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class CoreEngine:
    def __init__(self, config, on_status_change=None, on_log=None):
        self.config = config
        self.on_status = on_status_change or (lambda: None)
        self.log = on_log or (lambda msg: None)
        self.installer = AutoInstaller(config, status_callback=self.log)

        self.zapret_active = False
        self.tg_active = False
        self.busy = False
        self.tg_busy = False

        saved_prof = self.config.get("best_profile", "").replace(".bat", "")
        self.active_profile = saved_prof if saved_prof else "Не выбран"
        self.ping_ms = self.config.get("best_ping", None)
        self.local_ip = get_local_outbound_ip()
        self.target_ip = ""
        self.update_available_tag = ""

        self.winws_proc = None
        self.tg_proc = None
        self.tg_exe_name = os.path.basename(self.config.get("tg_proxy_path", "")) or ""
        self.tg_start_ts = 0.0
        self.tg_port_was_open = False

        self._dns_cache = {}
        self._ipset_sample_ips = []
        self._ping_in_flight = False
        self._last_ping_ts = 0.0

    def _query_doh_ipv4(self, host: str) -> str | None:
        doh_urls = (
            f"https://dns.google/resolve?name={urllib.parse.quote(host)}&type=A",
            f"https://1.1.1.1/dns-query?name={urllib.parse.quote(host)}&type=A",
        )
        for url in doh_urls:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/dns-json",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=1.6, context=SSL_CONTEXT) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    for ans in payload.get("Answer", []):
                        if ans.get("type") == 1:
                            cand = ans.get("data", "").strip()
                            if is_valid_public_ipv4(cand):
                                return cand
            except Exception:
                continue
        return None

    def _resolve_clean_ipv4(self, host: str) -> str | None:
        cached = self._dns_cache.get(host)
        if cached and (time.time() - cached[1]) < 600:
            return cached[0]

        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
            for info in infos:
                cand = info[4][0]
                if is_valid_public_ipv4(cand):
                    self._dns_cache[host] = (cand, time.time())
                    return cand
        except Exception:
            pass

        doh_ip = self._query_doh_ipv4(host)
        if doh_ip and is_valid_public_ipv4(doh_ip):
            self._dns_cache[host] = (doh_ip, time.time())
            return doh_ip

        return None

    def _load_ipset_targets(self, zap_dir: str):
        if self._ipset_sample_ips:
            return
        ipset_backup = os.path.join(zap_dir, "lists", "ipset-all.txt.backup")
        ipset_path = ipset_backup if os.path.isfile(ipset_backup) else os.path.join(zap_dir, "lists", "ipset-all.txt")
        if not os.path.isfile(ipset_path):
            return
        found = []
        try:
            with open(ipset_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#") or s == "0.0.0.0/0":
                        continue
                    try:
                        net = ipaddress.IPv4Network(s, strict=False)
                        if net.prefixlen == 32:
                            cand = str(net.network_address)
                        elif net.prefixlen >= 24 and net.num_addresses >= 4:
                            cand = str(net.network_address + 1)
                        else:
                            continue
                        if is_valid_public_ipv4(cand):
                            found.append(cand)
                            if len(found) >= 6:
                                break
                    except Exception:
                        continue
        except Exception:
            pass
        if found:
            self._ipset_sample_ips = found

    def _collect_unblocked_target_ips(self, mode: str) -> list[str]:
        hosts = ZAPRET_TARGET_HOSTS if mode == "zapret" else TG_TARGET_HOSTS
        ips = []
        with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
            for ip in pool.map(self._resolve_clean_ipv4, hosts):
                if ip and ip not in ips:
                    ips.append(ip)
        if mode == "zapret":
            for ip in self._ipset_sample_ips[:3]:
                if ip not in ips:
                    ips.append(ip)
        return ips

    def _measure_single_ip_rtt(self, args) -> tuple[str, int | None]:
        src_ip, dst_ip, port = args
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.4)
        t0 = time.perf_counter()
        try:
            if src_ip and src_ip != "0.0.0.0":
                try:
                    s.bind((src_ip, 0))
                except Exception:
                    pass
            s.connect((dst_ip, port))
            ms = int(round((time.perf_counter() - t0) * 1000))
            return dst_ip, max(1, ms)
        except Exception:
            return dst_ip, None
        finally:
            try:
                s.close()
            except Exception:
                pass

    def measure_route_ping(self, mode: str | None = None) -> tuple[str, str, int | None]:
        src_ip = get_local_outbound_ip()
        self.local_ip = src_ip

        if mode is None:
            mode = "zapret" if self.zapret_active else "tg"

        target_ips = self._collect_unblocked_target_ips(mode)
        if not target_ips:
            return src_ip, "", None

        tasks = [(src_ip, dst_ip, 443) for dst_ip in target_ips]
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            results = list(pool.map(self._measure_single_ip_rtt, tasks))

        valid = [(dst_ip, ms) for dst_ip, ms in results if ms is not None]
        if not valid:
            return src_ip, target_ips[0], None

        valid.sort(key=lambda item: item[1])
        best_dst, best_ms = valid[0]
        return src_ip, best_dst, best_ms

    def _update_ping_worker(self):
        try:
            src_ip, dst_ip, ms = self.measure_route_ping()
            if ms is not None and (self.zapret_active or self.tg_active):
                prev_ms = self.ping_ms
                prev_dst = self.target_ip
                self.local_ip = src_ip
                if dst_ip:
                    self.target_ip = dst_ip
                self.ping_ms = ms
                if self.zapret_active:
                    self.config.data["best_ping"] = ms
                if prev_ms != ms or prev_dst != self.target_ip:
                    self.on_status()
        finally:
            self._ping_in_flight = False

    def apply_zapret_service_preset(self, zap_dir: str):
        bin_dir = os.path.join(zap_dir, "bin")
        utils_dir = os.path.join(zap_dir, "utils")
        lists_dir = os.path.join(zap_dir, "lists")
        os.makedirs(bin_dir, exist_ok=True)
        os.makedirs(lists_dir, exist_ok=True)

        for folder in (bin_dir, utils_dir):
            if os.path.isdir(folder):
                gf_flag = os.path.join(folder, "game_filter.enabled")
                try:
                    with open(gf_flag, "w", encoding="utf-8") as f:
                        f.write("all")
                except OSError:
                    pass

                upd_flag = os.path.join(folder, "check_updates.enabled")
                if os.path.exists(upd_flag):
                    try:
                        os.remove(upd_flag)
                    except OSError:
                        pass

        ipset_all = os.path.join(lists_dir, "ipset-all.txt")
        ipset_backup = os.path.join(lists_dir, "ipset-all.txt.backup")
        if os.path.isfile(ipset_all):
            try:
                with open(ipset_all, "r", encoding="utf-8", errors="ignore") as f:
                    cur_val = f.read().strip()
                if cur_val and cur_val != "0.0.0.0/0" and not os.path.isfile(ipset_backup):
                    shutil.copy2(ipset_all, ipset_backup)
            except OSError:
                pass

        try:
            with open(ipset_all, "w", encoding="utf-8") as f:
                f.write("0.0.0.0/0\n")
        except OSError:
            pass

    def _ensure_user_lists(self, zap_dir: str, extra_args=None):
        lists_dir = os.path.join(zap_dir, "lists")
        os.makedirs(lists_dir, exist_ok=True)

        defaults = {
            "list-general-user.txt": "domain.example.abc\n",
            "list-exclude-user.txt": "domain.example.abc\n",
            "ipset-exclude-user.txt": "255.255.255.255/32\n",
        }
        for fname, content in defaults.items():
            fpath = os.path.join(lists_dir, fname)
            if not os.path.isfile(fpath):
                try:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(content)
                except OSError:
                    pass

        if extra_args:
            for arg in extra_args:
                val = arg.split("=", 1)[1] if "=" in arg else arg
                norm = val.replace("/", "\\").strip()
                if norm.lower().startswith("lists\\") and norm.lower().endswith(".txt"):
                    target_path = os.path.join(zap_dir, norm)
                    if not os.path.isfile(target_path):
                        try:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            placeholder = "255.255.255.255/32\n" if "ipset" in norm.lower() else "domain.example.abc\n"
                            with open(target_path, "w", encoding="utf-8") as f:
                                f.write(placeholder)
                        except OSError:
                            pass

    def _collect_service_vars(self, zap_dir: str) -> dict:
        vars_map = {
            "gamefilter": "1024-65535",
            "gamefiltertcp": "1024-65535",
            "gamefilterudp": "1024-65535",
        }
        service_bat = os.path.join(zap_dir, "service.bat")
        if not os.path.isfile(service_bat):
            return vars_map
        try:
            with open(service_bat, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for m in re.finditer(r'^\s*set\s+"?([A-Za-z0-9_]+)=([^"\r\n]+)"?', content, flags=re.IGNORECASE | re.MULTILINE):
                k = m.group(1).lower()
                v = m.group(2).strip()
                if "%" not in v and k not in ("bin", "lists") and not k.startswith("gamefilter"):
                    if k not in vars_map:
                        vars_map[k] = v
        except Exception:
            pass
        return vars_map

    def _parse_bat_to_winws_cmd(self, bat_path: str, zap_dir: str):
        try:
            with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        except Exception:
            return None, None

        joined = re.sub(r"\^\s*\r?\n\s*", " ", raw)

        winws_exe = os.path.join(zap_dir, "bin", "winws.exe")
        rel_bin = "bin" + os.sep
        if not os.path.isfile(winws_exe):
            for r, _, files in os.walk(zap_dir):
                for fn in files:
                    if fn.lower() == "winws.exe":
                        winws_exe = os.path.join(r, fn)
                        rel_bin = os.path.relpath(r, zap_dir).rstrip("\\/") + os.sep
                        break

        if not os.path.isfile(winws_exe):
            return None, None

        rel_lists = "lists" + os.sep
        env_vars = self._collect_service_vars(zap_dir)
        env_vars["bin"] = rel_bin
        env_vars["lists"] = rel_lists

        def expand_vars(text: str) -> str:
            text = re.sub(r"%~dp0", "", text, flags=re.IGNORECASE)
            for _ in range(4):
                def repl(m):
                    k = m.group(1).lower()
                    if k in env_vars:
                        return env_vars[k]
                    if k in os.environ:
                        return os.environ[k]
                    return m.group(0)
                new_text = re.sub(r"%([A-Za-z0-9_]+)%", repl, text)
                if new_text == text:
                    break
                text = new_text
            return text

        for line in joined.splitlines():
            s = line.strip()
            if not s or s.lower().startswith(("::", "rem ", "@rem")):
                continue

            m_set = re.match(r'^set\s+"?([A-Za-z0-9_]+)=(.*?)"?$', s, flags=re.IGNORECASE)
            if m_set:
                k = m_set.group(1).lower()
                if k not in ("bin", "lists") and not k.startswith("gamefilter"):
                    env_vars[k] = expand_vars(m_set.group(2))
                continue

            if "winws.exe" in s.lower():
                idx = s.lower().find("winws.exe")
                after = s[idx + len("winws.exe"):].strip()
                if after.startswith('"'):
                    after = after[1:].strip()

                after = expand_vars(after)
                if re.search(r"%[A-Za-z0-9_]+%", after):
                    return None, None

                args = [a.replace('"', "") for a in shlex.split(after, posix=False)]
                return winws_exe, args

        return None, None

    def _build_clean_bat_fallback(self, bat_path: str, zap_dir: str) -> str:
        with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        cleaned = [
            "@echo off\n",
            "chcp 65001 > nul\n",
            f'cd /d "{zap_dir}"\n',
            'set "GameFilter=1024-65535"\n',
            'set "GameFilterTCP=1024-65535"\n',
            'set "GameFilterUDP=1024-65535"\n',
        ]
        for line in lines:
            low = line.strip().lower()
            if low.startswith(("call service.bat", "pause", "@echo off", "chcp ")):
                continue
            line_fixed = re.sub(
                r'^\s*start\s+(?:"[^"]*"\s+)?(?:/[a-z]+\s+)*',
                "",
                line,
                flags=re.IGNORECASE
            )
            cleaned.append(line_fixed)

        tmp_bat = os.path.join(zap_dir, "_run_tmp.bat")
        with open(tmp_bat, "w", encoding="utf-8") as f:
            f.writelines(cleaned)
        return tmp_bat

    def _spawn_profile(self, bat_path: str, zap_dir: str):
        self.kill_winws()
        self.apply_zapret_service_preset(zap_dir)
        winws_exe, args = self._parse_bat_to_winws_cmd(bat_path, zap_dir)
        self._ensure_user_lists(zap_dir, extra_args=args)

        try:
            if winws_exe and args:
                self.winws_proc = subprocess.Popen(
                    [winws_exe, *args],
                    cwd=zap_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                tmp_bat = self._build_clean_bat_fallback(bat_path, zap_dir)
                self.winws_proc = subprocess.Popen(
                    ["cmd.exe", "/c", tmp_bat],
                    cwd=zap_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            return True, ""
        except Exception as e:
            return False, str(e)

    def _decode_bytes(self, raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "cp866", "cp1251"):
            try:
                return raw.decode(enc).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace").strip()

    def _read_proc_error(self) -> str:
        if not self.winws_proc:
            return ""
        try:
            rc = self.winws_proc.poll()
            out, err = self.winws_proc.communicate(timeout=0.3)
            err_txt = self._decode_bytes(err)
            out_txt = self._decode_bytes(out)

            for block in (err_txt, out_txt):
                if not block:
                    continue
                lines = [
                    ln.strip() for ln in block.splitlines()
                    if ln.strip() and not ln.strip().lower().startswith("github version ")
                ]
                if lines:
                    return lines[-1][:160]

            if rc is not None:
                return f"код выхода {rc}"
        except Exception:
            pass
        return ""

    def kill_winws(self):
        if self.winws_proc and self.winws_proc.poll() is None:
            try:
                self.winws_proc.kill()
            except Exception:
                pass
        self.winws_proc = None
        subprocess.run(
            ["taskkill", "/F", "/IM", "winws.exe", "/T"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

    def is_winws_alive(self) -> bool:
        if self.winws_proc is not None and self.winws_proc.poll() is None:
            return True
        return is_process_running("winws.exe")

    def _probe_single_endpoint(self, item):
        name, url, allowed_hosts, min_bytes, read_limit = item
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        target_ip = self._resolve_clean_ipv4(host)
        src_ip = self.local_ip
        conn = None
        t0 = time.perf_counter()
        try:
            conn = BoundHTTPSConnection(
                host=host,
                port=443,
                source_ip=src_ip,
                target_ip=target_ip,
                timeout=3.0,
                context=SSL_CONTEXT,
            )
            conn.request(
                "GET",
                path,
                headers={
                    "Host": host,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location", "")
                redir_host = urllib.parse.urlparse(loc).hostname or host
                if not any(redir_host.endswith(h) for h in allowed_hosts):
                    return name, False, target_ip, None

            if resp.status >= 500:
                return name, False, target_ip, None

            received = 0
            while received < read_limit:
                chunk = resp.read(min(16384, read_limit - received))
                if not chunk:
                    break
                received += len(chunk)

            if received < min_bytes:
                return name, False, target_ip, None

            ms = max(1, int(round((time.perf_counter() - t0) * 1000)))
            return name, True, target_ip, ms
        except Exception:
            return name, False, target_ip, None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def probe_all_services(self):
        self.local_ip = get_local_outbound_ip()
        with ThreadPoolExecutor(max_workers=len(PROBE_ENDPOINTS)) as pool:
            results = list(pool.map(self._probe_single_endpoint, PROBE_ENDPOINTS))

        passed = 0
        failed = []
        active_dst_ips = []
        fallback_rtts = []
        for name, ok, dst_ip, http_ms in results:
            if ok:
                passed += 1
                if dst_ip and dst_ip not in active_dst_ips:
                    active_dst_ips.append(dst_ip)
                if http_ms is not None:
                    fallback_rtts.append(http_ms)
            else:
                failed.append(name)

        src_ip, best_dst, rtt = self.measure_route_ping(mode="zapret")
        if rtt is not None:
            ping_val = rtt
        elif fallback_rtts:
            ping_val = min(fallback_rtts)
            best_dst = active_dst_ips[0] if active_dst_ips else best_dst
        else:
            ping_val = None
            best_dst = active_dst_ips[0] if active_dst_ips else best_dst

        return passed, len(PROBE_ENDPOINTS), src_ip, best_dst, ping_val, failed

    def collect_profiles(self, zap_dir):
        if not zap_dir or not os.path.isdir(zap_dir):
            return []
        bats = glob.glob(os.path.join(zap_dir, "*.bat"))
        valid = []
        for path in bats:
            name = os.path.basename(path)
            low = name.lower()
            if low.startswith("_run") or "service" in low or "cloudflare" in low:
                continue
            if low.startswith(("general", "discord")):
                valid.append(path)

        def priority(p):
            n = os.path.basename(p).lower()
            if "alt9" in n:
                return (0, n)
            if "alt" in n and "fake" not in n:
                return (1, n)
            if "alt" in n:
                return (2, n)
            if n == "general.bat":
                return (3, n)
            return (4, n)

        return sorted(valid, key=priority)

    def start_zapret(self, force_repick=False):
        if self.busy:
            return False
        self.busy = True
        self.on_status()

        try:
            zap_dir = self.installer.ensure_zapret(self.config.get("zapret_dir", ""))
            self.config.set("zapret_dir", zap_dir)
            self._load_ipset_targets(zap_dir)
            self.apply_zapret_service_preset(zap_dir)
            self.local_ip = get_local_outbound_ip()

            profiles = self.collect_profiles(zap_dir)
            if not profiles:
                self.log("Профили general*.bat не найдены.")
                return False

            saved_name = "" if force_repick else self.config.get("best_profile", "").strip()
            saved_path = os.path.join(zap_dir, saved_name) if saved_name else ""

            if saved_name and os.path.isfile(saved_path):
                clean = saved_name.replace(".bat", "")
                self.active_profile = f"Запуск {clean}..."
                self.on_status()
                self.log(f"Запуск профиля: {clean} (GameFilter: TCP+UDP, ipset: any)")

                ok_spawn, err_msg = self._spawn_profile(saved_path, zap_dir)
                if ok_spawn:
                    time.sleep(0.9)
                    if self.is_winws_alive():
                        self.zapret_active = True
                        self.active_profile = clean
                        src_ip, dst_ip, ms = self.measure_route_ping(mode="zapret")
                        self.local_ip = src_ip
                        self.target_ip = dst_ip
                        self.ping_ms = ms if ms is not None else self.config.get("best_ping", None)
                        route_txt = f" ({src_ip} → {dst_ip}: {self.ping_ms} ms)" if (dst_ip and self.ping_ms is not None) else ""
                        self.log(f"Активен профиль: {clean}{route_txt}")
                        return True
                    detail = self._read_proc_error()
                    self.log(f"winws.exe завершился ({detail or 'ошибка запуска'}).")
                else:
                    self.log(f"Ошибка запуска winws.exe: {err_msg}")

                self.zapret_active = False
                self.active_profile = clean
                return False

            self.log("Параметры: GameFilter=TCP+UDP, ipset=any")
            self.log(f"Тест профилей ({len(profiles)}) от {self.local_ip}...")
            candidates = []
            spawn_failures = 0
            last_detail = ""

            for idx, bat_path in enumerate(profiles, 1):
                prof_name = os.path.basename(bat_path)
                clean_name = prof_name.replace(".bat", "")
                self.active_profile = f"Тест [{idx}/{len(profiles)}]: {clean_name}"
                self.on_status()

                ok_spawn, err_msg = self._spawn_profile(bat_path, zap_dir)
                if not ok_spawn:
                    last_detail = err_msg
                    spawn_failures += 1
                    if spawn_failures >= 2 and not candidates:
                        break
                    continue

                time.sleep(1.3)
                if not self.is_winws_alive():
                    last_detail = self._read_proc_error()
                    spawn_failures += 1
                    if spawn_failures >= 2 and not candidates:
                        break
                    continue

                passed, total, src_ip, dst_ip, avg_ms, failed = self.probe_all_services()
                self.kill_winws()

                if passed > 0:
                    sort_ms = avg_ms if avg_ms is not None else 9999
                    ping_lbl = f"{avg_ms} ms" if avg_ms is not None else "OK"
                    route_lbl = f"{src_ip} → {dst_ip}" if dst_ip else src_ip
                    if passed == total:
                        self.log(f"[{idx}/{len(profiles)}] {clean_name}: OK (5/5) • {route_lbl} ({ping_lbl})")
                    else:
                        miss = ", ".join(failed[:2])
                        self.log(f"[{idx}/{len(profiles)}] {clean_name}: {passed}/{total} (нет: {miss}) • {route_lbl} ({ping_lbl})")
                    candidates.append((passed, -sort_ms, bat_path, prof_name, avg_ms, src_ip, dst_ip))
                else:
                    self.log(f"[{idx}/{len(profiles)}] {clean_name}: нет ответа")

            if not candidates:
                reason = last_detail or "рабочий профиль не найден"
                self.log(f"Тест завершён: {reason}")
                self.active_profile = "Не найден"
                self.zapret_active = False
                return False

            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            best_passed, _, best_bat, best_prof_name, best_ms, best_src, best_dst = candidates[0]
            best_clean = best_prof_name.replace(".bat", "")

            self.active_profile = f"Запуск {best_clean}..."
            self.on_status()

            ok_spawn, _ = self._spawn_profile(best_bat, zap_dir)
            if ok_spawn:
                time.sleep(0.9)
                if self.is_winws_alive():
                    self.config.set("best_profile", best_prof_name)
                    self.config.set("best_ping", best_ms)
                    self.config.set("profile_ver", PROFILE_SCHEMA_VER)
                    self.zapret_active = True
                    self.active_profile = best_clean
                    self.local_ip = best_src
                    self.target_ip = best_dst
                    self.ping_ms = best_ms
                    ping_str = f"{best_ms} ms, " if best_ms is not None else ""
                    route_str = f" [{best_src} → {best_dst}]" if best_dst else ""
                    self.log(f"Выбран профиль: {best_clean} ({ping_str}{best_passed}/{len(PROBE_ENDPOINTS)}){route_str}")
                    return True

            self.log(f"Не удалось запустить {best_clean}.")
            self.zapret_active = False
            return False

        except Exception as e:
            self.log(f"Ошибка Zapret: {e}")
            self.zapret_active = False
            return False
        finally:
            self.busy = False
            self.on_status()

    def stop_zapret(self, silent=False):
        self.kill_winws()
        self.zapret_active = False
        if not self.tg_active:
            self.ping_ms = None
            self.target_ip = ""
        saved = self.config.get("best_profile", "").replace(".bat", "")
        self.active_profile = saved if saved else "Отключено"
        if not silent:
            self.log("Zapret остановлен.")
            self.on_status()

    def reset_and_repick_profile(self):
        if self.busy:
            return
        self.config.set("best_profile", "")
        self.config.set("best_ping", None)
        self.config.set("use_zapret", True)
        self.log("Перепроверка профилей...")
        self.stop_zapret(silent=True)
        self.start_zapret(force_repick=True)

    def _is_port_open(self, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def _is_tg_process_running(self) -> bool:
        if self.tg_proc is not None and self.tg_proc.poll() is None:
            return True
        if self.tg_exe_name and is_process_running(self.tg_exe_name):
            return True
        return False

    def start_tg_proxy(self):
        if self.tg_busy:
            return False
        self.tg_busy = True
        self.on_status()

        try:
            exe_path = self.installer.ensure_tg_proxy(self.config.get("tg_proxy_path", ""))
            self.config.set("tg_proxy_path", exe_path)
            self.tg_exe_name = os.path.basename(exe_path)

            if self._is_tg_process_running():
                self.stop_tg_proxy(silent=True)
                time.sleep(0.25)

            self.tg_proc = subprocess.Popen(
                [exe_path],
                cwd=os.path.dirname(exe_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.tg_start_ts = time.time()
            self.tg_port_was_open = False
            self.tg_active = True
            port = self.config.get("tg_proxy_port", "1080")
            self.log(f"TG Proxy запущен (127.0.0.1:{port})")
            return True
        except Exception as e:
            self.log(f"Ошибка запуска TG Proxy: {e}")
            self.tg_active = False
            return False
        finally:
            self.tg_busy = False
            self.on_status()

    def stop_tg_proxy(self, silent=False):
        if self.tg_proc and self.tg_proc.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.tg_proc.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        if self.tg_exe_name:
            subprocess.run(
                ["taskkill", "/F", "/IM", self.tg_exe_name, "/T"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        self.tg_proc = None
        self.tg_active = False
        self.tg_port_was_open = False
        if not self.zapret_active:
            self.ping_ms = None
            self.target_ip = ""
        if not silent:
            self.log("TG Proxy остановлен.")
            self.on_status()

    def poll_external_state(self):
        changed = False

        if self.tg_active and not self.tg_busy:
            elapsed = time.time() - self.tg_start_ts
            try:
                port = int(self.config.get("tg_proxy_port", "1080"))
            except ValueError:
                port = 1080

            port_open = self._is_port_open(port)
            if port_open:
                self.tg_port_was_open = True

            proc_alive = self._is_tg_process_running()

            if elapsed > 2.0:
                if not proc_alive or (self.tg_port_was_open and not port_open):
                    self.tg_active = False
                    self.tg_proc = None
                    self.tg_port_was_open = False
                    if not self.zapret_active:
                        self.ping_ms = None
                        self.target_ip = ""
                    self.log("TG Proxy выключен в трее.")
                    changed = True

        if self.zapret_active and not self.busy:
            if not self.is_winws_alive():
                self.zapret_active = False
                if not self.tg_active:
                    self.ping_ms = None
                    self.target_ip = ""
                self.log("Процесс winws.exe остановлен.")
                changed = True

        if changed:
            self.on_status()

        if (self.zapret_active or self.tg_active) and not self.busy and not self._ping_in_flight:
            now = time.time()
            if (now - self._last_ping_ts) >= 1.5:
                self._last_ping_ts = now
                self._ping_in_flight = True
                threading.Thread(target=self._update_ping_worker, daemon=True).start()

    def check_updates_background(self):
        has_upd, latest_tag, _ = self.installer.check_zapret_update()
        cur_tag = self.config.get("zapret_version", "")
        if has_upd and latest_tag:
            self.update_available_tag = latest_tag
            if cur_tag:
                self.log(f"Доступно обновление Zapret: {latest_tag} (текущая: {cur_tag})")
            else:
                self.log(f"Доступен релиз Zapret: {latest_tag}")
            self.on_status()

    def update_zapret_now(self):
        if self.busy:
            return
        self.busy = True
        self.on_status()
        try:
            was_running = self.zapret_active
            self.stop_zapret(silent=True)
            z_dir = self.installer.ensure_zapret(force_update=True)
            self.apply_zapret_service_preset(z_dir)
            self.config.set("zapret_dir", z_dir)
            self.update_available_tag = ""
            self.log(f"Zapret обновлён до {self.config.get('zapret_version', 'latest')}.")
            if was_running:
                self.busy = False
                self.start_zapret()
                return
        except Exception as e:
            self.log(f"Ошибка обновления Zapret: {e}")
        finally:
            self.busy = False
            self.on_status()

    def shutdown_all(self):
        self.kill_winws()
        self.stop_tg_proxy(silent=True)
