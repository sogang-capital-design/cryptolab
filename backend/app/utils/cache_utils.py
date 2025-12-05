import hashlib
import json
import os
import pickle
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger


def _get_data_path() -> str:
    """data 디렉토리 경로를 반환합니다."""
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "data"))
    return data_dir


# 캐시 디렉토리 설정 - data/cache 폴더에 저장
_data_path = _get_data_path()
CACHE_DIR = Path(os.path.join(_data_path, "cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def generate_cache_key(prefix: str, **kwargs) -> str:
    """
    캐시 키를 생성합니다.

    Args:
        prefix: 캐시 키 접두사 (예: 'ohlcv', 'score_chart')
        **kwargs: 캐시 키에 포함할 파라미터들

    Returns:
        생성된 캐시 키
    """
    # 파라미터를 정렬하여 일관된 키 생성
    sorted_params = json.dumps(kwargs, sort_keys=True, default=str)
    param_hash = hashlib.md5(sorted_params.encode()).hexdigest()
    return f"{prefix}:{param_hash}"


def _get_cache_file_path(key: str) -> Path:
    """캐시 파일 경로를 반환합니다."""
    # 안전한 파일명 생성 (prefix와 hash 분리)
    safe_key = key.replace(":", "_").replace("/", "_")
    return CACHE_DIR / f"{safe_key}.cache"


def get_cached(key: str) -> Optional[Any]:
    """
    캐시에서 값을 가져옵니다.

    Args:
        key: 캐시 키

    Returns:
        캐시된 값 또는 None
    """
    try:
        cache_file = _get_cache_file_path(key)
        if not cache_file.exists():
            logger.info(f"Cache miss: {key}")
            return None

        with open(cache_file, 'rb') as f:
            value = pickle.load(f)

        logger.info(f"Cache hit: {key}")
        return value
    except Exception as e:
        logger.error(f"Cache get error for {key}: {e}")
        return None


def set_cached(key: str, value: Any) -> bool:
    """
    값을 캐시에 저장합니다.

    Args:
        key: 캐시 키
        value: 저장할 값

    Returns:
        성공 여부
    """
    try:
        cache_file = _get_cache_file_path(key)

        with open(cache_file, 'wb') as f:
            pickle.dump(value, f)

        logger.info(f"Cache set: {key}")
        return True
    except Exception as e:
        logger.error(f"Cache set error for {key}: {e}")
        return False


def delete_cached(pattern: str) -> int:
    """
    패턴과 일치하는 캐시를 삭제합니다.

    Args:
        pattern: 삭제할 캐시 키 패턴 (예: 'ohlcv:*', '*' for all)

    Returns:
        삭제된 파일의 개수
    """
    try:
        # 패턴을 glob 패턴으로 변환
        glob_pattern = pattern.replace(":", "_").replace("*", "*")
        if not glob_pattern.endswith("*"):
            glob_pattern += "*"
        glob_pattern += ".cache"

        deleted_count = 0
        for cache_file in CACHE_DIR.glob(glob_pattern):
            try:
                cache_file.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete {cache_file}: {e}")

        if deleted_count > 0:
            logger.info(f"Cache deleted: {deleted_count} files matching '{pattern}'")
        return deleted_count
    except Exception as e:
        logger.error(f"Cache delete error: {e}")
        return 0


def cache_response(prefix: str):
    """
    API 응답을 캐시하는 데코레이터

    Args:
        prefix: 캐시 키 접두사

    Example:
        @cache_response(prefix="ohlcv")
        async def get_ohlcv(req: OHLCVRequest):
            # ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 요청 객체에서 파라미터 추출
            cache_params = {}
            for arg in args:
                if hasattr(arg, 'model_dump'):
                    cache_params.update(arg.model_dump())
            cache_params.update(kwargs)

            # 캐시 키 생성
            cache_key = generate_cache_key(prefix, **cache_params)

            # 캐시 확인
            cached_result = get_cached(cache_key)
            if cached_result is not None:
                # Pydantic 모델로 변환
                if hasattr(func, '__annotations__') and 'return' in func.__annotations__:
                    return_type = func.__annotations__['return']
                    try:
                        return return_type(**cached_result)
                    except:
                        return cached_result
                return cached_result

            # 실제 함수 실행
            result = await func(*args, **kwargs)

            # 결과 캐시 저장
            if result:
                try:
                    if hasattr(result, 'model_dump'):
                        set_cached(cache_key, result.model_dump())
                    else:
                        set_cached(cache_key, result)
                except Exception as e:
                    logger.error(f"Failed to cache result: {e}")

            return result
        return wrapper
    return decorator


def cache_task_result(prefix: str):
    """
    Celery 태스크 결과를 캐시하는 데코레이터

    Args:
        prefix: 캐시 키 접두사

    Example:
        @celery_app.task(bind=True)
        @cache_task_result(prefix="score_chart")
        def score_chart_task(self, coin_symbol, timeframe, inference_time, history_window):
            # ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Celery task with bind=True인 경우 첫 번째 인자(self)는 캐시 키에서 제외
            cache_args = args
            if len(args) > 0 and hasattr(args[0], 'request'):
                # 첫 번째 인자가 Celery task instance인 경우 제외
                cache_args = args[1:]

            # 캐시 키 생성
            cache_params = {f"arg_{i}": arg for i, arg in enumerate(cache_args)}
            cache_params.update(kwargs)
            cache_key = generate_cache_key(prefix, **cache_params)

            # 캐시 확인
            cached_result = get_cached(cache_key)
            if cached_result is not None:
                return cached_result

            # 실제 함수 실행
            result = func(*args, **kwargs)

            # 결과 캐시 저장
            if result:
                set_cached(cache_key, result)

            return result
        return wrapper
    return decorator
