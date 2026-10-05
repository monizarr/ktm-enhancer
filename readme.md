# Foto Postgre Downloader

## Installasi

Buat venv python

```bash
  py -m venv nama_venv
  .\nama_venv\Scripts\activate
```

Clone repository

```bash
  git clone url_repo
```

Install requirement

```bash
  pip install -r repo\requirements.txt
```

Project sudah siap dijalankan

```bash
  cd repo
  py foto_single.py
```

## Foto KTM Enhancer

Aplikasi CLI untuk meningkatkan kualitas foto KTM mahasiswa (denoise, koreksi cahaya, restorasi wajah GFPGAN, resize ke 450x750px), lalu menyimpan hasilnya ke kolom `foto2` di database. Lihat `docs/superpowers/specs/2026-08-11-foto-ktm-enhancer-design.md` untuk desain lengkap.

### Kebutuhan environment

`gfpgan`/`basicsr` (dependency untuk restorasi wajah) **tidak kompatibel dengan Python 3.13** (error `KeyError: '__version__'` saat build, disebabkan perubahan `locals()` di PEP 667). Gunakan **Python 3.12** khusus untuk menjalankan enhancer ini:

```bash
py -3.12 -m venv .venv-enhancer
.venv-enhancer\Scripts\activate
pip install -r requirements.txt
```

Jika venv dibuat di path yang sangat dalam/panjang (misal di dalam folder worktree bercabang banyak), instalasi `torch`/`basicsr` bisa gagal dengan error `WinError 206: filename too long`. Jika ini terjadi, buat venv di path yang lebih pendek (misal `C:\venvs\<nama-proyek>`).

Install PyTorch dengan CUDA (sesuaikan versi CUDA dari `nvidia-smi`, contoh untuk CUDA 12.4):

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

**Patch wajib:** `basicsr` (versi 1.4.2, rilis terakhir) masih mengimpor `torchvision.transforms.functional_tensor` yang sudah dihapus di torchvision versi baru. Setelah install, edit file `<venv>/Lib/site-packages/basicsr/data/degradations.py` baris 8, ubah:

```python
from torchvision.transforms.functional_tensor import rgb_to_grayscale
```

menjadi:

```python
from torchvision.transforms.functional import rgb_to_grayscale
```

Download model weight GFPGAN sebelum menjalankan:

```bash
python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth', 'enhancer/models/GFPGANv1.4.pth')"
```

Salin `.env.example` ke `.env` dan isi kredensial database sebelum menjalankan `main.py`.

## Cara Penggunaan

### Enhancer foto KTM (`main.py`)

Pastikan `.venv-enhancer` sudah aktif dan `.env` sudah diisi (lihat bagian instalasi di atas). `main.py` mensyaratkan GPU NVIDIA dengan CUDA aktif (dibutuhkan model GFPGAN) — kecuali untuk mode `--replace-foto1`.

Proses semua NIM yang belum berstatus `success` di `foto.enhancement_log`, lalu simpan hasilnya ke kolom `foto2`:

```bash
py main.py
```

Proses satu NIM saja:

```bash
py main.py --nim=20126001
```

Proses daftar NIM dari file CSV (kolom default `nim`; jika hanya nama file yang diberikan, dicari otomatis di folder `Input/`):

```bash
py main.py --csv=daftar_nim.csv
py main.py --csv=daftar_nim.csv --csv-column=NIM_MHS   # jika nama kolom berbeda
```

Isi `foto2` dengan salinan `foto1` dari database tanpa enhance (tidak butuh GPU; bisa digabung dengan `--nim`, `--angkatan`, `--limit`, `--dry-run`):

```bash
py main.py --csv susulan.csv --no-enhance
```

Batasi jumlah NIM yang diproses dalam satu jalan:

```bash
py main.py --limit=50
```

Ulangi hanya NIM yang sebelumnya gagal (status `failed`):

```bash
py main.py --retry-failed
```

Filter berdasarkan angkatan (2 digit tahun di NIM, contoh angkatan 2026 → NIM `%26___`):

```bash
py main.py --angkatan=2026
```

Dry run — jalankan seluruh proses (denoise, restorasi wajah, resize) dan simpan hasil before/after ke folder lokal `local_output/`, tanpa menulis ke kolom `foto2` di database:

```bash
py main.py --nim=20126001 --dry-run
```

Ganti `foto1` dan/atau `foto2` milik satu NIM secara manual dengan file gambar baru (lalu langsung keluar). Pilih kolom lewat flag; LO lama otomatis dihapus:

```bash
py main.py --replace-foto1 20126001 path\ke\foto_baru.jpg                  # hanya foto1
py main.py --replace-foto2 20126001 path\ke\foto_baru.jpg                  # hanya foto2
py main.py --replace-foto1 --replace-foto2 20126001 path\ke\foto_baru.jpg  # foto1 & foto2
```

Ganti massal lewat CSV: berikan file CSV (kolom `nim`, bisa diubah dengan `--csv-column`) dan folder foto. Setiap NIM di CSV diganti dengan file `<folder>\<nim>.jpeg`; NIM yang fotonya tidak ada atau tidak terdaftar di database dilewati dan dilaporkan di akhir:

```bash
py main.py --replace-foto1 --replace-foto2 Input\susulan.csv path\folder\foto
```

Tambahkan `--enhance` agar `foto2` diisi hasil enhance (hanya berlaku jika `--replace-foto2` dipakai; butuh GPU NVIDIA dengan CUDA aktif):

```bash
py main.py --replace-foto1 --replace-foto2 20126001 path\ke\foto_baru.jpg --enhance
```

Upload foto untuk NIM yang belum ada fotonya (mengisi `foto1` & `foto2` sekaligus, lalu langsung keluar). Jika NIM belum ada baris di database, baris baru otomatis dibuat berdasarkan NIM yang diberikan. Secara default, `foto1` dan `foto2` sama-sama diisi foto mentah tanpa enhance:

```bash
py main.py --upload 20126244 Input\asing\20126244.jpeg
```

Tambahkan `--enhance` agar `foto1` tetap diisi foto mentah, sementara `foto2` diisi hasil enhance (denoise, koreksi cahaya, restorasi wajah GFPGAN, resize). Mode ini membutuhkan GPU NVIDIA dengan CUDA aktif:

```bash
py main.py --upload 20126244 Input\asing\20126244.jpeg --enhance
```

Upload foto baru per kolom dengan `--upload-foto1` dan/atau `--upload-foto2`. Bedanya dengan `--replace-foto*`: jika NIM belum ada di database, baris baru otomatis dibuat. Bisa untuk satu NIM atau massal lewat CSV (file `<folder>\<nim>.jpeg`, NIM yang fotonya tidak ada dilewati dan dilaporkan di akhir):

```bash
py main.py --upload-foto1 --upload-foto2 20126244 Input\asing\20126244.jpeg
py main.py --upload-foto1 --upload-foto2 Input\susulan.csv path\folder\foto
py main.py --upload-foto1 --upload-foto2 Input\susulan.csv path\folder\foto --enhance
```

### Versi web (`web/`)

Antarmuka web lokal untuk enhance per NIM: cari NIM, lihat `foto1` dan `foto2` berdampingan, klik **Enhance foto1** untuk membuat preview, lalu **Simpan ke foto2** (atau **Batal**). Preview belum ditulis ke database sampai tombol Simpan diklik. `foto1` tidak pernah diubah. Saat disimpan, `foto2` lama dihapus dan NIM dicatat `success` di `foto.enhancement_log`.

Fitur lain di halaman yang sama:

- **Upload foto1**: jika NIM belum punya `foto1`, bingkai foto1 berubah menjadi area upload (klik atau seret file JPEG/PNG, maks 15 MB; PNG dikonversi ke JPEG). Jika NIM belum terdaftar, baris baru dibuat otomatis. Upload ditolak jika `foto1` sudah ada, jadi `foto1` tidak pernah tertimpa.
- **Salin tanpa enhance**: isi `foto2` dengan salinan `foto1` apa adanya (sama seperti `--no-enhance` di CLI, tidak butuh GPU). Jika `foto2` sudah terisi, tombol perlu diklik dua kali sebagai konfirmasi.

Pintasan keyboard: `/` cari NIM, `U` upload foto1, `E` enhance, `K` salin tanpa enhance, `S` simpan preview, `Esc` batal, tahan `C` untuk membandingkan preview dengan foto asli.

#### Upload massal (`/massal`)

Buka menu **Massal** untuk mengunggah banyak foto sekaligus:

1. Klik **Pilih foto** / **Pilih folder**, atau seret foto/folder ke halaman. Nama file harus NIM berupa angka (`20126001.jpg`, JPEG/PNG, maks 15 MB). File lain dilewati dan dilaporkan di bagian "file dilewati".
2. Foto tampil sebagai lembar kontak beserta status di database (`NIM baru`, atau `f1 ✓/–  f2 ✓/–`). Setiap foto punya tombol **foto1** dan **foto2** untuk memilih kolom tujuan. Secara default hanya kolom yang masih kosong yang dipilih; kolom yang sudah terisi ditandai **timpa** jika dipilih. Gunakan pilihan cepat *Yang kosong / Semua / Tidak* dan filter *NIM baru / Menimpa / Gagal* di toolbar.
3. Aktifkan **Enhance foto2** jika foto2 harus diisi hasil enhance (foto1 tetap foto asli; butuh GPU). Tanpa opsi ini foto1 dan foto2 diisi foto asli.
4. Klik **Proses N foto**. Jika ada foto yang akan menimpa data lama, tombol perlu diklik sekali lagi sebagai konfirmasi. Progres tampil per foto; NIM yang belum terdaftar dibuat otomatis. Setiap NIM diproses dalam satu transaksi: jika gagal (misalnya enhance error), foto1 dan foto2 NIM itu tidak ada yang tersimpan.

Foto yang diunggah hanya disimpan di memori server sampai diproses atau dikeluarkan (tombol × atau **Bersihkan selesai**), dan hilang jika server dimatikan.

```bash
pip install -r requirements.txt   # sekali saja, untuk fastapi/uvicorn/jinja2
py -m web
```

Lalu buka http://127.0.0.1:8000 di browser. Server hanya bisa diakses dari PC ini (tidak dari komputer lain di jaringan). Enhance membutuhkan GPU NVIDIA dengan CUDA aktif; model GFPGAN dimuat saat enhance pertama, jadi klik pertama lebih lama. Tekan `Ctrl+C` di terminal untuk menghentikan server.

### Resize & encode foto KTM (`encode.py`)

Resize sebuah foto ke ukuran final 372x490px, simpan ke `Output/`, dan cetak hasil base64-nya:

```bash
py encode.py path\ke\foto.jpg
```

Kembalikan `foto2` seorang mahasiswa ke foto mentah (raw) yang tersimpan di `Input/raw/<nim>.jpg`:

```bash
py encode.py 20126001 --restore
```

### Download foto dari database (`foto_single.py`, `foto_csv.py`)

Skrip lama untuk mengunduh `foto1`/`foto2` sebagai file JPEG ke folder lokal (`Download/` atau `Output/`). Belum berbentuk CLI — NIM dan kredensial database (host, user, password) di-hardcode di dalam file, jadi edit dulu nilainya di source code sebelum dijalankan:

```bash
py foto_single.py   # unduh 1 NIM yang di-hardcode di dalam file, simpan ke Download/
py foto_csv.py       # unduh banyak NIM dari Input/md_foto.csv, simpan ke Output/
```

> Catatan: kredensial database di kedua skrip ini di-hardcode dengan host `10.10.3.6`, berbeda dari host di `.env` (`192.168.151.24`). Sesuaikan dulu jika servernya sudah pindah.
