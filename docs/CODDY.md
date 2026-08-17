---
name: Menjalankan Coddy Agent di Relay AI Desktop
description: Panduan lokal untuk menghubungkan Coddy ke provider OpenAI-compatible, menjalankan computer tools, melakukan handoff manusia, dan memeriksa persistence setelah Docker Compose restart.
tag: coddy-agent, computer-use, docker, golang, mcp, openai-compatible, openrouter
---

# Menjalankan Coddy Agent di Relay AI Desktop

Relay membungkus desktop, Coddy, dan computer tools dalam satu container. Coddy
menjaga percakapan serta ReAct loop, sedangkan proses Go MCP menyediakan kosakata
computer-use yang kecil dan konsisten. Model cukup menentukan hasil tindakan—klik
titik ini, drag dari A ke B, scroll di area ini—lalu proses Go mengurus lease,
gerakan pointer yang halus, dan validasi batas layar.

Panduan ini membawa stack dari clone sampai satu task Coddy. Bagian akhirnya
menguji dua perilaku yang penting untuk demo: manusia mengambil alih desktop yang
sama, lalu percakapan dan file tetap ada setelah `docker compose down` dan `up`.

## Prasyarat

Siapkan Docker Engine dengan plugin Compose, sekitar 3 GB ruang image, dan API key
dari provider yang kompatibel dengan OpenAI chat completions. Model multimodal
sangat disarankan. Accessibility tree membantu kontrol standar, tetapi canvas,
gambar, dan sebagian Electron UI tetap perlu dibaca dari screenshot.

## 1. Isi konfigurasi provider

Salin template environment:

```bash
cp .env.example .env
```

Untuk OpenAI langsung:

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-replace-me
OPENAI_MODEL=gpt-4o
```

Untuk OpenRouter:

```dotenv
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-replace-me
OPENAI_MODEL=openai/gpt-4o
```

Base URL harus menyertakan `/v1`. Nama model diteruskan apa adanya setelah nama
provider internal `gateway/`, jadi gunakan ID yang memang dikenal gateway kamu.
Model gratis cocok sebagai stub untuk memeriksa aliran SSE, timeline, dan tool
card; keberhasilan operasi desktop tetap bergantung pada kemampuan vision dan
computer-use model tersebut. Jangan commit `.env`.

## 2. Build dan jalankan

```bash
docker compose up -d --build
docker compose ps
```

Hanya ada satu service bernama `desktop`. Statusnya menjadi `healthy` setelah
desktop, control API, MCP, dan Coddy siap di dalam container. UI diterbitkan pada
`127.0.0.1:3000`.

Kalau panel tampil tetapi request agent mendapat 502, lihat proses dan log dari
service yang sama:

```bash
docker compose exec -T desktop supervisorctl status
docker compose logs --no-color --tail=150 desktop
```

Health check memeriksa control API, endpoint MCP, dan Coddy. Dengan satu lifecycle,
`compose up` tidak lagi bergantung pada urutan DNS atau tiga container berbeda.

## 3. Sambungkan browser dan jalankan task

Buka <http://127.0.0.1:3000>, masukkan password lokal `testtest`, lalu pilih
**Open desktop**. Klik tombol **C** untuk membuka flight recorder Coddy.

Berikan outcome yang dapat diverifikasi, misalnya:

> Buka Chromium, kunjungi example.com, lalu berhenti setelah judul halaman terlihat.

Saat **Run task** ditekan, UI melepaskan lease manusia bila lease itu sedang aktif.
Coddy kemudian memakai `ui_inspect` dan screenshot untuk grounding, menjalankan
aksi kecil, dan mengalirkan outcome, tool activity, serta error sebagai timeline
Markdown yang sudah dirender. Tombol **Take control** tetap di chrome, jadi
framebuffer tidak tertutup saat kamu memantau agent.

## 4. Ambil alih tanpa mengganti sesi

Ketika Coddy sedang bekerja, klik **Take control** atau tekan `Alt+Shift+C`.
Lease manusia selalu mem-preempt lease agent. Turn Coddy yang sedang berjalan
dibatalkan. Input MCP berikutnya menerima conflict dan agent berhenti, sementara
window, aplikasi, pointer OS, dan framebuffer tetap sama.

Pada observer mode, shield transparan berada di atas canvas noVNC. Pointer browser
tetap terlihat, tetapi event belum masuk ke desktop. Shield dilepas setelah
takeover berhasil; saat itulah keyboard dan pointer dikirim ke noVNC. Klik
**Release** atau tekan `Alt+Shift+C` untuk kembali menjadi observer. Coddy dapat
mengambil lease baru dan melanjutkan dari layar yang sama.

## 5. Pastikan state selamat dari down/up

Buat satu percakapan Coddy atau file kecil di desktop, kemudian jalankan:

```bash
docker compose down
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:3000/api/v1/control
```

`down` biasa menghapus container dan network, bukan named volume. Karena itu
`desktop-home`, `desktop-state`, dan `coddy-state` tetap ada. Setelah satu service
sehat, conversation dan file harus muncul kembali dan endpoint control tidak boleh
502. MCP memakai transport stateless, sehingga percakapan lama juga tidak membawa
session transport kedaluwarsa ke container baru.

Reset penuh memang destruktif dan harus disengaja:

```bash
docker compose down -v
docker compose up -d --build
```

Perintah itu menghapus file desktop, profil browser, manifest package, dan riwayat
Coddy yang tersimpan di named volumes.

## Bagaimana model mengoperasikan OS

Tool MCP `computer` menyediakan screenshot, gerakan pointer halus, click variants,
drag, mouse down/up, posisi cursor, type, key chord, hold-key, scroll empat arah,
wait, dan release-control. Tool `ui_inspect` menyediakan AT-SPI tree yang dibatasi.

Skill operator meminta model mengikuti loop pendek:

1. baca accessibility tree, lalu screenshot jika semantik tidak cukup;
2. cari target baru dan jangan memakai koordinat lama setelah layout berubah;
3. lakukan satu aksi kecil;
4. screenshot atau inspect lagi untuk memverifikasi hasil;
5. lepaskan kontrol ketika selesai atau ketika manusia masuk.

Gerak pointer panjang diinterpolasi dengan kurva smoothstep oleh proses Go, bukan
oleh model. Zoom memakai shortcut aplikasi seperti `CTRL`+`+`, `CTRL`+`-`, dan
`CTRL`+`0`, kemudian diverifikasi lewat screenshot. Recording tidak disembunyikan
sebagai primitive agent; gunakan aplikasi recording yang terlihat di desktop agar
hasil dan status rekamannya dapat diperiksa manusia.

## Validasi akhir

```bash
make test
make static
make smoke
```

Lulus berarti unit Python, JavaScript, dan Go sehat; MCP dapat dipanggil kembali
tanpa session transport; pointer bergerak di framebuffer nyata; takeover manusia
memblokir agent dengan 409; dan satu origin browser dapat memuat desktop serta
panel Coddy.
