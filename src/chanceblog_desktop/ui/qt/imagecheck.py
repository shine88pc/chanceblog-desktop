"""내 사진(로컬 이미지) 검사 — Qt 이미지 읽기(`QImageReader`)로 **진짜 이미지인지** 보고 규칙(`ui/core/imagerules.py`)에 따라 판정한다. 이미지 선택 창('i' 묶음)이 쓴다.

· 확장자만 믿지 않는다: `QImageReader.canRead()` 와 실제 형식(`format()`)을 본다(이름만 .jpg 인 GIF·텍스트 파일은 거절).
· EXIF 회전은 자동 적용(`setAutoTransform(True)`)한 크기로 판단하고, **원본 파일은 읽기만 한다**(쓰지 않는다). 화면용 썸네일은 메모리 안의 `QImage` 로 따로 만든다.
· 읽다가 실패해도 예외로 앱이 멈추지 않는다(읽지 못한 파일로 안내).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader

from ..core import imagerules as R


def _reader(path):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)                      # EXIF 회전 정보를 적용한다(원본 파일은 그대로)
    return reader


def probe(path):
    """`imagerules.judge` 에 넘길 읽기 도구 — 읽을 수 있는지·실제 형식·(회전 적용한)크기."""
    reader = _reader(path)
    if not reader.canRead():
        return R.Probe(False)
    return R.Probe(True, bytes(reader.format()).decode("ascii", "replace").lower(), *shown_size(reader))


def shown_size(reader):
    """회전을 적용한 (가로, 세로) — `QImageReader.size()` 는 저장된 크기라서, EXIF 가 90°·270° 회전 계열이면 가로·세로를 바꾼다."""
    size = reader.size()
    turn = reader.transformation()
    if int(getattr(turn, "value", turn)) & 4:                              # TransformationRotate90·270 과 그 거울·뒤집기 짝
        return size.height(), size.width()
    return size.width(), size.height()


def judge(path, **options):
    return R.judge(path, probe, **options)


def make_thumbnail(path, max_side=R.THUMB_MAX_SIDE):
    """화면에 보일 썸네일(`QImage`) — 읽을 수 없으면 None. 원본 파일은 쓰지 않는다.
    큰 JPEG·WebP 는 읽는 도중에 줄여서(`setScaledSize`) 메모리를 아끼지만, **PNG 에는 이 방법이 없어** 전체 크기로 읽은 뒤에 줄어든다 — 헤더만 큰 PNG(예: 8,000×8,000)는 그 크기만큼 메모리를 쓰고
    Qt 의 이미지 할당 한도(256MB)를 넘는 것은 읽기에 실패해 None 이 된다(`docs/UI_IMAGES.md` §6 — 이 묶음은 PNG 크기를 읽기 전에 따로 막지 않는다)."""
    reader = _reader(path)
    if not reader.canRead():
        return None
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > max_side:
        reader.setScaledSize(size.scaled(QSize(max_side, max_side), Qt.KeepAspectRatio))
    image = reader.read()
    return None if image.isNull() else image


def supported_formats():
    """이 PySide6 설치가 읽을 수 있는 이미지 형식 이름(소문자, 정렬). 설치 파일(Installer)에 JPG·PNG·WebP 읽기 플러그인이 들어갔는지 볼 때 쓴다."""
    return sorted(bytes(name).decode("ascii", "replace").lower() for name in QImageReader.supportedImageFormats())


def missing_required_formats():
    """지원해야 하는 형식(JPEG·PNG·WebP) 중 이 설치가 못 읽는 것 — 비어 있어야 정상."""
    have = set(supported_formats())
    return [name for name in ("jpeg", "png", "webp") if name not in have]
