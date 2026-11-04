"""내 사진(로컬 이미지) 형식별 로딩 점검표 — 임시 폴더에 형식별 시험 파일을 만들어 `QImageReader.canRead()`·실제 형식·판정(`ui/core/imagerules.py`)을 표로 보여 준다. 창을 띄우지 않는다(offscreen).

실행: python scripts/ui_image_check.py            (PySide6 가 있는 파이썬으로 — 표를 마크다운으로 출력)
표의 행: JPG·JPEG·PNG·WebP(지원) · 지원하지 않는 형식(GIF·BMP) · 확장자만 바꾼 가짜 · 20MB 초과 · 긴 변 12,000px 초과 · EXIF 회전. 원본 파일이 바뀌지 않았는지(해시)도 확인한다.
설치 파일(Installer)에 JPG·PNG·WebP 읽기 플러그인이 들어갔는지는 설치 마무리 단계의 시험 항목이다 — 여기서는 지금 환경의 `supportedImageFormats()` 와 플러그인 폴더 파일을 보여 준다.
"""
from __future__ import annotations

import hashlib
import os
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GIF_1X1 = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


def exif_orientation(jpeg_bytes, orientation):
    """JPEG 바로 뒤에 EXIF 방향 값만 담은 APP1 조각을 끼워 넣는다(시험 파일 만들기 — Qt 는 EXIF 를 쓰지 못한다)."""
    tiff = b"MM\x00\x2a\x00\x00\x00\x08" + b"\x00\x01" + b"\x01\x12\x00\x03\x00\x00\x00\x01" + struct.pack(">H", orientation) + b"\x00\x00" + b"\x00\x00\x00\x00"
    body = b"Exif\x00\x00" + tiff
    return jpeg_bytes[:2] + b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body + jpeg_bytes[2:]


def build_cases(folder):
    """(이름, 경로, 기대 판정 종류, 설명) 목록을 만든다. 파일은 `folder` 안에만 쓴다."""
    from PySide6.QtGui import QColor, QImage
    from chanceblog_desktop.ui.core import imagerules as R
    folder = Path(folder)

    def picture(width, height):
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(120, 160, 220))
        return image

    cases = []

    def add(label, name, expected, note, data=None, image=None):
        path = folder / name
        if image is not None:
            assert image.save(str(path)), name
        elif data is not None:
            path.write_bytes(data)
        cases.append((label, str(path), expected, note))

    for label, name in (("JPG", "photo.jpg"), ("JPEG", "photo.jpeg"), ("PNG", "photo.png"), ("WebP", "photo.webp")):
        add(label, name, R.OK, "지원 형식", image=picture(64, 48))
    add("GIF", "anim.gif", R.UNSUPPORTED, "지원하지 않는 형식(이름)", data=GIF_1X1)
    add("BMP", "plain.bmp", R.UNSUPPORTED, "지원하지 않는 형식(이름)", image=picture(8, 8))
    add("가짜(글자 파일을 .png 로)", "fake_text.png", R.NOT_IMAGE, "확장자만 사진", data="사진이 아닙니다".encode("utf-8") * 20)
    add("가짜(GIF 를 .jpg 로)", "fake_gif.jpg", R.UNSUPPORTED, "진짜 형식이 GIF", data=GIF_1X1)
    add("PNG 를 .jpg 로", "png_named.jpg", R.OK, "진짜 형식이 PNG 라 통과", data=_png_bytes(picture(16, 16)))
    big = folder / "toobig.jpg"
    with open(big, "wb") as handle:
        handle.truncate(R.MAX_BYTES + 1)
    cases.append(("20MB 초과", str(big), R.TOO_BIG, "20MB(20,971,520바이트) 넘음"))
    add("긴 변 12,001px(PNG)", "wide.png", R.OK, "쓸 수 있고 경고", image=_gray(12_001, 8))
    add("긴 변 13,000px(WebP)", "tall.webp", R.OK, "쓸 수 있고 경고", image=_gray(8, 13_000))
    jpeg = _jpeg_bytes(picture(40, 20))
    add("EXIF 회전 없음(40x20)", "plain_exif.jpg", R.OK, "가로 40 세로 20", data=jpeg)
    add("EXIF 회전 6(40x20 로 저장)", "rotated.jpg", R.OK, "자동 회전 → 가로 20 세로 40", data=exif_orientation(jpeg, 6))
    return cases


def _gray(width, height):
    from PySide6.QtGui import QImage
    image = QImage(width, height, QImage.Format_Grayscale8)
    image.fill(180)
    return image


def _png_bytes(image):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def _jpeg_bytes(image):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "JPEG", 90)
    return bytes(data)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(path, imagecheck):
    """(읽을 수 있나, 실제 형식, (가로, 세로)) — 읽기 도구는 이 함수 안에서만 파일을 연다(끝나면 닫힌다)."""
    reader = imagecheck._reader(path)
    can_read = reader.canRead()
    return can_read, (bytes(reader.format()).decode("ascii", "replace") if can_read else "-"), (imagecheck.shown_size(reader) if can_read else None)


def plugin_files():
    from PySide6.QtCore import QLibraryInfo
    folder = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / "imageformats"
    return sorted(item.name for item in folder.glob("*")) if folder.is_dir() else []


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(HERE.parent / "src"))
    from PySide6.QtGui import QGuiApplication
    from chanceblog_desktop.ui.qt import imagecheck
    app = QGuiApplication.instance() or QGuiApplication(["ui_image_check"])
    print("| 종류 | 이름 | 읽을 수 있나(canRead) | 실제 형식 | 크기(회전 적용) | 판정 | 경고 | 기대와 같음 | 원본 불변 |")
    print("|---|---|---|---|---|---|---|---|---|")
    rows = 0
    with tempfile.TemporaryDirectory() as tmp:
        for label, path, expected, _note in build_cases(tmp):
            before = digest(path) if os.path.getsize(path) < 10_000_000 else None
            can_read, fmt, size = inspect(path, imagecheck)
            verdict = imagecheck.judge(path)
            after = digest(path) if before is not None else None
            same = "예" if before == after else "아니오"
            print(f"| {label} | {Path(path).name} | {'예' if can_read else '아니오'} | {fmt} | {f'{size[0]}x{size[1]}' if size is not None else '-'} | {verdict.kind} | {'있음' if verdict.warning else '-'} | {'예' if verdict.kind == expected else '**아니오**'} | {same if before is not None else '(큰 파일은 해시 생략 — 크기·수정 시각 불변)'} |")
            rows += 1
    print()
    print("`QImageReader.supportedImageFormats()` =", ", ".join(imagecheck.supported_formats()))
    print("필수(jpeg·png·webp) 중 못 읽는 것 =", imagecheck.missing_required_formats() or "없음")
    print("플러그인 폴더(imageformats) 파일 =", ", ".join(plugin_files()))
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
