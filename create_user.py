"""
Создание пользователя для входа в систему (bootstrap для первого запуска).

Запуск из папки проекта:
    python create_user.py

Добавляет пользователя в users.json (пароль хранится как sha256).
"""
import hashlib
import json
import sys
from pathlib import Path

USERS_FILE = Path(__file__).parent / "users.json"
ROLES = {"admin", "editor", "viewer"}


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

    role = input("Роль (admin/editor/viewer) [admin]: ").strip() or "admin"
    if role not in ROLES:
        role = "admin"

    data = json.loads(USERS_FILE.read_text(encoding="utf-8")) if USERS_FILE.exists() else []

    for u in data:
        if u.get("username") == username:
            u["password"] = hsh(password)
            u["role"] = role
            break
    else:
        data.append({"username": username, "password": hsh(password), "role": role})

    USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: пользователь '{username}' (роль {role}) создан в users.json")


if __name__ == "__main__":
    main()
