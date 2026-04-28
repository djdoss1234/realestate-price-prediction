"""
Redis 캐시 레이어
==================
- FastAPI 엔드포인트 결과를 Redis에 캐싱
- 예측 결과: 1시간 TTL
- 저평가 목록: 30분 TTL
- 지역 목록: 24시간 TTL

환경변수:
  REDIS_URL=redis://localhost:6379/0  (기본값)
  REDIS_ENABLED=true
"""

import functools
import hashlib
import json
import logging
import os
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"

_client = None


def get_redis():
    global _client
    if _client is not None:
        return _client
    if not REDIS_ENABLED:
        return None
    try:
        import redis
        _client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        _client.ping()
        log.info("Redis 연결 성공: %s", REDIS_URL)
    except Exception as e:
        log.warning("Redis 연결 실패 (캐시 비활성화): %s", e)
        _client = None
    return _client


def _serialize(obj: Any) -> Any:
    """Pydantic BaseModel / list of BaseModel → dict/list for JSON serialization."""
    if hasattr(obj, "model_dump"):      # pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):            # pydantic v1
        return obj.dict()
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


def _make_key(prefix: str, *args, **kwargs) -> str:
    raw = json.dumps({"a": args, "k": kwargs}, sort_keys=True, ensure_ascii=False, default=_serialize)
    h   = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"realestate:{prefix}:{h}"


def cache(prefix: str, ttl: int = 3600):
    """
    FastAPI 엔드포인트에 붙이는 캐시 데코레이터.

    사용법:
        @app.get("/predict")
        @cache("predict", ttl=3600)
        def predict(req: PredictRequest):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            r = get_redis()
            # request 객체 (FastAPI)는 캐시 키에서 제외
            cache_kwargs = {k: v for k, v in kwargs.items()
                           if not hasattr(v, "client")}  # Request 제외
            key = _make_key(prefix, **cache_kwargs)

            if r:
                try:
                    cached = r.get(key)
                    if cached:
                        log.debug("캐시 히트: %s", key)
                        return json.loads(cached)
                except Exception as e:
                    log.warning("캐시 읽기 실패: %s", e)

            result = func(*args, **kwargs)

            if r:
                try:
                    serialized = json.dumps(_serialize(result), ensure_ascii=False, default=str)
                    r.setex(key, ttl, serialized)
                    log.debug("캐시 저장: %s (TTL=%ds)", key, ttl)
                except Exception as e:
                    log.warning("캐시 쓰기 실패: %s", e)

            return result
        return wrapper
    return decorator


def invalidate(prefix: str):
    """특정 prefix의 캐시 전체 삭제 (재학습 후 호출)"""
    r = get_redis()
    if not r:
        return 0
    try:
        keys = r.keys(f"realestate:{prefix}:*")
        if keys:
            r.delete(*keys)
        log.info("캐시 무효화: %s (%d건)", prefix, len(keys))
        return len(keys)
    except Exception as e:
        log.warning("캐시 무효화 실패: %s", e)
        return 0


def invalidate_all():
    """전체 캐시 삭제"""
    r = get_redis()
    if not r:
        return 0
    try:
        keys = r.keys("realestate:*")
        if keys:
            r.delete(*keys)
        log.info("전체 캐시 삭제: %d건", len(keys))
        return len(keys)
    except Exception as e:
        log.warning("전체 캐시 삭제 실패: %s", e)
        return 0


def cache_stats() -> dict:
    """캐시 현황 반환 (health 엔드포인트용)"""
    r = get_redis()
    if not r:
        return {"enabled": False}
    try:
        info = r.info("memory")
        keys = r.keys("realestate:*")
        return {
            "enabled":     True,
            "total_keys":  len(keys),
            "used_memory": info.get("used_memory_human", "?"),
            "url":         REDIS_URL.split("@")[-1],  # 비밀번호 마스킹
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}
