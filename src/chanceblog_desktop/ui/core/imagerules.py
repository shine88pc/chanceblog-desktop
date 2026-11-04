"""내 사진(로컬 이미지)을 받는 규칙 — 이미지 선택 창('i' 묶음)이 쓰고, 규격은 여기서 정한다. 이 파일은 PySide6 를 모른다: 실제 이미지인지 읽는 일은 `ui/qt/imagecheck.py`(QImageReader)가 하고
여기서는 **무엇을 받고 무엇을 거절하는지**와 사용자에게 보일 문구를 정한다.

규칙(운영자 2026-11-03 22:27):
  · 지원 형식은 JPG·JPEG·PNG·WebP **만**이다. **확장자만 보지 않는다** — Qt 이미지 읽기(`QImageReader.canRead()`)로 진짜 이미지인지 보고, 읽은 실제 형식도 위 넷이어야 한다
    (이름만 .jpg 인 GIF·BMP 는 거절).
  · EXIF 회전 정보는 자동으로 적용한다. **원본 파일은 절대 수정하지 않는다**(읽기만 한다) — 화면에 보이는 썸네일은 따로 만든다.
  · 기본 최대 파일 크기 20MB(넘으면 거절), 긴 변이 12,000px 를 넘으면 쓸 수는 있지만 경고한다.
  · 지원하지 않는 파일에는 사용자용 안내 문구를 보인다(기술 용어·영문 코드 없이).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .text import T

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SUPPORTED_FORMATS = frozenset({"jpeg", "jpg", "png", "webp"})      # QImageReader.format() 이 돌려주는 실제 형식 이름(소문자)
MAX_BYTES = 20 * 1024 * 1024
LONG_SIDE_WARN = 12_000
THUMB_MAX_SIDE = 640

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
