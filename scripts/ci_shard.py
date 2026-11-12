"""CI 시험을 몇 조각으로 나눠 한 조각만 돌린다(D-220) — `python -m unittest discover -s tests -v` 와 같은 시험을 같은 방식으로 찾아 시험 파일(모듈) 단위로 나눈다.

왜: 시험이 6천 개를 넘고, git 과 프로세스를 진짜로 쓰는 몇 파일(`test_pages_publish`·`test_service_recovery`·`test_service_repolock` 등)이 전체 시간의 약 3/4 를 차지한다.
    윈도 칸이 21~29분 걸려 병합 부탁이 그만큼 늦어졌다. 조각을 서로 다른 러너에서 동시에 돌리면 칸 하나가 약 1/3(10분 안팎)이 된다.
사용: python scripts/ci_shard.py <조각 번호 1..N> <조각 수 N> [--list] [--tests-dir=폴더]
      인자 대신 환경 변수 CI_SHARD·CI_SHARD_TOTAL 로도 준다(ci.yml 이 쓰는 방식). 둘 다 없으면 조각 하나(= 전체, `discover` 와 같다)로 돈다.
      --list 는 그 조각에 들어갈 시험 파일 이름만 보여 주고 끝난다. --tests-dir 는 시험을 시험하려고 둔 것이다.
규칙(`tests/test_ci_shard.py` 가 지킨다):
  · 모든 시험 파일은 조각 하나에만 들어간다(빠지거나 겹치지 않는다). 불러오기에 실패한 파일도 어느 조각에 들어가 그 조각을 빨갛게 만든다(삼키지 않는다).
  · 나누는 방법은 정해져 있다(같은 입력이면 늘 같은 조각). 무거운 파일은 아래 WEIGHTS 의 대략의 시간(초, 개발 PC 에서 잰 값)으로, 나머지는 DEFAULT_WEIGHT 로 쳐서
    무거운 파일부터 지금 가장 가벼운 조각에 넣는다. 새 시험 파일은 자동으로 어느 조각에 들어간다(표에 없어도 된다).
  · 조각이 비면(조각 수가 파일 수보다 큰 경우 등) 실패로 끝난다 — 아무것도 안 돌고 초록이 되는 일이 없게.
  · 시험이 하나라도 실패하면(불러오기 실패 포함) 종료 코드가 0 이 아니다.
"""
from __future__ import annotations

import heapq
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
MAX_SHARDS = 99
DEFAULT_WEIGHT = 4            # 20초 미만인 파일 125개의 평균(약 4초)
# 개발 PC(부하 있음)에서 파일마다 따로 돌려 잰 초(2026-11-07, 143개 파일 6,454개 시험 합계 약 60분). 20초 이상인 파일만 적는다 — 대략의 균형용일 뿐 정확할 필요는 없다.
WEIGHTS = {
    "test_pages_publish": 780,
    "test_service_recovery": 460,
    "test_service_repolock": 430,
    "test_pages_repo": 265,
    "test_service_unpushed": 225,
    "test_service_candidates_process": 180,
    "test_service_echo": 135,
    "test_service_pages_git": 130,
    "test_auto_pr_workflow": 100,
    "test_vendor_core": 90,
    "test_service_keys_cli": 75,
    "test_service_suggest_process": 55,
    "test_service_draft_process": 40,
    "test_content_migration": 40,
    "test_service_pushed_post": 40,
    "test_topics_generate": 30,
    "test_service_lock": 25,
    "test_topicdb_backup": 25,
}


def module_of(test):
    """시험 한 개가 속한 시험 파일(모듈) 이름. 불러오기에 실패했거나 불러오다 건너뛴 파일은 클래스가 `unittest.loader` 안에 있고 파일 이름이 시험 이름에 들어 있다."""
    cls = type(test)
    if cls.__module__ == "unittest.loader":
        return getattr(test, "_testMethodName", cls.__name__)
    return cls.__module__


def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaves(item)
        else:
            yield item


def discover(tests_dir=TESTS):
    """`unittest discover -s tests` 와 같은 방식으로 시험을 찾아 {파일 이름: [시험, ...]}(이름 순)로 돌려준다."""
    sys.path.insert(0, str(ROOT))                          # `python -m unittest` 는 현재 폴더(저장소 맨 위)를 먼저 찾는다 — 같게
    suite = unittest.TestLoader().discover(str(tests_dir), pattern="test*.py", top_level_dir=str(tests_dir))
    found = {}
    for test in leaves(suite):
        found.setdefault(module_of(test), []).append(test)
    return dict(sorted(found.items()))


def weight_of(name):
    return WEIGHTS.get(name, DEFAULT_WEIGHT)


def assign(names, total):
    """{파일 이름: 조각 번호(1..total)}. 무거운 파일부터(같으면 이름 순) 지금 가장 가벼운 조각(같으면 번호가 작은 쪽)에 넣는다 — 같은 입력이면 늘 같은 결과."""
    heap = [(0, index) for index in range(1, total + 1)]
    heapq.heapify(heap)
    table = {}
    for name in sorted(names, key=lambda item: (-weight_of(item), item)):
        load, index = heapq.heappop(heap)
        table[name] = index
        heapq.heappush(heap, (load + weight_of(name), index))
    return table


def parse(argv, env):
    """(조각 번호, 조각 수, 옵션) — 잘못된 입력이면 ValueError."""
    options = {}
    words = []
    for item in argv:
        if item.startswith("--"):
            key, has_value, value = item.partition("=")
            if key not in ("--list", "--tests-dir"):
                raise ValueError(f"모르는 옵션: {key}")
            if (key == "--tests-dir") != bool(has_value) or (key == "--tests-dir" and not value):
                raise ValueError(f"옵션 모양이 틀리다: {item} (--list 는 값 없이, --tests-dir=폴더 는 값과 함께)")
            options[key] = value if has_value else True
        else:
            words.append(item)
    if len(words) not in (0, 2):
        raise ValueError("조각 번호와 조각 수를 둘 다 주거나 아무것도 주지 않는다")
    if words:
        shard_text, total_text = words
    else:
        shard_text, total_text = env.get("CI_SHARD"), env.get("CI_SHARD_TOTAL")
        if shard_text is None and total_text is None:
            shard_text = total_text = "1"                  # 아무것도 안 주면 조각 하나(= 전체)
        elif shard_text is None or total_text is None:
            raise ValueError("CI_SHARD 와 CI_SHARD_TOTAL 은 둘 다 있거나 둘 다 없어야 한다")
    try:
        shard, total = int(shard_text), int(total_text)
    except (TypeError, ValueError):
        raise ValueError(f"조각 번호·조각 수가 정수가 아니다: {shard_text!r} {total_text!r}") from None
    if not 1 <= total <= MAX_SHARDS or not 1 <= shard <= total:
        raise ValueError(f"조각 번호는 1~조각 수, 조각 수는 1~{MAX_SHARDS} 여야 한다: {shard}/{total}")
    return shard, total, options


def make_runner():
    """시험 실패·오류 글에서 비밀 모양을 가리는 러너(`tests/secret_support.MaskingTextTestRunner` — PCSEC1 H1: 옛 시험의 `assertNotIn(비밀, 출력)` 이 실패해도 비밀을 찍지 않는다).
    못 불러오면 보통 러너로 돌아가되 그 사실을 표준 오류로 알린다(시험 결과·종료 코드는 어느 쪽이든 같다)."""
    try:
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(TESTS))
        from secret_support import MaskingTextTestRunner
    except Exception as error:
        print(f"가리는 시험 러너를 불러오지 못해 보통 러너로 돌린다({type(error).__name__})", file=sys.stderr, flush=True)
        return unittest.TextTestRunner(verbosity=2)
    return MaskingTextTestRunner(verbosity=2)


def main(argv=None, env=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    try:
        shard, total, options = parse(argv, env)
    except ValueError as error:
        print(f"조각을 정하지 못했다: {error}", file=sys.stderr)
        return 2
    tests_dir = Path(options["--tests-dir"]) if isinstance(options.get("--tests-dir"), str) else TESTS
    found = discover(tests_dir)
    table = assign(found, total)
    if sorted(table) != sorted(found):
        print("조각 나누기가 시험 파일을 빠뜨리거나 겹쳤다 — 나누는 코드의 오류", file=sys.stderr)
        return 2
    mine = [name for name in found if table[name] == shard]
    if "--list" in options:
        print("\n".join(mine))
        return 0
    if not mine:
        print(f"조각 {shard}/{total} 에 들어갈 시험 파일이 없다(시험 파일 {len(found)}개) — 조각 수를 줄여라", file=sys.stderr)
        return 1
    tests = [test for name in mine for test in found[name]]
    everything = sum(len(items) for items in found.values())
    print(f"조각 {shard}/{total}: 시험 파일 {len(mine)}개·시험 {len(tests):,}개 (전체 {len(found)}개 파일·{everything:,}개 시험)", flush=True)
    result = make_runner().run(unittest.TestSuite(tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
