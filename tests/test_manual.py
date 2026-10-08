import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from web import app as web_app


@pytest.fixture
def client():
    with patch("web.app.connect_db", return_value=MagicMock()):
        yield TestClient(web_app.app)


def photo(fmt="JPEG"):
    out = io.BytesIO()
    Image.new("RGB", (40, 60), "red").save(out, format=fmt)
    return out.getvalue()


def upload(client, column="foto1", data=None, **extra):
    return client.post("/upload-manual", data=dict(nim="123", kolom=column, **extra),
                       files={"file": ("photo.jpg", photo() if data is None else data)},
                       follow_redirects=False)


@pytest.mark.parametrize("column", ["foto1", "foto2"])
@patch("web.app.insert_nim")
@patch("web.app.fetch_foto1", return_value=None)
@patch("web.app.fetch_foto2", return_value=None)
@patch("web.app.replace_foto1", return_value=True)
@patch("web.app.replace_foto2", return_value=True)
@patch("web.app.get_restorer")
def test_manual_upload_preserves_jpeg_and_only_updates_target(restorer, r2, r1, f2, f1, insert, client, column):
    data = photo()
    response = upload(client, column, data)
    assert response.status_code == 303
    assert "jenis=ok" in response.headers["location"]
    chosen, other = (r1, r2) if column == "foto1" else (r2, r1)
    chosen.assert_called_once()
    assert chosen.call_args.args[1:] == ("123", data)
    chosen.call_args.args[0].commit.assert_called_once()
    other.assert_not_called()
    restorer.assert_not_called()


@patch("web.app.insert_nim")
@patch("web.app.fetch_foto1", return_value=b"existing")
@patch("web.app.replace_foto1", return_value=True)
def test_overwrite_requires_explicit_permission(replace, fetch, insert, client):
    assert "jenis=gagal" in upload(client).headers["location"]
    replace.assert_not_called()
    assert "jenis=ok" in upload(client, timpa="true").headers["location"]
    replace.assert_called_once()


@patch("web.app.insert_nim")
def test_invalid_file_and_column_do_not_write(insert, client):
    assert "jenis=gagal" in upload(client, data=b"invalid").headers["location"]
    assert upload(client, column="other").status_code == 400
    assert "jenis=gagal" in upload(client, data=photo("GIF")).headers["location"]
    insert.assert_not_called()


@patch("web.app.insert_nim")
@patch("web.app.fetch_foto2", return_value=None)
@patch("web.app.replace_foto2", return_value=True)
def test_png_converts_without_resize_and_clears_old_preview(replace, fetch, insert, client):
    web_app.previews["123"] = b"old"
    web_app.preview_settings["123"] = {"brightness": 0}
    upload(client, column="foto2", data=photo("PNG"))
    with Image.open(io.BytesIO(replace.call_args.args[2])) as img:
        assert img.format == "JPEG"
        assert img.size == (40, 60)
    assert "123" not in web_app.previews
    assert "123" not in web_app.preview_settings


def test_manual_tab_active_and_form_available(client):
    response = client.get("/upload-manual")
    assert response.status_code == 200
    assert 'href="/upload-manual" aria-current="page"' in response.text
    assert 'href="/" aria-current="page"' not in response.text
    assert 'name="kolom" value="foto2"' in response.text


@pytest.mark.parametrize("occupied", [None, "foto1", "foto2"])
@pytest.mark.parametrize("allow", [False, True])
def test_upload_both_checks_all_targets_before_writing(client, occupied, allow):
    with patch("web.app.insert_nim"), \
         patch("web.app.fetch_foto1", return_value=b"old" if occupied == "foto1" else None), \
         patch("web.app.fetch_foto2", return_value=b"old" if occupied == "foto2" else None), \
         patch("web.app.replace_foto1", return_value=True) as r1, \
         patch("web.app.replace_foto2", return_value=True) as r2:
        data = photo()
        response = upload(client, column="keduanya", data=data, timpa=str(allow).lower())
        if occupied and not allow:
            assert "jenis=gagal" in response.headers["location"]
            r1.assert_not_called()
            r2.assert_not_called()
        else:
            assert "jenis=ok" in response.headers["location"]
            conn = r1.call_args.args[0]
            r1.assert_called_once_with(conn, "123", data)
            r2.assert_called_once_with(conn, "123", data)
            conn.commit.assert_called_once()


def test_second_target_failure_rolls_back_both_and_retains_preview(client):
    with patch("web.app.insert_nim"), \
         patch("web.app.fetch_foto1", return_value=None), \
         patch("web.app.fetch_foto2", return_value=None), \
         patch("web.app.replace_foto1", return_value=True) as r1, \
         patch("web.app.replace_foto2", side_effect=RuntimeError("failed")):
        web_app.previews["123"] = b"pending"
        response = upload(client, column="keduanya")
        assert "jenis=gagal" in response.headers["location"]
        conn = r1.call_args.args[0]
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()
        assert web_app.previews.pop("123") == b"pending"
