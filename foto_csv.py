import psycopg2
import base64
import csv
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

                print(
                    f"File {file_name} berhasil disimpan di folder {folder_path}.")

        except psycopg2.Error as e:
            print(f"Error saat membuka Large Object {oid}: {e}")
            # Batalkan transaksi jika ada error
            conn.rollback()


def process_nim_from_csv(csv_file_path):
    conn = connect_db()
    if not conn:
        return

    # Membaca NIM dari file CSV
    try:
        with open(csv_file_path, mode='r', newline='', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            headers = reader.fieldnames
            # Tambahkan baris ini untuk debugging
            print(f"Header yang terbaca: {headers}")

            for row in reader:
                nim = row['nim'].strip()  # Ambil NIM dari kolom 'nim'

                try:
                    with conn.cursor() as cursor:
                        # Query untuk mengambil OID foto1 dan foto2 berdasarkan NIM
                        query = f"SELECT foto1, foto2 FROM foto.md_foto WHERE nim = '{nim}'"
                        cursor.execute(query)
                        result = cursor.fetchone()

                    if result:
                        foto1_oid = result[0]  # OID untuk foto1
                        foto2_oid = result[1]  # OID untuk foto2

                        # Tentukan folder untuk menyimpan foto
                        folder_path = os.path.join('Output')

                        # Proses pengambilan dan penyimpanan untuk masing-masing foto
                        if foto1_oid is not None:
                            fetch_and_save_lob(
                                conn, foto1_oid, folder_path, f"{nim}.jpeg")
                        elif foto2_oid is not None:
                            fetch_and_save_lob(
                                conn, foto2_oid, folder_path, f"{nim}.jpeg")
                    else:
                        print(
                            f"Tidak ada data OID yang ditemukan untuk NIM {nim}.")

                except psycopg2.Error as e:
                    print(f"Error executing query for NIM {nim}: {e}")
                    conn.rollback()

    except FileNotFoundError:
        print(f"File CSV {csv_file_path} tidak ditemukan.")
    except Exception as e:
        print(f"Error membaca CSV: {e}")

    conn.close()
    print("Database disconnected")


if __name__ == "__main__":
    # Path ke file CSV
    csv_file_path = 'Input/md_foto.csv'  # Ganti dengan nama file CSV yang sesuai
    process_nim_from_csv(csv_file_path)
