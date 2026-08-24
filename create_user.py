"""
Создание пользователя для входа в систему (bootstrap для первого запуска).

Запуск из папки проекта:
    python create_user.py

users.json хранится как словарь:
    { "логин": {"password": "<sha256>", "admin": true/false} }
"""
import hashlib
import json
import sys
from pathlib import Path

USERS_FILE = Path(__file__).parent / "users.json"


def hsh(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def main():
    username = input("Логин: ").strip()
    if not username:
        print("Логин не может быть пустым")
        sys.exit(1)

    password = input("Пароль: ")
    if len(password) < 4:
        print("Пароль слишком короткий (мин. 4 символа)")
        sys.exit(1)

    admin_raw = input("Админ? (y/N): ").strip().lower()
    is_admin = admin_raw in ("y", "yes", "да", "1")

    users = {}
    if USERS_FILE.exists():
        try:
            data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                users = data
            elif isinstance(data, list):
                for u in data:
                    users[u.get("username", "")] = {
                        "password": u.get("password", ""),
                        "admin": u.get("role") == "admin" or bool(u.get("admin"))
                    }
        except Exception:
            pass

    users[username] = {"password": hsh(password), "admin": is_admin}
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: '{username}' (админ={is_admin}) сохранён в users.json")


if __name__ == "__main__":
    main()
