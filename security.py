"""
보안 유틸리티
=============
JWT 인증 · Rate Limiting · 접근 로그 · 민감정보 마스킹
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError, jwt
from passlib.context import CryptContext
from slowapi import Limiter
from slowapi.util import get_remote_address

# ── 환경변수 ──────────────────────────────────────────────────
JWT_SECRET_KEY   = os.getenv("JWT_SECRET_KEY", "change-me-in-production-please")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_MIN   = int(os.getenv("JWT_EXPIRE_MIN", "60"))

API_KEY          = os.getenv("API_KEY", "")          # X-API-Key 헤더값
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "")   # /token 발급용 비밀번호

# ── 로거 (민감정보 필터 포함) ──────────────────────────────────
_MASK_PATTERNS = [
    re.compile(r"(key|token|secret|password|auth)[=: ]+\S+", re.I),
    re.compile(r"[a-f0-9]{32,}"),   # 긴 hex 문자열
]

class _SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        for p in _MASK_PATTERNS:
            msg = p.sub(lambda m: m.group(0).split("=")[0] + "=***MASKED***"
                        if "=" in m.group(0) else "***MASKED***", msg)
        record.msg = msg
        record.args = ()
        return True

def get_access_logger() -> logging.Logger:
    logger = logging.getLogger("realestate.access")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        handler.addFilter(_SensitiveFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

access_log = get_access_logger()

# ── Rate Limiter ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# ── 비밀번호 해싱 ──────────────────────────────────────────────
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

# ── JWT ───────────────────────────────────────────────────────
def create_access_token(subject: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MIN)
    return jwt.encode({"sub": subject, "exp": exp}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

_bearer = HTTPBearer(auto_error=False)

def require_jwt(credentials: HTTPAuthorizationCredentials = Security(_bearer)) -> str:
    """JWT Bearer 토큰 필수 의존성"""
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer 토큰 필요")
    subject = decode_token(credentials.credentials)
    if not subject:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않거나 만료된 토큰")
    return subject

# ── API Key ───────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: str = Security(_api_key_header)) -> str:
    """X-API-Key 헤더 검증 의존성 (API_KEY 미설정 시 스킵)"""
    if not API_KEY:
        return "no-key-configured"
    if key != API_KEY:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "유효하지 않은 API 키")
    return key

def optional_auth(
    key: str = Security(_api_key_header),
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> bool:
    """API Key 또는 JWT 중 하나만 있으면 통과"""
    if API_KEY and key == API_KEY:
        return True
    if credentials:
        sub = decode_token(credentials.credentials)
        if sub:
            return True
    if not API_KEY:
        return True  # 키 미설정 시 개방 (개발 환경)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                        "X-API-Key 헤더 또는 Bearer 토큰 필요",
                        headers={"WWW-Authenticate": "Bearer"})

# ── 접근 로그 미들웨어 ─────────────────────────────────────────
async def access_log_middleware(request: Request, call_next):
    start = time.perf_counter()
    ip    = request.client.host if request.client else "unknown"
    path  = request.url.path
    qs    = str(request.url.query)

    # 쿼리스트링에서 민감 파라미터 마스킹
    for p in _MASK_PATTERNS:
        qs = p.sub("***", qs)

    response = await call_next(request)
    elapsed  = (time.perf_counter() - start) * 1000

    access_log.info(
        "ip=%s method=%s path=%s qs=%s status=%d elapsed=%.1fms",
        ip, request.method, path, qs or "-", response.status_code, elapsed
    )

    # 비정상 접근 감지 (4xx/5xx 연속)
    if response.status_code in (401, 403, 429):
        access_log.warning("SUSPICIOUS ip=%s path=%s status=%d", ip, path, response.status_code)

    return response
