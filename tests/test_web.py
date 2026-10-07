from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from web import app as web_app


@pytest.fixture
def client():
    web_app.previews.clear()
    with patch("web.app.connect_db", return_value=MagicMock()):
        yield TestClient(web_app.app)
    web_app.previews.clear()


@patch("web.app.fetch_foto2", return_value=None)
@patch("web.app.fetch_foto1", return_value=b"before")
def test_index_shows_foto1_and_enhance_button(mock_f1, mock_f2, client):
    resp = client.get("/?nim=20126001")

    assert resp.status_code == 200
    assert "/foto/20126001/foto1" in resp.text
    assert 'action="/enhance/20126001"' in resp.text
    assert 'action="/simpan/20126001"' not in resp.text


@patch("web.app.fetch_foto2", return_value=None)
@patch("web.app.fetch_foto1", return_value=b"before")
def test_index_with_preview_shows_save_and_cancel(mock_f1, mock_f2, client):
    web_app.previews["20126001"] = b"after"

    resp = client.get("/?nim=20126001&pesan=x&jenis=ok")

    assert "/preview/20126001" in resp.text
    assert 'action="/simpan/20126001"' in resp.text
    assert 'action="/batal/20126001"' in resp.text
    assert 'class="status ok"' in resp.text


def test_index_unknown_message_type_falls_back_to_info(client):
    resp = client.get("/?pesan=x&jenis=<script>")

    assert 'class="status info"' in resp.text


def test_invalid_nim_rejected(client):
    resp = client.get("/foto/abc'--/foto1")

    assert resp.status_code == 400


@patch("web.app.fetch_foto1", return_value=b"before")
def test_foto_endpoint_returns_jpeg(mock_f1, client):
    resp = client.get("/foto/20126001/foto1")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == b"before"


@patch("web.app.get_restorer", return_value=MagicMock())
@patch("web.app.enhance", return_value=b"after")
@patch("web.app.replace_foto2")
@patch("web.app.fetch_foto1", return_value=b"before")
def test_enhance_only_creates_preview_without_writing_db(
    mock_f1, mock_replace, mock_enhance, mock_restorer, client
):
    resp = client.post("/enhance/20126001", follow_redirects=False)

    assert resp.status_code == 303
    assert web_app.previews["20126001"] == b"after"
    mock_enhance.assert_called_once()
    assert mock_enhance.call_args.args[0] == b"before"
    mock_replace.assert_not_called()


@patch("web.app.enhance")
@patch("web.app.fetch_foto1", return_value=None)
def test_enhance_with_empty_foto1_reports_message(mock_f1, mock_enhance, client):
    resp = client.post("/enhance/20126001", follow_redirects=False)

    assert "foto1+kosong" in resp.headers["location"]
    mock_enhance.assert_not_called()
    assert "20126001" not in web_app.previews


@patch("web.app.log_result")
@patch("web.app.replace_foto2", return_value=True)
def test_simpan_writes_preview_to_foto2_only(mock_replace, mock_log, client):
    web_app.previews["20126001"] = b"after"

    resp = client.post("/simpan/20126001", follow_redirects=False)

    assert resp.status_code == 303
    conn = mock_replace.call_args.args[0]
    mock_replace.assert_called_once_with(conn, "20126001", b"after")
    mock_log.assert_called_once_with(conn, "20126001", "success")
    conn.commit.assert_called_once()
    assert "20126001" not in web_app.previews


@patch("web.app.replace_foto2")
def test_simpan_without_preview_does_nothing(mock_replace, client):
    resp = client.post("/simpan/20126001", follow_redirects=False)

    assert resp.status_code == 303
    mock_replace.assert_not_called()


@patch("web.app.log_result")
@patch("web.app.replace_foto2", return_value=False)
def test_simpan_unknown_nim_rolls_back_and_keeps_preview(mock_replace, mock_log, client):
    web_app.previews["99999999"] = b"after"

    client.post("/simpan/99999999", follow_redirects=False)

    conn = mock_replace.call_args.args[0]
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    mock_log.assert_not_called()
    assert "99999999" in web_app.previews


def test_batal_drops_preview(client):
    web_app.previews["20126001"] = b"after"

    client.post("/batal/20126001", follow_redirects=False)

    assert "20126001" not in web_app.previews


def _gambar(fmt):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (30, 50), (200, 180, 160)).save(out, format=fmt)
    return out.getvalue()


@patch("web.app.nim_exists", return_value=False)
@patch("web.app.fetch_foto2", return_value=None)
@patch("web.app.fetch_foto1", return_value=None)
def test_index_empty_foto1_shows_upload_zone(mock_f1, mock_f2, mock_exists, client):
    resp = client.get("/?nim=20126244")

    assert 'action="/upload-foto1/20126244"' in resp.text
    assert "NIM belum terdaftar" in resp.text
    assert 'action="/salin/20126244"' not in resp.text


@patch("web.app.nim_exists", return_value=True)
@patch("web.app.fetch_foto2", return_value=b"x")
@patch("web.app.fetch_foto1", return_value=b"before")
def test_index_salin_asks_confirmation_when_foto2_exists(mock_f1, mock_f2, mock_exists, client):
    resp = client.get("/?nim=20126001")

    assert 'action="/upload-foto1/20126001"' not in resp.text
    assert 'data-konfirmasi="Timpa foto2?"' in resp.text


@patch("web.app.replace_foto1", return_value=True)
@patch("web.app.insert_nim")
@patch("web.app.nim_exists", return_value=False)
@patch("web.app.fetch_foto1", return_value=None)
def test_upload_foto1_creates_row_and_stores_jpeg_as_is(
    mock_f1, mock_exists, mock_insert, mock_replace, client
):
    jpg = _gambar("JPEG")

    resp = client.post(
        "/upload-foto1/20126244", files={"file": ("a.jpg", jpg, "image/jpeg")}, follow_redirects=False
    )

    assert resp.status_code == 303
    assert "NIM+baru" in resp.headers["location"]
    conn = mock_replace.call_args.args[0]
    mock_insert.assert_called_once_with(conn, "20126244")
    mock_replace.assert_called_once_with(conn, "20126244", jpg)
    conn.commit.assert_called_once()


@patch("web.app.replace_foto1", return_value=True)
@patch("web.app.insert_nim")
@patch("web.app.nim_exists", return_value=True)
@patch("web.app.fetch_foto1", return_value=None)
def test_upload_foto1_converts_png_to_jpeg(mock_f1, mock_exists, mock_insert, mock_replace, client):
    client.post("/upload-foto1/20126244", files={"file": ("a.png", _gambar("PNG"), "image/png")})

    stored = mock_replace.call_args.args[2]
    assert stored[:3] == b"\xff\xd8\xff"


@patch("web.app.replace_foto1")
@patch("web.app.insert_nim")
@patch("web.app.fetch_foto1", return_value=b"existing")
def test_upload_foto1_never_overwrites_existing_foto1(mock_f1, mock_insert, mock_replace, client):
    resp = client.post(
        "/upload-foto1/20126001", files={"file": ("a.jpg", _gambar("JPEG"), "image/jpeg")},
        follow_redirects=False,
    )

    assert "sudah+ada" in resp.headers["location"]
    mock_insert.assert_not_called()
    mock_replace.assert_not_called()


@patch("web.app.replace_foto1")
@patch("web.app.connect_db")
def test_upload_foto1_rejects_non_image(mock_connect, mock_replace, client):
    resp = client.post(
        "/upload-foto1/20126001", files={"file": ("a.jpg", b"bukan gambar", "image/jpeg")},
        follow_redirects=False,
    )

    assert "jenis=gagal" in resp.headers["location"]
    mock_connect.assert_not_called()
    mock_replace.assert_not_called()


@patch("web.app.log_result")
@patch("web.app.replace_foto1")
@patch("web.app.replace_foto2", return_value=True)
@patch("web.app.fetch_foto1", return_value=b"before")
def test_salin_copies_foto1_to_foto2_without_touching_foto1(
    mock_f1, mock_replace2, mock_replace1, mock_log, client
):
    resp = client.post("/salin/20126001", follow_redirects=False)

    assert "jenis=ok" in resp.headers["location"]
    conn = mock_replace2.call_args.args[0]
    mock_replace2.assert_called_once_with(conn, "20126001", b"before")
    mock_replace1.assert_not_called()
    mock_log.assert_called_once_with(conn, "20126001", "success")
    conn.commit.assert_called_once()


@patch("web.app.replace_foto2")
@patch("web.app.fetch_foto1", return_value=None)
def test_salin_with_empty_foto1_does_nothing(mock_f1, mock_replace2, client):
    resp = client.post("/salin/20126001", follow_redirects=False)

    assert "jenis=gagal" in resp.headers["location"]
    mock_replace2.assert_not_called()


@patch("web.app.get_restorer", return_value=MagicMock())
@patch("web.app.enhance", return_value=b"filtered")
@patch("web.app.fetch_foto2", return_value=None)
@patch("web.app.fetch_foto1", return_value=b"before")
def test_filter_settings_pass_to_pipeline_and_survive_redirect(f1, f2, enhance, restorer, client):
    resp = client.post("/enhance/20126001", data={"brightness": "25", "smoothness": "0"})
    assert resp.status_code == 200
    assert enhance.call_args.kwargs["brightness"] == 25
    assert enhance.call_args.kwargs["smoothness"] == 0
    assert 'value="25.0"' in resp.text
    assert client.get("/preview/20126001").content == b"filtered"
    client.post("/batal/20126001")
    assert "20126001" not in web_app.preview_settings


@pytest.mark.parametrize("value", ["81", "-81", "nan", "inf", "abc"])
@patch("web.app.enhance")
def test_invalid_filter_rejected_before_processing(enhance, client, value):
    resp = client.post("/enhance/20126001", data={"brightness": value})
    assert resp.status_code == 422
    enhance.assert_not_called()
