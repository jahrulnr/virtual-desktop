---
name: Menjalankan Coddy Agent di Relay AI Desktop
description: Panduan lokal untuk menghubungkan Coddy ke provider OpenAI-compatible, memahami tool computer MCP, melakukan handoff manusia, dan memeriksa persistence setelah Docker Compose restart.
tag: coddy-agent, computer-use, docker, golang, mcp, openai-compatible, openrouter
---

# Menjalankan Coddy Agent di Relay AI Desktop

Relay tidak meminta model menguasai Linux lewat koordinat mentah sendirian. Coddy
menjadi harness yang menjaga percakapan dan ReAct loop, sementara sidecar Go
menyediakan kosakata computer-use yang kecil dan konsisten. Hasilnya, model yang
bukan frontier tetap mendapat tindakan tingkat tujuan—klik titik ini, drag dari A
ke B, scroll di area ini—dan sidecar mengurus detail seperti lease, gerakan pointer
yang halus, serta validasi batas layar.

Panduan ini membawa stack dari clone sampai satu task Coddy, lalu menguji kasus
yang paling penting untuk demo: manusia mengambil alih sesi yang sama dan state
tetap ada sesudah `docker compose down` lalu `up`.

## Prasyarat

Siapkan Docker Engine dengan plugin Compose, sekitar 3 GB ruang image, dan API key
dari provider yang kompatibel dengan OpenAI chat completions. Model multimodal
sangat disarankan. Accessibility tree membantu untuk kontrol standar, tetapi
canvas, gambar, dan sebagian Electron chrome tetap harus dibaca dari screenshot.

## Langkah 1: Isi konfigurasi provider

Salin template environment:

```bash
cp .env.example .env
```

Untuk OpenAI langsung, isi:

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-replace-me
OPENAI_MODEL=gpt-4o
```

Untuk OpenRouter, contoh minimumnya:

```dotenv
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-replace-me
OPENAI_MODEL=openai/gpt-4o
```

Base URL harus menyertakan `/v1`. Nama model diteruskan apa adanya setelah nama
provider internal `gateway/`, jadi gunakan ID yang memang dikenal gateway kamu.
Jangan commit `.env`.

Empat capability lokal di bagian bawah template aman hanya untuk demo loopback.
Ganti semuanya sebelum port diteruskan lewat tunnel, reverse proxy, atau jaringan
lain.

## Langkah 2: Build dan jalankan tiga servis

```bash
docker compose up -d --build
docker compose ps
```

Tunggu sampai `desktop`, `computer-mcp`, dan `coddy` berstatus `healthy`. Hanya
desktop yang diterbitkan ke host, tepatnya `127.0.0.1:3000`. Port MCP dan Coddy
tetap berada di network Compose.

Kalau panel tampil tetapi request agent mendapat 502, periksa kesehatan upstream:

```bash
docker compose ps
docker compose logs --no-color --tail=100 desktop computer-mcp coddy
```

Compose menunggu dependency sehat saat start pertama. Nginx juga memakai nama DNS
servis, bukan IP container yang lama, sehingga recreate normal tidak mengunci proxy
ke alamat yang sudah mati.

## Langkah 3: Sambungkan browser dan jalankan task

Buka <http://127.0.0.1:3000>, masukkan password development `testtest`, lalu pilih
**Open desktop**. Klik tombol **C** untuk membuka flight recorder Coddy.

Berikan outcome yang dapat diverifikasi, misalnya:

> Buka Chromium, kunjungi example.com, lalu berhenti setelah judul halaman terlihat.

Saat **Run task** ditekan, UI melepaskan lease manusia bila lease itu sedang aktif.
Coddy lalu memakai `ui_inspect` dan screenshot untuk grounding, menjalankan aksi
kecil, dan menampilkan aktivitas tool di panel. Shell/file tool bawaan Coddy berada
di container terpisah dengan workspace kosong; operasi desktop tetap harus lewat
MCP.

## Langkah 4: Ambil alih tanpa mengganti sesi

Ketika Coddy sedang bekerja, klik **Take control**. Lease manusia selalu
mem-preempt lease agent. Input MCP berikutnya menerima conflict dan agent harus
berhenti, sementara window, aplikasi, pointer OS, dan framebuffer tetap sama.

Pada observer mode, ada shield transparan di atas canvas noVNC. Pointer browser
tetap terlihat, tetapi event belum masuk ke desktop. Shield baru dilepas setelah
takeover sukses; saat itulah keyboard dan pointer benar-benar dikirim ke noVNC.
Klik **Release control** untuk kembali menjadi observer. Coddy dapat mengambil
lease baru pada langkah berikutnya.

## Langkah 5: Pastikan state selamat dari down/up

Buat satu percakapan Coddy atau file kecil di desktop, kemudian jalankan:

```bash
docker compose down
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:3000/api/v1/control
```

`down` biasa menghapus container dan network, bukan named volume. Karena itu
`desktop-home`, manifest install, dan `coddy-state` tetap ada. Setelah ketiga servis
sehat, conversation dan file harus muncul kembali dan endpoint control tidak boleh
502.

Reset penuh memang destruktif dan harus disengaja:

```bash
docker compose down -v
docker compose up -d --build
```

Perintah itu menghapus seluruh file desktop, profil browser, manifest package, dan
riwayat Coddy yang tersimpan di named volumes.

## Bagaimana model mengoperasikan OS

Tool MCP `computer` menyediakan screenshot, gerakan pointer halus, click variants,
drag, mouse down/up, posisi cursor, type, key chord, hold-key, scroll empat arah,
wait, dan release-control. Tool `ui_inspect` menyediakan AT-SPI tree yang dibatasi.

Skill operator meminta model mengikuti loop pendek:

1. baca accessibility tree, lalu screenshot jika semantik tidak cukup;
2. cari target baru—jangan memakai koordinat lama setelah layout berubah;
3. lakukan satu aksi kecil;
4. screenshot atau inspect lagi untuk memverifikasi hasil;
5. lepaskan kontrol ketika selesai atau ketika manusia masuk.

Gerak pointer panjang diinterpolasi dengan kurva smoothstep oleh sidecar, bukan
oleh model. Zoom dilakukan dengan shortcut aplikasi seperti `CTRL`+`+`,
`CTRL`+`-`, dan `CTRL`+`0`, kemudian diverifikasi lewat screenshot. Recording tidak
dibuat sebagai primitive tersembunyi karena dapat menangkap data privat; agent
harus meminta konfirmasi dan memakai aplikasi recording yang terlihat di desktop.

## Batas keamanan yang perlu diingat

Konfigurasi ini cocok untuk local single-user demo, bukan hostile multi-tenant
sandbox. Desktop memakai X11 bersama, paket `.deb` yang disetujui dapat menjalankan
maintainer script sebagai root, egress belum dibatasi, dan Docker seccomp untuk
desktop masih `unconfined` agar Chromium/Electron mempertahankan sandbox internal.

Coddy menyimpan API key provider di environment-nya. Built-in command tool memakai
mode `ask`, tetapi command yang disetujui tetap dapat membaca environment proses.
Untuk produksi, taruh credential asli di model proxy terpisah dan berikan Coddy
token sempit berumur pendek. Baca [model keamanan](SECURITY.md) sebelum membuka
stack ke jaringan.

## Validasi akhir

```bash
make test
make static
make smoke
```

Lulus berarti unit Python dan Go sehat, Compose valid, screenshot MCP benar-benar
berupa image content, pointer bergerak di framebuffer nyata, takeover manusia
memblokir agent dengan 409, dan satu origin browser tetap dapat memuat desktop
serta panel Coddy.
