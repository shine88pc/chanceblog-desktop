"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)이 아는 값과 공급자의 모양 — 화면은 이 모양만 안다. 실제 서비스(`service/projects.py`·`review.py`)는 얇은 어댑터(`ui/posts_adapter.py`)가 같은 모양으로 맞추고, 메모리에서만 일하는 가짜(`post_fake.py`)가 예시·시험을 맡는다.

이 화면이 **글 저장소에 쓰는 일은 사용자가 눌렀을 때뿐이고 넷**이다 — 가져오기(`import_post`)·검토 시작(`review_post`)·승인(`approve_post`)·승인 취소(`revoke_post`). 그 앞의 파일 읽기(`read_import_file`)는 읽기뿐이다.
글 흐름 1b(D-642)가 쓰기 둘을 더한다 — 복사 표시(`mark_copied`)·발행 주소 기록(`record_published`) — 그래서 여섯이다. 읽기도 둘 늘었다: `load_history`(발행 기록)·`load_work_log`(작업 로그).
읽기(`load_posts`·`load_post`)는 파일도 폴더도 만들지 않는다. 모든 메서드는 **작업 스레드**에서 불린다(화면 스레드가 아니다). PySide6 도 파일도 서비스도 모른다.
글(제목·본문)은 값 객체의 `repr` 에 나오지 않는다(오류·로그에 글이 새지 않게).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .jobs import JobFailure

PAGES, NAVER_A, NAVER_B = "github_pages", "naver_a", "naver_b"
PLATFORMS = (PAGES, NAVER_A, NAVER_B)                                   # 이 화면이 다루는 플랫폼 — 서비스 `review.SUPPORTED` 와 같다(시험이 견준다). Blogger 는 이 흐름에 없다(1c 의 자리)
NAVER_PLATFORMS = (NAVER_A, NAVER_B)
KINDS = ("markdown", "html")                                            # 가져오기 종류
LANGS = ("ko", "en")
KINDS_OF_FAILURE = ("input", "secret", "check", "stale", "notfound", "state", "gate", "similarity", "profile", "locked", "disk", "io", "corrupt", "newer", "file", "other", "package", "address")


class PostFailure(JobFailure):
    """글 검토의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 화면이 다르게 다룰 종류(`kind`). `field`·`where`·`kinds` 는 문장 자리에 들어가는 **고정 이름**뿐(입력한 글이 아니다)."""

    def __init__(self, user_message, code="", *, kind="other", retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"


# ---- 목록·상세 ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PostRow:
    project_id: str
    title: str = field(repr=False)
    revision: int = 1
    updated_at: str = ""
    statuses: tuple = ()                                     # ((플랫폼, 상태), …) — 이 화면이 다루는 셋(`PLATFORMS` 순서). 글을 읽을 수 없으면 비어 있다
    error: str = ""                                          # 글을 읽지 못했을 때의 오류 코드('' 이면 정상)


@dataclass(frozen=True)
class PostsData:
    rows: tuple = ()
    profiles: tuple = ()                                     # 설정 파일에 프로필이 있는 네이버 블로그 열쇠들 — 검토를 켤 수 있는 네이버 블로그
    state: str = "ok"                                        # ok · missing(글 저장소 파일이 아직 없다 — 빈 목록)
    sample: bool = False
    offline: bool = False                                    # 예시에서만(실제 읽기는 네트워크를 쓰지 않는다)
    epoch: object = None                                     # 컨트롤러가 읽기를 시작할 때 붙이는 세대 번호 — 그 뒤에 쓰기가 끝났으면 이 값은 낡은 것이라 버린다(공급자는 비워 둔다)


@dataclass(frozen=True)
class PlatformStatus:
    platform: str
    status: str
    rendered_revision: object = None
    has_rendering: bool = False
    error_code: str = ""
    published_url: str = field(default="", repr=False)       # 직접 발행한 글의 주소(기록했을 때만 — 글 흐름 1b)
    published_at: str = ""                                   # 그 주소를 기록한 때(UTC 글, `2026-11-24T05:30:12Z` 모양)


@dataclass(frozen=True)
class PreviewBlock:
    kind: str                                                # heading · paragraph · list · quote
    text: str = field(default="", repr=False)                # 이미 가린 글(목록·인용은 여러 줄)


@dataclass(frozen=True)
class PostPreview:
    blocks: tuple = ()
    total: int = 0                                           # 전체 문단(블록) 수
    chars: int = 0                                           # 본문 글자 수(공백 제외, 서식 기호 제외)
    images: int = 0                                          # 이미지 자리 수(그리지 않는다)
    refs: int = 0                                            # 출처 수
    cut: bool = False                                        # 앞부분만 보이나

    @property
    def shown(self):
        return len(self.blocks)


@dataclass(frozen=True)
class NaverPackageInfo:
    """저장된 네이버 복사 패키지의 화면용 모습(글 흐름 1b, D-643) — 복사 준비됨·복사함인 블로그 하나의 것이다. **그 블로그의 것만** 담는다(A 와 B 는 각자 따로 읽는다). 글은 `repr` 에 나오지 않는다.
    복사할 글(`title`·`body`·`tags`·`copy_text`)은 이 값이 만들어질 때(작업 스레드) 키·토큰 모양을 미리 검사했고, 모양이 있는 것은 `blocked` 에 열쇠가 들어 있다 — 그 복사는 하지 않는다."""
    platform: str
    title: str = field(default="", repr=False)                # 복사할 제목
    body: str = field(default="", repr=False)                 # 복사할 본문(평문)
    tags: str = field(default="", repr=False)                 # 복사할 태그(`#태그 #태그`)
    copy_text: str = field(default="", repr=False)            # 전체 복사 글(제목·본문·태그·이미지 자리·체크리스트·주의)
    chars: int = 0
    paragraphs: int = 0
    images: int = 0
    category: str = field(default="", repr=False)
    warnings: tuple = field(default=(), repr=False)
    checklist: tuple = field(default=(), repr=False)
    blocked: tuple = ()                                      # 키·토큰 모양이 있어 복사하지 않는 것들의 열쇠(`title`·`body`·`tags`·`all`)
    sample: bool = False


@dataclass(frozen=True)
class PostDetail:
    project_id: str
    title: str = field(repr=False)
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    platforms: tuple = ()                                    # PlatformStatus × `PLATFORMS` 순서
    preview: object = None                                   # PostPreview
    sample: bool = False
    epoch: object = None                                     # 읽기 세대 번호(`PostsData.epoch` 와 같다)
    packages: tuple = field(default=(), repr=False)          # NaverPackageInfo — 복사 준비됨·복사함인 네이버 블로그마다 하나(글 흐름 1b)

    def platform(self, key):
        return next((item for item in self.platforms if item.platform == key), None)

    def package(self, key):
        return next((item for item in self.packages if item.platform == key), None)


# ---- 검토 ------------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SimilarityInfo:
    level: str = "ok"                                        # ok · warn · high — 서비스 `SimilarityReport.level`
    overall: float = 0.0
    reasons: tuple = ()                                      # 서비스가 쓴 이유 글(비밀 모양을 가린 뒤 보인다)

    @property
    def blocks(self):
        return self.level == "high"


@dataclass(frozen=True)
class ReviewReport:
    """`검토 시작` 이 돌려준 결과 — 발행 전 검사·건강 효과 단정·비밀 모양과 플랫폼 글 요약. 글은 담지 않는다(이름·숫자·고정 코드뿐)."""
    project_id: str
    platform: str
    revision: int
    status: str                                              # 검토 뒤의 플랫폼 상태(보통 REVIEW_REQUIRED)
    gate_ok: bool = True                                     # Pages 발행 전 검사 통과(네이버는 관문이 없어 늘 True)
    gate_codes: tuple = ()                                   # 걸린 검사 코드들(처음 나온 순서, 중복 없음)
    gate_details: tuple = ()                                 # 서비스가 쓴 사유 글(가린 뒤 줄였다) — 접힌 자세히에만 쓴다
    warnings: tuple = ()                                     # 참고(막지 않는다)
    summary: tuple = ()                                      # 만든 글의 한 줄 요약 글들(분야·언어·크기, 제목·글자 수 …)
    similarity: object = None                                # SimilarityInfo 또는 None
    health: object = None                                    # `draft_rules.HealthReview` (단계·막힘 문장 앞부분)
    spots: tuple = ()                                        # ((칸 이름, 줄, 유형 이름), …) — 키·토큰 모양이 있는 위치와 유형뿐(글 자체는 어디에도 없다)
    sample: bool = False
    pages: object = field(default=None, repr=False)          # 이 검토가 쓴 Pages 값(`PagesValues`) — 한 줄 설명·태그의 건강 판정이 이 값에 걸렸고, 승인 요청이 같은 값을 들고 가 승인 직전 재검사가 다시 건다(글 흐름 1b, D-652)


@dataclass(frozen=True)
class ImportFile:
    name: str = field(default="", repr=False)                # 보이는 파일 이름(확장자를 뗀 것 — 제목 칸의 제안)
    text: str = field(default="", repr=False)
    chars: int = 0
    encoding: str = "utf-8"


@dataclass(frozen=True)
class ImportRequest:
    kind: str
    title: str = field(repr=False)
    body: str = field(repr=False)


@dataclass(frozen=True)
class PagesValues:
    category: str = field(default="", repr=False)
    lang: str = ""
    image_url: str = field(default="", repr=False)
    tags: tuple = field(default=(), repr=False)
    description: str = field(default="", repr=False)


@dataclass(frozen=True)
class ReviewRequest:
    project_id: str
    platform: str
    pages: object = None                                     # PagesValues(Pages 일 때)


@dataclass(frozen=True)
class ApproveRequest:
    project_id: str
    platform: str
    revision: int                                            # 사용자가 검토 결과를 읽은 글의 판 — 다르면 승인하지 않는다
    similarity_ack: bool = False                             # 두 블로그 글이 많이 비슷한 것을 알고도 승인한다(센 확인창을 거쳤을 때만 참 — 글 흐름 1b, D-646)
    pages: object = field(default=None, repr=False)          # 검토가 쓴 Pages 값 — 승인 직전 건강 효과 단정 재검사가 같은 값을 건다(D-652)


@dataclass(frozen=True)
class RevokeRequest:
    project_id: str
    platform: str


@dataclass(frozen=True)
class CopiedRequest:
    """`복사했어요`(copied 참 — 복사 준비됨 → 복사함) 또는 `복사 표시 취소`(거짓 — 복사함 → 복사 준비됨) — 글 흐름 1b."""
    project_id: str
    platform: str
    copied: bool = True


@dataclass(frozen=True)
class RecordRequest:
    """`발행 주소 기록` — 네이버에 직접 발행한 글의 주소(글 흐름 1b). 주소 글은 `repr` 에 나오지 않는다."""
    project_id: str
    platform: str
    url: str = field(default="", repr=False)


@dataclass(frozen=True)
class PostOutcome:
    kind: str                                                # imported · reviewed · approved · revoked · copied · uncopied · recorded · file
    detail: object = None                                    # PostDetail — 일을 마친 뒤의 글 모습
    review: object = None                                    # ReviewReport (reviewed)
    file: object = None                                      # ImportFile (file)


class PostsProvider:
    """글 검토 화면 데이터 공급자 공통 모양 — 모든 메서드는 작업 스레드에서 불린다. 읽기는 `load_posts`·`load_post`·`read_import_file`, 쓰기는 나머지 넷(사용자가 눌렀을 때만)."""
    sample = False

    def load_posts(self, progress, cancelled):
        raise NotImplementedError

    def load_post(self, project_id, progress, cancelled):
        raise NotImplementedError

    def read_import_file(self, path, progress, cancelled):
        raise NotImplementedError

    def import_post(self, request, progress, cancelled):
        raise NotImplementedError

    def review_post(self, request, progress, cancelled):
        raise NotImplementedError

    def approve_post(self, request, progress, cancelled):
        raise NotImplementedError

    def revoke_post(self, request, progress, cancelled):
        raise NotImplementedError

    def mark_copied(self, request, progress, cancelled):
        """글 흐름 1b — `CopiedRequest` 를 받아 복사함으로 표시하거나 되돌린다(쓰기, 글 저장소 한 곳)."""
        raise NotImplementedError

    def record_published(self, request, progress, cancelled):
        """글 흐름 1b — `RecordRequest` 를 받아 직접 발행한 글의 주소를 기록한다(쓰기, 글 저장소 한 곳)."""
        raise NotImplementedError

    def load_history(self, progress, cancelled):
        """글 흐름 1b — 발행 기록 목록(`post_history.HistoryData`)을 읽는다(읽기뿐)."""
        raise NotImplementedError

    def load_work_log(self, progress, cancelled):
        """글 흐름 1b — 작업 로그(`post_history.WorkLogData`)를 읽는다(읽기뿐)."""
        raise NotImplementedError


__all__ = ["ApproveRequest", "CopiedRequest", "ImportFile", "ImportRequest", "NaverPackageInfo", "PAGES", "PLATFORMS", "PagesValues", "PlatformStatus", "PostDetail", "PostFailure", "PostOutcome", "PostPreview",
           "PostRow", "PostsData", "PostsProvider", "PreviewBlock", "RecordRequest", "ReviewReport", "ReviewRequest", "RevokeRequest", "SimilarityInfo"]
