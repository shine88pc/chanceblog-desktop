"""'내 글 문체 참고값 보기'의 실제 공급자 — 읽기 기반(`service/own_posts.py`)과 순수 계산(`content/style_stats.py`)을 화면이 아는 모양(`ui/core/style_view.py`)으로 맞추는 얇은 어댑터다(N-3a, 결정 D-330–D-339).
**읽기뿐이다**: 부르는 것은 `own_posts.read_own_files`·`own_posts.check_pasted_text` 와 `style_stats.analyze`·`summarize` 뿐이고 파일을 만들거나 고치거나 지우지 않으며 로그·캐시·클립보드·네트워크를 쓰지 않는다.
데이터 폴더·설정·프로필·보관함·연결 저장소는 읽지도 쓰지도 않는다(이 어댑터는 `service/context` 를 가져오지 않는다 — 소스 시험이 확인한다). 읽은 글은 이 어댑터의 지역 변수로만 있다가 숫자로 바뀌면 버려진다.

오류 처리(읽기 기반 문서의 'N-3a 가 조심할 점'): `AppError`(모두 `CONTENT_INVALID` 의 고정 문장)를 잡으면 `rendered().message` 만 꺼내고 `error.__traceback__ = None` 으로 호출 흔적을 끊고, 오류는 `except` 밖에서 새로 낸다(앞 오류가 따라붙지 않게).
경로·파일 이름·글은 화면·로그·예외 어디에도 되풀이하지 않고, 몇 번째 파일이 문제인지도 알리지 않는다(전체 거절). 마크다운 숫자는 **입력 경로의 확장자**로 가른다(읽기 기반의 값에는 확장자가 담기지 않는다).
이 모듈은 PySide6 를 모른다. 무거운 모듈(`service/own_posts`·`content/style_stats`)은 쓰는 함수 안에서 늦게 가져온다.
"""
from __future__ import annotations

from ..errors import AppError
from .core.jobs import JobFailure
from .core.style_view import MAX_ITEMS, StyleProvider, StyleRefusal
from .core.text import T

CODE = "CONTENT_INVALID"                           # 읽기 기반이 내는 오류 코드 하나(새 오류 코드는 만들지 않는다)


def _form_of(path):
    """입력 경로의 확장자로 형식을 가른다 — `.md`(대소문자 무시)는 마크다운, 그 밖(읽기 기반이 받는 `.txt`)은 텍스트."""
    return "md" if str(path).lower().endswith(".md") else "txt"


class ServiceStyleProvider(StyleProvider):
    """읽기 기반 서비스를 화면이 아는 모양으로 맞춘다. 거절은 고정 문장(`rendered().message`)뿐이다."""
    sample = False

    def check_files(self, paths):
        """파일들을 읽을 수 있는지만 본다 — 읽기 기반이 같은 검사로 읽고 글은 바로 버린다(같은 파일 두 번·형식·크기·링크 …)."""
        from ..service import own_posts
        message = None
        try:
            own_posts.read_own_files(list(paths))
        except AppError as error:
            message = error.rendered().message
            error.__traceback__ = None                                         # 호출 흔적이 붙드는 지역 변수(경로)를 놓는다
        finally:
            paths = None                                                       # 이 틀의 인자도 놓는다 — 새로 내는 거절의 호출 흔적이 위치를 붙들지 않게
        if message is not None:
            raise StyleRefusal(message)                                        # `except` 밖에서 낸다 — 앞 오류가 따라붙지 않는다

    def check_pasted(self, text):
        """붙여 넣은 글을 파일과 같은 한도·같은 거절 문장으로 검사한다."""
        from ..service import own_posts
        message = None
        try:
            own_posts.check_pasted_text(text)
        except AppError as error:
            message = error.rendered().message
            error.__traceback__ = None
        finally:
            text = None
        if message is not None:
            raise StyleRefusal(message)

    def compute(self, paths, pasted_text):
        """파일들(입력 순서)과 붙여 넣은 글(맨 뒤)을 읽어 세고 `(StyleSummary, 글마다 CP949 로 읽었는지, 글마다 붙여 넣은 글인지)` 를 돌려준다. 거절은 `JobFailure`(고정 문장, 코드 `CONTENT_INVALID`)."""
        from ..content import style_stats
        from ..service import own_posts
        message = None
        result = None
        try:
            items = list(own_posts.read_own_files(list(paths))) if paths else []
            forms = [_form_of(path) for path in paths]
            if pasted_text and pasted_text.strip():
                items.append(own_posts.check_pasted_text(pasted_text))
                forms.append("pasted")
            if len(items) <= MAX_ITEMS:                                            # 화면이 막지만 이 어댑터도 막는다 — 글은 파일과 붙여 넣은 글을 합쳐 최대 2개
                stats = [style_stats.analyze(item.text, form) for item, form in zip(items, forms, strict=True)]
                result = (style_stats.summarize(stats), tuple(item.encoding == "cp949" for item in items), tuple(form == "pasted" for form in forms))
            items = None                                                       # 읽은 글은 숫자가 된 뒤 바로 놓는다
        except AppError as error:
            message = error.rendered().message
            error.__traceback__ = None
        finally:
            paths = pasted_text = items = stats = None                         # 어느 길로 끝나든(오류 포함) 이 틀의 위치·글을 놓는다
        if message is not None:
            raise JobFailure(message, code=CODE)
        if result is None:
            raise JobFailure(T["style_fail_toomany"], code=CODE)
        return result


__all__ = ["CODE", "ServiceStyleProvider"]
