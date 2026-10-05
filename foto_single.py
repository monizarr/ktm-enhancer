import psycopg2
import base64
import os


def connect_db():
    try:
        # Konfigurasi koneksi database
        conn = psycopg2.connect(
            dbname="dbstain",
            user="taqiem",
            password="taqiem",
            host="10.10.3.6",
            port="5432",
            options="-c search_path=foto"
        )
        print("Database connected")
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
        return None


def fetch_and_save_lob(conn, oid, folder_path, file_name):
    if oid is not None:
        try:
            # Mulai transaksi baru
            with conn.cursor() as cursor:
                # Coba buka Large Object
                lo = conn.lobject(oid, 'rb')
                foto_data = lo.read()
                lo.close()

                # Encode data LOB ke Base64
                foto_base64 = base64.b64encode(foto_data).decode('utf-8')
                foto_binary = base64.b64decode(foto_base64)

                # Membuat folder jika belum ada
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)

                # Simpan file ke disk
                file_path = os.path.join(folder_path, file_name)
                with open(file_path, 'wb') as file:
                    file.write(foto_binary)

                print(f"File {file_name} berhasil disimpan.")

        except psycopg2.Error as e:
            print(f"Error saat membuka Large Object {oid}: {e}")
            # Batalkan transaksi jika ada error
            conn.rollback()


def main():
    conn = connect_db()
    if not conn:
        return

    # Ambil OID dari kolom foto1 dan foto2 menggunakan NIM
    nim = '20326030'  # Ganti dengan NIM mahasiswa yang ingin diambil
    try:
        with conn.cursor() as cursor:
            query = f"SELECT foto1, foto2 FROM foto.md_foto WHERE nim = '{nim}'"
            cursor.execute(query)
            result = cursor.fetchone()

        if result:
            oid_foto1 = result[0]
            oid_foto2 = result[1]

            folder_path = os.path.join("Download")

            # Proses pengambilan dan penyimpanan untuk masing-masing foto
            # if oid_foto1 is not None:
            fetch_and_save_lob(
                conn, oid_foto1, folder_path, f"{nim}.jpeg")
            # elif oid_foto2 is not None:
            # fetch_and_save_lob(conn, oid_foto2, folder_path, f"{nim}.jpeg")

        else:
            print("Tidak ada data OID yang ditemukan.")

    except psycopg2.Error as e:
        print(f"Error executing query: {e}")
        conn.rollback()

    conn.close()
    print("Database disconnected")


if __name__ == "__main__":
    main()
