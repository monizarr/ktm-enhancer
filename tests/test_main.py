from unittest.mock import MagicMock, patch

from main import process_nim, replace_fotos, replace_from_csv


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
@patch("main.write_foto2")
@patch("main.save_local")
@patch("main.enhance")
@patch("main.fetch_foto1")
def test_process_nim_without_restorer_copies_foto1_to_foto2(
    mock_fetch, mock_enhance, mock_save_local, mock_write_foto2, mock_log_result
):
    conn = MagicMock()
    mock_fetch.return_value = b"before"

    ok, error = process_nim(conn, "111", restorer=None, dry_run=False)

    assert ok is True
    mock_enhance.assert_not_called()
    mock_save_local.assert_not_called()
    mock_write_foto2.assert_called_once_with(conn, "111", b"before")
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


@patch("main.replace_foto2", return_value=True)
@patch("main.replace_foto1", return_value=True)
def test_replace_fotos_only_foto2(mock_r1, mock_r2):
    conn = MagicMock()

    replaced = replace_fotos(conn, "111", b"img", do_foto1=False, do_foto2=True)

    assert replaced == ["foto2"]
    mock_r1.assert_not_called()
    mock_r2.assert_called_once_with(conn, "111", b"img")


@patch("main.replace_foto2", return_value=True)
@patch("main.replace_foto1", return_value=False)
def test_replace_fotos_returns_none_when_nim_missing(mock_r1, mock_r2):
    replaced = replace_fotos(MagicMock(), "111", b"img", do_foto1=True, do_foto2=True)

    assert replaced is None
    mock_r2.assert_not_called()


@patch("main.replace_foto2", return_value=True)
@patch("main.replace_foto1", return_value=True)
@patch("main.connect_db")
def test_replace_from_csv_uses_nim_jpeg_and_skips_missing_file(
    mock_connect, mock_r1, mock_r2, tmp_path
):
    conn = MagicMock()
    mock_connect.return_value = conn
    (tmp_path / "111.jpeg").write_bytes(b"foto111")

    replace_from_csv(["111", "222"], str(tmp_path), True, True, None, "tanpa enhance")

    mock_r1.assert_called_once_with(conn, "111", b"foto111")
    mock_r2.assert_called_once_with(conn, "111", b"foto111")
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@patch("main.replace_foto2", return_value=True)
@patch("main.replace_foto1", return_value=True)
@patch("main.insert_nim")
def test_replace_fotos_create_missing_inserts_nim_first(mock_insert, mock_r1, mock_r2):
    conn = MagicMock()

    replaced = replace_fotos(
        conn, "111", b"img", do_foto1=True, do_foto2=True, create_missing=True
    )

    assert replaced == ["foto1", "foto2"]
    mock_insert.assert_called_once_with(conn, "111")


@patch("main.replace_foto1", return_value=True)
@patch("main.insert_nim")
def test_replace_fotos_without_create_missing_does_not_insert(mock_insert, mock_r1):
    replace_fotos(MagicMock(), "111", b"img", do_foto1=True, do_foto2=False)

    mock_insert.assert_not_called()
