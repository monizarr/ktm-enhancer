import os
import time
from urllib.parse import urlencode

from fastapi import FastAPI, Form, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from enhancer.db import (
    connect_db,
    fetch_foto1,
    fetch_foto2,
    insert_nim,
    log_result,
    nim_exists,
    replace_foto1,
    replace_foto2,
)
from enhancer.pipeline import enhance
from web.batch import router as batch_router
from web.core import WEB_DIR, MAX_UPLOAD_BYTES, buat_templates, check_nim, get_restorer, gpu_lock, to_jpeg

app = FastAPI(title="Foto KTM Enhancer")
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")
templates = buat_templates()
app.include_router(batch_router)

# Hasil enhance yang belum disimpan, per NIM. Hanya di memori (aplikasi lokal, satu pengguna).
previews = {}
preview_settings = {}
FILTER_CONTROLS = [
    ("brightness", "Brightness", -80, 80, 1, 0),
    ("contrast", "Kontras", 0.5, 2, 0.05, 1),
    ("smoothness", "Smoothness", 0, 20, 1, 10),
    ("saturation", "Saturasi", 0, 2, 0.05, 1),
    ("sharpness", "Ketajaman", 0, 2, 0.1, 0),
    ("lighting", "Koreksi cahaya otomatis", 0, 4, 0.1, 2),
]


def redirect_home(nim, pesan=None, jenis="info"):
    params = {"nim": nim}
    if pesan:
        params["pesan"] = pesan
        params["jenis"] = jenis
    return RedirectResponse(f"/?{urlencode(params)}", status_code=303)


def jpeg(data):
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/")
def index(request: Request, nim: str = "", pesan: str = "", jenis: str = "info"):
    if jenis not in ("info", "ok", "gagal"):
        jenis = "info"
    context = {
        "filter_controls": FILTER_CONTROLS,
        "settings": preview_settings.get(nim.strip(), {}),
        "nim": "", "pesan": pesan, "jenis": jenis, "terdaftar": False,
        "ada_foto1": False, "ada_foto2": False, "ada_preview": False,
    }
    if nim.strip():
        nim = check_nim(nim)
        conn = connect_db()
        try:
            context["terdaftar"] = nim_exists(conn, nim)
            context["ada_foto1"] = fetch_foto1(conn, nim) is not None
            context["ada_foto2"] = fetch_foto2(conn, nim) is not None
        finally:
            conn.close()
        context["nim"] = nim
        context["ada_preview"] = nim in previews
        context["v"] = int(time.time())
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/foto/{nim}/{kolom}")
def foto(nim: str, kolom: str):
    nim = check_nim(nim)
    if kolom not in ("foto1", "foto2"):
        raise HTTPException(status_code=404)
    conn = connect_db()
    try:
        data = fetch_foto1(conn, nim) if kolom == "foto1" else fetch_foto2(conn, nim)
    finally:
        conn.close()
    if data is None:
        raise HTTPException(status_code=404, detail=f"{kolom} kosong")
    return jpeg(data)


@app.get("/preview/{nim}")
def preview(nim: str):
    nim = check_nim(nim)
    if nim not in previews:
        raise HTTPException(status_code=404, detail="Belum ada preview")
    return jpeg(previews[nim])


@app.post("/enhance/{nim}")
def enhance_nim(
    nim: str,
    brightness: float = Form(0, ge=-80, le=80, allow_inf_nan=False),
    contrast: float = Form(1, ge=0.5, le=2, allow_inf_nan=False),
    smoothness: float = Form(10, ge=0, le=20, allow_inf_nan=False),
    saturation: float = Form(1, ge=0, le=2, allow_inf_nan=False),
    sharpness: float = Form(0, ge=0, le=2, allow_inf_nan=False),
    lighting: float = Form(2, ge=0, le=4, allow_inf_nan=False),
):
    nim = check_nim(nim)
    conn = connect_db()
    try:
        before = fetch_foto1(conn, nim)
    finally:
        conn.close()
    if before is None:
        return redirect_home(nim, "foto1 kosong, tidak ada yang bisa di-enhance", "gagal")

    try:
        with gpu_lock:
            settings = dict(brightness=brightness, contrast=contrast, smoothness=smoothness,
                            saturation=saturation, sharpness=sharpness, lighting=lighting)
            previews[nim] = enhance(before, get_restorer(), **settings)
            preview_settings[nim] = settings
    except Exception as exc:  # noqa: BLE001 - tampilkan error ke pengguna, jangan crash server
        return redirect_home(nim, f"Enhance gagal: {exc}", "gagal")
    return redirect_home(nim, "Preview siap. Periksa lalu klik Simpan ke foto2.")


@app.post("/simpan/{nim}")
def simpan(nim: str):
    nim = check_nim(nim)
    if nim not in previews:
        return redirect_home(nim, "Tidak ada preview untuk disimpan")

    conn = connect_db()
    try:
        # replace_foto2 hanya mengubah kolom foto2; foto1 tidak disentuh
        if not replace_foto2(conn, nim, previews[nim]):
            conn.rollback()
            return redirect_home(nim, "NIM tidak ditemukan di database", "gagal")
        log_result(conn, nim, "success")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    del previews[nim]
    preview_settings.pop(nim, None)
    return redirect_home(nim, "foto2 berhasil disimpan", "ok")


@app.post("/batal/{nim}")
def batal(nim: str):
    nim = check_nim(nim)
    previews.pop(nim, None)
    preview_settings.pop(nim, None)
    return redirect_home(nim, "Preview dibatalkan")


@app.post("/upload-foto1/{nim}")
async def upload_foto1(nim: str, file: UploadFile = File(...)):
    nim = check_nim(nim)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        return redirect_home(nim, "File kosong", "gagal")
    if len(data) > MAX_UPLOAD_BYTES:
        return redirect_home(nim, "File terlalu besar (maks 15 MB)", "gagal")
    try:
        data = to_jpeg(data)
    except ValueError as exc:
        return redirect_home(nim, str(exc), "gagal")

    conn = connect_db()
    try:
        # Hanya untuk NIM yang belum punya foto1: foto1 yang sudah ada tidak boleh tertimpa
        if fetch_foto1(conn, nim) is not None:
            return redirect_home(nim, "foto1 sudah ada, upload dibatalkan", "gagal")
        baru = not nim_exists(conn, nim)
        insert_nim(conn, nim)
        if not replace_foto1(conn, nim, data):
            conn.rollback()
            return redirect_home(nim, "Gagal menyimpan foto1", "gagal")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    pesan = "foto1 berhasil diupload" + (" (NIM baru ditambahkan)" if baru else "")
    return redirect_home(nim, pesan, "ok")


@app.post("/salin/{nim}")
def salin(nim: str):
    """Isi foto2 dengan salinan foto1 apa adanya (tanpa enhance). foto1 tidak diubah."""
    nim = check_nim(nim)
    conn = connect_db()
    try:
        data = fetch_foto1(conn, nim)
        if data is None:
            return redirect_home(nim, "foto1 kosong, tidak ada yang bisa disalin", "gagal")
        if not replace_foto2(conn, nim, data):
            conn.rollback()
            return redirect_home(nim, "NIM tidak ditemukan di database", "gagal")
        log_result(conn, nim, "success")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return redirect_home(nim, "foto2 diisi salinan foto1 (tanpa enhance)", "ok")



def redirect_manual(nim="", pesan="", jenis="info"):
    return RedirectResponse("/upload-manual?" + urlencode(
        dict(nim=nim, pesan=pesan, jenis=jenis)), status_code=303)


@app.get("/upload-manual")
def manual_page(request: Request, nim: str = "", pesan: str = "", jenis: str = "info"):
    context = dict(halaman="manual", nim="", pesan=pesan,
                   jenis=jenis if jenis in ("info", "ok", "gagal") else "info",
                   terdaftar=False, ada_foto1=False, ada_foto2=False, v=time.time_ns())
    if nim.strip():
        nim = check_nim(nim)
        context["nim"] = nim
        try:
            conn = connect_db()
            try:
                context["terdaftar"] = nim_exists(conn, nim)
                context["ada_foto1"] = fetch_foto1(conn, nim) is not None
                context["ada_foto2"] = fetch_foto2(conn, nim) is not None
            finally:
                conn.close()
        except Exception:
            context.update(pesan="Database belum dapat diakses. Coba lagi nanti.", jenis="gagal")
    return templates.TemplateResponse(request, "manual.html", context)


@app.post("/upload-manual")
async def manual_upload(nim: str = Form(...), kolom: str = Form(...),
                        file: UploadFile = File(...), timpa: bool = Form(False)):
    nim = check_nim(nim)
    if kolom not in ("foto1", "foto2", "keduanya"):
        raise HTTPException(status_code=400, detail="Pilih foto1, foto2, atau keduanya")
    targets = ("foto1", "foto2") if kolom == "keduanya" else (kolom,)
    tujuan = " dan ".join(targets)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not data or len(data) > MAX_UPLOAD_BYTES:
        return redirect_manual(nim, "File kosong atau melebihi batas 15 MB", "gagal")
    try:
        data = to_jpeg(data, allowed_formats=("JPEG", "PNG"))
    except ValueError as exc:
        return redirect_manual(nim, str(exc), "gagal")
    try:
        conn = connect_db()
        try:
            insert_nim(conn, nim)
            # Serialisasi pemeriksaan dan penimpaan untuk NIM yang sama.
            with conn.cursor() as cursor:
                cursor.execute("SELECT nim FROM foto.md_foto WHERE nim = %s FOR UPDATE", (nim,))
            occupied = []
            for target in targets:
                fetch = fetch_foto1 if target == "foto1" else fetch_foto2
                if fetch(conn, nim) is not None:
                    occupied.append(target)
            if occupied and not timpa:
                conn.rollback()
                return redirect_manual(nim, f"{' dan '.join(occupied)} sudah terisi. Centang izin timpa dan pilih file lagi jika ingin menggantinya.", "gagal")
            for target in targets:
                replace = replace_foto1 if target == "foto1" else replace_foto2
                if not replace(conn, nim, data):
                    raise ValueError("NIM tidak ditemukan")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception:
        return redirect_manual(nim, "Upload gagal. Periksa koneksi database lalu coba lagi.", "gagal")
    # Preview lama tidak boleh disimpan setelah foto sumber/tujuan diganti.
    previews.pop(nim, None)
    preview_settings.pop(nim, None)
    return redirect_manual(nim, f"Foto berhasil diupload ke {tujuan} tanpa filter", "ok")
