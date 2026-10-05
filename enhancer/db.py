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


def get_pending_nims(conn, limit=None, retry_failed_only=False, nim_like=None):
    if retry_failed_only:
        query = (
            "SELECT nim FROM foto.md_foto "
            "WHERE nim IN (SELECT nim FROM foto.enhancement_log WHERE status = 'failed')"
        )
    else:
        query = (
            "SELECT nim FROM foto.md_foto "
            "WHERE nim NOT IN (SELECT nim FROM foto.enhancement_log WHERE status = 'success')"
        )

    params = []

    if nim_like is not None:
        query += " AND nim LIKE %s"
        params.append(nim_like)

    query += " ORDER BY nim"

    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params) if params else None)
        return [row[0] for row in cursor.fetchall()]


def fetch_foto1(conn, nim):
    return _fetch_foto(conn, nim, "foto1")


def fetch_foto2(conn, nim):
    return _fetch_foto(conn, nim, "foto2")


def _fetch_foto(conn, nim, column):
    if column not in ("foto1", "foto2"):
        raise ValueError(f"Kolom tidak valid: {column}")

    with conn.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM foto.md_foto WHERE nim = %s", (nim,))
        result = cursor.fetchone()

    if result is None or result[0] is None:
        return None

    lo = conn.lobject(result[0], "rb")
    data = lo.read()
    lo.close()
    return data


def nim_exists(conn, nim):
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM foto.md_foto WHERE nim = %s", (nim,))
        return cursor.fetchone() is not None


def foto_status(conn, nims):
    """Return {nim: (ada_foto1, ada_foto2)} untuk NIM yang sudah terdaftar."""
    if not nims:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT nim, foto1 IS NOT NULL, foto2 IS NOT NULL FROM foto.md_foto WHERE nim = ANY(%s)",
            (list(nims),),
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def insert_nim(conn, nim):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO foto.md_foto (nim) VALUES (%s) ON CONFLICT (nim) DO NOTHING",
            (nim,),
        )


def _replace_foto(conn, nim, column, image_bytes):
    if column not in ("foto1", "foto2"):
        raise ValueError(f"Kolom tidak valid: {column}")

    with conn.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM foto.md_foto WHERE nim = %s", (nim,))
        result = cursor.fetchone()

    if result is None:
        return False

    old_oid = result[0]

    lo = conn.lobject(0, "wb")
    lo.write(image_bytes)
    new_oid = lo.oid
    lo.close()

    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE foto.md_foto SET {column} = %s WHERE nim = %s",
            (new_oid, nim),
        )

    if old_oid is not None:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_largeobject_metadata WHERE oid = %s", (old_oid,)
            )
            old_exists = cursor.fetchone() is not None
            # Jangan hapus jika OID lama masih dirujuk kolom foto lain
            cursor.execute(
                "SELECT 1 FROM foto.md_foto WHERE foto1 = %s OR foto2 = %s LIMIT 1",
                (old_oid, old_oid),
            )
            still_referenced = cursor.fetchone() is not None
        if old_exists and not still_referenced:
            conn.lobject(old_oid).unlink()

    return True


def replace_foto1(conn, nim, image_bytes):
    return _replace_foto(conn, nim, "foto1", image_bytes)


def replace_foto2(conn, nim, image_bytes):
    return _replace_foto(conn, nim, "foto2", image_bytes)


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
