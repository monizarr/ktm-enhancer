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
