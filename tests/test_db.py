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
