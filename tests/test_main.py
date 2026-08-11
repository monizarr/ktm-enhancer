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
