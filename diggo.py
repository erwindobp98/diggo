"""
Diggo Farmer

Commands:
  python diggo.py              → Auto farmer (loop dinamis)
  python diggo.py --add        → Tambah akun baru via login Telegram
  python diggo.py pass <acc>   → Fetch initData manual untuk 1 akun
  python diggo.py pass-all     → Fetch initData manual semua akun
  python diggo.py help         → Bantuan
"""

import asyncio
import json
import logging
import random
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, quote

import httpx
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import (
    RequestAppWebViewRequest,
    RequestMainWebViewRequest,
    RequestWebViewRequest,
)
from telethon.tl.types import (
    InputBotAppShortName,
    KeyboardButtonWebView,
    KeyboardButtonSimpleWebView,
)


# =====================================================================
# PATH
# =====================================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SESSIONS_DIR = BASE_DIR / "sessions"
DATA_DIR = BASE_DIR / "data"
LOG_PATH = BASE_DIR / "error.log"

SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================================
# LOGGER
# =====================================================================

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("diggo")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


LOGGER = setup_logger()
LOGGER.info("=" * 70)
LOGGER.info("Diggo Farmer dimulai")


def log_info(account_id: str, message: str):
    LOGGER.info(f"[{account_id}] {message}")


def log_warn(account_id: str, message: str):
    LOGGER.warning(f"[{account_id}] {message}")


def log_error(account_id: str, context: str, error: Exception):
    LOGGER.error(f"[{account_id}] {context}: {type(error).__name__}: {error}")
    LOGGER.error(f"[{account_id}] Traceback:\n{traceback.format_exc()}")


# =====================================================================
# CONFIG
# =====================================================================

DEFAULT_CONFIG = {
    "telegram": {
        "api_id": 224069,
        "api_hash": "f2ddfd53867f28a3b6b98e80fa010e9d",
    },
    "bot": {
        "username": "Diggominer_bot",
        "short_name": "app",
        "app_url": "https://diggo.linkpc.net/",
        "api_url": "https://diggo.linkpc.net/api",
        "referral": "ref_b96048f836ebd23b1ea33651",
    },
    "mining": {
        "claim_interval_hours": 8,
    },
    "tasks": {
        "social_confirm_margin_seconds": 3,
        "dwell_seconds_min": 10,
        "dwell_seconds_max": 14,
        "join_delay_seconds": 3,
    },
    "cycle": {
        "min_wait_seconds": 300,
        "max_wait_seconds": 21600,
        "request_timeout": 30,
        "retry_count": 3,
        "stagger_seconds": 3,
    },
    "initdata": {
        "ttl_minutes": 25,
    },
    "logging": {
        "level": "INFO",
    },
}

if not CONFIG_PATH.exists():
    CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("=" * 80)
    print("config.json belum ada — sudah dibuat otomatis.")
    print(f"Lokasi: {CONFIG_PATH}")
    print("=" * 80)
    sys.exit(0)


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"config.json tidak valid: {e}")
        sys.exit(1)

    def merge(target, defaults):
        for k, v in defaults.items():
            if k not in target:
                target[k] = v
            elif isinstance(v, dict) and isinstance(target[k], dict):
                merge(target[k], v)

    merge(cfg, DEFAULT_CONFIG)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return cfg


CFG = load_config()

API_ID = int(CFG["telegram"]["api_id"])
API_HASH = str(CFG["telegram"]["api_hash"])

BOT_USERNAME = str(CFG["bot"]["username"]).lstrip("@")
BOT_SHORT_NAME = str(CFG["bot"].get("short_name") or "app").strip("/")
APP_URL = str(CFG["bot"]["app_url"]).rstrip("/")
API_URL = str(CFG["bot"]["api_url"]).rstrip("/")
REFERRAL_CODE = str(CFG["bot"].get("referral") or "").strip()

MINING_CLAIM_HOURS = int(CFG["mining"]["claim_interval_hours"])

SOCIAL_CONFIRM_MARGIN = int(CFG["tasks"].get("social_confirm_margin_seconds", 3))
DWELL_MIN = float(CFG["tasks"].get("dwell_seconds_min", 10))
DWELL_MAX = float(CFG["tasks"].get("dwell_seconds_max", 14))
JOIN_DELAY = float(CFG["tasks"].get("join_delay_seconds", 3))

MIN_WAIT = int(CFG["cycle"].get("min_wait_seconds", 300))
MAX_WAIT = int(CFG["cycle"].get("max_wait_seconds", 21600))
REQUEST_TIMEOUT = int(CFG["cycle"]["request_timeout"])
RETRY_COUNT = int(CFG["cycle"]["retry_count"])
STAGGER_SECONDS = int(CFG["cycle"].get("stagger_seconds", 3))

INITDATA_TTL_MIN = int(CFG["initdata"].get("ttl_minutes", 50))


# =====================================================================
# DASHBOARD — Vertikal per akun
# =====================================================================

SLOTS = ["ACCOUNT", "AUTH", "MINING", "TASK", "SQUAD", "CHEST"]

STATUS_STYLES = {
    "SUCCESS": "bold green", "SUCCESSFUL": "bold green",
    "READY": "bold green", "OK": "bold green",
    "JOINED": "bold green", "DONE": "bold green",
    "CLAIMED": "bold green", "OPENED": "bold green",
    "START": "bold yellow", "RUNNING": "bold yellow",
    "REQUEST": "yellow", "RESPONSE": "green",
    "WAIT": "bold yellow", "SKIP": "dim yellow",
    "CACHE": "cyan", "FETCH": "cyan", "SAVED": "cyan",
    "MISS": "yellow", "RETRY": "bold magenta", "BUSY": "bold magenta",
    "INPUT": "bold yellow", "CLAIM": "bold yellow",
    "REFRESH": "cyan", "FAILED": "bold red",
    "ERROR": "bold red", "INVALID": "bold red",
    "DWELL": "bold yellow",
}


class Dashboard:
    def __init__(self):
        self.accounts: list[str] = []
        self.data: dict = {}
        self.lock = asyncio.Lock()
        self._console = Console()
        self._live = None
        self._started = False

    def register(self, account_id: str):
        if account_id not in self.data:
            self.data[account_id] = {
                slot: {"status": "WAIT", "detail": "Menunggu..."}
                for slot in SLOTS
            }

    def start(self):
        if self._started:
            return
        self._live = Live(
            self.build_layout(),
            console=self._console,
            refresh_per_second=4,
            screen=True,
            transient=False,
        )
        self._live.start(refresh=True)
        self._started = True

    def stop(self):
        if self._live is not None:
            try:
                self._live.stop()
            finally:
                self._live = None
                self._started = False

    async def update(self, account_id: str, slot: str, status: str, detail: str):
        async with self.lock:
            self.register(account_id)
            slot_key = str(slot).upper()
            if slot_key not in SLOTS:
                slot_key = "ACCOUNT"
            self.data[account_id][slot_key] = {
                "status": str(status).upper(),
                "detail": str(detail),
            }
            self.render()

    def build_table(self) -> Table:
        table = Table(
            title="⛏️  Diggo Farmer",
            box=box.ROUNDED,
            border_style="bright_blue",
            header_style="bold white on blue",
            expand=True,
            show_lines=False,
        )
        table.add_column("ACCOUNT", style="bold cyan", min_width=12, no_wrap=True)
        table.add_column("SLOT", style="bold magenta", min_width=10, no_wrap=True)
        table.add_column("DETAIL", ratio=1, overflow="fold")

        for idx, acc in enumerate(self.accounts):
            if idx > 0:
                table.add_section()
            account_rows = self.data.get(acc, {})
            for slot_idx, slot in enumerate(SLOTS):
                row = account_rows.get(slot, {"status": "WAIT", "detail": "-"})
                status = str(row.get("status", "-")).upper()
                detail = str(row.get("detail", "-")).replace("\n", " ").strip()
                if len(detail) > 110:
                    detail = detail[:107] + "..."
                style = STATUS_STYLES.get(status, "white")
                acc_display = acc if slot_idx == 0 else ""
                table.add_row(
                    acc_display,
                    slot,
                    f"[{style}]{status}[/{style}] · {detail}",
                )
        return table

    def build_layout(self):
        if not self.accounts:
            return Panel("Menunggu akun...", title="⛏️  Diggo Farmer")
        return self.build_table()

    def render(self):
        if not self._started or self._live is None:
            return
        self._live.update(self.build_layout(), refresh=True)


DASHBOARD = Dashboard()


async def activity(account_id: str, slot: str, status: str, detail: str):
    await DASHBOARD.update(account_id, slot, status, detail)


# =====================================================================
# STATE
# =====================================================================

@dataclass
class AccountState:
    account_id: str
    last_balance: float = 0.0
    last_level: int = 0
    cycles_run: int = 0
    last_run_ts: int = 0


class StateManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def load(self, account_id: str) -> AccountState:
        path = self.base_dir / f"{account_id}.json"
        if path.exists():
            try:
                return AccountState(**json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return AccountState(account_id=account_id)

    def save(self, state: AccountState):
        path = self.base_dir / f"{state.account_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)


# =====================================================================
# HELPERS
# =====================================================================

def now_ts() -> float:
    return time.time()


def parse_iso(ts: str | None) -> float:
    if not ts:
        return 0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def find_next_task_reset(tasks_state: dict, server_now_ms: int) -> int:
    """
    Cari waktu reset terdekat dari task yang sedang pending / belum open.
    Return timestamp detik. 0 kalau tidak ada.
    """
    if not isinstance(tasks_state, dict):
        return 0
    now_s = now_ts()
    earliest = None
    for task_id, record in tasks_state.items():
        if not isinstance(record, dict):
            continue
        for key in ("availableAt", "resetAt", "nextAt", "cooldownUntil"):
            ts = record.get(key)
            if ts is None:
                continue
            if isinstance(ts, (int, float)):
                candidate = float(ts)
                if candidate > 1e11:
                    candidate /= 1000.0
                if candidate > now_s:
                    if earliest is None or candidate < earliest:
                        earliest = candidate
    return int(earliest) if earliest else 0


# =====================================================================
# API CLIENT
# =====================================================================

class ApiClient:
    # Endpoint yang WAJIB pakai Idempotency-Key
    WRITE_ENDPOINTS = (
        "/claims/mining",
        "/tasks/claim",
        "/tasks/social/start",
        "/tasks/social/confirm",
        "/tasks/verify",
        "/streak/claim",
        "/referrals/claim",
        "/chests/open",
        "/withdrawals",
        "/adsgram/",
        "/ton/",
    )

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.token: str | None = None
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    async def close(self):
        await self._client.aclose()

    def set_token(self, token: str | None):
        self.token = token

    def _needs_idempotency(self, path: str) -> bool:
        """Cek apakah endpoint butuh Idempotency-Key."""
        return any(path.startswith(ep) for ep in self.WRITE_ENDPOINTS)

    def _headers(self, idempotency_key: str | None = None) -> dict:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": APP_URL,
            "Referer": APP_URL + "/",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def call(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        url = f"{API_URL}{path}"
        last_error = None

        for attempt in range(RETRY_COUNT):
            try:
                response = await self._client.request(
                    method=method.upper(),
                    url=url,
                    json=data if method.lower() in ("post", "put", "patch") else None,
                    headers=self._headers(idempotency_key),
                )
                payload = response.json() if response.content else {}

                if response.status_code < 200 or response.status_code >= 300:
                    err = payload.get("error") if isinstance(payload, dict) else None
                    log_warn(
                        self.account_id,
                        f"HTTP {response.status_code} {method.upper()} {path}: {err}",
                    )
                    if isinstance(payload, dict):
                        payload.setdefault("_http_status", response.status_code)
                    return payload if isinstance(payload, dict) else {"error": err}

                return payload

            except Exception as e:
                last_error = e
                if attempt < RETRY_COUNT - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        return {"success": False, "error": f"HTTP error: {last_error}"}

    async def get(self, path: str) -> dict:
        return await self.call("get", path)

    async def post(self, path: str, data: dict | None = None,
                   idempotency_key: str | None = None) -> dict:
        # Auto-generate Idempotency-Key untuk endpoint write
        if idempotency_key is None and self._needs_idempotency(path):
            idempotency_key = str(uuid.uuid4())
        return await self.call("post", path, data or {}, idempotency_key)


# =====================================================================
# DIGGO CLIENT
# =====================================================================

class DiggoClient:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.tg: TelegramClient | None = None
        self.api = ApiClient(account_id)
        self.init_data_raw: str | None = None
        self.init_data_fetched_at: float = 0
        self.user_obj: dict | None = None
        self.tg_id: int | None = None
        self.state: dict = {}
        self.state_read_at: float = 0
        self._joined_channels: set = set()

    # ------------------------------------------------------------------
    # Cache paths
    # ------------------------------------------------------------------

    def _session_path(self) -> Path:
        return SESSIONS_DIR / self.account_id

    def _initdata_cache_path(self) -> Path:
        return SESSIONS_DIR / f"{self.account_id}.initdata"

    def _load_cached_initdata(self) -> tuple[str | None, float]:
        """Return (init_data, fetched_at)."""
        p = self._initdata_cache_path()
        if not p.exists():
            return None, 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None, 0
            init_data = data.get("initData")
            fetched_at = float(data.get("fetchedAt", 0))
            if not init_data:
                return None, 0
            age_min = (now_ts() - fetched_at) / 60
            if age_min > INITDATA_TTL_MIN:
                return None, fetched_at
            return init_data, fetched_at
        except Exception:
            return None, 0

    def _save_initdata(self, init_data: str):
        try:
            self._initdata_cache_path().write_text(
                json.dumps({
                    "initData": init_data,
                    "fetchedAt": int(now_ts()),
                    "userId": self.tg_id,
                }, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log_warn(self.account_id, f"Gagal simpan initData: {e}")

    def _clear_cached_initdata(self):
        try:
            p = self._initdata_cache_path()
            if p.exists():
                p.unlink()
                log_info(self.account_id, "Cache initData dihapus")
        except Exception as e:
            log_warn(self.account_id, f"Gagal hapus cache initData: {e}")

        

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    async def connect(self, require_login: bool = True) -> bool:
        # Pastikan folder sessions/ writable
        try:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            test_file = SESSIONS_DIR / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
        except Exception as e:
            raise RuntimeError(f"Folder sessions/ tidak writable: {e}")

        self.tg = TelegramClient(
            str(self._session_path()),
            API_ID, API_HASH,
            device_model="Samsung Galaxy S23",
            system_version="Android 14",
            app_version="10.5.2",
            lang_code="en",
            system_lang_code="en-US",
        )

        last_error = None
        for attempt in range(RETRY_COUNT):
            try:
                await self.tg.connect()
                last_error = None
                break
            except Exception as e:
                last_error = e
                await asyncio.sleep(2 + attempt * 2)

        if last_error:
            raise RuntimeError(f"Telegram connect failed: {last_error}")

        if not await self.tg.is_user_authorized():
            if not require_login:
                return False
            await activity(self.account_id, "AUTH", "INPUT",
                           "Session belum ada — login Telegram")
            await self.tg.disconnect()
            await self.login_new_telegram()
            return True

        me = await self.tg.get_me()
        await activity(self.account_id, "AUTH", "OK",
                       f"@{me.username or '-'} | ID={me.id}")
        return True

    async def login_new_telegram(self):
        self.tg = TelegramClient(
            str(self._session_path()),
            API_ID, API_HASH,
            device_model="Samsung Galaxy S23",
            system_version="Android 14",
            app_version="10.5.2",
            lang_code="en",
            system_lang_code="en-US",
        )
        await self.tg.connect()
        phone = input(f"\nNomor Telegram untuk {self.account_id}: ").strip()
        if not phone:
            raise RuntimeError("Nomor kosong")
        await self.tg.send_code_request(phone)
        code_input = input("Kode OTP: ").strip()
        try:
            await self.tg.sign_in(phone=phone, code=code_input)
        except SessionPasswordNeededError:
            password = input("Password 2FA: ")
            await self.tg.sign_in(password=password)

        me = await self.tg.get_me()
        await activity(self.account_id, "AUTH", "SUCCESS",
                       f"@{me.username or '-'} | ID={me.id}")

    async def close(self):
        try:
            await self.api.close()
        except Exception:
            pass
        if self.tg:
            try:
                await self.tg.disconnect()
            except Exception:
                pass
            self.tg = None

    # ------------------------------------------------------------------
    # Fetch initData via WebView
    # ------------------------------------------------------------------

    async def fetch_webapp_query(self) -> str:
        if not self.tg:
            raise RuntimeError("Telegram belum connect")

        bot = await self.tg.get_entity(BOT_USERNAME)
        start_param = REFERRAL_CODE or "start"

        await activity(self.account_id, "AUTH", "FETCH",
                       "Buka WebApp bot...")

        # Coba RequestAppWebView (short name)
        if BOT_SHORT_NAME:
            try:
                result = await self.tg(RequestAppWebViewRequest(
                    peer=bot,
                    app=InputBotAppShortName(
                        bot_id=bot,
                        short_name=BOT_SHORT_NAME,
                    ),
                    platform="android",
                    start_param=start_param,
                ))
                if result.url and "#" in result.url:
                    return self._extract_init_data_from_url(result.url)
            except Exception as e:
                log_warn(self.account_id, f"RequestAppWebView gagal: {e}")

        # Fallback: cari tombol di pesan bot
        try:
            messages = await self.tg.get_messages(bot, limit=20)
            for msg in messages:
                if not msg.reply_markup:
                    continue
                rows = getattr(msg.reply_markup, "rows", None) or []
                for row in rows:
                    for button in row.buttons:
                        url = getattr(button, "url", None)
                        if not url:
                            continue
                        if isinstance(button, KeyboardButtonWebView) or \
                           isinstance(button, KeyboardButtonSimpleWebView):
                            try:
                                result = await self.tg(RequestWebViewRequest(
                                    peer=bot, bot=bot, platform="android",
                                    url=url, start_param=start_param,
                                ))
                                if result.url and "#" in result.url:
                                    return self._extract_init_data_from_url(result.url)
                            except Exception:
                                continue
        except Exception:
            pass

        # Fallback terakhir: RequestMainWebView
        try:
            result = await self.tg(RequestMainWebViewRequest(
                peer=bot, bot=bot, platform="android",
                start_param=start_param,
            ))
            if result.url and "#" in result.url:
                return self._extract_init_data_from_url(result.url)
        except Exception as e:
            log_warn(self.account_id, f"RequestMainWebView gagal: {e}")

        raise RuntimeError(f"WebApp URL tidak ditemukan di @{BOT_USERNAME}")

    def _extract_init_data_from_url(self, url: str) -> str:
        if "#" not in url:
            raise RuntimeError("URL tidak memiliki fragment")
        fragment = url.split("#", 1)[1]
        params = parse_qs(fragment)
        if "tgWebAppData" not in params:
            raise RuntimeError("tgWebAppData tidak ada")
        raw = params["tgWebAppData"][0]
        qs = parse_qs(raw)
        if "user" not in qs:
            raise RuntimeError("Data user tidak ada")
        try:
            user_obj = json.loads(qs["user"][0])
        except Exception as e:
            raise RuntimeError(f"JSON user tidak valid: {e}")
        if not isinstance(user_obj, dict) or not user_obj.get("id"):
            raise RuntimeError("Data user tidak valid")

        self.init_data_raw = raw
        self.user_obj = user_obj
        self.tg_id = int(user_obj["id"])
        self.init_data_fetched_at = now_ts()

        self._save_initdata(raw)

        log_info(self.account_id, f"initData OK ({len(raw)} chars)")
        return raw

    async def ensure_init_data(self) -> str:
        cached, fetched_at = self._load_cached_initdata()
        if cached:
            age_min = (now_ts() - fetched_at) / 60
            await activity(self.account_id, "AUTH", "CACHE",
                           f"initData cache ({age_min:.0f}m)")
            self.init_data_raw = cached
            self.init_data_fetched_at = fetched_at
            qs = parse_qs(cached)
            if "user" in qs:
                try:
                    self.user_obj = json.loads(qs["user"][0])
                    self.tg_id = int(self.user_obj.get("id") or 0)
                except Exception:
                    pass
            return cached

        if not self.tg:
            await self.connect(require_login=True)

        await activity(self.account_id, "AUTH", "FETCH",
                       "Fetch initData baru...")
        return await self.fetch_webapp_query()

    # ------------------------------------------------------------------
    # Login ke API Diggo
    # ------------------------------------------------------------------

    async def login(self):
        await self.ensure_init_data()
        await activity(self.account_id, "AUTH", "RUNNING",
                       "Login /auth/telegram...")

        result = await self.api.post(
            "/auth/telegram",
            {"initData": self.init_data_raw},
        )

        # Cek error expired_init_data → refresh & retry
        err_msg = str(result.get("error") or "").lower()
        is_expired = (
            result.get("_http_status") == 401
            and "expired" in err_msg
        )

        if is_expired:
            log_warn(self.account_id,
                     "initData expired, refresh dari Telegram...")
            await activity(self.account_id, "AUTH", "REFRESH",
                           "initData expired, fetch ulang...")

            # Hapus cache lama
            try:
                cache_path = self._initdata_cache_path()
                if cache_path.exists():
                    cache_path.unlink()
            except Exception:
                pass

            # Fetch initData baru
            self.init_data_raw = None
            self.init_data_fetched_at = 0

            if not self.tg:
                await self.connect(require_login=True)

            try:
                self.init_data_raw = await self.fetch_webapp_query()
            except Exception as e:
                await activity(self.account_id, "AUTH", "FAILED",
                               f"Refresh gagal: {str(e)[:40]}")
                raise RuntimeError(f"Refresh initData gagal: {e}")

            # Coba login lagi
            await activity(self.account_id, "AUTH", "RUNNING",
                           "Login ulang dengan initData baru...")
            result = await self.api.post(
                "/auth/telegram",
                {"initData": self.init_data_raw},
            )

        # Cek lagi
        if result.get("success") is False or not result.get("token"):
            err = result.get("error") or "Login gagal"
            await activity(self.account_id, "AUTH", "FAILED", str(err)[:60])
            raise RuntimeError(f"Login gagal: {err}")

        self.api.set_token(result["token"])

        if result.get("state"):
            self._apply_state(result["state"])

        await activity(self.account_id, "AUTH", "SUCCESS",
                       "Token OK")

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _apply_state(self, state: dict):
        if isinstance(state, dict) and state:
            self.state = state
            self.state_read_at = now_ts()

    async def load_state(self):
        result = await self.api.get("/state")
        if result.get("state"):
            self._apply_state(result["state"])
        elif result.get("balance") is not None or result.get("mining"):
            self._apply_state(result)
        return self.state

    def user(self) -> dict:
        return self.state.get("user", {}) if isinstance(self.state, dict) else {}

    def mining(self) -> dict:
        return self.state.get("mining", {}) if isinstance(self.state, dict) else {}

    def tasks(self) -> dict:
        return self.state.get("tasks", {}) if isinstance(self.state, dict) else {}

    def friends(self) -> dict:
        return self.state.get("friends", {}) if isinstance(self.state, dict) else {}

    def withdrawals_state(self) -> dict:
        return self.state.get("withdrawals", {}) if isinstance(self.state, dict) else {}

    def get_server_now_ms(self) -> int:
        v = self.state.get("serverNow") if isinstance(self.state, dict) else None
        if isinstance(v, (int, float)) and v > 0:
            return int(v if v > 1e11 else v * 1000)
        return int(now_ts() * 1000)

    # ------------------------------------------------------------------
    # Mining
    # ------------------------------------------------------------------

    def _get_balance_str(self) -> str:
        """Ambil balance dengan format rapi."""
        try:
            bal = self.state.get("balance") or 0
            f = float(bal)
            if f >= 1000:
                return f"{f:,.2f}"
            if f >= 1:
                return f"{f:.2f}"
            return f"{f:.4f}"
        except (TypeError, ValueError):
            return str(self.state.get("balance", "?"))

    async def claim_mining(self):
        mining = self.mining()
        if not mining:
            await activity(self.account_id, "MINING", "SKIP",
                           "Tidak ada data mining")
            return 0

        next_claim_at = mining.get("nextClaimAt")
        if isinstance(next_claim_at, str):
            next_claim_at = parse_iso(next_claim_at) * 1000
        next_claim_at = int(next_claim_at or 0)

        server_now = self.get_server_now_ms()
        if next_claim_at > server_now:
            sisa = (next_claim_at - server_now) / 1000
            h, m = int(sisa // 3600), int((sisa % 3600) // 60)
            bal = self._get_balance_str()
            await activity(self.account_id, "MINING", "WAIT",
                           f"Next claim in {h:02d}:{m:02d} | Bal: {bal}")
            return next_claim_at

        pending_units = mining.get("pendingUnits") or 0
        if not pending_units or float(pending_units) <= 0:
            bal = self._get_balance_str()
            await activity(self.account_id, "MINING", "SKIP",
                           f"Nothing mined yet | Bal: {bal}")
            return next_claim_at or 0

        bal = self._get_balance_str()
        await activity(self.account_id, "MINING", "CLAIM",
                       f"Pending={mining.get('pending', '?')} DIGGO | Bal: {bal}")

        result = await self.api.post("/claims/mining")
        if result.get("success") is False:
            err = str(result.get("error") or "")[:60]
            await activity(self.account_id, "MINING", "FAILED",
                           f"{err} | Bal: {bal}")
            return next_claim_at or 0

        if result.get("state"):
            self._apply_state(result["state"])

        amount = (result.get("amount")
                  or result.get("claimedAmount")
                  or result.get("claimed")
                  or "?")
        log_info(self.account_id, f"Claim mining OK +{amount} DIGGO")

        # Balance setelah claim
        bal_after = self._get_balance_str()
        await activity(self.account_id, "MINING", "SUCCESS",
                       f"+{amount} DIGGO | Bal: {bal_after}")

        return self.mining().get("nextClaimAt") or 0

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    TASK_TITLES = {
        "checkin": "Daily Check-In",
        "play": "Reach Level",
        "telegram": "Join Community",
        "community_react": "React in Community",
        "x": "X",
        "x_follow": "Follow on X",
        "x_post": "Engage X Post",
        "invite": "Invite Friends",
        "ad": "Watch Ad",
    }

    def _task_title(self, task_id: str) -> str:
        return self.TASK_TITLES.get(task_id, task_id)

    def _is_task_open(self, record: dict) -> bool:
        if not isinstance(record, dict):
            return False
        return (
            record.get("enabled") is not False
            and not record.get("pending")
            and not record.get("claimed")
        )

    def _is_task_ready(self, task_id: str, record: dict) -> bool:
        if not isinstance(record, dict):
            return False
        if task_id == "checkin":
            return True
        progress = record.get("progress", 0)
        total = record.get("total", 0)
        try:
            return float(progress) >= float(total) and float(total) > 0
        except (TypeError, ValueError):
            return False

    def _is_telegram_url(self, url: str) -> bool:
        """Cek apakah URL adalah link Telegram (t.me / telegram.me)."""
        if not url:
            return False
        return "t.me/" in url or "telegram.me/" in url

    async def complete_tasks(self) -> int:
        tasks = self.tasks()
        if not tasks:
            await activity(self.account_id, "TASK", "SKIP",
                           "Tidak ada task")
            return 0

        # Skip task ad
        task_ids = [tid for tid in tasks.keys() if tid != "ad"]

        total_claimed = 0
        for task_id in task_ids:
            record = tasks.get(task_id)
            if not self._is_task_open(record):
                continue
            try:
                claimed = await self._complete_task(task_id, record)
                if claimed:
                    total_claimed += 1
            except Exception as e:
                log_warn(self.account_id,
                         f"Task '{self._task_title(task_id)}' error: {e}")
                await activity(self.account_id, "TASK", "FAILED",
                               f"{self._task_title(task_id)}: {str(e)[:40]}")
            await asyncio.sleep(2)

        if total_claimed:
            await activity(self.account_id, "TASK", "SUCCESS",
                           f"{total_claimed} task claimed")
        else:
            await activity(self.account_id, "TASK", "SKIP",
                           "Tidak ada yang bisa di-claim")

        next_reset = find_next_task_reset(tasks, self.get_server_now_ms())
        return next_reset

    async def _complete_task(self, task_id: str, record: dict) -> bool:
        title = self._task_title(task_id)

        # Ready → langsung claim
        if self._is_task_ready(task_id, record):
            return await self._claim_task(task_id, title)

        # Telegram → join + verify + claim
        if task_id == "telegram":
            return await self._complete_telegram_task(record, title)

        # Self-reported → start + dwell + confirm + claim
        if record.get("verification") == "self_reported":
            return await self._complete_social_task(task_id, record, title)

        # Task lain belum ada handler
        await activity(self.account_id, "TASK", "SKIP",
                       f"{title}: belum ada handler")
        return False

    async def _claim_task(self, task_id: str, title: str) -> bool:
        await activity(self.account_id, "TASK", "CLAIM", title[:40])
        result = await self.api.post("/tasks/claim", {"taskId": task_id})
        if result.get("success") is False:
            err = str(result.get("error") or "")[:60]
            log_warn(self.account_id, f"Claim '{title}' gagal: {err}")
            return False

        if result.get("state"):
            self._apply_state(result["state"])

        # Multi-field amount
        amount = (result.get("amount")
                  or result.get("claimedAmount")
                  or result.get("claimed")
                  or 0)
        if float(amount or 0) > 0:
            await activity(self.account_id, "TASK", "SUCCESS",
                           f"{title[:35]} +{amount} DIGGO")
            log_info(self.account_id, f"Claimed '{title}' +{amount} DIGGO")
            return True
        else:
            await activity(self.account_id, "TASK", "OK",
                           f"{title[:35]} sudah diklaim")
            return False

    async def _complete_telegram_task(self, record: dict, title: str) -> bool:
        url = record.get("url") or ""
        # Hanya join kalau URL Telegram
        if url and self._is_telegram_url(url):
            await activity(self.account_id, "TASK", "RUNNING",
                           f"Join {url[:40]}...")
            await self._join_telegram_link(url)
            await asyncio.sleep(JOIN_DELAY)

        await activity(self.account_id, "TASK", "RUNNING",
                       f"{title}: verify...")
        verify_result = await self.api.post("/tasks/verify",
                                              {"taskId": "telegram"})
        if verify_result.get("state"):
            self._apply_state(verify_result["state"])

        updated = self.tasks().get("telegram")
        if updated and self._is_task_open(updated) and \
           self._is_task_ready("telegram", updated):
            return await self._claim_task("telegram", title)
        return False

    async def _complete_social_task(self, task_id: str, record: dict,
                                     title: str) -> bool:
        url = record.get("url") or ""
        # Hanya join kalau URL Telegram (x.com/youtube.com di-skip)
        if url and self._is_telegram_url(url):
            await self._join_telegram_link(url)

        # Start
        start_result = await self.api.post("/tasks/social/start",
                                             {"taskId": task_id})
        if start_result.get("success") is False:
            err = str(start_result.get("error") or "")[:60]
            await activity(self.account_id, "TASK", "FAILED",
                           f"{title}: {err}")
            return False

        attempt = start_result.get("attempt") or {}
        attempt_id = attempt.get("attemptId")
        confirm_at = attempt.get("confirmAt")

        if not attempt_id:
            await activity(self.account_id, "TASK", "FAILED",
                           f"{title}: no attemptId")
            return False

        if isinstance(confirm_at, str):
            confirm_at = parse_iso(confirm_at) * 1000
        confirm_at = int(confirm_at or 0)
        server_now = self.get_server_now_ms()
        wait_ms = max(0, confirm_at - server_now)
        wait_s = wait_ms / 1000 + SOCIAL_CONFIRM_MARGIN

        # Dwell
        remaining = int(wait_s)
        while remaining > 0:
            await activity(self.account_id, "TASK", "DWELL",
                           f"{title[:30]} | wait {remaining:02d}s")
            await asyncio.sleep(min(2, remaining))
            remaining -= 2

        # Confirm
        confirm_result = await self.api.post("/tasks/social/confirm", {
            "taskId": task_id,
            "attemptId": attempt_id,
            "confirmed": True,
        })
        if confirm_result.get("state"):
            self._apply_state(confirm_result["state"])

        # Claim
        return await self._claim_task(task_id, title)

    # ------------------------------------------------------------------
    # Streak
    # ------------------------------------------------------------------

    async def claim_streak(self):
        rewards = self.state.get("dayRewards") or []
        if not isinstance(rewards, list):
            await activity(self.account_id, "STREAK", "SKIP",
                           "Tidak ada dayRewards")
            return

        target = None
        for item in rewards:
            if not isinstance(item, dict):
                continue
            if item.get("status") != "available":
                continue
            completed = item.get("completedTasks", 0)
            required = item.get("requiredTasks", 0)
            try:
                if float(completed) >= float(required):
                    target = item
                    break
            except (TypeError, ValueError):
                continue

        if not target:
            # Silent skip — tidak perlu tampil di dashboard
            return

        day = target.get("day")
        await activity(self.account_id, "TASK", "CLAIM",
                       f"Streak Day {day}")

        result = await self.api.post("/streak/claim", {"day": day})
        if result.get("success") is False:
            err = str(result.get("error") or "")[:60]
            await activity(self.account_id, "TASK", "FAILED",
                           f"Streak: {err}")
            return

        if result.get("state"):
            self._apply_state(result["state"])

        amount = (result.get("amount")
                  or result.get("claimedAmount")
                  or target.get("diggo")
                  or "?")
        await activity(self.account_id, "TASK", "SUCCESS",
                       f"Streak Day {day} +{amount} DIGGO")
        log_info(self.account_id, f"Claim streak day {day} +{amount}")

    # ------------------------------------------------------------------
    # Squad / Commission
    # ------------------------------------------------------------------

    async def claim_commission(self):
        friends = self.friends()
        commission = friends.get("commission") or {}
        pending_units = commission.get("pendingUnits") or 0

        try:
            if float(pending_units) <= 0:
                await activity(self.account_id, "SQUAD", "SKIP",
                               "Tidak ada komisi")
                return
        except (TypeError, ValueError):
            await activity(self.account_id, "SQUAD", "SKIP",
                           "Tidak ada komisi")
            return

        await activity(self.account_id, "SQUAD", "CLAIM",
                       f"Pending={commission.get('pending', '?')}")

        result = await self.api.post("/referrals/claim")
        if result.get("success") is False:
            err = str(result.get("error") or "")[:60]
            await activity(self.account_id, "SQUAD", "FAILED", err)
            return

        if result.get("state"):
            self._apply_state(result["state"])

        amount = (result.get("amount")
                  or result.get("claimedAmount")
                  or commission.get("pending")
                  or "?")
        await activity(self.account_id, "SQUAD", "SUCCESS",
                       f"+{amount} DIGGO")
        log_info(self.account_id, f"Claim commission +{amount}")

    # ------------------------------------------------------------------
    # Chests
    # ------------------------------------------------------------------

    async def open_chests(self):
        result = await self.api.get("/chests?mode=live")
        chests_data = result.get("chests") if isinstance(result, dict) else None
        if not isinstance(chests_data, dict):
            await activity(self.account_id, "CHEST", "SKIP",
                           "Response chests tidak valid")
            return

        server_now = chests_data.get("serverNow") or self.get_server_now_ms()
        chests = chests_data.get("chests") or []

        openable = []
        for chest in chests:
            if not isinstance(chest, dict):
                continue
            if not chest.get("unlocked"):
                continue
            if not chest.get("funded"):
                continue
            next_open = chest.get("nextOpenAt")
            if next_open:
                if isinstance(next_open, str):
                    next_open = parse_iso(next_open) * 1000
                try:
                    if int(next_open) > int(server_now):
                        continue
                except (TypeError, ValueError):
                    pass
            openable.append(chest)

        if not openable:
            await activity(self.account_id, "CHEST", "SKIP",
                           "Tidak ada chest")
            return

        for chest in openable:
            chest_id = chest.get("id", "?")
            await activity(self.account_id, "CHEST", "CLAIM",
                           f"Open {chest_id}")
            try:
                res = await self.api.post("/chests/open", {
                    "chestId": chest_id,
                    "mode": "live",
                })
                if res.get("success") is False:
                    err = str(res.get("error") or "")[:50]
                    await activity(self.account_id, "CHEST", "FAILED",
                                   f"{chest_id}: {err}")
                    continue

                opening = res.get("opening") or {}
                reward = opening.get("reward") or {}
                amount = reward.get("amount")
                if amount is None and reward.get("amountUnits") is not None:
                    units = float(reward["amountUnits"])
                    if reward.get("asset") == "TON":
                        amount = units / 1e9
                    else:
                        amount = units
                asset = reward.get("asset", "?")
                rarity = reward.get("rarity", "?")
                await activity(self.account_id, "CHEST", "OPENED",
                               f"{chest_id}: {amount} {asset} ({rarity})")
                log_info(self.account_id,
                         f"Opened chest {chest_id}: {amount} {asset} ({rarity})")
            except Exception as e:
                log_warn(self.account_id, f"Open chest {chest_id} gagal: {e}")
            await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Join Telegram link
    # ------------------------------------------------------------------

    async def _join_telegram_link(self, link: str) -> bool:
        if not self.tg or not link:
            return False

        username = None
        try:
            parts = link.rstrip("/").split("/")
            for part in parts:
                if part and part not in ("t.me", "telegram.me", "http:", "https:") \
                   and not part.startswith("?"):
                    username = part
                    break
        except Exception:
            return False

        if not username:
            return False

        if username in self._joined_channels:
            return True

        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            entity = await self.tg.get_entity(username)
            await self.tg(JoinChannelRequest(entity))
            self._joined_channels.add(username)
            log_info(self.account_id, f"Joined @{username}")
            return True
        except Exception as e:
            err = str(e).lower()
            if "already" in err or "participant" in err:
                self._joined_channels.add(username)
                return True
            log_warn(self.account_id, f"Gagal join {username}: {e}")
            return False

    # ------------------------------------------------------------------
    # Update ACCOUNT row
    # ------------------------------------------------------------------

    async def update_account_row(self, status: str = "READY"):
        mining = self.mining()
        friends = self.friends()
        level = self.state.get("currentLevel", 0)
        balance = self.state.get("balance", 0)
        ths = mining.get("ths", "?")
        daily = mining.get("daily", "?")
        pending = mining.get("pending", "?")
        referrals = friends.get("registeredCount", 0)

        detail = (
            f"Lv={level} | Speed={ths} TH/s | Daily={daily} | "
            f"Bal={balance} | Pending={pending} | Ref={referrals}"
        )
        await activity(self.account_id, "ACCOUNT", status, detail)

    # ------------------------------------------------------------------
    # Process (satu cycle)
    # ------------------------------------------------------------------

    async def process(self, state: AccountState) -> int:
        # 1. Ensure Telegram connection
        if not self.tg:
            await self.connect(require_login=True)

        # 2. Login ke API
        await self.login()

        # 3. Load state
        await self.load_state()

        balance_before = self.state.get("balance")
        await self.update_account_row("READY")

        # 4. Mining
        await self.claim_mining()

        # 5. Tasks
        next_task_reset = await self.complete_tasks()

        # 6. Streak
        await self.claim_streak()

        # 7. Squad
        await self.claim_commission()

        # 8. Chests
        await self.open_chests()

        # 9. Update state
        await self.load_state()
        balance_after = self.state.get("balance")
        level_after = self.state.get("currentLevel", 0)

        state.last_balance = float(balance_after or 0)
        state.last_level = int(level_after or 0)
        state.cycles_run += 1
        state.last_run_ts = int(now_ts())

        await self.update_account_row("READY")
        await activity(self.account_id, "ACCOUNT", "SUCCESS",
                       f"Cycle done | {balance_before} → {balance_after} DIGGO")

        # Hitung wait
        next_claim_at = self.mining().get("nextClaimAt") or 0
        if isinstance(next_claim_at, str):
            next_claim_at = parse_iso(next_claim_at) * 1000
        next_claim_at = int(next_claim_at or 0) / 1000
        server_now = self.get_server_now_ms() / 1000

        candidates = []
        if next_claim_at > server_now:
            candidates.append(next_claim_at - server_now)
        if next_task_reset and next_task_reset > server_now:
            candidates.append(next_task_reset - server_now)

        if candidates:
            wait = min(candidates)
        else:
            wait = 3600

        wait = max(MIN_WAIT, min(wait, MAX_WAIT))
        wait += random.randint(15, 45)
        return int(wait)


# =====================================================================
# WORKER
# =====================================================================

async def run_account_cycle(account_id: str, state_mgr: StateManager) -> int:
    state = state_mgr.load(account_id)
    client = DiggoClient(account_id)
    log_info(account_id, "Cycle dimulai")
    try:
        wait = await client.process(state)
        return wait
    except Exception as e:
        log_error(account_id, "Cycle error", e)
        msg = str(e).strip() or type(e).__name__
        await activity(account_id, "ACCOUNT", "ERROR", msg[:70])
        return 600
    finally:
        state_mgr.save(state)
        await client.close()


async def run_account_worker(account_id: str, state_mgr: StateManager):
    while True:
        wait = await run_account_cycle(account_id, state_mgr)

        remaining = wait
        while remaining > 0:
            h = remaining // 3600
            m = (remaining % 3600) // 60
            s = remaining % 60
            await activity(account_id, "ACCOUNT", "WAIT",
                           f"Next cycle in {h:02d}:{m:02d}:{s:02d}")
            await asyncio.sleep(min(60, remaining))
            remaining -= 60


async def _staggered_worker(account_id: str, state_mgr: StateManager,
                             delay: int):
    if delay > 0:
        await asyncio.sleep(delay)
    await run_account_worker(account_id, state_mgr)


# =====================================================================
# GET INITDATA MODE (manual)
# =====================================================================

async def get_pass_mode(account_id: str):
    print(f"\n🔑 Fetch initData — {account_id}\n")
    client = DiggoClient(account_id)
    try:
        await client.connect(require_login=True)
        init_data = await client.fetch_webapp_query()
        print(f"✅ initData OK ({len(init_data)} chars)")
    finally:
        await client.close()


async def get_pass_all_mode():
    accounts = sorted(p.stem for p in SESSIONS_DIR.glob("acc_*.session"))
    if not accounts:
        print("❌ Tidak ada akun")
        sys.exit(1)
    for idx, acc in enumerate(accounts, 1):
        print(f"\n[{idx}/{len(accounts)}] {acc}")
        try:
            await get_pass_mode(acc)
        except Exception as e:
            print(f"❌ {acc}: {e}")


# =====================================================================
# ADD ACCOUNT MODE
# =====================================================================

async def add_account_mode():
    print()
    print("=" * 70)
    print("  ➕ TAMBAH AKUN BARU (Diggo)")
    print("=" * 70)
    print()

    existing = sorted(p.stem for p in SESSIONS_DIR.glob("acc_*.session"))
    next_num = 1
    while f"acc_{next_num:03d}" in existing:
        next_num += 1
    account_id = f"acc_{next_num:03d}"

    print(f"Akun berikutnya: {account_id}")
    print()
    confirm = input("Lanjut? (y/n): ").strip().lower()
    if confirm != "y":
        print("Dibatalkan.")
        return

    client = DiggoClient(account_id)
    try:
        await client.connect(require_login=True)
        print()
        print("📥 Fetch initData...")
        try:
            await client.fetch_webapp_query()
            print("✅ initData disimpan")
        except Exception as e:
            print(f"⚠️  Gagal fetch initData: {e}")
    finally:
        await client.close()

    print()
    print("=" * 70)
    print(f"  ✅ {account_id} siap")
    print("=" * 70)


# =====================================================================
# MAIN
# =====================================================================

def get_existing_accounts() -> list[str]:
    return sorted(p.stem for p in SESSIONS_DIR.glob("acc_*.session"))


async def run_farmer():
    log_info("main", "Main loop dimulai")
    print()
    print("=" * 70)
    print("  ⛏️  DIGGO FARMER — AUTO MODE")
    print("=" * 70)
    print()

    accounts = get_existing_accounts()
    if not accounts:
        print("Belum ada akun. Tambah dulu:")
        print("  python diggo.py --add")
        sys.exit(0)

    DASHBOARD.accounts = accounts
    for account in accounts:
        DASHBOARD.register(account)

    DASHBOARD.start()
    DASHBOARD.render()

    try:
        state_mgr = StateManager(DATA_DIR)
        tasks = []
        for idx, acc in enumerate(accounts):
            delay = idx * STAGGER_SECONDS
            tasks.append(_staggered_worker(acc, state_mgr, delay))
        await asyncio.gather(*tasks)
    except SystemExit:
        log_warn("main", "Worker exit")
    except Exception as e:
        log_error("main", "run_farmer exception", e)
    finally:
        DASHBOARD.stop()
        log_info("main", "Main loop selesai")


def print_help():
    print(__doc__)
    print()
    print("Contoh:")
    print("  python diggo.py --add          → tambah akun baru")
    print("  python diggo.py                → start farmer")
    print("  python diggo.py pass acc_001   → fetch initData 1 akun")
    print("  python diggo.py pass-all       → fetch initData semua akun")


if __name__ == "__main__":
    try:
        args = sys.argv[1:]

        if not args:
            asyncio.run(run_farmer())
        elif args[0] in ("--add", "add"):
            asyncio.run(add_account_mode())
        elif args[0] == "pass":
            if len(args) < 2:
                print("Usage: python diggo.py pass <account_id>")
                sys.exit(1)
            asyncio.run(get_pass_mode(args[1]))
        elif args[0] == "pass-all":
            asyncio.run(get_pass_all_mode())
        elif args[0] in ("-h", "--help", "help"):
            print_help()
        else:
            print(f"❌ Argumen tidak dikenal: {args[0]}")
            print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        LOGGER.info("Bot dihentikan oleh user")
        print()
        print("Bot dihentikan.")
    except Exception as e:
        LOGGER.critical(f"FATAL: {type(e).__name__}: {e}")
        LOGGER.critical(traceback.format_exc())
        print(f"\n❌ Bot crash: {e}")
        print(f"Cek detail di: {LOG_PATH}")
        raise
