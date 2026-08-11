
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
