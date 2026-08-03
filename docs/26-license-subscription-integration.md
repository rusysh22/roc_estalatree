# 26 — Integrasi License ↔ Berlangganan (Subscription)

> Dokumen ini menjelaskan secara spesifik bagaimana **License** (kunci aktivasi produk OSS, `apps/licensing`) terhubung dengan **Subscription** (hak akses berulang/recurring, `apps/billing`) di platform Berlanggan. Dokumen ini melengkapi, bukan menggantikan: [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) (model Grant/Provisioner umum), [14-state-machines.md](14-state-machines.md) (aturan transisi status), dan [25-license-webhook-api-flow.md](25-license-webhook-api-flow.md) (alur webhook + Activation API `/activate` `/validate` `/deactivate`). Bagian B6 di bawah mendokumentasikan endpoint `/v1/operation-authorize` dan model `OperationPolicy` yang **belum** dibahas di dokumen manapun sebelumnya.

---

## Bagian A — Dokumentasi Fungsional

### A1. Konsep dasar

| Istilah | Arti |
|---|---|
| **License** | Kunci aktivasi (`XXXX-XXXX-XXXX`) yang ditempel pelanggan ke produk OSS mereka (mis. RoC Support Desk) agar produk itu menyala. |
| **Subscription** ("Berlangganan") | Hak akses **berulang** (bulanan/tahunan) terhadap sebuah Plan. Diperpanjang otomatis dengan memotong saldo wallet pelanggan (bukan kartu kredit — lihat [01-overview.md](01-overview.md) soal kenapa model prabayar dipakai). |
| **Grant** | Lapisan generik di baliknya (lihat [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md)). License adalah **spesialisasi** dari Grant bertipe `license_key`. |

**Relasi kardinalitas:**
- 1 Subscription → bisa punya banyak License (jarang; umumnya 1) — via `License.subscription` (FK, nullable).
- 1 License → paling banyak 1 Subscription. **Nullable** karena tidak semua License berasal dari plan recurring:
  - Plan **one-time** (`Plan.interval = none`) → License dibuat tanpa Subscription (`subscription=None`) → license berlaku selamanya (perpetual), tidak pernah `expired`, hanya bisa `revoked` manual.
  - Plan **monthly/yearly** → License dibuat **dengan** Subscription → siklus hidup License mengikuti siklus hidup Subscription.

Singkatnya: **Subscription adalah "mesin penagihan berulang"; License adalah "kunci" yang menyala/mati mengikuti mesin itu.**

### A2. Alur bisnis end-to-end

```
1. Pelanggan checkout Plan recurring (bulanan/tahunan)
        │
2. Order dibuat & dibayar (saldo wallet atau top-up Duitku dulu)
        │
3. Order paid → sistem membuat SATU PAKET sekaligus:
        • Subscription  (status=active, current_period_end = +1 bulan/tahun)
        • Grant         (status=active, terhubung ke Subscription)
        • License       (status=active, terhubung ke Grant & Subscription)
        │
4. Pelanggan menerima kunci license via WhatsApp + Email + Dashboard
        │
5. Pelanggan aktivasi kunci di produk OSS-nya → 1 seat terpakai (Installation)
        │
6. Produk melakukan heartbeat berkala (/validate) selama subscription aktif
        │
   ── Setiap periode (bulanan/tahunan), sistem mencoba PERPANJANG OTOMATIS ──
        │
7a. Saldo cukup → Subscription diperpanjang (current_period_end maju 1 periode),
    License tetap aktif, tidak ada gangguan ke pelanggan.
        │
7b. Saldo TIDAK cukup → Subscription masuk masa GRACE (default 3 hari).
    License TETAP dianggap aktif selama masa grace (tidak ada perubahan status
    tersimpan di database — dicek real-time, lihat B3). Pelanggan dapat
    reminder WA/Email untuk top up.
        │
8a. Pelanggan top up dalam masa grace → Subscription otomatis pulih ke active
    pada validasi/perpanjangan berikutnya. Tidak perlu aksi manual ops.
        │
8b. Masa grace habis tanpa top up → Subscription → SUSPENDED, dan ini
    DI-CASCADE (ditulis ke database) ke Grant dan License → keduanya jadi
    SUSPENDED. Produk OSS akan mulai menolak akses pada heartbeat berikutnya.
        │
9. Jika auto_renew dimatikan pelanggan dan periode berakhir tanpa perpanjangan
   → Subscription → CANCELLED (final), License ikut disuspend (bukan revoke —
   data license tetap ada untuk audit/riwayat, hanya aksesnya dimatikan).
```

**Yang membedakan alur ini dari Plan one-time:** pada plan one-time, tidak ada langkah 6–9 — License langsung aktif selamanya begitu Order dibayar, tidak ada job perpanjangan yang berjalan.

### A3. Tabel dampak status Subscription → License

| Status Subscription | Status Grant & License (tersimpan) | Dampak ke Activation API | Aksi ops yang dibutuhkan |
|---|---|---|---|
| `active` | `active` | Semua endpoint (`activate`/`validate`/`operation-authorize`) mengizinkan akses. | Tidak ada. |
| `grace` | **Tidak berubah** (tetap `active` di DB) | `validate`/`activate` tetap mengembalikan status `grace` (dianggap aktif oleh produk), dicek real-time — lihat B3. | Tidak ada; sistem mengirim reminder otomatis. |
| `suspended` | Di-cascade → `suspended` | Semua endpoint menolak dengan `status: "suspended"`. Produk OSS terkunci. | Tunggu pelanggan top up (self-heal) atau reaktivasi manual dari Console bila ada kasus khusus (mis. refund manual sudah selesai). |
| `cancelled` | Di-cascade → `suspended` (bukan `revoked`) | Sama seperti suspended — akses ditolak. | Data & riwayat license tetap tersimpan; kalau pelanggan beli ulang, dibuatkan Subscription+License baru. |

Catatan penting: **suspend ≠ revoke**. Revoke pada License hanya terjadi karena tindakan manual (penyalahgunaan, chargeback) — lihat `apps/licensing/services.py` dan [14-state-machines.md](14-state-machines.md). Siklus penagihan (grace/suspend/cancel) tidak pernah otomatis me-revoke License; ia hanya suspend, sehingga selalu bisa dipulihkan.

### A4. Skenario dukungan pelanggan (khusus terkait Subscription)

| Pelanggan bilang... | Yang sebenarnya terjadi | Yang perlu dicek/dilakukan |
|---|---|---|
| "Saya masih bisa pakai walau belum bayar bulan ini" | Wajar — masih dalam **masa grace** (`ACTIVATION_GRACE_DAYS`, default 3 hari). Ini fitur, bukan bug — mencegah pelanggan kena kunci dadakan. | Cek status Subscription di Console. Jika `grace`, informasikan tenggat waktu top up. |
| "License saya tiba-tiba suspended padahal saya masih pakai" | Grace period sudah habis dan saldo masih kurang saat job perpanjangan berjalan (`renew_subscriptions`, tiap jam). | Minta pelanggan top up saldo — sistem otomatis reaktivasi (`renew()` di-cascade) pada perpanjangan berikutnya, tidak perlu klik apa pun di Console. |
| "Saya sudah top up tapi license belum nyala lagi" | Perpanjangan otomatis berjalan by job terjadwal (bukan instan saat top up), atau `try_renew_grace_subscriptions` belum sempat jalan. | Cek `Setting → RENEWAL_ADVANCE_HOURS` dan log job Celery. Biasanya pulih dalam beberapa menit; jika >15 menit eskalasi ke dev. |
| "Saya mau berhenti berlangganan" | Set `auto_renew=False` pada Subscription (via Console/Dashboard). Akses tetap jalan sampai `current_period_end`, baru setelah itu di-cancel otomatis oleh job `cancel_expired_subscriptions`. | Jangan revoke manual — biarkan job yang menangani supaya konsisten dengan kebijakan "bayar penuh sampai periode habis". |
| "Saya upgrade/downgrade plan, license saya kok tidak berubah seat limit-nya" | Perubahan plan pada Subscription aktif adalah alur terpisah (lihat catatan di B2) — pastikan `License.seat_limit` disinkronkan sesuai kebijakan produk saat ini (cek dengan tim dev bila fitur ganti-plan sudah tersedia). | Verifikasi plan Order/Subscription terbaru vs `seat_limit` License di Console. |

### A5. Siapa melakukan apa

- **Pelanggan (Dashboard):** lihat kunci license, status Subscription & tanggal perpanjangan berikutnya, kelola seat/device sendiri (deactivate device lama).
- **Ops (Console / Customer 360):** lihat gabungan Order + Subscription + License satu pelanggan, bisa suspend/resume/revoke License manual untuk kasus luar kebijakan otomatis (chargeback, penyalahgunaan).
- **Superadmin (Admin → Settings):** atur `ACTIVATION_GRACE_DAYS`, `SUBSCRIPTION_GRACE_DAYS`, `GLOBAL_GRACE_EXTENSION_DAYS` (perpanjang grace semua orang saat insiden), `MAINTENANCE_MODE` (jangan pernah kunci produk pelanggan saat sistem kita down).

---

## Bagian B — Dokumentasi Teknis

### B1. Model data & relasi

```
catalog.Plan (interval: none|monthly|yearly, seat_limit, entitlements M2M)
     │
     │ dibeli via
     ▼
billing.Order (status: pending|paid|failed|refunded)
     │ saat paid →
     ▼
billing.Subscription  (hanya dibuat jika plan.interval != none)
  - status: active | grace | suspended | cancelled
  - current_period_end
  - auto_renew
     │ OneToMany
     ▼
provisioning.Grant  (subscription FK, nullable)
  - status: active | suspended | revoked | expired
  - type = "license_key"
     │ OneToOne
     ▼
licensing.License  (subscription FK + grant FK — DUA jalur ke Subscription)
  - key (XXXX-XXXX-XXXX)
  - status: active | suspended | revoked | expired
  - seat_limit
     │ OneToMany
     ▼
licensing.Installation  (per-device seat)
  - fingerprint, status: active | deactivated
```

File model terkait:
- [`apps/billing/models.py`](../apps/billing/models.py) — `Subscription`
- [`apps/provisioning/models.py`](../apps/provisioning/models.py) — `Grant`
- [`apps/licensing/models.py`](../apps/licensing/models.py) — `License`, `Installation`, `OperationPolicy`

Catatan desain: `License` menyimpan **dua** foreign key yang mengarah ke area Subscription — `subscription` (langsung) dan `grant` (yang juga punya `subscription`). Ini bukan duplikasi tak berguna: `subscription` dipakai untuk kalkulasi cepat (mis. `_license_expires_at`), sedangkan `grant` adalah jalur resmi untuk kaskade lifecycle generik (renew/suspend/resume/revoke) yang berlaku untuk semua tipe Deliverable, tidak hanya license key.

### B2. Provisioning — pembuatan License dari Order

`apps/licensing/provisioner.py` → `LicenseKeyProvisioner.provision(order, deliverable, *, subscription=None)`:

1. Membuat `License` (key otomatis via `assign_unique_license_key`), `subscription=subscription` (bisa `None` untuk one-time).
2. Membuat `Grant` bertipe `license_key`, `subscription=subscription`, `payload={"license_key": ..., "license_id": ...}`.
3. Menghubungkan balik `License.grant = grant`.

`subscription` di sini berasal dari pemanggil (billing checkout flow) — dibuat **sebelum** provisioning dipanggil, hanya untuk plan recurring. Ini yang menjelaskan kenapa `License.subscription` dan `Grant.subscription` bisa `null`.

Ganti-plan (upgrade/downgrade) pada Subscription yang sudah berjalan **belum** punya alur khusus di layer provisioner ini per kode saat ini — perubahan plan efektif berarti Subscription/Order baru mengikuti alur checkout standar. Jika kebutuhan ini muncul, ini area yang perlu diperluas (lihat [19-extensibility.md](19-extensibility.md) untuk pola penambahan Provisioner/alur baru).

### B3. Kaskade siklus hidup (Subscription → Grant → License)

Semua ada di [`apps/billing/subscription_service.py`](../apps/billing/subscription_service.py):

| Fungsi | Trigger | Efek pada Subscription | Efek yang di-cascade ke Grant/License |
|---|---|---|---|
| `renew_subscription(sub)` | Job `renew_subscriptions` (tiap jam, `RENEWAL_ADVANCE_HOURS` sebelum jatuh tempo) atau `try_renew_grace_subscriptions` saat pelanggan top up | `current_period_end` maju 1 periode, `status → ACTIVE` | Untuk **semua** Grant non-REVOKED milik sub ini: `provisioner.renew(grant)` → `LicenseKeyProvisioner.renew()` set `Grant.status=ACTIVE` **dan** `License.status=ACTIVE`. Ini juga yang mem-pulihkan Grant yang sempat SUSPENDED (jalur grace→renew). |
| `suspend_subscription(sub)` | Dipanggil oleh `process_grace_expirations` saat masa grace habis | `status → SUSPENDED` | `provisioner.suspend(grant)` → set `Grant.status=SUSPENDED` **dan** `License.status=SUSPENDED`. Ditulis `AuditLog` (`license.suspended`). |
| `cancel_subscription(sub)` | Job `cancel_expired_subscriptions`, hanya untuk `auto_renew=False` yang periodenya sudah lewat | `status → CANCELLED` (final) | **Sama seperti suspend** — `provisioner.suspend(grant)` dipanggil (bukan revoke), karena cancel bukan pelanggaran, hanya akhir masa berlaku. |

Semua tiga fungsi memakai `select_for_update()` pada baris `Subscription` di dalam `transaction.atomic()` dan idempotent (aman dipanggil job berulang).

**Kasus khusus `grace` — TIDAK ada kaskade tertulis.** Saat Subscription masuk `GRACE`, tidak ada pemanggilan `provisioner.suspend/resume` — `Grant`/`License` di database **tetap berstatus `active`**. Alasannya: akses selama grace tetap harus jalan, dan status "grace" dihitung **secara real-time** saat Activation API dipanggil, bukan ditulis permanen ke License. Ini didefinisikan di `apps/licensing/services.py` fungsi `_effective_access_status(license)`:

```python
def _effective_access_status(license) -> str:
    # urutan prioritas — yang paling ketat menang duluan
    if license.status == REVOKED:            return "revoked"
    if license.status == EXPIRED:             return "expired"
    if license.status == SUSPENDED:           return "suspended"
    if license.grant.status == REVOKED:       return "revoked"
    if license.grant.status == EXPIRED:       return "expired"
    if license.grant.status == SUSPENDED:     return "suspended"
    if license.subscription.status == GRACE:      return "grace"
    if license.subscription.status in (SUSPENDED, CANCELLED): return "suspended"
    return "active"
```

Jadi ada **dua lapis** penegakan status:
1. **Lapis tertulis (persisted):** kaskade `renew/suspend` dari B2 menulis `License.status`/`Grant.status` — ini yang jadi sumber kebenaran jangka panjang dan yang dilihat di Admin/Console.
2. **Lapis real-time (computed):** `_effective_access_status()` dipanggil di setiap `activate`, `validate`, dan `authorize_operation` untuk menangkap kondisi `grace` (yang sengaja tidak ditulis ke `License.status`) dan sebagai pertahanan berlapis kalau kaskade belum sempat jalan.

### B4. Tanggal kedaluwarsa: komersial vs token

Dua hal yang **jangan tertukar** — ada di `apps/licensing/services.py`:

- **`license_expires_at`** (`_license_expires_at`) = tanggal akses komersial berakhir:
  - Jika `License.subscription` terisi → `subscription.current_period_end` (maju otomatis tiap renewal).
  - Jika `License.grant.valid_until` terisi (Grant one-time dengan masa berlaku) → itu.
  - Jika tidak ada keduanya → `None` (license perpetual/one-time tanpa batas).
- **`token_expires_at`** = masa berlaku token heartbeat pendek (default 1 hari, `ACTIVATION_TOKEN_TTL_DAYS`), **tidak ada hubungannya** dengan tanggal komersial — hanya memaksa produk melakukan `/validate` secara berkala.

Field `expires_at` di response API dipertahankan untuk kompatibilitas mundur dan **selalu berarti `token_expires_at`**, bukan tanggal Subscription — konsumen API baru harus pakai `license_expires_at` untuk keperluan UI/gating.

### B5. Endpoint Activation API terkait Subscription

Ringkasan (detail lengkap request/response ada di [25-license-webhook-api-flow.md](25-license-webhook-api-flow.md) §B2 — tidak diulang di sini):

- `POST /v1/activate` — daftar device baru, mengecek `_effective_access_status` (termasuk status Subscription) sebelum mengeluarkan token.
- `POST /v1/validate` — heartbeat berkala; ini titik di mana perubahan status Subscription (mis. baru saja `suspended`) benar-benar dirasakan produk OSS pelanggan.
- `POST /v1/deactivate` — melepas seat, tidak terpengaruh status Subscription.

### B6. `OperationPolicy` & `POST /v1/operation-authorize` (baru — belum ada di dokumen lain)

Selain akses "boleh jalan / tidak" yang biner (`active`/`suspended`/dst di atas), produk kadang butuh otorisasi **granular per-fitur premium** — mis. tombol "Export ke PDF" hanya untuk plan tertentu. Ini yang dilayani `OperationPolicy` + endpoint `/v1/operation-authorize`, **terpisah** dari mekanisme `entitlements` biasa (yang hanya informatif, dicek sendiri oleh produk secara lokal) — di sini server yang **mengeluarkan izin bertanda-tangan** yang bisa diverifikasi produk.

**Model `OperationPolicy`** (`apps/licensing/models.py`, migrasi baru `0002_operationpolicy.py`):

| Field | Arti |
|---|---|
| `product` (FK ke `catalog.Product`) | Policy melekat ke produk katalog, **bukan** hard-code nama aplikasi — satu produk bisa punya banyak operation policy. |
| `operation` (slug) | Nama operasi, bebas didefinisikan operator, mis. `api_access`, `export_pdf`. |
| `entitlement_key` | Key entitlement pada Plan yang harus dicek, mis. `API_ACCESS`. |
| `required_value` (default `"true"`) | Nilai entitlement yang wajib cocok (string, case-insensitive) agar operasi diizinkan. |
| `token_ttl_seconds` (default 300) | Berapa lama otorisasi yang diterbitkan berlaku. |
| `is_active` | Matikan policy tanpa menghapusnya. |

Contoh konkret: plan "Professional" punya entitlement `API_ACCESS=true`; ops membuat `OperationPolicy(product=roc-support-desk, operation="api_access", entitlement_key="API_ACCESS", required_value="true", token_ttl_seconds=300)`. Produk yang mau memakai fitur API access memanggil `/v1/operation-authorize` dengan `operation="api_access"` — server mengecek entitlement plan pelanggan saat itu juga dan hanya mengeluarkan otorisasi jika cocok.

**Alur `authorize_operation()`** (`apps/licensing/services.py`):

1. Rate limit: 30 request/60 dtk per license key (`_RATE_LIMIT_OPERATION`), 120/60 dtk per IP.
2. **`MAINTENANCE_MODE` TIDAK berlaku di sini** — beda dengan `/validate`. Saat maintenance, endpoint ini justru **menolak** (`service_unavailable`), fail-closed. Alasan: entitlement/otorisasi premium tidak boleh "sok aktif" saat sistem sedang tidak bisa memverifikasi entitlement dengan benar; hanya heartbeat biasa yang boleh fail-open.
3. Verifikasi `token` (token aktivasi yang sama dari `/activate` — bukan token baru).
4. Hitung `_effective_access_status(license)` — harus `active`/`grace` (sama seperti endpoint lain, jadi status Subscription tetap relevan di sini).
5. Pastikan `fingerprint` punya `Installation` aktif (device terdaftar).
6. Cari `OperationPolicy` yang cocok `product` + `operation` + `is_active=True`. Tidak ketemu → `operation_unavailable`.
7. Bandingkan `entitlements[policy.entitlement_key]` (dari `Grant.get_entitlements()`, bersumber dari `Plan.entitlements` M2M) dengan `policy.required_value`. Tidak cocok → `not_entitled`.
8. Terbitkan `authorization` (bukan token biasa — payload berisi `license_id`, `product_id`, `fingerprint`, `operation`, `request_hash`, `issued_at`, `expires_at`) dan **tanda tangani Ed25519** via `entitlement_signing.sign_entitlement()` — sama seperti amplop entitlement di `/activate`/`/validate`. Kegagalan signing → `service_unavailable` (fail-closed, tidak pernah keluarkan otorisasi tak bertanda tangan untuk operasi premium — beda dari envelope biasa yang di dev boleh unsigned).
9. Update `last_seen` Installation + tulis `AuditLog` (`license.operation_authorized`).

**Contoh request:**
```bash
curl -X POST https://<domain>/v1/operation-authorize \
  -H "Content-Type: application/json" \
  -d '{
    "license_key": "XXXX-XXXX-XXXX",
    "fingerprint": "sha256-of-hw-id",
    "token": "<token-dari-activate/validate>",
    "operation": "api_access",
    "request_hash": "opsional-hash-untuk-idempotensi-sisi-produk"
  }'
```

**Response** (`OperationAuthorizationResponse`):
```json
{
  "status": "authorized",
  "authorization": {
    "license_id": "XXXX-XXXX-XXXX",
    "product_id": "roc-support-desk",
    "fingerprint": "sha256-of-hw-id",
    "operation": "api_access",
    "request_hash": "...",
    "issued_at": "2026-08-03T00:00:00Z",
    "expires_at": "2026-08-03T00:05:00Z"
  },
  "authorization_signature": "base64-ed25519-signature"
}
```

Kemungkinan `status`: `authorized` · `invalid_request` (operation/hash melebihi panjang maksimum) · `rate_limited` · `service_unavailable` (maintenance mode atau signing key belum diset) · `invalid` (token tidak valid) · `revoked`/`suspended`/`expired`/`grace`-nya-ditolak (dari `_effective_access_status`, artinya **status Subscription yang bermasalah otomatis membuat operasi premium ikut ditolak**) · `deactivated` (device tidak terdaftar) · `operation_unavailable` (belum dikonfigurasi via Admin) · `not_entitled` (plan pelanggan tidak mencakup fitur ini).

Kelola `OperationPolicy` via **Admin → Licensing → Operation policies** (`apps/licensing/admin.py`, `OperationPolicyAdmin`) — tidak perlu deploy untuk menambah operasi premium baru per produk.

### B7. Entitlements — jembatan Plan ↔ Grant ↔ API

```
catalog.Plan.entitlements  (M2M: key, name, value)
        │
        ▼  Grant.get_entitlements()  →  {key: value, ...}
        │  (apps/provisioning/models.py)
        ▼
dipakai di:
  - response /activate, /validate  → field "entitlements" (untuk gating fitur lokal di produk)
  - authorize_operation()          → dicocokkan dengan OperationPolicy.entitlement_key/required_value
```

Prinsip desainnya sama seperti [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) §15.3: fitur tidak di-hardcode per plan di kode — cukup atur `entitlements` di Admin, tanpa migrasi skema.

### B8. Keamanan yang relevan ke Subscription

- **Ed25519 signing** (`apps/licensing/entitlement_signing.py`, key di env `MARKETPLACE_ED25519_PRIVATE_KEY_B64`, **bukan** di `Setting`/DB): menandatangani amplop `entitlement` (activate/validate) dan `authorization` (operation-authorize) supaya produk bisa memverifikasi respons tidak dipalsukan proxy yang disusupi.
  - Perubahan terbaru: di **production** (`settings.DEBUG=False`), kegagalan signing (key belum diset) sekarang **melempar exception** alih-alih diam-diam mengembalikan entitlement tak bertanda tangan berstatus "active" — mencegah kondisi fail-open yang berbahaya di produksi. Di dev, tetap fallback unsigned untuk kenyamanan.
- **`ACTIVATION_TOKEN_TTL_DAYS`**: default diturunkan dari 7 hari → **1 hari** — instalasi baru perlu heartbeat lebih sering, memperketat jendela antara Subscription berubah status dan produk benar-benar merasakannya.
- **Rate limiting** per license key & per IP mencegah brute-force pengecekan kombinasi `operation` pada `authorize_operation` (lihat B6 poin 1).
- **`X-Berlanggan-Secret`** (opsional, `ACTIVATION_API_SECRET` Setting) berlaku untuk semua endpoint termasuk `/operation-authorize` (satu `Router` dengan auth yang sama, lihat `apps/licensing/api.py`).

### B9. Setting terkait (Admin, tanpa deploy)

| Key | Default | Pengaruh ke License↔Subscription |
|---|---|---|
| `ACTIVATION_TOKEN_TTL_DAYS` | `1` | Umur token heartbeat sebelum harus `/validate` ulang. |
| `ACTIVATION_GRACE_DAYS` | `3` | Berapa lama token kedaluwarsa masih diterima sebagai `grace`. |
| `SUBSCRIPTION_GRACE_DAYS` | `3` | Berapa lama Subscription boleh telat bayar sebelum `suspend_subscription()` dipanggil job. |
| `GLOBAL_GRACE_EXTENSION_DAYS` | `0` | Tombol darurat: tambah grace semua pelanggan sekaligus (insiden pembayaran, dll). |
| `RENEWAL_ADVANCE_HOURS` | `3` | Berapa jam sebelum jatuh tempo, job `renew_subscriptions` mulai mencoba menagih. |
| `MAINTENANCE_MODE` | `false` | `/validate` selalu `active` (fail-open); `/operation-authorize` justru menolak (fail-closed) — lihat B6. |

### B10. Dokumen terkait

- [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) — model Deliverable/Provisioner/Grant umum yang mendasari License.
- [14-state-machines.md](14-state-machines.md) — semua transisi status valid (Subscription, License, Grant, Installation).
- [25-license-webhook-api-flow.md](25-license-webhook-api-flow.md) — alur webhook pembayaran Duitku dan detail penuh `/activate` `/validate` `/deactivate`.
- [23-configuration.md](23-configuration.md) — tabel lengkap semua Setting.
- [06-data-model.md](06-data-model.md) — ERD keseluruhan platform.
