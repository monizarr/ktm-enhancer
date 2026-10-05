"""Upload massal: foto bernama <nim>.jpg diunggah ke meja (memori), dipilih per foto
untuk foto1 dan/atau foto2, lalu diproses di latar belakang (opsional enhance foto2)."""

import itertools
import os
import re
import threading

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from enhancer.db import (
    connect_db,
    foto_status,
    insert_nim,
    log_result,
    replace_foto1,
    replace_foto2,
)
from enhancer.pipeline import enhance
from web.core import MAX_UPLOAD_BYTES, buat_templates, check_nim, get_restorer, gpu_lock, to_jpeg

EKSTENSI_FOTO = (".jpg", ".jpeg", ".png")
# Nama file harus NIM angka saja, agar file seperti "scan (1).jpg" tidak membuat baris NIM palsu
NIM_FILE_PATTERN = re.compile(r"^[0-9]{5,15}$")

router = APIRouter(prefix="/massal")
templates = buat_templates()

# nim -> {"data": bytes JPEG, "nama": nama file asli, "versi": int, "hasil": None|"ok"|"gagal", "pesan": str}
staging = {}
_versi = itertools.count(1)
job = {"berjalan": False, "total": 0, "selesai": 0, "sekarang": None}
_job_lock = threading.Lock()


class ItemProses(BaseModel):
    nim: str
    foto1: bool = False
    foto2: bool = False


class PermintaanProses(BaseModel):
    items: list[ItemProses]
    enhance: bool = False


class PermintaanHapus(BaseModel):
    nims: list[str] = []
    semua: bool = False
    selesai: bool = False


def nim_dari_nama_file(nama):
    """'folder/20126001.JPG' -> '20126001'; None jika bukan file foto bernama NIM."""
    base = os.path.basename(nama.replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    if ext.lower() not in EKSTENSI_FOTO:
        return None, "bukan file foto (jpg/jpeg/png)"
    stem = stem.strip()
    if not NIM_FILE_PATTERN.match(stem):
        return None, "nama file bukan NIM (harus angka saja)"
    return stem, None


def _tolak_jika_berjalan():
    if job["berjalan"]:
        raise HTTPException(status_code=409, detail="Proses masih berjalan, tunggu sampai selesai")


@router.get("")
def halaman(request: Request):
    return templates.TemplateResponse(request, "batch.html", {"halaman": "massal"})


@router.get("/daftar")
def daftar():
    nims = list(staging)
    status = {}
    if nims:
        conn = connect_db()
        try:
            status = foto_status(conn, nims)
        finally:
            conn.close()
    items = []
    for nim in nims:
        entry = staging[nim]
        ada_foto1, ada_foto2 = status.get(nim, (False, False))
        items.append({
            "nim": nim,
            "nama": entry["nama"],
            "ukuran": len(entry["data"]),
            "versi": entry["versi"],
            "terdaftar": nim in status,
            "ada_foto1": ada_foto1,
            "ada_foto2": ada_foto2,
            "hasil": entry["hasil"],
            "pesan": entry["pesan"],
        })
    return {"items": items, "job": dict(job)}


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    _tolak_jika_berjalan()
    diterima, ditolak = [], []
    for f in files:
        nama = f.filename or "(tanpa nama)"
        nim, alasan = nim_dari_nama_file(nama)
        if nim is None:
            ditolak.append({"nama": nama, "alasan": alasan})
            continue
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            ditolak.append({"nama": nama, "alasan": "lebih dari 15 MB"})
            continue
        try:
            data = to_jpeg(data)
        except ValueError as exc:
            ditolak.append({"nama": nama, "alasan": str(exc)})
            continue
        diganti = nim in staging
        staging[nim] = {
            "data": data,
            "nama": os.path.basename(nama.replace("\\", "/")),
            "versi": next(_versi),
            "hasil": None,
            "pesan": "",
        }
        diterima.append({"nim": nim, "diganti": diganti})
    return {"diterima": diterima, "ditolak": ditolak}


@router.get("/foto/{nim}")
def foto(nim: str):
    nim = check_nim(nim)
    if nim not in staging:
        raise HTTPException(status_code=404)
    # URL memuat ?v=<versi>, jadi aman di-cache: foto pengganti mendapat versi baru
    return Response(content=staging[nim]["data"], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/hapus")
def hapus(req: PermintaanHapus):
    _tolak_jika_berjalan()
    if req.semua:
        target = list(staging)
    elif req.selesai:
        target = [n for n, e in staging.items() if e["hasil"] == "ok"]
    else:
        target = req.nims
    for nim in target:
        staging.pop(nim, None)
    return {"dihapus": len(target)}


def proses_batch(items, use_enhance):
    """Tulis setiap item ke database; satu NIM = satu transaksi (foto1 & foto2 sukses/gagal bersama)."""
    try:
        restorer = get_restorer() if use_enhance and any(i.foto2 for i in items) else None
        conn = connect_db()
    except Exception as exc:  # noqa: BLE001 - laporkan ke semua item, jangan biarkan job menggantung
        for item in items:
            if item.nim in staging:
                staging[item.nim].update(hasil="gagal", pesan=str(exc))
        with _job_lock:
            job.update(berjalan=False, sekarang=None, selesai=job["total"])
        return

    try:
        for item in items:
            nim = item.nim
            entry = staging.get(nim)
            job["sekarang"] = nim
            if entry is None:
                job["selesai"] += 1
                continue
            try:
                data = entry["data"]
                insert_nim(conn, nim)
                ditulis = []
                if item.foto1:
                    replace_foto1(conn, nim, data)
                    ditulis.append("foto1")
                if item.foto2:
                    foto2 = data
                    if restorer is not None:
                        with gpu_lock:
                            foto2 = enhance(data, restorer)
                    replace_foto2(conn, nim, foto2)
                    log_result(conn, nim, "success")
                    ditulis.append("foto2 enhance" if restorer is not None else "foto2")
                conn.commit()
                entry.update(hasil="ok", pesan=" + ".join(ditulis))
            except Exception as exc:  # noqa: BLE001 - kegagalan satu NIM tidak boleh menghentikan batch
                conn.rollback()
                entry.update(hasil="gagal", pesan=str(exc))
                if item.foto2:
                    try:
                        log_result(conn, nim, "failed", str(exc))
                        conn.commit()
                    except Exception:  # noqa: BLE001
                        conn.rollback()
            job["selesai"] += 1
    finally:
        conn.close()
        with _job_lock:
            job.update(berjalan=False, sekarang=None)


@router.post("/proses")
def proses(req: PermintaanProses):
    items = [i for i in req.items if (i.foto1 or i.foto2) and i.nim in staging]
    if not items:
        raise HTTPException(status_code=400, detail="Tidak ada foto yang dipilih untuk foto1 atau foto2")
    use_enhance = req.enhance and any(i.foto2 for i in items)
    if use_enhance:
        try:
            get_restorer()  # cek GPU/model di depan agar error langsung terlihat
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Enhance tidak bisa dipakai: {exc}") from exc

    with _job_lock:
        if job["berjalan"]:
            raise HTTPException(status_code=409, detail="Proses masih berjalan")
        job.update(berjalan=True, total=len(items), selesai=0, sekarang=None)
    for item in items:
        staging[item.nim].update(hasil=None, pesan="")

    threading.Thread(target=proses_batch, args=(items, use_enhance), daemon=True).start()
    return {"total": len(items), "enhance": use_enhance}


@router.get("/status")
def status():
    return {
        "job": dict(job),
        "hasil": {nim: [e["hasil"], e["pesan"]] for nim, e in staging.items() if e["hasil"]},
    }
