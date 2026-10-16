# ⛏️ Diggo Farmer

Bot auto-farmer untuk **Diggo Miner** (Telegram WebApp) — single file Python, multi-akun, dengan dashboard real-time.

---

## ✨ Fitur

- 🔁 **Auto loop dinamis** — interval adaptif berdasarkan `nextClaimAt` mining & task reset
- 👥 **Multi-akun** — jalankan banyak akun sekaligus dalam satu proses
- 📊 **Dashboard real-time** — tampilan vertikal per akun (Rich Live)
- 🔐 **Auto-fetch initData** — via Telegram WebView (RequestAppWebView)
- 💾 **Cache initData** — dengan TTL, auto-refresh saat expired
- ⛏️ **Auto claim mining** — sesuai jadwal `nextClaimAt`
- 🎯 **Auto tasks** — check-in, join community, social tasks, streak, verify
- 🎁 **Auto open chests** — dengan mode live
- 💰 **Auto claim commission** — dari referral/squad
- 🆔 **Idempotency-Key** otomatis untuk endpoint write
- 🔄 **Retry otomatis** + rotasi log + error handling per akun

---

## 📦 Persyaratan

- **Python 3.10+**
- **Telegram API ID & API Hash** (dari [my.telegram.org](https://my.telegram.org))
- Koneksi internet stabil
- Akun Telegram (bisa lebih dari satu)

---

## 🚀 Instalasi

### 1. Clone repository

```bash
git clone https://github.com/erwindobp98/diggo.git
cd diggo
```

### 2. Install dependencies

```bash
pip install httpx rich telethon
```

Atau jika ada `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Jalankan pertama kali (auto-generate config)

```bash
python diggo.py
```

Saat pertama kali dijalankan, bot akan membuat `config.json` otomatis lalu exit. Edit file tersebut (lihat bagian [Konfigurasi](#-konfigurasi)).

---

## ⚙️ Konfigurasi

File `config.json` akan dibuat otomatis di root folder:

```json
{
  "telegram": {
    "api_id": 224069,
    "api_hash": "f2ddfd53867f28a3b6b98e80fa010e9d"
  },
  "bot": {
    "username": "Diggominer_bot",
    "short_name": "app",
    "app_url": "https://diggo.linkpc.net/",
    "api_url": "https://diggo.linkpc.net/api",
    "referral": "ref_b96048f836ebd23b1ea33651"
  },
  "mining": {
    "claim_interval_hours": 8
  },
  "tasks": {
    "social_confirm_margin_seconds": 3,
    "dwell_seconds_min": 10,
    "dwell_seconds_max": 14,
    "join_delay_seconds": 3
  },
  "cycle": {
    "min_wait_seconds": 300,
    "max_wait_seconds": 21600,
    "request_timeout": 30,
    "retry_count": 3,
    "stagger_seconds": 3
  },
  "initdata": {
    "ttl_minutes": 25
  },
  "logging": {
    "level": "INFO"
  }
}
```

### Penjelasan field penting

| Field | Deskripsi |
|-------|-----------|
| `telegram.api_id` / `api_hash` | Kredensial API Telegram Anda. **Ganti dengan milik sendiri.** |
| `bot.username` | Username bot Diggo (tanpa `@`) |
| `bot.short_name` | Short name WebApp bot |
| `bot.app_url` | URL WebApp Diggo |
| `bot.api_url` | Base URL API Diggo |
| `bot.referral` | Kode referral (opsional, isi jika ingin referral) |
| `mining.claim_interval_hours` | Fallback interval claim mining |
| `tasks.dwell_seconds_min/max` | Durasi dwell untuk social task |
| `cycle.min_wait_seconds` | Minimal jeda antar cycle |
| `cycle.max_wait_seconds` | Maksimal jeda antar cycle |
| `cycle.stagger_seconds` | Delay antar akun saat start (hindari rate limit) |
| `initdata.ttl_minutes` | Umur cache initData sebelum refresh |

> ⚠️ **Penting:** Ganti `api_id` dan `api_hash` dengan milik Anda dari [my.telegram.org](https://my.telegram.org). Jangan pakai milik orang lain.

---

## 🎮 Cara Pakai

### Tambah akun baru

```bash
python diggo.py --add
```

Anda akan diminta:
1. Nomor Telegram (format internasional, contoh: `+6281234567890`)
2. Kode OTP dari aplikasi Telegram
3. Password 2FA (jika aktif)

Session akan disimpan di `sessions/acc_001.session`, dst.

### Fetch initData manual (1 akun)

```bash
python diggo.py pass acc_001
```

### Fetch initData manual (semua akun)

```bash
python diggo.py pass-all
```

### Jalankan farmer (auto mode)

```bash
python diggo.py
```

Bot akan:
1. Load semua akun dari folder `sessions/`
2. Menampilkan dashboard real-time
3. Loop otomatis per akun (claim mining, tasks, chests, dll)

Hentikan dengan `Ctrl+C`.

### Bantuan

```bash
python diggo.py help
```

---

## 📁 Struktur Folder

```
diggo/
├── diggo.py                 # Script utama
├── config.json              # Konfigurasi (auto-generate)
├── error.log                # Log error (rotating)
├── sessions/                # Session Telegram + cache initData
│   ├── acc_001.session
│   ├── acc_001.session-journal
│   ├── acc_001.initdata
│   └── ...
└── data/                    # State per akun
    ├── acc_001.json
    └── ...
```

| Folder/File | Isi |
|-------------|-----|
| `sessions/` | Session Telegram & cache initData (JANGAN di-share!) |
| `data/` | State runtime (balance, level, cycles) |
| `error.log` | Log error & warning (maks 2MB × 3 backup) |
| `config.json` | Konfigurasi bot |

---

## 🔧 Cara Kerja

### Alur satu cycle per akun

```
1. Connect Telegram (session atau login baru)
2. Fetch / cache initData
3. Login ke API Diggo (/auth/telegram)
4. Load state (/state)
5. Claim mining (jika waktunya)
6. Complete tasks (checkin, telegram, social, streak)
7. Claim commission (referral)
8. Open chests
9. Reload state & update dashboard
10. Hitung wait time → sleep → ulangi
```

### Perhitungan wait time

Bot memilih waktu tunggu terdekat dari:
- `mining.nextClaimAt` — waktu claim mining berikutnya
- `tasks` reset terdekat

Lalu di-clamp antara `MIN_WAIT` dan `MAX_WAIT`, ditambah random `15–45` detik.

### Auto-refresh initData

Jika login gagal dengan `expired_init_data`:
1. Cache lama dihapus
2. Fetch initData baru dari Telegram WebView
3. Login ulang otomatis

---

## 🐛 Troubleshooting

### `Folder sessions/ tidak writable`

Pastikan folder `sessions/` ada dan bisa ditulis:
```bash
mkdir -p sessions data
chmod 755 sessions data
```

### `SessionPasswordNeededError`

Akun Anda mengaktifkan 2FA. Saat `--add`, masukkan password 2FA dengan benar.

### `initData expired` berulang

- Pastikan `bot.short_name` di config sesuai dengan bot Diggo
- Coba `python diggo.py pass acc_001` untuk fetch manual
- Hapus `sessions/acc_001.initdata` lalu jalankan ulang

### `Telegram connect failed`

- Cek koneksi internet
- Cek `api_id` dan `api_hash` di `config.json`
- Coba hapus `.session-journal` yang korup

### Dashboard tampil kacau

Gunakan terminal dengan dukungan ANSI (bukan CMD lama). Termux, Windows Terminal, iTerm2, GNOME Terminal semuanya OK.

### Bot crash

Cek `error.log` untuk detail traceback:
```bash
tail -n 100 error.log
```

---

## 🛡️ Keamanan

- **JANGAN** commit folder `sessions/`, `data/`, atau `config.json` ke GitHub.
- Tambahkan `.gitignore`:

```gitignore
sessions/
data/
config.json
error.log
*.session
*.session-journal
__pycache__/
venv/
.venv/
```

- Session Telegram = akses penuh ke akun Anda. Simpan di tempat aman.

---

## ⚠️ Disclaimer

> **Gunakan dengan risiko sendiri.**
>
> - Bot ini dibuat untuk tujuan **edukasi** dan **otomasi pribadi**.
> - Penyalahgunaan (spam, multi-akun masif, eksploitasi bug) dapat menyebabkan **akun Telegram Anda dibanned**.
> - Developer **tidak bertanggung jawab** atas kerugian, banned akun, atau konsekuensi lain.
> - Pastikan Anda mematuhi **Terms of Service** Telegram dan platform terkait.

---
## Made with ❤️ for the Diggo community ##
