import argparse
import os
import sys

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

    import torch

    if not torch.cuda.is_available():
        print(
            "Error: GPU CUDA tidak terdeteksi. Alat ini membutuhkan GPU NVIDIA "
            "dengan CUDA aktif untuk menjalankan model GFPGAN.\n"
            "Silakan lihat bagian setup pada README untuk instruksi instalasi "
            "driver/CUDA yang sesuai."
        )
        sys.exit(1)

    conn = connect_db()
    try:
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

        print(f"\nSelesai. Sukses: {success_count}, Gagal: {failed_count}, Total: {total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
