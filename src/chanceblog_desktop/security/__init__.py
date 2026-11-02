"""비밀 가리기·보안 저장소 접근(키는 소스·로그·내보내기·DB 에 쓰지 않는다 — docs/SECURITY.md)."""
from .mask import MAX_LOG_CHARS, safe_detail
from .mask import mask as mask_text         # 함수 이름 `mask` 를 패키지에 그대로 올리면 `security.mask`(모듈)을 가려 `import …security.mask as m` 이 함수가 된다

__all__ = ["MAX_LOG_CHARS", "mask_text", "safe_detail"]
