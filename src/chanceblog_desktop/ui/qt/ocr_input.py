"""글자 읽기에 보낼 사진 한 장을 **메모리에서 읽고 줄이는** Qt 쪽(결정 D-513, 설계서 3-4·2-7, 시험 계획 T-H) — 사진 경로를 받아 `(너비, 높이, RGB 24비트 바이트)` 를 돌려준다. 디스크에 쓰는 것은 0이다.
읽기 도구(`imagecheck`)의 규칙을 그대로 따른다: `QImageReader` + `setAutoTransform(True)`(휴대폰 회전 정보를 적용 — 원본 파일은 읽기만 한다).

줄이는 방법(긴 변을 `size_name`(960 또는 1600) 이하로, 작은 사진은 늘리지 않는다):
  · JPG·WebP 는 `setScaledSize` 로 **읽는 도중에** 줄인다 — 큰 사진도 메모리를 아낀다(긴 변이 12,000px 를 넘어도 경고만 있고 줄여서 읽는다).
  · PNG 는 그런 길이 없어 전체를 읽은 뒤에 줄인다 — 그래서 가로x세로가 6천만 화소를 넘는 PNG 는 **읽기 전에** 거절한다(미리보기를 막는 기존 규칙 `photo_rules.preview_blocked` 와 같은 기준). 아주 큰 JPG·WebP(3억 화소 초과)도 같은 이유로 읽기 전에 거절한다.
  · 읽기에 실패한 큰 사진(할당 한도 초과)은 `OCR_TOO_BIG`, 그 밖의 읽기 실패는 `OCR_FAILED` 로 알린다(오류 코드뿐 — 경로·파일 이름이 오류에 들어가지 않는다).
RGB 바이트: Qt 이미지의 한 줄은 4바이트 정렬이라 줄마다 패딩이 있다 — 패딩을 빼고 이어 붙인다. 투명한 사진(PNG)은 **흰 바탕에 올린 뒤** 바꾼다(안 하면 투명 픽셀이 검게 되어 글자가 사라진다). EXIF 는 `QImage` 에 없어서 자연히 빠진다.
이 파일은 사진 경로를 읽기에만 쓰고 어디에도 적거나 되풀이하지 않으며, 파일을 쓰거나 지우는 호출·네트워크·하위 프로세스가 없다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

from ...errors import AppError
from ..core import photo_ocr_view as pov
from ..core import photo_rules as rules
from . import imagecheck

READ_PIXEL_LIMIT = 300_000_000            # PNG 가 아닌 사진(JPG·WebP)도 가로x세로가 이 값을 넘으면 읽지 않는다(스마트폰의 가장 큰 사진도 2억 화소 안쪽 — 읽는 도중 줄여도 읽는 시간이 길어지는 것을 막는 상한)


def long_side(size_name):
    """읽는 크기 이름(`"960"`·`"1600"`) → 긴 변 픽셀 수. 모르는 이름은 기본(960)이다."""
    return int(size_name) if size_name in pov.SIZES else int(pov.SIZE_NORMAL)


def _opaque(image):
    """투명한 픽셀이 있는 그림은 흰 바탕에 올린다 — 투명 픽셀이 검게 변해 글자가 사라지는 것을 막는다. 투명하지 않으면 그대로."""
    if not image.hasAlphaChannel():
        return image
    flat = QImage(image.width(), image.height(), QImage.Format_RGB32)
    flat.fill(QColor(255, 255, 255))
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    return flat


def _packed(bits, width, height, stride):
    """RGB888 이미지의 바이트에서 줄마다의 패딩(4바이트 정렬)을 뺀다 → 길이가 `너비 x 높이 x 3` 인 바이트."""
    row = width * 3
    if stride == row:
        return bytes(bits[:row * height])
    return b"".join(bytes(bits[line * stride:line * stride + row]) for line in range(height))


def prepare(path, size_name=pov.SIZE_NORMAL):
    """사진 한 장 → `(너비, 높이, RGB 바이트)` — 휴대폰 회전을 적용하고 긴 변이 `size_name` 이하가 되게 줄인 것. 못 읽으면 `AppError`(`OCR_TOO_BIG`·`OCR_FAILED`)."""
    side = long_side(size_name)
    seen = imagecheck.judge(path)                                                 # 넣을 때 거른 것(확장자·크기·실제 형식 JPG·PNG·WebP)을 읽을 때도 다시 본다 — 이름만 .jpg 인 SVG·GIF·TIFF 는 읽지 않는다(독립 검증 S SP-4)
    if not seen.ok:
        raise AppError("OCR_FAILED")
    pixels = seen.width * seen.height
    if rules.preview_blocked(seen.format, seen.width, seen.height) or pixels > READ_PIXEL_LIMIT:
        raise AppError("OCR_TOO_BIG")                                             # 읽기 전에 거절한다 — PNG 는 읽은 뒤에야 줄일 수 있어 메모리를 크게 쓴다
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    stored = reader.size()
    if seen.format != "png" and stored.isValid() and max(stored.width(), stored.height()) > side:
        reader.setScaledSize(stored.scaled(QSize(side, side), Qt.KeepAspectRatio))      # JPG·WebP — 읽는 도중에 줄인다(저장된 방향 기준이라 회전은 읽은 뒤에 적용된다)
    image = reader.read()
    if image.isNull():
        raise AppError("OCR_TOO_BIG" if pixels > rules.PNG_PIXEL_LIMIT else "OCR_FAILED")
    if max(image.width(), image.height()) > side:
        image = image.scaled(QSize(image.width(), image.height()).scaled(QSize(side, side), Qt.KeepAspectRatio), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)      # PNG — 읽은 뒤에 줄인다
    rgb = _opaque(image).convertToFormat(QImage.Format_RGB888)
    if rgb.isNull() or rgb.width() < 1 or rgb.height() < 1:
        raise AppError("OCR_FAILED")
    return rgb.width(), rgb.height(), _packed(rgb.constBits(), rgb.width(), rgb.height(), rgb.bytesPerLine())


__all__ = ["READ_PIXEL_LIMIT", "long_side", "prepare"]
