# 27 — Notifikasi WhatsApp & Pilihan Kanal (Email ⟷ WhatsApp)

> **Status dokumen:** RENCANA (belum diimplementasikan). Keputusan user pada §F **sudah final** (2026-08-29) — lihat ADR-022.
> Dokumen ini melengkapi: [08-integrations.md](08-integrations.md) §8.2 (WA gateway), [16-auth-and-sso.md](16-auth-and-sso.md) (identitas & verifikasi), [22-feature-catalog.md](22-feature-catalog.md), dan kode `apps/notifications/`.
> Bahasa: dokumen fungsional Bahasa Indonesia; semua identifier kode / string UI dasar tetap Bahasa Inggris (lihat [DECISIONS.md](DECISIONS.md) → Language).

---

## A. Tujuan

1. Menetapkan **kirim.chat** sebagai WA gateway produksi (menutup Open Question "WA gateway" di [STATUS.md](STATUS.md)).
2. Mengubah model notifikasi dari **aditif** (email *dan* WA jalan sendiri-sendiri) menjadi **pilihan kanal**: **pelanggan (`Customer`)** memilih menerima notifikasi lewat **Email ATAU WhatsApp** — satu kanal utama, bukan keduanya.
3. **Penjual (`SellerProfile`) tetap email-only** — tidak ada pilihan kanal untuk penjual (ADR-022 / F3). Notifikasi penjual yang saat ini lewat WA (`order.awaiting_confirmation` ke seller) **dipindahkan ke email**.
4. Melengkapi struktur data kontak pelanggan (`wa_number`, status verifikasi, preferensi) yang saat ini belum memadai.
5. Menambah verifikasi nomor WA via OTP.
6. Memisahkan **notifikasi transaksional** dari **promosi** (consent terpisah). **Promosi email-only** dulu (F5); WA marketing menyusul setelah quality-rating stabil.

Non-tujuan (fase ini): OTP login / passwordless, 2FA admin (sudah direncanakan terpisah di [16](16-auth-and-sso.md)), notifikasi push/PWA, kanal Instagram/Messenger kirim.chat.

---

## B. Kondisi saat ini (audit)

### B1. Yang sudah ada

| Komponen | Lokasi | Catatan |
|---|---|---|
| Abstraksi WA gateway swappable | `apps/notifications/whatsapp.py` | Backend `console` (dev) + `fonnte` (prod). Tambah backend = 1 kelas `.send()` + daftar di `_BACKENDS`. |
| Normalisasi nomor ID | `whatsapp.normalize_number()` | `08xx → 628xx`, `+62 → 62`. |
| Task async + retry | `apps/notifications/tasks.py` | `deliver_whatsapp`, `deliver_email`, + email HTML (`deliver_order_confirmation_email`, `deliver_topup_confirmation_email`). |
| Handler domain-event | `apps/notifications/handlers.py` | `topup.paid`, `order.paid`, `order.awaiting_confirmation`, `order.payment_rejected`, `subscription.renewed/graced/suspended/cancelled`. |
| Reminder renewal H-3 / H-1 | `apps/notifications/reminders.py` + task `send_renewal_reminders` (hourly) | Hanya untuk `Subscription.status=ACTIVE, auto_renew=True` **dan** saldo kurang. Dedup via `NotificationLog`. |
| Dedup | `NotificationLog` (`dedup_key` unik) | |
| Email suppression | `EmailSuppression` + ESP bounce webhook | **Tidak ada padanan untuk WA.** |
| Invoice PDF | `apps/billing/invoice_service.render_invoice_pdf()` | Dilampirkan di email order confirmation. |

Domain events yang di-`emit` (sumber: `apps/billing/`): `topup.paid`, `order.paid`, `order.awaiting_confirmation`, `order.payment_rejected`, `subscription.renewed`, `subscription.graced`, `subscription.suspended`, `subscription.cancelled`.

### B2. Kekurangan yang menghalangi desain "pilih 1 kanal"

| # | Masalah | Dampak |
|---|---|---|
| K1 | `Customer.notif_wa` + `Customer.notif_email` = **dua boolean independen, keduanya default `True`**. `handlers._wa()` & `_email()` dipanggil terpisah. | Email + WA **dua-duanya terkirim** → "tabrakan". |
| K2 | `reminders.py` sengaja kirim ke **dua kanal** (dedup_key terpisah `:wa` / `:email`). | Sama seperti K1. |
| K3 | Handler `order.awaiting_confirmation` nembak WA penjual langsung (`handlers.py:126-134`), tanpa opt-out / verifikasi. | **Keputusan (ADR-022): penjual email-only.** Kode WA-ke-seller dihapus, diganti `deliver_email`. `SellerProfile` tidak diubah. |
| K4 | **Tidak ada `wa_number_verified_at`** di model manapun. | Nomor salah ketik → notifikasi hilang diam-diam. Kalau WA jadi kanal utama, ini tidak boleh. |
| K5 | `wa_number = CharField(max_length=20, blank=True)` **tanpa validator**. Normalisasi hanya saat kirim. | Data kotor, tak konsisten. |
| K6 | Satu `User` bisa jadi `Customer` **dan** `SellerProfile` → `wa_number` ditulis 2 tempat. | Diterima: `Customer.wa_number` untuk notifikasi (dgn verifikasi); `SellerProfile.wa_number` hanya display kontak. Tidak digabung (bisnis ≠ pribadi). |
| K7 | Tidak ada suppression / keyword STOP untuk WA. | Kepatuhan kebijakan WhatsApp. |
| K8 | Tidak ada tracking status kirim (sent/delivered/read/failed). | Tak bisa fallback saat WA gagal; tak ada observability. |
| K9 | Reminder **hanya** untuk langganan `auto_renew=True`. Langganan berjangka non-auto-renew tidak dapat pengingat kedaluwarsa apa pun. | Gap fitur (lihat §D). |

> Catatan: `apps/catalog/models` juga punya `wa_number` pada produk — itu **tombol "Contact via WA"** di storefront untuk produk tipe kontak. **Beda domain, jangan digabung.**

---

## C. Desain

### C1. Model: pilihan kanal, bukan dua boolean

Kanal notifikasi = **satu pilihan** per penerima:

```python
# apps/core/models.py
class NotificationChannel(models.TextChoices):
    EMAIL = "email", "Email"
    WHATSAPP = "whatsapp", "WhatsApp"
```

Aturan:

- Default = `EMAIL` (email selalu ada & terverifikasi untuk signup password; identitas anchor allauth).
- Opsi `WHATSAPP` di UI **terkunci** sampai `wa_number` terverifikasi via OTP.
- `resolve_channel()` = kanal **efektif** — otomatis turun ke `EMAIL` jika WA dipilih tapi nomor belum/tidak lagi terverifikasi, atau nomor kena WA-suppression.

### C2. Model: field preferensi pada `Customer` saja

WA notifikasi = fitur **pelanggan saja** (ADR-022). Jadi field preferensi ditaruh **langsung di `Customer`** — bukan abstract mixin (over-engineering untuk satu model). `SellerProfile` **tidak berubah** (tetap `wa_number` untuk display kontak; tidak ada `notification_channel`).

```python
# apps/accounts/models.py — Customer
class Customer(TimestampedModel):
    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="customer")
    wa_number = models.CharField(max_length=20, blank=True, validators=[validate_wa_number])
    wa_number_verified_at = models.DateTimeField(null=True, blank=True)
    notification_channel = models.CharField(
        max_length=10, choices=NotificationChannel.choices,
        default=NotificationChannel.EMAIL,
    )
    notif_promo = models.BooleanField(
        default=False, help_text="Opt-in eksplisit untuk pesan promosi (terpisah dari transaksional)."
    )
    notes = models.TextField(blank=True)
    # notif_wa / notif_email DIHAPUS (lihat C3)

    @property
    def wa_verified(self) -> bool:
        return self.wa_number_verified_at is not None

    def resolve_channel(self) -> str:
        """Kanal efektif. Fallback ke email bila WA dipilih tapi belum/tidak lagi valid."""
        if (self.notification_channel == NotificationChannel.WHATSAPP
                and self.wa_verified
                and not wa_suppressed(self.wa_number)):
            return NotificationChannel.WHATSAPP
        return NotificationChannel.EMAIL

    @property
    def notify_email_address(self) -> str:
        return self.user.email
```

- `validate_wa_number` (di `apps/core`): validator format (E.164 ID: `62` + 9–13 digit setelah normalisasi). Nomor **tidak** unik di DB (keluarga/tim bisa berbagi nomor) — keunikan hanya dicek untuk anti-abuse OTP.
- Notifikasi **penjual** selalu ke `seller.user.email` — tidak ada `resolve_channel` untuk penjual.

### C3. Migrasi data (dari boolean lama — `Customer` saja)

| Kondisi lama (`Customer`) | `notification_channel` baru |
|---|---|
| `notif_wa=True` & `notif_email=False` | `whatsapp` (hanya jika `wa_number` non-blank; kalau blank → `email`) |
| selain itu | `email` |

- `notif_wa` / `notif_email` **dihapus** setelah migrasi data.
- `wa_number_verified_at` = `NULL` untuk semua baris lama → semua yang tadinya `whatsapp` **efektif jatuh ke email** sampai user verifikasi ulang. Ini disengaja (aman).
- Backfill: normalisasi + validasi semua `Customer.wa_number` existing; nomor invalid dikosongkan + dicatat.
- `SellerProfile` **tidak disentuh** oleh migrasi ini.

### C4. Refactor dispatch — hilangkan "tabrakan"

Ganti `_wa()` + `_email()` yang jalan independen dengan **satu fungsi**:

```python
# apps/notifications/dispatch.py
def notify(recipient, *, event, wa_text, email_subject, email_body,
           email_html_task=None, always_email=False, dedup_ref=None):
    """Kirim SATU notifikasi ke kanal efektif penerima.

    always_email=True  → dokumen bernilai (receipt/invoice/license key): email SELALU
                         dikirim; kalau kanal = WA, kirim juga ringkasan singkat ke WA.
    """
    channel = recipient.resolve_channel()
    if channel == NotificationChannel.WHATSAPP:
        deliver_whatsapp.delay(normalize_number(recipient.wa_number), wa_text)
        if always_email:
            _dispatch_email(recipient, email_subject, email_body, email_html_task)
    else:
        _dispatch_email(recipient, email_subject, email_body, email_html_task)
```

- `handlers.py` & `reminders.py` dipindah ke `notify()`.
- `reminders.py`: `dedup_key` jadi **satu per (sub, window)** tanpa suffix kanal.
- Fallback: bila webhook kirim.chat melaporkan `failed` untuk sebuah pesan, task follow-up mengirim ulang lewat email (butuh menyimpan konteks pesan — lihat C6 Outbox).
- **Notifikasi penjual** (`order.awaiting_confirmation` ke seller) **tidak** lewat `notify()` channel-resolve — langsung `deliver_email` ke `seller.user.email`. Kode WA-ke-seller di `handlers.py:126-134` dihapus.

### C5. Backend kirim.chat

`KirimChatBackend` di `apps/notifications/whatsapp.py`:

| Item | Nilai |
|---|---|
| Base URL | `https://api-prod.kirim.chat/api/v1/public` |
| Auth | Header `Authorization: Bearer $WA_TOKEN` (key `kc_live_…`) |
| Health | `GET /health` |
| Kirim | `POST /messages/send` — body `{phone_number, channel:"whatsapp", message_type:"text"|"template", content|template...}` |
| Status | `GET /messages/{id}/status` |
| Rate limit | 60 pesan / menit (WA) |
| Webhook | event `sent/delivered/read/failed` + inbound; signature HMAC-SHA256; retry backoff 5× |

- `WA_BACKEND=kirimchat` (Setting), `WA_TOKEN` (**env only**, secret — konsisten dgn `FonnteBackend` H1).
- Env baru di `.env.example`: `WA_TOKEN=`, `KIRIMCHAT_WEBHOOK_SECRET=`.
- Fonnte backend tetap ada (fallback / rollback cepat).

### C6. Webhook kirim.chat — status & inbound ✅ (2026-08-29)

`POST /notifications/webhook/kirimchat/` (`apps/notifications/views.kirimchat_webhook`,
logika di `apps/notifications/webhooks.py`).

Payload kirim.chat: `{event_type, event_id, timestamp, data:{message_id, customer_phone, content, direction, channel}}`.

1. **Verifikasi** header `X-KirimChat-Signature: sha256=<hmac-sha256(raw_body, KIRIMCHAT_WEBHOOK_SECRET)>` → 401 kalau gagal; 500 kalau secret belum di-set.
2. **Idempotency** — `event_id` disimpan di cache (Redis) 1 hari; duplikat → `200 OK (duplicate)` tanpa proses.
3. **Status** `message.sent/delivered/read` → update `NotificationDelivery` (cari via `provider_msg_id`); tidak mundur ke status lebih rendah.
4. **`message.failed`** → status `failed` + `fallback_delivery_to_email()` (kirim ulang `email_subject`/`email_body` yang tersimpan; status jadi `fallback_sent`).
5. **`message.received`** dengan `content` = `STOP/BERHENTI/UNSUB/UNSUBSCRIBE/BATAL/KELUAR` → `WhatsAppSuppression(number, opt_out)` + semua `Customer` bernomor itu yang `channel=whatsapp` dipindah ke `email` + balas konfirmasi 1×. Kata `MULAI/START/LANJUT/SUBSCRIBE` → hapus suppression.
6. Jawab 2xx dalam < 5 detik (proses ringan, task async).

**Model baru** (`apps/notifications/models.py`) — bukan meng-extend `NotificationLog` (semantiknya beda: `NotificationLog` = dedup, `NotificationDelivery` = outbox):

```python
class WhatsAppSuppression(TimestampedModel):
    number = models.CharField(max_length=20, unique=True)   # normalized 62…
    reason = ...   # opt_out | invalid_number | complaint | manual
    detail = models.TextField(blank=True)

class NotificationDelivery(TimestampedModel):
    customer = FK(Customer, null=True, on_delete=SET_NULL, related_name="notifications")
    event, channel, recipient
    wa_text, email_subject, email_body        # retained for WA→email fallback
    status  = queued|sent|delivered|read|failed|fallback_sent
    provider, provider_msg_id (indexed), error
```

Value-document email (HTML receipt) di-dispatch task-nya sendiri dan **tidak** ditrack di `NotificationDelivery`.

### C7. Verifikasi nomor WA via OTP

Alur (di dashboard pelanggan — penjual tidak punya verifikasi WA):

1. User isi/ubah `wa_number` → status `unverified`.
2. Klik "Kirim kode" → generate OTP 6 digit, simpan **hash**-nya + `expires_at` (5 menit) di `WhatsAppOTP`, kirim via `deliver_whatsapp` (template kategori **authentication**).
3. User masukkan kode → cocok & belum kedaluwarsa → set `wa_number_verified_at = now()`.
4. Rate limit: maks 3 kirim / nomor / jam; maks 5 percobaan verifikasi / kode; cooldown 60 detik antar kirim.
5. Ganti nomor → `wa_number_verified_at` di-reset `NULL`.

```python
class WhatsAppOTP(TimestampedModel):
    number      = models.CharField(max_length=20)
    code_hash   = models.CharField(max_length=128)
    expires_at  = models.DateTimeField()
    attempts    = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
```

### C8. Kebijakan template WhatsApp (WABA)

Pesan **business-initiated di luar 24 jam** customer-service window **wajib pakai template pre-approved**. Yang termasuk: semua reminder, `subscription.*`, OTP, promosi.
Pesan **dalam 24 jam** setelah user meng-inbound boleh free-text.

Registry template: `apps/notifications/templates_registry.py` — peta `event → {template_name, category, variables[]}`. Kategori WA yang dipakai fase ini:
- **authentication** → OTP verifikasi nomor.
- **utility** → reminder, status langganan, konfirmasi order/top-up, invoice.
- **marketing** → **tidak dipakai** (promosi email-only, F5). Diaktifkan kemudian via ADR baru.

Daftar template yang perlu diajukan ke kirim.chat/Meta ada di §E.

### C9. Consent promosi (terpisah)

- `notif_promo` (default `False`) **independen** dari `notification_channel`.
- **Keputusan F5: promosi email-only** untuk sekarang. Pesan promosi hanya dikirim ke `Customer` dengan `notif_promo=True`, **selalu lewat email** apa pun `notification_channel`-nya.
- WA marketing (kategori template `marketing`) **ditunda** — diaktifkan hanya setelah volume transaksional & quality-rating WA stabil, lewat ADR baru.
- Setiap email marketing menyertakan link unsubscribe / preference center.

### C10. Quiet hours, rate limit, batching

- **Quiet hours** 22:00–07:00 WIB untuk non-urgent (reminder, promo) → tunda ke jam 07:00. Urgent (`suspended`, `payment_rejected`, OTP) tetap dikirim.
- Broadcast: throttle ≤ 60 WA/menit (batasan kirim.chat), antri via Celery rate limit.
- `Setting` baru: `WA_QUIET_START`, `WA_QUIET_END`, `WA_BROADCAST_RATE`.

---

## D. Katalog notifikasi (target akhir)

Legenda kanal: **P** = kirim ke kanal pilihan pelanggan (`resolve_channel`); **E!** = email selalu, plus ringkasan ke kanal pilihan bila WA; **S:email** = ke penjual, selalu email.

| Event | Kanal | Template cat. | Status |
|---|---|---|---|
| `topup.paid` | E! | utility | ada (refactor) |
| `order.paid` (+ license key / akses) | E! | utility | ada (refactor) |
| `order.awaiting_confirmation` (buyer) | P | utility | ada (refactor) |
| `order.awaiting_confirmation` (seller) | S:email | — | ada (**pindah WA→email**) |
| `order.payment_rejected` | P (urgent) | utility | ada (refactor) |
| **Invoice pending — reminder H+1j & ~2j sebelum expiry** | P | utility | **baru** |
| **Invoice / order expired** | P | utility | **baru** |
| `subscription.renewed` | P | utility | ada (refactor; + tambah email) |
| Reminder renewal H-3 / H-1 (auto_renew, saldo kurang) | P | utility | ada (refactor jadi 1 kanal) |
| **Reminder kedaluwarsa lisensi non-auto-renew H-7 / H-3 / H-1** | P | utility | **baru (K9)** |
| **Lisensi/langganan berakhir hari ini** | P | utility | **baru** |
| `subscription.graced` (hari-0) | P | utility | ada (refactor) |
| **Grace countdown H-2 / H-1 sebelum suspend** | P | utility | **baru** |
| `subscription.suspended` | P (urgent) | utility | ada (refactor) |
| `subscription.cancelled` | P | utility | ada (refactor) |
| **Saldo rendah proaktif (sebelum renewal gagal)** | P | utility | **baru (Tier 2)** |
| **Welcome (signup / pembelian pertama)** | P | utility | **baru (Tier 2)** |
| **OTP verifikasi nomor WA** | WA only | authentication | **baru** |
| **Promosi / produk baru / win-back** | email only (butuh `notif_promo`) | — | **baru (Tier 3)** |

---

## E. Rencana implementasi (bertahap)

### Fase N.1 — Fondasi kanal & gateway ✅ (2026-08-29)
- [x] `NotificationChannel` (`apps/core/models.py`) + `validate_wa_number` / `normalize_wa_number` (`apps/core/validators.py`).
- [x] `Customer`: `wa_number_verified_at` / `notification_channel` / `notif_promo` + `wa_verified` / `resolve_channel()` / `notify_email_address`; `notif_wa` / `notif_email` dihapus. `SellerProfile` tidak disentuh.
- [x] Migrasi `0007_customer_notification_channel` — skema + data (boolean lama → channel) + normalisasi/pembersihan `wa_number`. Reversible.
- [x] `KirimChatBackend` + `_BACKENDS["kirimchat"]`; `.env.example` (`WA_TOKEN`, `KIRIMCHAT_WEBHOOK_SECRET`); `docs/08` & `docs/23` diperbarui.
- [x] Dispatch handlers + `reminders.py` dipindah ke `resolve_channel()` (satu kanal; receipt selalu email + WA copy); notif seller → email.
- [x] Admin `CustomerAdmin` + form `dashboard/profile` (radio kanal, kunci WA sampai verified, toggle promo).
- [x] Tes: `tests/test_notification_channel.py` (validator, `resolve_channel`, backend HTTP) + `tests/test_notifications.py` ditulis ulang untuk model 1-kanal. Suite: 224 pass (2 gagal pre-existing, tidak terkait).

### Fase N.2 — Dispatch terpadu ✅ (2026-08-29)
- [x] `apps/notifications/dispatch.py` — `notify()`, `notify_wa_copy()`, `effective_channel()`, `fallback_delivery_to_email()`. `handlers.py` & `reminders.py` memakainya.
- [x] `reminders.py`: satu `dedup_key` per (sub, window); lewat `notify()`.
- [x] Model **`NotificationDelivery`** (outbox terpisah, bukan `NotificationLog`) — event/channel/recipient/wa_text/email_subject/email_body/status/provider/provider_msg_id/error.
- [x] `deliver_whatsapp` task terima `delivery_id`; update status (sent + `provider_msg_id`; failed + fallback saat retry habis).
- [x] Bug fix: `whatsapp.get_backend()` — `Setting` tidak pernah di-import (NameError laten di prod). `send_whatsapp()` kini kembalikan `provider_msg_id`.
- [x] Semua teks notifikasi diubah ke **Bahasa Inggris** (konsisten dgn DECISIONS.md → Language).
- [x] Tes: `tests/test_notifications.py` (tepat satu kanal per event).

### Fase N.3 — Webhook & suppression ✅ (2026-08-29)
- [x] `apps/notifications/webhooks.py` + `views.kirimchat_webhook` + `urls.py` → `/notifications/webhook/kirimchat/` (didaftarkan di `config/urls.py`).
- [x] Verifikasi HMAC-SHA256 (`X-KirimChat-Signature`), idempotency `event_id` via cache.
- [x] Status `sent/delivered/read` → update `NotificationDelivery`; `failed` → fallback email otomatis.
- [x] `WhatsAppSuppression` model + admin; STOP/START keyword; `effective_channel()` cek suppression.
- [x] Tes: `tests/test_notification_webhook.py` (signature 401, delivered, failed→fallback, idempotency, STOP).

### Fase N.4 — OTP verifikasi nomor (pelanggan) ✅ (2026-08-30)
- [x] `WhatsAppOTP` model (migration `notifications/0004`) — hanya hash kode, `expires_at`, `attempts` (maks 5), `consumed_at`.
- [x] `apps/notifications/otp.py` — `request_code()` / `verify_code()`; rate limit: cooldown 60s, maks 3 kirim/nomor/jam, cek suppression. Kode 6 digit, TTL 5 menit, dikirim via `deliver_whatsapp` (plain text; template `authentication` menyusul di N.5).
- [x] Views `dashboard:wa_send_otp` / `dashboard:wa_verify_otp`; `dashboard/profile.html` — kartu "WhatsApp number" (input → Send code → Enter code → Verify); nomor **tidak lagi** disimpan lewat form profil utama, hanya via alur OTP. Radio "WhatsApp" terkunci sampai `wa_verified` (sudah dari N.1).
- [x] Ganti nomor / verify ulang → `verify_code` set `wa_number` + `wa_number_verified_at`.
- [x] Tes: `tests/test_wa_otp.py` (happy path, brute-force lock, kedaluwarsa, cooldown, suppressed, view wiring).

> Preference center penuh (link unsubscribe di email, dst.) digabung ke N.7.

### Fase N.5 — Template WABA
- [ ] `templates_registry.py`.
- [ ] Ajukan template ke kirim.chat/Meta (lihat daftar di bawah) — **butuh waktu approval, mulai awal**.
- [ ] `KirimChatBackend.send()` dukung `message_type="template"` + variabel.

### Fase N.6 — Notifikasi baru (Tier 1)
- [ ] Reminder invoice pending + expired.
- [ ] Reminder kedaluwarsa lisensi non-auto-renew (H-7/H-3/H-1) + "berakhir hari ini".
- [ ] Grace countdown H-2/H-1.
- [ ] `subscription.renewed` + email.

### Fase N.7 — Tier 2 & 3
- [ ] Saldo rendah proaktif, welcome message.
- [ ] Quiet hours + broadcast throttle.
- [ ] Promosi / win-back / produk baru — **email-only** (opt-in `notif_promo`).

**Draft template WABA untuk diajukan** (nama sementara — semua kategori utility kecuali OTP):
`otp_wa_verification` (auth) · `topup_success` · `order_success` · `order_pending_payment` · `order_expired` ·
`renewal_reminder` · `license_expiry_reminder` · `license_expired` · `subscription_renewed` ·
`subscription_grace` · `grace_countdown` · `subscription_suspended` · `subscription_cancelled` ·
`low_balance_alert` · `welcome`.
Template `marketing` **tidak diajukan** fase ini (promosi email-only).

---

## F. Keputusan user — FINAL (2026-08-29, dikunci di ADR-022)

| # | Keputusan |
|---|---|
| F1 | Kwitansi/invoice/license key → **selalu email** + ringkasan singkat ke WA bila kanal pelanggan = WA (`always_email=True`). |
| F2 | Notifikasi kritis (`suspended`, `payment_rejected`) → **ikut kanal pilihan pelanggan saja** (tidak dipaksa email). |
| F3 | **Penjual email-only.** Tidak ada pilihan kanal untuk `SellerProfile`. Notif seller `order.awaiting_confirmation` yang kini lewat WA → **dipindah ke email** (`handlers.py:126-134` dihapus). |
| F4 | **WA notifikasi = fitur pelanggan (`Customer`) saja.** Default kanal pelanggan baru = `email`; opsi WA muncul setelah verifikasi nomor. |
| F5 | **Promosi email-only** untuk sekarang. WA marketing ditunda sampai quality-rating stabil (ADR baru nanti). |
| F6 | `Customer.wa_number` (notifikasi, terverifikasi) dan `SellerProfile.wa_number` (display kontak) **tetap terpisah**. |
| F7 | **ADR-022 dibuat** — lihat [DECISIONS.md](DECISIONS.md). |

---

## G. Open Questions (lanjutan, non-blocking)

- Multi-nomor / multi-kontak per akun (mis. tim penjual) — tunda sampai ada permintaan.
- Kanal Instagram/Messenger kirim.chat untuk customer support inbox — di luar scope.
- Biaya per pesan & anggaran bulanan WA — perlu angka dari kirim.chat untuk proyeksi.
- Retensi data `NotificationLog`/outbox (housekeeping) — usul: purge > 180 hari.
