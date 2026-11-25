"""내 사진(로컬 이미지) 검사 — Qt 이미지 읽기(`QImageReader`)로 **진짜 이미지인지** 보고 규칙(`ui/core/imagerules.py`)에 따라 판정한다. 이미지 선택 창('i' 묶음)이 쓴다.

· 확장자만 믿지 않는다: **파일 앞 12바이트의 표지**(JPEG·PNG·WebP)를 직접 본 뒤에만 읽기 도구를 만들고 그 형식으로 못박는다(`open_checked`, 결정 D-680 — 이름만 .jpg 인 SVG 는 크기를 묻는 것만으로 안의 경로를 열었다).
  표지가 없는 파일(GIF·SVG·글자 …)에는 읽기 도구를 만들지 않고, 읽기 도구가 지원하지 않는 형식을 말해도 `size()` 는 부르지 않는다(`imagerules.probe_reader`).
· EXIF 회전은 자동 적용(`setAutoTransform(True)`)한 크기로 판단하고, **원본 파일은 읽기만 한다**(쓰지 않는다). 화면용 썸네일은 메모리 안의 `QImage` 로 따로 만든다.
· 읽다가 실패해도 예외로 앱이 멈추지 않는다(읽지 못한 파일로 안내).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader

from ..core import imagerules as R


def pinned_reader(path, kind, reader_class=None):
    """형식을 못박은 읽기 도구 — 자동 형식 추측을 끄고 `kind`(jpeg·png·webp)의 해석기만 쓴다. 파일 속 내용이 다른 형식(SVG 같은 것)이라도 그 해석기가 골라질 수 없다.
    `reader_class` 는 시험이 기록용 하위 종류를 끼우는 자리다(없으면 `QImageReader`)."""
    reader = (reader_class or QImageReader)(str(path), kind.encode("ascii"))
    reader.setAutoDetectImageFormat(False)             # 형식을 못박았으니 내용을 보고 다른 해석기를 고르지 않는다
    reader.setAutoTransform(True)                      # EXIF 회전 정보를 적용한다(원본 파일은 그대로)
    return reader


def open_checked(path, reader_class=None):
    """JPEG·PNG·WebP 로 **확인된** 파일의 `(읽기 도구, 형식)` — 파일 앞 12바이트를 직접 본 **뒤에만** 읽기 도구를 만든다. 표지가 없거나 파일을 열 수 없으면 `(None, "")`(읽기 도구를 만들지 않는다).
    크기를 묻거나 화소를 읽는 길(판정·미리보기·글자 읽기 입력)은 모두 여기를 지난다 — 읽기 직전에 다시 확인하므로 검사 뒤에 파일이 바뀌어도 다른 형식의 해석기가 돌지 않는다."""
    try:
        kind = R.sniff_format(R.read_head(path))
    except (OSError, ValueError):                                          # 열 수 없는 파일·널 글자가 든 경로 — 읽기 도구를 만들지 않는다
        return None, ""
    if not kind:
        return None, ""
    return pinned_reader(path, kind, reader_class), kind


def _reader(path):
    """점검표(`scripts/ui_image_check.py`)·시험이 쓰는 읽기 도구 — 표지를 확인한 파일만 형식을 못박아 만들고, 아니면 아무것도 읽지 못하는 빈 읽기 도구를 준다(`canRead()` 가 거짓)."""
    reader, _kind = open_checked(path)
    return reader if reader is not None else QImageReader()


def probe(path):
    """`imagerules.judge` 에 넘길 읽기 도구 — 읽을 수 있는지·실제 형식·(회전 적용한)크기. 표지를 먼저 보고(`imagerules.probe_file`) 지원하는 형식일 때만 크기를 묻는다."""
    return R.probe_file(path, pinned_reader, shown_size)


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
    reader, _kind = open_checked(path)
    if reader is None or not reader.canRead():
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
