from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.youtube_api import YouTubeAPI

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

youtube_api = YouTubeAPI(
    client_secret_file=str(settings.BASE_DIR / "client_secret.json"),
    tokens_dir=str(settings.TOKENS_DIR)
)


@router.post("/authorize")
async def authorize(data: dict):
    email = data.get("email")
    if not email:
        return JSONResponse({"status": "error", "message": "Email required"})

    cred_file = settings.GOOGLE_CREDENTIALS_DIR / f"{_safe_email(email)}.json"
    youtube_api.client_secret_file = str(cred_file) if cred_file.exists() else str(
        settings.BASE_DIR / "client_secret.json")

    if youtube_api.authenticate(email):
        return JSONResponse({"status": "success", "message": f"Authorized: {email}"})
    return JSONResponse({"status": "error", "message": "Authorization failed"})


@router.post("/upload-credentials")
async def upload_credentials(email: str = Form(...), credentials: UploadFile = File(...)):
    contents = await credentials.read()
    import json
    try:
        json.loads(contents)
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    creds_dir = settings.GOOGLE_CREDENTIALS_DIR
    creds_dir.mkdir(exist_ok=True)
    cred_file = creds_dir / f"{_safe_email(email)}.json"
    with open(cred_file, "wb") as f:
        f.write(contents)
    return {"status": "success", "message": f"Credentials saved for {email}"}


@router.get("/accounts")
async def get_accounts():
    creds_dir = settings.GOOGLE_CREDENTIALS_DIR
    accounts = []
    if creds_dir.exists():
        for f in creds_dir.glob("*.json"):
            email = f.stem.replace("_at_", "@").replace("_", ".")
            token_file = youtube_api.get_token_file(email)
            accounts.append({
                "email": email,
                "credentials_file": str(f),
                "has_token": token_file.exists()
            })
    return {"status": "success", "accounts": accounts}


@router.delete("/accounts")
async def delete_account(data: dict):
    email = data.get("email", "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    safe = _safe_email(email)
    deleted = []
    for path in [
        settings.GOOGLE_CREDENTIALS_DIR / f"{safe}.json",
        youtube_api.get_token_file(email),
    ]:
        if path.exists() and path.is_file():
            path.unlink()
            deleted.append(str(path))
    return {"status": "success", "deleted": deleted}


def _safe_email(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")
