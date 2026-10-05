import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from web import app as web_app
from web import batch
from web.batch import ItemProses, nim_dari_nama_file, proses_batch


def _gambar(fmt):
    out = io.BytesIO()
    Image.new("RGB", (30, 50), (200, 180, 160)).save(out, format=fmt)
    return out.getvalue()


JPG = _gambar("JPEG")


@pytest.fixture(autouse=True)
def bersih():
    batch.staging.clear()
    batch.job.update(berjalan=False, total=0, selesai=0, sekarang=None)
    yield
    batch.staging.clear()
    batch.job.update(berjalan=False, total=0, selesai=0, sekarang=None)


@pytest.fixture
def client():
    return TestClient(web_app.app)


def _stage(nim, data=JPG):
    batch.staging[nim] = {"data": data, "nama": f"{nim}.jpg", "versi": 1, "hasil": None, "pesan": ""}


@pytest.mark.parametrize(
    "nama, nim",
    [
        ("20126001.jpg", "20126001"),
        ("folder/sub/20126001.JPEG", "20126001"),
        ("C:\\foto\\20126001.png", "20126001"),
        ("20126001.gif", None),
        ("foto budi.jpg", None),
        ("Thumbs.db", None),
    ],
)
def test_nim_dari_nama_file(nama, nim):
    assert nim_dari_nama_file(nama)[0] == nim


def test_upload_accepts_named_photos_and_reports_rejects(client):
    files = [
        ("files", ("20126001.jpg", JPG, "image/jpeg")),
        ("files", ("20126002.png", _gambar("PNG"), "image/png")),
        ("files", ("budi.jpg", JPG, "image/jpeg")),
        ("files", ("20126003.jpg", b"bukan gambar", "image/jpeg")),
    ]

    resp = client.post("/massal/upload", files=files)

    data = resp.json()
    assert [d["nim"] for d in data["diterima"]] == ["20126001", "20126002"]
    assert {d["nama"] for d in data["ditolak"]} == {"budi.jpg", "20126003.jpg"}
    assert batch.staging["20126001"]["data"] == JPG
    assert batch.staging["20126002"]["data"][:3] == b"\xff\xd8\xff"  # PNG dikonversi ke JPEG


def test_upload_same_nim_replaces_and_bumps_version(client):
    client.post("/massal/upload", files=[("files", ("20126001.jpg", JPG, "image/jpeg"))])
    versi_lama = batch.staging["20126001"]["versi"]

    resp = client.post("/massal/upload", files=[("files", ("20126001.jpg", JPG, "image/jpeg"))])

    assert resp.json()["diterima"] == [{"nim": "20126001", "diganti": True}]
    assert batch.staging["20126001"]["versi"] > versi_lama


def test_upload_rejected_while_job_running(client):
    batch.job["berjalan"] = True

    resp = client.post("/massal/upload", files=[("files", ("20126001.jpg", JPG, "image/jpeg"))])

    assert resp.status_code == 409
    assert batch.staging == {}


@patch("web.batch.foto_status", return_value={"20126001": (True, False)})
@patch("web.batch.connect_db", return_value=MagicMock())
def test_daftar_merges_db_status(mock_connect, mock_status, client):
    _stage("20126001")
    _stage("20126999")

    items = {i["nim"]: i for i in client.get("/massal/daftar").json()["items"]}

    assert items["20126001"]["terdaftar"] is True
    assert items["20126001"]["ada_foto1"] is True
    assert items["20126001"]["ada_foto2"] is False
    assert items["20126999"]["terdaftar"] is False


@patch("web.batch.log_result")
@patch("web.batch.replace_foto2")
@patch("web.batch.replace_foto1")
@patch("web.batch.insert_nim")
@patch("web.batch.connect_db")
def test_proses_batch_writes_original_to_both_without_enhance(
    mock_connect, mock_insert, mock_r1, mock_r2, mock_log
):
    conn = mock_connect.return_value
    _stage("20126001")
    batch.job.update(berjalan=True, total=1)

    proses_batch([ItemProses(nim="20126001", foto1=True, foto2=True)], use_enhance=False)

    mock_insert.assert_called_once_with(conn, "20126001")
    mock_r1.assert_called_once_with(conn, "20126001", JPG)
    mock_r2.assert_called_once_with(conn, "20126001", JPG)
    mock_log.assert_called_once_with(conn, "20126001", "success")
    conn.commit.assert_called_once()
    assert batch.staging["20126001"]["hasil"] == "ok"
    assert batch.job["berjalan"] is False
    assert batch.job["selesai"] == 1


@patch("web.batch.log_result")
@patch("web.batch.enhance", return_value=b"enhanced")
@patch("web.batch.get_restorer", return_value=MagicMock())
@patch("web.batch.replace_foto2")
@patch("web.batch.replace_foto1")
@patch("web.batch.insert_nim")
@patch("web.batch.connect_db")
def test_proses_batch_with_enhance_keeps_foto1_original(
    mock_connect, mock_insert, mock_r1, mock_r2, mock_restorer, mock_enhance, mock_log
):
    conn = mock_connect.return_value
    _stage("20126001")

    proses_batch([ItemProses(nim="20126001", foto1=True, foto2=True)], use_enhance=True)

    mock_r1.assert_called_once_with(conn, "20126001", JPG)
    mock_r2.assert_called_once_with(conn, "20126001", b"enhanced")
    assert mock_enhance.call_args.args[0] == JPG
    assert batch.staging["20126001"]["pesan"] == "foto1 + foto2 enhance"


@patch("web.batch.log_result")
@patch("web.batch.replace_foto2")
@patch("web.batch.replace_foto1")
@patch("web.batch.insert_nim")
@patch("web.batch.connect_db")
def test_proses_batch_foto2_only_does_not_touch_foto1(
    mock_connect, mock_insert, mock_r1, mock_r2, mock_log
):
    _stage("20126001")

    proses_batch([ItemProses(nim="20126001", foto1=False, foto2=True)], use_enhance=False)

    mock_r1.assert_not_called()
    mock_r2.assert_called_once()


@patch("web.batch.log_result")
@patch("web.batch.replace_foto2")
@patch("web.batch.replace_foto1")
@patch("web.batch.insert_nim")
@patch("web.batch.connect_db")
def test_proses_batch_failure_rolls_back_that_nim_and_continues(
    mock_connect, mock_insert, mock_r1, mock_r2, mock_log
):
    conn = mock_connect.return_value
    mock_r2.side_effect = [RuntimeError("disk penuh"), None]
    _stage("20126001")
    _stage("20126002")

    proses_batch(
        [ItemProses(nim="20126001", foto1=True, foto2=True), ItemProses(nim="20126002", foto1=True, foto2=True)],
        use_enhance=False,
    )

    conn.rollback.assert_called_once()
    mock_log.assert_any_call(conn, "20126001", "failed", "disk penuh")
    assert batch.staging["20126001"]["hasil"] == "gagal"
    assert batch.staging["20126001"]["pesan"] == "disk penuh"
    assert batch.staging["20126002"]["hasil"] == "ok"
    conn.close.assert_called_once()


@patch("web.batch.connect_db", side_effect=RuntimeError("DB mati"))
def test_proses_batch_db_down_marks_all_failed_and_releases_job(mock_connect):
    _stage("20126001")
    batch.job.update(berjalan=True, total=1)

    proses_batch([ItemProses(nim="20126001", foto1=True)], use_enhance=False)

    assert batch.staging["20126001"]["hasil"] == "gagal"
    assert batch.job["berjalan"] is False


def test_proses_without_selection_rejected(client):
    _stage("20126001")

    resp = client.post("/massal/proses", json={"items": [{"nim": "20126001"}]})

    assert resp.status_code == 400


@patch("web.batch.get_restorer", side_effect=RuntimeError("GPU CUDA tidak terdeteksi"))
def test_proses_enhance_without_gpu_rejected_upfront(mock_restorer, client):
    _stage("20126001")

    resp = client.post(
        "/massal/proses", json={"enhance": True, "items": [{"nim": "20126001", "foto2": True}]}
    )

    assert resp.status_code == 400
    assert "GPU" in resp.json()["detail"]
    assert batch.job["berjalan"] is False


@patch("web.batch.threading.Thread")
def test_proses_starts_background_job(mock_thread, client):
    _stage("20126001")
    _stage("20126002")

    resp = client.post(
        "/massal/proses",
        json={"items": [{"nim": "20126001", "foto1": True}, {"nim": "20126002"}, {"nim": "tidak-ada", "foto1": True}]},
    )

    assert resp.json() == {"total": 1, "enhance": False}
    assert batch.job["berjalan"] is True
    items, use_enhance = mock_thread.call_args.kwargs["args"]
    assert [i.nim for i in items] == ["20126001"]
    mock_thread.return_value.start.assert_called_once()


def test_proses_rejected_while_running(client):
    _stage("20126001")
    batch.job["berjalan"] = True

    resp = client.post("/massal/proses", json={"items": [{"nim": "20126001", "foto1": True}]})

    assert resp.status_code == 409


def test_hapus_selesai_only_removes_successful(client):
    _stage("20126001")
    _stage("20126002")
    batch.staging["20126001"]["hasil"] = "ok"

    client.post("/massal/hapus", json={"selesai": True})

    assert list(batch.staging) == ["20126002"]


def test_halaman_massal_renders(client):
    resp = client.get("/massal")

    assert resp.status_code == 200
    assert 'id="input-folder"' in resp.text
    assert 'href="/massal" aria-current="page"' in resp.text
