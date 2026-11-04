"""번호 자리에 친 글을 오류 문구에 되풀이해도 되는가 — 되풀이해도 되는 '번호 모양' 판정을 이 한 곳에 둔다(docs/SECURITY.md §7).

후보·글 번호 자리나 백업 파일 자리에 키를 잘못 쳐도, 오류 문구·`--json`·`--verbose` 의 기록용 한 줄·예외 글에 그 값이 다시 나오면 안 된다 — 이 앱이 받을 네이버·Unsplash 키는
마지막 관문(`security.mask`)이 모르는 일반 영숫자라서 가리지 못한다. 그래서 친 글이 **번호 모양일 때만** 그대로 보이고 아니면 고정 말로 바꾼다.
오류를 만드는 곳(`AppError` 의 칸 값)에서 바꾸므로 화면·`--json`·기록용 한 줄이 모두 같은 말이다.

번호 모양은 가장 좁게 잡는다(넓으면 짧은 키 조각이 번호 모양으로 통과한다):
  · 사람이 번호 자리에 치는 것 — 순번(숫자 1~3자리)이나 번호의 앞부분. 후보·글 번호는 `uuid4().hex`(16진수 32자)이고 화면에 보이는 짧은 번호는 앞 8자이므로 **16진수 8자 이하** 하나다.
  · 백업 파일 자리 — 앱이 만드는 이름 `chanceblog-날짜-시각.db`(`Store.backup`) 하나. 그 밖의 이름·경로는 되풀이하지 않는다.
이 모듈은 표준 라이브러리만 쓰고 불러올 때 아무 일도 하지 않는다(콘텐츠 저장소도 쓴다).
"""
from __future__ import annotations

import re

NUMBER_REF = re.compile(r"[0-9A-Fa-f]{1,8}")                          # 순번·번호 앞부분 — 8자는 화면에 보이는 짧은 번호(`short_id`)의 길이이고, 이보다 긴 16진수는 키 조각일 수 있다
BACKUP_FILE = re.compile(r"chanceblog-[0-9]{8}-[0-9]{6}\.db")         # `Store.backup` 이 만드는 이름(`\d` 는 다른 나라 숫자도 받아서 ASCII 숫자만)
TYPED_NUMBER = "(입력한 번호)"
TYPED_FILE = "(입력한 파일)"


def _shown(text, shape, placeholder):
    """text 가 shape 와 **통째로** 맞으면 그대로(글이 아니면 맞지 않는다), 아니면 placeholder."""
    return text if isinstance(text, str) and shape.fullmatch(text) else placeholder


def shown_ref(text):
    """오류 문구에 넣을 번호 — 번호 모양(`NUMBER_REF`)이면 친 그대로, 아니면 `(입력한 번호)`."""
    return _shown(text, NUMBER_REF, TYPED_NUMBER)


def shown_backup(name):
    """오류 문구에 넣을 백업 파일 이름 — 앱이 만드는 이름 모양(`BACKUP_FILE`)이면 그대로, 아니면 `(입력한 파일)`. 경로가 아니라 파일 이름만 받는다."""
    return _shown(name, BACKUP_FILE, TYPED_FILE)
