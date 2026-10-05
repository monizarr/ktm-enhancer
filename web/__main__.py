import warnings

import uvicorn

warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")

if __name__ == "__main__":
    # Hanya bisa diakses dari PC ini (127.0.0.1), tidak dari komputer lain di jaringan
    print("Buka http://127.0.0.1:8000 di browser. Tekan Ctrl+C untuk berhenti.")
    uvicorn.run("web.app:app", host="127.0.0.1", port=8000)
