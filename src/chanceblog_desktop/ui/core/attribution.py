"""사진 출처(Unsplash) — 화면 부품이 쓰는 규칙. 이미지 화면('i' 묶음)은 이 값을 쓰고, 부품의 규격은 여기서 정한다. PySide6 를 모른다.

규칙(운영자 2026-11-03 22:27):
  · **출처 복사는 두 줄**이다 — ① `Photo by <사진작가 이름> on Unsplash` ② **그 사진의 Unsplash 사진 페이지 주소 + UTM**. 둘째 줄에는 사진작가 프로필 주소가 아니라 **사진 페이지 주소**를 쓴다.
  · 사진 페이지 주소와 사진작가 프로필 주소는 **내부 메타데이터에 각각 따로** 저장한다(`PhotoCredit.metadata`).
  · 복사한 뒤 `출처 복사됨` 안내(토스트)를 보인다.
외부(Unsplash 응답)에서 온 이름·주소는 '데이터'다 — 길이·제어 문자를 정리하고 주소는 https 로 Unsplash 주소만 받는다(다른 주소·로그인 정보가 든 주소는 거절).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .text import T

UTM_SOURCE = "chanceblog_desktop"            # Unsplash 가 요구하는 `utm_source`(앱 이름) — 앱 등록 이름이 정해지면 바꾼다
UTM_MEDIUM = "referral"
ALLOWED_HOSTS = frozenset({"unsplash.com", "www.unsplash.com"})
MAX_NAME = 80
MAX_URL = 300
_HIDDEN = frozenset({"Cf", "Cc", "Cs", "Co", "Zl", "Zp"})


class CreditError(ValueError):
    """사진 출처 값이 올바르지 않다(이유만 담고 받은 값은 담지 않는다)."""


def clean_name(value):
    text = "".join(" " if unicodedata.category(ch) in _HIDDEN else ch for ch in str(value or ""))
    text = " ".join(text.split())
    if not text:
        raise CreditError("사진작가 이름이 비어 있다")
    return text if len(text) <= MAX_NAME else text[:MAX_NAME - 1] + "…"


def check_url(value, what="주소"):
    """Unsplash 의 https 주소만 받는다 — 로그인 정보·다른 주소·공백·제어 문자가 있으면 거절."""
    text = str(value or "").strip()
    if not text or len(text) > MAX_URL or re.search(r"[\s\x00-\x1f\x7f]", text):
        raise CreditError(f"{what}가 올바르지 않다")
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password or parts.port not in (None, 443):
        raise CreditError(f"{what}는 Unsplash 의 https 주소여야 한다")
    return text


def with_utm(url, source=UTM_SOURCE):
    """주소에 `utm_source`·`utm_medium=referral` 을 붙인다(이미 있는 utm 값은 바꾸고 다른 인자는 둔다)."""
    parts = urlsplit(check_url(url))
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith("utm_")]
    query += [("utm_source", source), ("utm_medium", UTM_MEDIUM)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


@dataclass(frozen=True)
class PhotoCredit:
    photographer_name: str
    photo_page_url: str                      # 그 사진의 Unsplash 사진 페이지 주소(UTM 붙이기 전)
    photographer_profile_url: str            # 사진작가 프로필 주소(따로 저장 — 출처 복사에는 쓰지 않는다)

    def __post_init__(self):
        object.__setattr__(self, "photographer_name", clean_name(self.photographer_name))
        object.__setattr__(self, "photo_page_url", check_url(self.photo_page_url, "사진 페이지 주소"))
        object.__setattr__(self, "photographer_profile_url", check_url(self.photographer_profile_url, "사진작가 프로필 주소"))

    def first_line(self):
        return T["credit_line"].format(name=self.photographer_name)

    def photo_link(self, source=UTM_SOURCE):
        return with_utm(self.photo_page_url, source)

    def profile_link(self, source=UTM_SOURCE):
        return with_utm(self.photographer_profile_url, source)

    def copy_text(self, source=UTM_SOURCE):
        """복사되는 글 — 두 줄: ① 'Photo by 이름 on Unsplash' ② 사진 페이지 주소 + UTM."""
        return f"{self.first_line()}\n{self.photo_link(source)}"

    def metadata(self):
        """내부 메타데이터 — 사진 페이지 주소와 사진작가 프로필 주소를 각각 따로 둔다."""
        return {"photographer_name": self.photographer_name, "photo_page_url": self.photo_page_url, "photographer_profile_url": self.photographer_profile_url}
