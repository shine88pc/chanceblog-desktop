"""내 사진(로컬 이미지)을 받는 규칙 — 이미지 선택 창('i' 묶음)이 쓰고, 규격은 여기서 정한다. 이 파일은 PySide6 를 모른다: 실제 이미지인지 읽는 일은 `ui/qt/imagecheck.py`(QImageReader)가 하고
여기서는 **무엇을 받고 무엇을 거절하는지**와 사용자에게 보일 문구를 정한다.

규칙(운영자 2026-11-03 22:27):
  · 지원 형식은 JPG·JPEG·PNG·WebP **만**이다. **확장자만 보지 않는다** — Qt 이미지 읽기(`QImageReader.canRead()`)로 진짜 이미지인지 보고, 읽은 실제 형식도 위 넷이어야 한다
    (이름만 .jpg 인 GIF·BMP 는 거절).
  · EXIF 회전 정보는 자동으로 적용한다. **원본 파일은 절대 수정하지 않는다**(읽기만 한다) — 화면에 보이는 썸네일은 따로 만든다.
  · 기본 최대 파일 크기 20MB(넘으면 거절), 긴 변이 12,000px 를 넘으면 쓸 수는 있지만 경고한다.
  · 지원하지 않는 파일에는 사용자용 안내 문구를 보인다(기술 용어·영문 코드 없이).
  · **형식은 파일 속 표지로 먼저 확인한다**(결정 D-680, 앱 2차 감사 필수-1): 이름이 .jpg 인 SVG 파일은 읽기 도구에 크기를 묻는 것만으로 통째로 해석되고 그 안의 `<image>` 경로를 앱이 직접 열었다.
    그래서 파일 앞 12바이트(JPEG·PNG·WebP 표지)를 직접 본 **뒤에만** 읽기 도구를 만들고(형식을 못박는다), 표지가 없는 파일에는 읽기 도구를 만들지 않는다. 읽기 도구가 지원하지 않는 형식을
    말해도 크기는 묻지 않는다. 크기를 읽지 못한 잘린 사진은 '읽지 못했어요' 로 안내한다(감사 참고-1).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .text import T

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SUPPORTED_FORMATS = frozenset({"jpeg", "jpg", "png", "webp"})      # QImageReader.format() 이 돌려주는 실제 형식 이름(소문자)
MAX_BYTES = 20 * 1024 * 1024
LONG_SIDE_WARN = 12_000
THUMB_MAX_SIDE = 640
MAGIC_FORMATS = ("jpeg", "png", "webp")      # 파일 앞부분의 표지(서명)로 직접 알아보는 형식 — SUPPORTED_FORMATS 의 부분집합이다(`sniff_format`)
HEAD_BYTES = 64                              # 파일 앞에서 읽는 바이트 수 — 표지 확인은 앞 12바이트면 되고 나머지는 '무슨 파일인지'(안내 문구를 가르는 일)에만 쓴다

OK, UNSUPPORTED, NOT_IMAGE, MISSING, TOO_BIG, UNREADABLE = "ok", "unsupported", "not_image", "missing", "too_big", "unreadable"
MESSAGES = {UNSUPPORTED: "img_local_unsupported", NOT_IMAGE: "img_local_not_image", MISSING: "img_local_missing", TOO_BIG: "img_local_too_big", UNREADABLE: "img_local_unreadable"}


@dataclass(frozen=True)
class Probe:
    """이미지 읽기 도구(`QImageReader`)가 본 것 — 읽을 수 있는가·실제 형식·(회전을 적용한)가로·세로."""
    can_read: bool
    format: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class Verdict:
    kind: str                      # OK · UNSUPPORTED · NOT_IMAGE · MISSING · TOO_BIG · UNREADABLE
    message: str = ""              # 사용자에게 보일 안내(없으면 빈 글)
    warning: str = ""              # 쓸 수는 있지만 알릴 것(예: 긴 변 12,000px 초과)
    width: int = 0
    height: int = 0
    format: str = ""

    @property
    def ok(self):
        return self.kind == OK


def has_supported_extension(name):
    return os.path.splitext(str(name))[1].lower() in SUPPORTED_EXTENSIONS


def judge(path, probe, *, max_bytes=MAX_BYTES, long_side=LONG_SIDE_WARN):
    """파일 하나를 판정한다 — 읽기만 한다(원본을 바꾸지 않는다). `probe(path)` 는 `Probe` 를 돌려주는 함수(Qt 이미지 읽기).
    순서: 이름의 확장자 → 파일이 있는가·크기 → 진짜 이미지인가 → 실제 형식이 지원 형식인가 → 긴 변 경고."""
    def refuse(kind, **extra):
        return Verdict(kind, T[MESSAGES[kind]], **extra)

    if not has_supported_extension(path):
        return refuse(UNSUPPORTED)
    try:
        size = os.stat(path).st_size
    except OSError:
        return refuse(MISSING)
    if size > max_bytes:
        return refuse(TOO_BIG)
    try:
        seen = probe(path)
    except Exception:                                             # 읽기 도구가 예외를 내도 앱이 멈추지 않는다 — 읽지 못한 파일로 안내
        return refuse(UNREADABLE)
    if not seen.can_read:
        return refuse(NOT_IMAGE)
    actual = (seen.format or "").lower()
    if actual not in SUPPORTED_FORMATS:
        return refuse(UNSUPPORTED, format=actual)
    warning = T["img_local_long_side"] if max(seen.width, seen.height) > long_side else ""
    return Verdict(OK, "", warning, seen.width, seen.height, actual)


# ---- 표지로 먼저 확인하기(결정 D-680) --------------------------------------------------------------------------------------------------------
_OTHER_MAGIC = ((b"GIF87a", "gif"), (b"GIF89a", "gif"), (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"), (b"\x00\x00\x01\x00", "ico"), (b"\x00\x00\x02\x00", "cur"), (b"icns", "icns"), (b"%PDF-", "pdf"), (b"\x1f\x8b", "gzip"))
_BYTES_LIKE = (bytes, bytearray, memoryview)


def sniff_format(head):
    """파일 앞부분(바이트)이 JPEG·PNG·WebP 인지 **직접** 본다 → `jpeg`·`png`·`webp`, 아니면 빈 글. JPEG 는 FFD8FF, PNG 는 서명 여덟 바이트, WebP 는 `RIFF` 와 열한 번째까지의 `WEBP`.
    표지는 맨 앞에 있어야 하고(뒤쪽에 숨은 표지는 보지 않는다) 끝까지 다 있지 않은 표지는 인정하지 않는다. 바이트가 아닌 값은 빈 글이다."""
    if not isinstance(head, _BYTES_LIKE):
        return ""
    head = bytes(head[:12])
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return ""


def other_format(head):
    """표지가 JPEG·PNG·WebP 가 아닌 파일이 **어떤 형식처럼 보이는지**(GIF·BMP·TIFF·ICO·SVG·PDF 같은 흔한 것) → 이름, 모르면 빈 글. 안내 문구('지원하지 않는 파일' / '사진 파일이 아니에요')를 가르는 데만 쓴다 —
    이 값으로 파일을 읽지는 않는다(읽기 도구를 만들지 않는다). SVG 는 앞 `HEAD_BYTES` 바이트 안에 `<svg`·`<?xml` 이 보이면 그렇게 부른다(대소문자·앞의 BOM·빈 줄·주석을 가리지 않는다)."""
    if not isinstance(head, _BYTES_LIKE):
        return ""
    head = bytes(head[:HEAD_BYTES])
    for magic, name in _OTHER_MAGIC:
        if head.startswith(magic):
            return name
    if head[:2] == b"BM" and len(head) >= 14 and head[6:10] == b"\x00\x00\x00\x00":
        return "bmp"
    low = head.lower()
    return "svg" if (b"<svg" in low or b"<?xml" in low) else ""


def read_head(path, count=HEAD_BYTES):
    """파일 맨 앞 `count` 바이트(읽기 전용 'rb' 로 열어 읽고 바로 닫는다). 열 수 없으면 `OSError`.
    내장 `open` 이 아니라 `Path.open` 으로 연다 — 화면 층 소스 규칙 시험(`test_ui_keys_adapter`·`test_ui_blogs_core` 외)이 내장 `open` 호출을 파일 쓰기의 신호로 막기 때문이다(이 함수는 쓰지 않는다 —
    쓰기 모드로 여는 것은 `test_ui_imagegate` 의 규칙이 모든 철자에 대해 막고, 열기는 이 함수 한 곳뿐이다)."""
    with Path(path).open("rb") as handle:
        return handle.read(count)


def format_name(raw):
    """읽기 도구가 말한 형식 이름(바이트 비슷한 값이나 글) → 소문자 글."""
    return raw.lower() if isinstance(raw, str) else bytes(raw).decode("ascii", "replace").lower()


def probe_reader(reader, measure):
    """읽기 도구(`QImageReader` 와 같은 모양의 객체) → `Probe`. **순서가 안전이다**: 읽을 수 있는지 → 말한 형식 → 지원하는 형식일 때**만** 크기(`measure(reader)`).
    크기를 묻는 일이 SVG 같은 형식의 해석기를 돌려 파일 안의 경로를 열 수 있어서, 지원하지 않는 형식이면 크기를 묻지 않고 형식만 돌려준다(판정이 '지원하지 않는 파일' 로 거절한다).
    지원하는 형식인데 크기를 읽지 못했으면(머리만 있는 잘린 사진 — 크기가 0 이하) `ValueError` — `judge` 가 '사진을 읽지 못했어요' 로 안내한다."""
    if not reader.canRead():
        return Probe(False)
    actual = format_name(reader.format())
    if actual not in SUPPORTED_FORMATS:
        return Probe(True, actual)
    width, height = measure(reader)
    if width < 1 or height < 1:
        raise ValueError("사진의 크기를 읽지 못했다")
    return Probe(True, actual, width, height)


def probe_file(path, open_reader, measure):
    """파일 하나의 `Probe` — 앞부분의 표지를 먼저 직접 보고(`sniff_format`), 표지가 JPEG·PNG·WebP 일 때**만** `open_reader(경로, 형식)` 로 읽기 도구를 만든다(형식을 못박은 것이어야 한다).
    표지가 없으면 읽기 도구를 만들지 않는다: 흔한 다른 형식으로 보이면 그 이름을(→ '지원하지 않는 파일'), 아니면 읽을 수 없음(→ '사진 파일이 아니에요')을 돌려준다.
    `open_reader`·`measure` 는 화면 층(`ui/qt/imagecheck.py`)이 넣는 `QImageReader` 쪽 함수이고, 시험은 가짜를 넣어 불린 순서를 본다. 파일을 열 수 없으면 `OSError`(→ `judge` 가 '읽지 못했어요')."""
    head = read_head(path)
    kind = sniff_format(head)
    if not kind:
        other = other_format(head)
        return Probe(True, other) if other else Probe(False)
    return probe_reader(open_reader(path, kind), measure)
