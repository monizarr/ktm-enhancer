import argparse
import csv
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")

from enhancer.db import (
    connect_db,
    fetch_foto1,
    get_pending_nims,
    insert_nim,
    log_result,
    replace_foto1,
    replace_foto2,
    write_foto2,
)
from enhancer.pipeline import enhance, load_restorer

LOCAL_OUTPUT_DIR = "local_output"
INPUT_DIR = "Input"
MODEL_PATH = os.path.join("enhancer", "models", "GFPGANv1.4.pth")


def load_nims_from_csv(csv_path, column="nim"):
    if not os.path.exists(csv_path):
        # "\Input\susulan.csv" diperlakukan relatif terhadap folder project
        stripped = csv_path.lstrip("\\/")
        if os.path.exists(stripped):
            csv_path = stripped
        elif not os.path.isabs(csv_path):
            csv_path = os.path.join(INPUT_DIR, csv_path)

    if not os.path.exists(csv_path):
        print(f"Error: file CSV tidak ditemukan: {csv_path}")
        sys.exit(1)

    nims = []
    seen = set()
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or column not in reader.fieldnames:
            print(f"Error: kolom '{column}' tidak ditemukan di {csv_path}")
            sys.exit(1)

        for row in reader:
            nim = (row.get(column) or "").strip()
            if nim and nim not in seen:
                seen.add(nim)
                nims.append(nim)

    return nims


def save_local(nim, before_bytes, after_bytes):
    os.makedirs(LOCAL_OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_OUTPUT_DIR, f"{nim}_before.jpg"), "wb") as f:
        f.write(before_bytes)
    with open(os.path.join(LOCAL_OUTPUT_DIR, f"{nim}_after.jpg"), "wb") as f:
        f.write(after_bytes)


def load_restorer_for_enhance():
    import torch

    if not torch.cuda.is_available():
        print(
            "Error: GPU CUDA tidak terdeteksi. Mode --enhance membutuhkan GPU NVIDIA "
            "dengan CUDA aktif untuk menjalankan model GFPGAN.\n"
            "Silakan lihat bagian setup pada README untuk instruksi instalasi "
            "driver/CUDA yang sesuai."
        )
        sys.exit(1)
    return load_restorer(MODEL_PATH)


def replace_fotos(conn, nim, image_bytes, do_foto1, do_foto2, restorer=None, create_missing=False):
    """Ganti foto1 dan/atau foto2. Return daftar kolom yang diganti, atau None jika NIM tidak ada.

    Jika create_missing=True (mode upload), baris NIM dibuat dulu bila belum ada.
    """
    if create_missing:
        insert_nim(conn, nim)
    replaced = []
    if do_foto1:
        if not replace_foto1(conn, nim, image_bytes):
            return None
        replaced.append("foto1")
    if do_foto2:
        foto2_bytes = enhance(image_bytes, restorer) if restorer is not None else image_bytes
        if not replace_foto2(conn, nim, foto2_bytes):
            return None
        replaced.append("foto2")
    return replaced


def replace_from_csv(nims, folder, do_foto1, do_foto2, restorer, mode, create_missing=False):
    total = len(nims)
    success_count = 0
    failed_count = 0

    conn = connect_db()
    try:
        for i, nim in enumerate(nims, start=1):
            path_file = os.path.join(folder, f"{nim}.jpeg")
            if not os.path.exists(path_file):
                failed_count += 1
                print(f"[{i}/{total}] {nim} ... FAILED: file tidak ditemukan: {path_file}")
                continue

            try:
                with open(path_file, "rb") as f:
                    image_bytes = f.read()
                replaced = replace_fotos(
                    conn, nim, image_bytes, do_foto1, do_foto2, restorer, create_missing
                )
                if replaced is None:
                    conn.rollback()
                    failed_count += 1
                    print(f"[{i}/{total}] {nim} ... FAILED: NIM tidak ditemukan di database")
                    continue
                conn.commit()
            except Exception as exc:  # noqa: BLE001 - kegagalan satu NIM tidak boleh menghentikan batch
                conn.rollback()
                failed_count += 1
                print(f"[{i}/{total}] {nim} ... FAILED: {exc}")
                continue

            success_count += 1
            print(f"[{i}/{total}] {nim} ... OK ({' & '.join(replaced)}, {mode})")

        print(f"\nSelesai. Sukses: {success_count}, Gagal: {failed_count}, Total: {total}")
    finally:
        conn.close()


def run_foto_command(parser, args, values, do_foto1, do_foto2, create_missing):
    """Jalankan --replace-foto1/2 atau --upload-foto1/2 untuk satu NIM atau file CSV."""
    flags = "--upload-foto1/--upload-foto2" if create_missing else "--replace-foto1/--replace-foto2"
    if len(values) != 2:
        parser.error(f"{flags} membutuhkan tepat 2 argumen: NIM PATH_FILE atau FILE.csv FOLDER_FOTO")

    use_enhance = args.enhance and do_foto2
    mode = "dengan enhance" if use_enhance else "tanpa enhance"
    verb = "diupload" if create_missing else "diganti"

    if values[0].lower().endswith(".csv"):
        csv_path, folder = values
        if not os.path.isdir(folder):
            print(f"Error: folder foto tidak ditemukan: {folder}")
            sys.exit(1)
        nims = load_nims_from_csv(csv_path, column=args.csv_column)
        restorer = load_restorer_for_enhance() if use_enhance else None
        replace_from_csv(nims, folder, do_foto1, do_foto2, restorer, mode, create_missing)
        return

    nim, path_file = values
    if not os.path.exists(path_file):
        print(f"Error: file tidak ditemukan: {path_file}")
        sys.exit(1)

    with open(path_file, "rb") as f:
        image_bytes = f.read()

    restorer = load_restorer_for_enhance() if use_enhance else None

    conn = connect_db()
    try:
        replaced = replace_fotos(
            conn, nim, image_bytes, do_foto1, do_foto2, restorer, create_missing
        )
        if replaced is None:
            conn.rollback()
            print(f"Error: NIM {nim} tidak ditemukan di database")
            sys.exit(1)

        conn.commit()
        print(f"{' & '.join(replaced)} untuk NIM {nim} berhasil {verb} dengan {path_file} ({mode})")
    finally:
        conn.close()


def process_nim(conn, nim, restorer, dry_run):
    before_bytes = fetch_foto1(conn, nim)
    if before_bytes is None:
        log_result(conn, nim, "failed", "foto1 kosong")
        return False, "foto1 kosong"

    # restorer None = mode --no-enhance: foto2 diisi salinan foto1 apa adanya
    if restorer is None:
        after_bytes = before_bytes
    else:
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
    parser.add_argument(
        "--angkatan",
        type=int,
        default=None,
        help="Filter berdasarkan angkatan (contoh: 2026 -> nim LIKE '%%26___')",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help=(
            "Nama/path file CSV berisi kolom 'nim' untuk diproses "
            "(dicari di folder Input/ jika hanya nama file yang diberikan)"
        ),
    )
    parser.add_argument(
        "--csv-column",
        type=str,
        default="nim",
        help="Nama kolom NIM di file CSV (default: nim)",
    )
    parser.add_argument(
        "--replace-foto1",
        nargs="*",
        metavar="NIM PATH_FILE",
        default=None,
        help=(
            "Ganti foto1 milik NIM tertentu dengan file gambar baru, lalu keluar. "
            "Bisa digabung: --replace-foto1 --replace-foto2 NIM PATH_FILE"
        ),
    )
    parser.add_argument(
        "--replace-foto2",
        nargs="*",
        metavar="NIM PATH_FILE",
        default=None,
        help="Ganti foto2 milik NIM tertentu dengan file gambar baru, lalu keluar",
    )
    parser.add_argument(
        "--upload-foto1",
        nargs="*",
        metavar="NIM PATH_FILE",
        default=None,
        help=(
            "Upload foto1 untuk NIM (baris NIM dibuat otomatis jika belum ada), lalu keluar. "
            "Bisa digabung: --upload-foto1 --upload-foto2 FILE.csv FOLDER_FOTO"
        ),
    )
    parser.add_argument(
        "--upload-foto2",
        nargs="*",
        metavar="NIM PATH_FILE",
        default=None,
        help="Upload foto2 untuk NIM (baris NIM dibuat otomatis jika belum ada), lalu keluar",
    )
    parser.add_argument(
        "--upload",
        nargs=2,
        metavar=("NIM", "PATH_FILE"),
        default=None,
        help="Upload foto untuk NIM yang belum ada fotonya (mengisi foto1 & foto2), lalu keluar",
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        help=(
            "Dipakai bersama --upload/--replace-foto2/--upload-foto2: foto1 diisi foto mentah, "
            "foto2 diisi hasil enhance "
            "(tanpa ini, foto1 & foto2 sama-sama foto mentah)"
        ),
    )
    parser.add_argument(
        "--no-enhance",
        action="store_true",
        help=(
            "Mode batch (--csv/--nim/--angkatan/--limit): isi foto2 dengan salinan foto1 "
            "dari database tanpa enhance (tidak butuh GPU)"
        ),
    )
    args = parser.parse_args()

    # NIM & PATH_FILE (atau FILE.csv FOLDER_FOTO) boleh ditulis setelah flag mana pun,
    # mis. --replace-foto1 --replace-foto2 NIM PATH_FILE
    is_replace = args.replace_foto1 is not None or args.replace_foto2 is not None
    is_upload = args.upload_foto1 is not None or args.upload_foto2 is not None
    if is_replace and is_upload:
        parser.error("--replace-foto* dan --upload-foto* tidak bisa dipakai bersamaan")

    if is_replace:
        values = (args.replace_foto1 or []) + (args.replace_foto2 or [])
        run_foto_command(
            parser, args, values,
            do_foto1=args.replace_foto1 is not None,
            do_foto2=args.replace_foto2 is not None,
            create_missing=False,
        )
        return

    if is_upload:
        values = (args.upload_foto1 or []) + (args.upload_foto2 or [])
        run_foto_command(
            parser, args, values,
            do_foto1=args.upload_foto1 is not None,
            do_foto2=args.upload_foto2 is not None,
            create_missing=True,
        )
        return

    if args.upload:
        nim, path_file = args.upload
        if not os.path.exists(path_file):
            print(f"Error: file tidak ditemukan: {path_file}")
            sys.exit(1)

        with open(path_file, "rb") as f:
            image_bytes = f.read()

        restorer = load_restorer_for_enhance() if args.enhance else None

        conn = connect_db()
        try:
            ok = replace_foto1(conn, nim, image_bytes)
            if not ok:
                insert_nim(conn, nim)
                ok = replace_foto1(conn, nim, image_bytes)
                if not ok:
                    conn.rollback()
                    print(f"Error: gagal membuat baris baru untuk NIM {nim}")
                    sys.exit(1)

            foto2_bytes = enhance(image_bytes, restorer) if args.enhance else image_bytes
            write_foto2(conn, nim, foto2_bytes)

            conn.commit()
            mode = "dengan enhance" if args.enhance else "tanpa enhance"
            print(f"Foto untuk NIM {nim} berhasil diupload ({mode}): foto1 & foto2 terisi")
        finally:
            conn.close()
        return

    if not args.no_enhance:
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
        restorer = None if args.no_enhance else load_restorer(MODEL_PATH)

        nim_like = None
        if args.angkatan is not None:
            year_suffix = str(args.angkatan)[-2:]
            nim_like = f"%{year_suffix}___"

        if args.nim:
            nims = [args.nim]
        elif args.csv:
            nims = load_nims_from_csv(args.csv, column=args.csv_column)
        else:
            nims = get_pending_nims(
                conn,
                limit=args.limit,
                retry_failed_only=args.retry_failed,
                nim_like=nim_like,
            )

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
