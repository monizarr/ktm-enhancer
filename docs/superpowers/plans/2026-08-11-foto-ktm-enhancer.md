# Foto KTM Enhancer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python CLI that reads student photos from `foto1` (Large Object) in PostgreSQL, runs them through a denoise → lighting-correction → GFPGAN face-restoration → resize pipeline, and writes the result back to `foto2`, with dry-run mode, local before/after backups, and a status log table for resumability.

**Architecture:** A small `enhancer/` package with two independent modules — `db.py` (all SQL/Large Object access, credentials from `.env`) and `pipeline.py` (pure image transform, no DB dependency, independently testable with local JPEG files) — orchestrated by a top-level `main.py` CLI. A new `foto.enhancement_log` table tracks per-NIM success/failure so batches are resumable and idempotent.

**Tech Stack:** Python, psycopg2-binary, python-dotenv, OpenCV (`opencv-python`), Pillow, NumPy, GFPGAN (with PyTorch/CUDA), pytest + unittest.mock for tests that don't require a live DB or GPU.

**Reference spec:** `docs/superpowers/specs/2026-08-11-foto-ktm-enhancer-design.md`

---

## Before You Start

This plan assumes:
- Windows machine with an NVIDIA GPU and CUDA-capable driver already installed (confirmed by the user).
- Python 3.9+ available (check with `python --version`).
- Network access to download the GFPGAN model weights (~332MB) and PyTorch.
- Access to the existing PostgreSQL instance at `10.10.3.6` with the same credentials used in `foto_single.py`.

**PyTorch with CUDA note:** `pip install torch` on Windows without extra flags often installs a CPU-only build. Before Task 5, go to https://pytorch.org/get-started/locally/, select your OS / CUDA version, and run the exact `pip install torch torchvision --index-url ...` command it gives you. Verify afterward with:
```bash
python -c "import torch; print(torch.cuda.is_available())"
```
Expected: `True`. If `False`, stop and fix the PyTorch install before continuing to Task 5 — the pipeline will still run on CPU but far slower than designed.

---

### Task 1: Project scaffolding & configuration

**Files:**
- Create: `enhancer/__init__.py`
- Create: `enhancer/models/.gitkeep`
- Modify: `requirements.txt`
- Create: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Create the package folders**

```bash
mkdir -p enhancer/models local_output
touch enhancer/__init__.py enhancer/models/.gitkeep
```

- [ ] **Step 2: Update `requirements.txt`**

Replace its contents with:
```
psycopg2-binary
python-dotenv
opencv-python
numpy
Pillow
gfpgan
pytest
```
(`torch`/`torchvision` intentionally excluded — installed separately per the CUDA-specific command above. `gfpgan` will pull in `basicsr`, `facexlib`, `realesrgan`, `tqdm` automatically.)

- [ ] **Step 3: Create `.env.example`**

```
PGFOTO_DB_NAME=dbstain
PGFOTO_DB_USER=taqiem
PGFOTO_DB_PASSWORD=changeme
PGFOTO_DB_HOST=10.10.3.6
PGFOTO_DB_PORT=5432
```

Then create your real `.env` (not committed) with the actual password:
```bash
cp .env.example .env
```
Edit `.env` and fill in `PGFOTO_DB_PASSWORD` with the real value.

- [ ] **Step 4: Update `.gitignore`**

Add these lines to the existing `.gitignore`:
```
.env
local_output/
enhancer/models/*.pth
```

- [ ] **Step 5: Install base dependencies**

```bash
pip install -r requirements.txt
```
Expected: installs without error (this does not yet include PyTorch — that's Task 5).

- [ ] **Step 6: Commit**

```bash
git add enhancer/__init__.py enhancer/models/.gitkeep requirements.txt .env.example .gitignore
git commit -m "Scaffold enhancer package structure and config"
```

---

### Task 2: `db.py` — connection and pending-NIM query

**Files:**
- Create: `enhancer/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/__init__.py` (empty) and `tests/test_db.py`:

```python
from unittest.mock import MagicMock
from enhancer.db import get_pending_nims


def _mock_conn(fetchall_return):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall_return
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_get_pending_nims_default_excludes_success():
    conn, cursor = _mock_conn([("111",), ("222",)])
    result = get_pending_nims(conn)
    assert result == ["111", "222"]
    sql = cursor.execute.call_args[0][0]
    assert "NOT IN" in sql
    assert "status = 'success'" in sql


def test_get_pending_nims_retry_failed_only():
    conn, cursor = _mock_conn([("333",)])
    result = get_pending_nims(conn, retry_failed_only=True)
    assert result == ["333"]
    sql = cursor.execute.call_args[0][0]
    assert "status = 'failed'" in sql


def test_get_pending_nims_with_limit_passes_param():
    conn, cursor = _mock_conn([])
    get_pending_nims(conn, limit=50)
    sql, params = cursor.execute.call_args[0]
    assert "LIMIT" in sql
    assert params == (50,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enhancer.db'`

- [ ] **Step 3: Implement `enhancer/db.py` (connection + pending query only for now)**

```python
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def connect_db():
    return psycopg2.connect(
        dbname=os.environ["PGFOTO_DB_NAME"],
        user=os.environ["PGFOTO_DB_USER"],
        password=os.environ["PGFOTO_DB_PASSWORD"],
        host=os.environ["PGFOTO_DB_HOST"],
        port=os.environ["PGFOTO_DB_PORT"],
        options="-c search_path=foto",
    )


def get_pending_nims(conn, limit=None, retry_failed_only=False):
    if retry_failed_only:
        query = (
            "SELECT nim FROM foto.md_foto "
            "WHERE nim IN (SELECT nim FROM foto.enhancement_log WHERE status = 'failed') "
            "ORDER BY nim"
        )
    else:
        query = (
            "SELECT nim FROM foto.md_foto "
            "WHERE nim NOT IN (SELECT nim FROM foto.enhancement_log WHERE status = 'success') "
            "ORDER BY nim"
        )

    params = None
    if limit is not None:
        query += " LIMIT %s"
        params = (limit,)

    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return [row[0] for row in cursor.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add enhancer/db.py tests/__init__.py tests/test_db.py
git commit -m "Add db connection and pending-NIM query with mocked tests"
```

---

### Task 3: `db.py` — fetch, write-back, and logging

**Files:**
- Modify: `enhancer/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_fetch_foto1_returns_bytes():
    from enhancer.db import fetch_foto1

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (42,)
    conn.cursor.return_value.__enter__.return_value = cursor
    lob = MagicMock()
    lob.read.return_value = b"jpegbytes"
    conn.lobject.return_value = lob

    result = fetch_foto1(conn, "111")

    assert result == b"jpegbytes"
    conn.lobject.assert_called_once_with(42, "rb")


def test_fetch_foto1_returns_none_when_no_row():
    from enhancer.db import fetch_foto1

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    conn.cursor.return_value.__enter__.return_value = cursor

    assert fetch_foto1(conn, "111") is None


def test_fetch_foto1_returns_none_when_foto1_null():
    from enhancer.db import fetch_foto1

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (None,)
    conn.cursor.return_value.__enter__.return_value = cursor

    assert fetch_foto1(conn, "111") is None


def test_write_foto2_creates_lobject_and_updates_row():
    from enhancer.db import write_foto2

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    lob = MagicMock()
    lob.oid = 999
    conn.lobject.return_value = lob

    write_foto2(conn, "111", b"newbytes")

    conn.lobject.assert_called_once_with(0, "wb")
    lob.write.assert_called_once_with(b"newbytes")
    sql, params = cursor.execute.call_args[0]
    assert "UPDATE foto.md_foto SET foto2" in sql
    assert params == (999, "111")


def test_log_result_upserts():
    from enhancer.db import log_result

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    log_result(conn, "111", "failed", "foto1 kosong")

    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (nim) DO UPDATE" in sql
    assert params == ("111", "failed", "foto1 kosong")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_foto1'`

- [ ] **Step 3: Add the functions to `enhancer/db.py`**

Append to `enhancer/db.py`:

```python
def fetch_foto1(conn, nim):
    with conn.cursor() as cursor:
        cursor.execute("SELECT foto1 FROM foto.md_foto WHERE nim = %s", (nim,))
        result = cursor.fetchone()

    if result is None or result[0] is None:
        return None

    lo = conn.lobject(result[0], "rb")
    data = lo.read()
    lo.close()
    return data


def write_foto2(conn, nim, image_bytes):
    lo = conn.lobject(0, "wb")
    lo.write(image_bytes)
    new_oid = lo.oid
    lo.close()

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE foto.md_foto SET foto2 = %s WHERE nim = %s",
            (new_oid, nim),
        )


def log_result(conn, nim, status, error_message=None):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO foto.enhancement_log (nim, status, error_message, processed_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (nim) DO UPDATE
            SET status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                processed_at = EXCLUDED.processed_at
            """,
            (nim, status, error_message),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add enhancer/db.py tests/test_db.py
git commit -m "Add fetch_foto1, write_foto2, log_result to db module"
```

---

### Task 4: `pipeline.py` — pure image transforms (no model)

**Files:**
- Create: `enhancer/pipeline.py`
- Test: `tests/test_pipeline.py`
- Test fixture: copy `Download/20326030.jpeg` to `tests/fixtures/sample.jpg`

- [ ] **Step 1: Copy a real sample photo into test fixtures**

```bash
mkdir -p tests/fixtures
cp Download/20326030.jpeg tests/fixtures/sample.jpg
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
import numpy as np

from enhancer.pipeline import (
    TARGET_SIZE,
    decode_jpeg,
    denoise,
    correct_lighting,
    resize_final,
    encode_jpeg,
)


def _load_sample():
    with open("tests/fixtures/sample.jpg", "rb") as f:
        return f.read()


def test_decode_jpeg_returns_bgr_array():
    img = decode_jpeg(_load_sample())
    assert isinstance(img, np.ndarray)
    assert img.ndim == 3
    assert img.shape[2] == 3


def test_denoise_preserves_shape():
    img = decode_jpeg(_load_sample())
    result = denoise(img)
    assert result.shape == img.shape


def test_correct_lighting_preserves_shape():
    img = decode_jpeg(_load_sample())
    result = correct_lighting(img)
    assert result.shape == img.shape


def test_resize_final_produces_target_dimensions():
    img = decode_jpeg(_load_sample())
    result = resize_final(img)
    height, width = result.shape[:2]
    assert (width, height) == TARGET_SIZE


def test_encode_jpeg_roundtrip_decodable():
    img = decode_jpeg(_load_sample())
    resized = resize_final(img)
    encoded = encode_jpeg(resized)
    assert isinstance(encoded, bytes)
    decoded_again = decode_jpeg(encoded)
    height, width = decoded_again.shape[:2]
    assert (width, height) == TARGET_SIZE
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enhancer.pipeline'`

- [ ] **Step 4: Implement `enhancer/pipeline.py` (transforms only, no GFPGAN yet)**

```python
import io

import cv2
import numpy as np
from PIL import Image

TARGET_SIZE = (450, 750)  # (width, height)


def decode_jpeg(image_bytes):
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def denoise(img):
    return cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)


def correct_lighting(img):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    lab = cv2.merge((l_channel, a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def resize_final(img):
    return cv2.resize(img, TARGET_SIZE, interpolation=cv2.INTER_LANCZOS4)


def encode_jpeg(img_bgr):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=95, dpi=(96, 96))
    return buf.getvalue()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add enhancer/pipeline.py tests/test_pipeline.py tests/fixtures/sample.jpg
git commit -m "Add pure image transform functions for enhancement pipeline"
```

---

### Task 5: `pipeline.py` — GFPGAN face restoration + full `enhance()`

This task needs PyTorch with CUDA installed (see "Before You Start") and downloads a ~332MB model file, so its verification is manual rather than an automated pytest run.

**Files:**
- Modify: `enhancer/pipeline.py`

- [ ] **Step 1: Download the GFPGAN model weights**

```bash
python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth', 'enhancer/models/GFPGANv1.4.pth')"
```
Expected: `enhancer/models/GFPGANv1.4.pth` exists and is roughly 332MB (`ls -la enhancer/models/`).

- [ ] **Step 2: Install GFPGAN and PyTorch (if not already done per "Before You Start")**

```bash
pip install gfpgan
python -c "import torch; print(torch.cuda.is_available())"
```
Expected: `True`. If `False`, stop and reinstall PyTorch with the correct CUDA index URL before continuing.

- [ ] **Step 3: Add `load_restorer` and `restore_face` to `enhancer/pipeline.py`**

Append to `enhancer/pipeline.py`:

```python
def load_restorer(model_path, device="cuda"):
    from gfpgan import GFPGANer

    return GFPGANer(
        model_path=model_path,
        upscale=2,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,
        device=device,
    )


def restore_face(img, restorer):
    _, _, restored_img = restorer.enhance(
        img, has_aligned=False, only_center_face=False, paste_back=True
    )
    return restored_img


def enhance(image_bytes, restorer):
    img = decode_jpeg(image_bytes)
    img = denoise(img)
    img = correct_lighting(img)
    img = restore_face(img, restorer)
    img = resize_final(img)
    return encode_jpeg(img)
```

- [ ] **Step 4: Manually verify against the real sample photo**

```bash
python -c "
from enhancer.pipeline import load_restorer, enhance

restorer = load_restorer('enhancer/models/GFPGANv1.4.pth')
with open('tests/fixtures/sample.jpg', 'rb') as f:
    original = f.read()
result = enhance(original, restorer)
with open('local_output/manual_check_after.jpg', 'wb') as f:
    f.write(result)
print('done, bytes:', len(result))
"
```
Expected: runs without error (facexlib may auto-download a small face-detection model on first run — that's expected and only happens once), prints a byte count, and `local_output/manual_check_after.jpg` opens as a sharper, upscaled 450x750 version of `tests/fixtures/sample.jpg`. Open both files and visually compare.

- [ ] **Step 5: Commit**

```bash
git add enhancer/pipeline.py
git commit -m "Add GFPGAN face restoration and full enhance() pipeline"
```

(Do not commit `enhancer/models/GFPGANv1.4.pth` — it's excluded by `.gitignore` from Task 1.)

---

### Task 6: `main.py` — CLI orchestrator

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
from unittest.mock import MagicMock, patch

from main import process_nim


@patch("main.log_result")
@patch("main.write_foto2")
@patch("main.save_local")
@patch("main.enhance")
@patch("main.fetch_foto1")
def test_process_nim_dry_run_skips_write_foto2(
    mock_fetch, mock_enhance, mock_save_local, mock_write_foto2, mock_log_result
):
    conn = MagicMock()
    mock_fetch.return_value = b"before"
    mock_enhance.return_value = b"after"

    ok, error = process_nim(conn, "111", restorer=MagicMock(), dry_run=True)

    assert ok is True
    assert error is None
    mock_save_local.assert_called_once_with("111", b"before", b"after")
    mock_write_foto2.assert_not_called()
    mock_log_result.assert_called_once_with(conn, "111", "success")


@patch("main.log_result")
@patch("main.write_foto2")
@patch("main.save_local")
@patch("main.enhance")
@patch("main.fetch_foto1")
def test_process_nim_live_run_calls_write_foto2(
    mock_fetch, mock_enhance, mock_save_local, mock_write_foto2, mock_log_result
):
    conn = MagicMock()
    mock_fetch.return_value = b"before"
    mock_enhance.return_value = b"after"

    ok, error = process_nim(conn, "111", restorer=MagicMock(), dry_run=False)

    assert ok is True
    mock_write_foto2.assert_called_once_with(conn, "111", b"after")
    mock_log_result.assert_called_once_with(conn, "111", "success")


@patch("main.log_result")
@patch("main.enhance")
@patch("main.fetch_foto1")
def test_process_nim_skips_when_foto1_missing(mock_fetch, mock_enhance, mock_log_result):
    conn = MagicMock()
    mock_fetch.return_value = None

    ok, error = process_nim(conn, "111", restorer=MagicMock(), dry_run=True)

    assert ok is False
    assert error == "foto1 kosong"
    mock_enhance.assert_not_called()
    mock_log_result.assert_called_once_with(conn, "111", "failed", "foto1 kosong")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Implement `main.py`**

```python
import argparse
import os

from enhancer.db import (
    connect_db,
    fetch_foto1,
    get_pending_nims,
    log_result,
    write_foto2,
)
from enhancer.pipeline import enhance, load_restorer

LOCAL_OUTPUT_DIR = "local_output"
MODEL_PATH = os.path.join("enhancer", "models", "GFPGANv1.4.pth")


def save_local(nim, before_bytes, after_bytes):
    os.makedirs(LOCAL_OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_OUTPUT_DIR, f"{nim}_before.jpg"), "wb") as f:
        f.write(before_bytes)
    with open(os.path.join(LOCAL_OUTPUT_DIR, f"{nim}_after.jpg"), "wb") as f:
        f.write(after_bytes)


def process_nim(conn, nim, restorer, dry_run):
    before_bytes = fetch_foto1(conn, nim)
    if before_bytes is None:
        log_result(conn, nim, "failed", "foto1 kosong")
        return False, "foto1 kosong"

    after_bytes = enhance(before_bytes, restorer)
    save_local(nim, before_bytes, after_bytes)

    if not dry_run:
        write_foto2(conn, nim, after_bytes)

    log_result(conn, nim, "success")
    return True, None


def main():
    parser = argparse.ArgumentParser(description="Peningkatan kualitas foto KTM mahasiswa")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--nim", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    conn = connect_db()
    restorer = load_restorer(MODEL_PATH)

    if args.nim:
        nims = [args.nim]
    else:
        nims = get_pending_nims(conn, limit=args.limit, retry_failed_only=args.retry_failed)

    total = len(nims)
    success_count = 0
    failed_count = 0

    for i, nim in enumerate(nims, start=1):
        try:
            ok, error = process_nim(conn, nim, restorer, args.dry_run)
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - any failure for this NIM must not abort the batch
            conn.rollback()
            log_result(conn, nim, "failed", str(exc))
            conn.commit()
            ok, error = False, str(exc)

        if ok:
            success_count += 1
            print(f"[{i}/{total}] {nim} ... OK")
        else:
            failed_count += 1
            print(f"[{i}/{total}] {nim} ... FAILED: {error}")

    conn.close()
    print(f"\nSelesai. Sukses: {success_count}, Gagal: {failed_count}, Total: {total}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests across `test_db.py`, `test_pipeline.py`, `test_main.py` pass.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Add main.py CLI orchestrator with dry-run and retry support"
```

---

### Task 7: Database migration and end-to-end manual verification

**Files:**
- Create: `docs/superpowers/specs/enhancement_log.sql` (the migration, kept for reference/reruns)

- [ ] **Step 1: Save the migration SQL**

Create `docs/superpowers/specs/enhancement_log.sql`:

```sql
CREATE TABLE foto.enhancement_log (
    nim VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL,
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT now()
);
```

- [ ] **Step 2: Run the migration against the real database**

```bash
python -c "
from enhancer.db import connect_db
conn = connect_db()
with conn.cursor() as cur:
    with open('docs/superpowers/specs/enhancement_log.sql') as f:
        cur.execute(f.read())
conn.commit()
conn.close()
print('enhancement_log table created')
"
```
Expected: prints confirmation, no errors. If the table already exists, this will error — that's fine, it means this step was already done.

- [ ] **Step 3: Dry-run a single known NIM**

```bash
python main.py --dry-run --nim 20326030
```
Expected: prints `[1/1] 20326030 ... OK`, creates `local_output/20326030_before.jpg` and `local_output/20326030_after.jpg`. Open both and visually confirm the "after" image is sharper/cleaner and exactly 450x750px, and that `foto2` in the database is still unchanged (dry-run).

- [ ] **Step 4: Dry-run a small representative sample**

```bash
python main.py --dry-run --limit 20
```
Expected: processes 20 NIMs, prints a per-NIM OK/FAILED line and a final summary. Review the `local_output/` before/after pairs for a mix of dark, blurry, and already-good photos to confirm quality holds up across conditions.

- [ ] **Step 5: Full live batch**

Once satisfied with the sample:
```bash
python main.py
```
Expected: processes all ~2355 pending NIMs, updates `foto2` for each success, prints a final summary like `Selesai. Sukses: 2340, Gagal: 15, Total: 2355`.

- [ ] **Step 6: Investigate and retry failures**

```sql
SELECT nim, error_message, processed_at FROM foto.enhancement_log WHERE status = 'failed';
```
For each failure, check the reason (e.g. `foto1 kosong`, corrupt image, transient DB error). Once underlying issues are understood/fixed, retry just the failed ones:
```bash
python main.py --retry-failed
```

- [ ] **Step 7: Commit the migration reference file**

```bash
git add docs/superpowers/specs/enhancement_log.sql
git commit -m "Add enhancement_log migration SQL for reference"
```

---

## Plan Self-Review Notes

- **Spec coverage:** architecture/components (Task 1, 2, 3), pipeline order denoise→CLAHE→GFPGAN→resize (Task 4, 5), CLI flags `--dry-run`/`--nim`/`--limit`/`--retry-failed` (Task 6), error handling with per-NIM try/except and per-NIM commit (Task 6 `main()`), local before/after backups (Task 6 `save_local`), `enhancement_log` table and SQL-injection fix via parameterized queries (Task 2, 3, 7), testing plan (Tasks 2-6 automated, Task 5 and 7 manual/GPU/DB) — all covered.
- **Out of scope confirmed:** no GUI, no scheduler, no changes to existing `foto_single.py`/`foto_csv.py` — none of the tasks above touch those files.
