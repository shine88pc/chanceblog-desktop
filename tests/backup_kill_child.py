"""백업을 도중에 갑자기 죽이는 시험의 자식 프로세스(시험 파일이 아니다 — tests/test_service_backup_interrupt.py 가 띄운다).

사용: backup_kill_child.py <src 폴더> <tests 폴더> <임시 폴더> <바꿀 함수 이름> <몇 번째 부름> <before|after> [restore <되돌릴 백업 이름>]
뒤의 두 인자를 주면 백업이 아니라 그 백업을 되돌리는 중에 죽인다(복원 진행 표지 시험).
`os._exit` 로 곧바로 죽는다(정리 코드·`finally` 가 돌지 않는다 — 앱이 강제로 끝나거나 전원이 나가는 것과 가장 비슷하다). 지정한 부름이 한 번도 오지 않으면 죽지 않고 끝난다(종료 코드 0 — 시험이 이를 실패로 본다).
`before` 는 그 함수를 부르기 직전에, `after` 는 그 함수가 끝난 직후에 죽는다.
"""
import os
import sys

src, tests, tmp, name, nth, when = sys.argv[1:7]
sys.path.insert(0, src)
sys.path.insert(0, tests)

import service_support as ss  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402

DIED = 9
ctx = ss.make_ctx(tmp, repo=None)
real = getattr(bf, name)
count = [0]


def wrapper(*args, **kwargs):
    count[0] += 1
    here = count[0] == int(nth)
    if here and when == "before":
        os._exit(DIED)
    result = real(*args, **kwargs)
    if here and when == "after":
        os._exit(DIED)
    return result


setattr(bf, name, wrapper)
if len(sys.argv) > 8 and sys.argv[7] == "restore":
    bf.restore_full_backup(ctx, sys.argv[8], confirmed=True)
else:
    bf.create_full_backup(ctx)
