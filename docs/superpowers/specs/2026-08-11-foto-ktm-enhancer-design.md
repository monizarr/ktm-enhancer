# Desain: Aplikasi Peningkatan Kualitas Foto KTM Mahasiswa

## Latar Belakang

Foto KTM mahasiswa disimpan di PostgreSQL (`dbstain`, schema `foto`, tabel `md_foto`) sebagai Large Object, dirujuk lewat kolom `foto1` (foto asli) dan `foto2` (saat ini kosong/tidak dipakai). Repo ini sudah punya dua script (`foto_single.py`, `foto_csv.py`) yang mengunduh foto dari `foto1`/`foto2` ke disk berdasarkan NIM.

Tujuan: proses foto di `foto1` melalui pipeline peningkatan kualitas gambar (denoise, koreksi cahaya/warna, restorasi & upscaling wajah), lalu simpan hasilnya ke `foto2` di database yang sama — `foto1` tidak pernah diubah, jadi selalu ada foto asli sebagai referensi/rollback.

Skala data: ~2355 mahasiswa. GPU NVIDIA (CUDA) tersedia di mesin lokal yang akan menjalankan aplikasi.

## Arsitektur

```
pgfoto-enhancer/
├── .env                    # kredensial DB (gitignored)
├── .env.example
├── requirements.txt
├── enhancer/
│   ├── __init__.py
│   ├── db.py                # koneksi DB, fetch foto1, update foto2, log status
│   ├── pipeline.py          # denoise -> CLAHE -> GFPGAN -> resize 450x750
│   └── models/               # cache model weights GFPGAN (auto-download)
├── local_output/             # backup lokal before/after (gitignored)
└── main.py                   # CLI entrypoint
```

### Komponen

- **`db.py`** — satu-satunya tempat yang tahu soal SQL & Large Object.
  - `get_pending_nims(limit=None)` — NIM yang belum berstatus `success` di `enhancement_log` (retry otomatis untuk yang `failed`).
  - `fetch_foto1(nim)` — baca Large Object dari `foto1`, return `bytes` atau `None`.
  - `write_foto2(nim, image_bytes)` — buat Large Object baru (`conn.lobject(0, 'wb')`), lalu `UPDATE foto.md_foto SET foto2 = %s WHERE nim = %s` dengan **parameterized query** (memperbaiki celah SQL injection f-string di script lama).
  - `log_result(nim, status, error_message=None)` — upsert ke `enhancement_log`.
  - Kredensial dibaca dari `.env` via `python-dotenv`, bukan hardcode.

- **`pipeline.py`** — pure function `enhance(image_bytes: bytes) -> bytes`, tanpa dependensi ke DB, sehingga bisa dites dengan file gambar lokal secara terpisah.

- **`main.py`** — CLI orchestrator (`argparse`). Load model GFPGAN sekali di awal proses (mahal), lalu loop NIM pending.

### Tabel baru

```sql
CREATE TABLE foto.enhancement_log (
    nim VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL,        -- 'success' | 'failed'
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT now()
);
```

## Alur Data (Pipeline) per NIM

1. `get_pending_nims()` → daftar NIM kandidat.
2. `fetch_foto1(nim)` → `bytes` JPEG asli. Jika `None` → log `failed` dengan pesan `"foto1 kosong"`, skip ke NIM berikutnya (tidak masuk pipeline).
3. `pipeline.enhance(image_bytes)`:
   1. Decode ke array OpenCV (BGR).
   2. Denoise: `cv2.fastNlMeansDenoisingColored`.
   3. Koreksi cahaya/warna: CLAHE pada channel L (LAB color space).
   4. Face restoration + upscale: GFPGAN (`GFPGANer`, backbone RealESRGAN, `bg_upsampler` dimatikan — background KTM tidak relevan), `device='cuda'`.
   5. Resize final ke 450x750px, `cv2.resize` dengan `INTER_LANCZOS4`.
   6. Encode ke JPEG (mode RGB/24-bit, DPI 96x96 via `PIL.Image.save(..., dpi=(96,96))`, quality tinggi ~95).
   7. Return `bytes` JPEG final.
4. Simpan salinan lokal `local_output/{nim}_before.jpg` dan `local_output/{nim}_after.jpg` — **selalu**, baik dry-run maupun live.
5. Jika **bukan** dry-run: `write_foto2(nim, enhanced_bytes)`.
6. `log_result(nim, 'success')`, atau `'failed'` + pesan error jika ada exception di langkah manapun.

## Error Handling

- Setiap NIM diproses dalam `try/except` sendiri — kegagalan tidak menghentikan batch, lanjut ke NIM berikutnya.
- Satu koneksi DB dipakai untuk seluruh batch, tapi `commit()` dilakukan **per-NIM** (bukan di akhir), supaya interupsi di tengah jalan (Ctrl+C, crash) tidak menghilangkan hasil NIM yang sudah sukses. `rollback()` hanya untuk transaksi NIM yang gagal.
- Model GFPGAN di-load sekali di awal proses, dipakai ulang untuk semua NIM.

## CLI

```
python main.py                      # proses semua NIM pending, update DB
python main.py --dry-run            # proses semua, simpan ke local_output/, TIDAK update DB
python main.py --nim 20326030       # proses satu NIM saja
python main.py --limit 50           # proses maksimal 50 NIM
python main.py --retry-failed       # khusus proses ulang yang berstatus failed
```

Output progres per-NIM ke stdout, plus ringkasan sukses/gagal di akhir batch.

## Testing / Rencana Verifikasi

1. `pipeline.enhance()` dites terpisah dari DB memakai file JPEG yang sudah ada di folder `Download/` — cek output tepat 450x750px, mode RGB, ukuran file wajar, dan verifikasi visual before/after.
2. `db.py` dites dengan `--dry-run --nim <satu_nim>` untuk memastikan query & Large Object read/write benar sebelum menyentuh data lain.
3. Sampling representatif: `--dry-run --limit 20` mencakup foto gelap, buram, dan sudah bagus — review visual hasil di `local_output/`.
4. Full batch live (`python main.py` tanpa limit) setelah sampling oke — review ringkasan akhir, investigasi record `failed` satu per satu, lalu `--retry-failed` bila perlu.

## Keluar dari Cakupan (Out of Scope)

- UI/GUI — ini adalah CLI tool yang dijalankan manual di lokal.
- Proses otomatis terjadwal (cron/scheduler) — dijalankan manual oleh operator.
- Migrasi/perbaikan kredensial hardcode di `foto_single.py`/`foto_csv.py` yang sudah ada — di luar cakupan pekerjaan ini, hanya aplikasi baru yang memakai `.env`.
