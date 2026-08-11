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
