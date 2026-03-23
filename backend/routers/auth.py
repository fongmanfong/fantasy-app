from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..services.yahoo_service import YahooService

router = APIRouter(prefix="/api/auth", tags=["auth"])


class CredentialsRequest(BaseModel):
    client_id: str
    client_secret: str


@router.post("/yahoo/credentials")
def save_credentials(req: CredentialsRequest, db: Session = Depends(get_db)):
    svc = YahooService(db)
    svc.save_credentials(req.client_id, req.client_secret)
    return {"message": "Credentials saved"}


@router.get("/yahoo/login")
def yahoo_login(db: Session = Depends(get_db)):
    svc = YahooService(db)
    try:
        url = svc.get_auth_url()
        return {"auth_url": url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class OobCallbackRequest(BaseModel):
    code: str


@router.post("/yahoo/oob-callback")
def yahoo_oob_callback(req: OobCallbackRequest, db: Session = Depends(get_db)):
    svc = YahooService(db)
    try:
        # User may paste the full redirect URL or just the code
        raw = req.code.strip()
        if raw.startswith("http"):
            parsed = urlparse(raw)
            code = parse_qs(parsed.query).get("code", [None])[0]
            if not code:
                raise ValueError("No 'code' parameter found in URL")
        else:
            code = raw
        svc.handle_callback(code)
        return {"message": "Authenticated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/yahoo/status")
def auth_status(db: Session = Depends(get_db)):
    svc = YahooService(db)
    creds = svc.get_credentials()
    return {
        "has_credentials": creds is not None and bool(creds.client_id),
        "is_authenticated": creds is not None and bool(creds.access_token),
    }
