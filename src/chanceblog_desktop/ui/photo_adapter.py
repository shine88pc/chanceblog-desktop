"""'사진 정리'의 실제 공급자(사진 연동 2단계, 결정 D-499) — 사진 파일을 **읽기만** 하는 얇은 어댑터다. 파일 판정은 화면 층의 이미지 읽기(`ui/qt/imagecheck.py` — `QImageReader` 로 진짜 이미지인지·실제 형식·EXIF 회전을 적용한 크기)와
`ui/core/imagerules.py`(JPG·JPEG·PNG·WebP 만·20MB·긴 변 12,000px 경고)를 그대로 쓰고, 목록 전체가 아직 그 자리에 있는지는 서비스(`service/photo_manifest.py` 의 `check_files` — 경로 위 폴더까지 `lstat` 으로 링크·클라우드 파일을 보고 `imagerules.judge` 에 판정을 맡긴다)를 부른다.
**이 어댑터는 파일을 만들거나 쓰거나 지우거나 복사하지 않는다**(읽기뿐 — 사진 목록의 저장은 3단계). 화면 코드(`ui/qt`·`ui/core`)에도 그런 호출이 없다. 이미지 읽기(Qt)는 쓰는 함수 안에서 늦게 가져오므로 이 모듈은 PySide6 없이도 가져온다(시험은 읽기 도구를 바꿔 끼운다).
**경로·파일 이름은 어디에도 되풀이하지 않는다** — 돌려주는 값(`Verdict`·`FileState`)에는 경로가 없고, 읽기 도구가 예외를 내면 그대로 올리지 않고 부른 쪽(`PhotoBoard`)이 고정 문장으로 바꾼다(오류 기록·로그에 나가지 않는다). 이 모듈은 AI·네트워크·하위 프로세스·표준 출력을 쓰지 않는다.
"""
from __future__ import annotations

from ..service import photo_manifest as service
from .core.photo_view import FileState, PhotoProvider


class ServicePhotoProvider(PhotoProvider):
    """사진 파일을 읽기만 한다. `judge`·`probe` 는 시험이 바꿔 끼우는 자리 — 주지 않으면 Qt 이미지 읽기(`imagecheck`)를 늦게 가져와 쓴다."""
    sample = False

    def __init__(self, *, judge=None, probe=None):
        self._judge, self._probe = judge, probe

    @staticmethod
    def _imagecheck():
        from .qt import imagecheck                                       # 늦게 가져온다(PySide6 가 있는 화면 층에서만 쓴다)
        return imagecheck

    def judge(self, path):
        """파일 하나의 판정(`imagerules.Verdict`) — 읽기만 한다(원본을 바꾸지 않는다)."""
        return (self._judge or self._imagecheck().judge)(path)

    def check(self, manifest):
        """목록의 사진 파일이 아직 있는지(읽기만) → `(FileState, …)`. 읽기 도구로 진짜 이미지인지·실제 형식·크기까지 본다."""
        results = service.check_files(manifest, probe=self._probe or self._imagecheck().probe)
        return tuple(FileState(item.photo_id, item.state, item.message, item.warning, item.width, item.height, item.format, item.verified) for item in results)


__all__ = ["ServicePhotoProvider"]
