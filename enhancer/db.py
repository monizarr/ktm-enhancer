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
