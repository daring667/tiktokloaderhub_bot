import os
import base64


def setup_cookies():
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "cookies.txt")
    )

    if os.path.exists(path):
        print("[log] cookies.txt уже существует — пропускаю создание")
        return

    b64 = os.getenv("COOKIES_B64")
    if not b64:
        print("[warn] COOKIES_B64 не задана. Куки не будут использованы.")
        return

    try:
        data = base64.b64decode(b64)
        with open(path, "wb") as f:
            f.write(data)
        print("[log] cookies.txt успешно создан из COOKIES_B64")
    except Exception as e:
        print(f"[err] Ошибка при создании cookies.txt: {e}")
