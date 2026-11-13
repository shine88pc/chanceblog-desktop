"""시험 도우미 — 비밀(카나리)이 출력에 새지 않았는지 확인하되 **실패 메시지에 비밀도 출력도 싣지 않는다**(PCSEC1 H1: 시험 실패 출력도 비밀이 나가는 길이다).

`assertNotIn(비밀, 출력)` 은 실패할 때 비밀이 든 출력 전체를 찍는다 — 시험 로그·CI 로그·AI 에게 붙여 넣은 화면에 비밀이 남는다. 이 도우미는 실패 메시지에 **무엇을 확인하던 중이었는지(`what`)·어떤 모양으로
샜는지(원문·퍼센트·16진수·base64·조각)·몇 번째 글자 자리인지·출력의 길이**만 적는다. 성공하면 아무 말 없다.

쓰는 법: `assert_no_secret(self, 비밀, 출력, what="명령줄 출력")` · 비밀이 여럿이면 `assert_masked_only(self, [비밀들], 출력, what=…)`. 비밀은 시험 안에서 `make_canary(라벨)` 로
`CANARY_` 로 시작하는 가짜 값을 **런타임에 만들어** 쓴다(저장소 비밀 스캐너가 소스 글자를 훑는다 — 키 모양을 한 덩어리로 소스에 쓰지 않는다).

**기존 시험까지 한꺼번에**: 옛 시험의 `assertNotIn(비밀, 출력)` 은 실패할 때 출력 전체를 찍는다. `MaskingTextTestRunner`(= 공통 경계의 `mask_block` 으로 실패 글과 시험 설명을 가려서 내는 러너)로 돌리면
시험을 한 줄도 고치지 않고 시험 실패 출력에서 비밀 모양이 가려진다: `python -X utf8 tests/run_masked.py discover -s tests -p "test_xxx.py"`.
"""
import base64
import hashlib
import unittest
import urllib.parse

WINDOW = 8                 # 조각 검사의 창 길이(글자) — 비밀의 고유한 부분에서 이 길이의 조각이 하나라도 출력에 있으면 샌 것이다


def make_canary(label, size=20):
    """결정적 가짜 비밀 — `CANARY_<라벨>_<16진수 size자>`. 진짜 비밀이 아니고 라벨이 같으면 값도 같다."""
    return f"CANARY_{label}_" + hashlib.sha256(("pcsec1-boundary:" + label).encode("utf-8")).hexdigest()[:size]


def variants(secret):
    """비밀이 출력에 남는 흔한 모양들 → {모양 이름: 찾을 글}(비밀 자신과 같은 것은 한 번만)."""
    raw = secret.encode("utf-8")
    found = {"원문": secret, "퍼센트": urllib.parse.quote(secret, safe=""), "16진수": raw.hex(), "base64": base64.b64encode(raw).decode("ascii"),
             "base64url": base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")}
    return {kind: text for kind, text in found.items() if text and (kind == "원문" or text != secret)}


def unique_part(secret):
    """조각 검사에 쓸 비밀의 고유한 부분 — 마지막 `_` 뒤(앞의 `CANARY_라벨_` 은 비밀이 아니다). 너무 짧으면 비밀 전체."""
    tail = secret.rsplit("_", 1)[-1]
    return tail if len(tail) >= WINDOW else secret


def find_leak(secret, output):
    """출력에서 비밀이 샌 흔적을 찾는다 → (모양 이름, 글자 위치) 또는 None. **값은 돌려주지 않는다.**"""
    text = output if isinstance(output, str) else str(output)
    for kind, needle in variants(secret).items():
        position = text.find(needle)
        if position >= 0:
            return kind, position
    part = unique_part(secret)
    for start in range(max(len(part) - WINDOW + 1, 1)):
        window = part[start:start + WINDOW]
        if len(window) >= min(WINDOW, len(part)):
            position = text.find(window)
            if position >= 0:
                return "조각", position
    return None


def leak_count(secrets, output):
    """여러 비밀 중 출력에 샌 것의 개수(표를 만들 때 쓴다)."""
    return sum(1 for secret in secrets if find_leak(secret, output) is not None)


def uninstall_boundary():
    """같은 프로세스에서 화면 진입점(`ui.launcher.main`)을 부르는 시험의 뒷정리 — `launcher.main` 은 맨 앞에서 공통 출력 경계를 깐다(PCKIT 독립 검증 D2).
    깔린 채 두면 시험 러너의 `sys.stdout`·예외 훅·로깅 훅에 경계가 남는다. 깔려 있지 않으면 아무것도 안 한다(`self.addCleanup(sec.uninstall_boundary)` 로 건다).
    또한 `launcher.main` 이 윈도에서 이 프로세스에 쥐게 하는 단일 실행 뮤텍스(SINGLEWIN)도 놓는다 — 놓지 않으면 시험 프로세스가 끝날 때까지 기본 데이터 폴더의 뮤텍스를 쥐고 있어, 같은 PC 에서 동시에 도는 다른 시험 프로세스의 같은 시험이 '이미 열려 있음' 으로 판정해
    진짜 안내 상자에서 멈춘다. `launcher.main` 을 같은 프로세스에서 부르는 시험 파일은 모두 이것을 건다(`tests/test_single_instance.py` 의 소스 훑기 시험이 지킨다)."""
    from chanceblog_desktop.security import boundary                      # 늦게 불러온다 — 이 도우미 모듈은 앱 없이도 불러올 수 있다
    installed = boundary.active()
    if installed is not None:
        installed.uninstall()
    from chanceblog_desktop.ui import single_instance
    single_instance.release_all()                                         # `launcher.main` 은 윈도에서 이 프로세스가 끝날 때까지 쥐는 단일 실행 뮤텍스도 잡는다(SINGLEWIN) — 시험이 끝나면 놓아, 시험 사이·동시에 도는 다른 시험 프로세스에 남지 않게 한다(윈도가 아니면 아무것도 안 한다)


def assert_no_secret(case, secret, output, what="출력"):
    """비밀이 출력에 없다 — 있으면 실패하되 메시지에는 `what`·모양·위치·출력 길이만 적는다."""
    hit = find_leak(secret, output)
    if hit is not None:
        kind, position = hit
        case.fail(f"{what}: 비밀이 새어 나왔습니다 — 모양 '{kind}'·{position}번째 글자 근처(출력 {len(output if isinstance(output, str) else str(output))}자). 값은 이 메시지에 적지 않습니다")


def assert_masked_only(case, secrets, output, what="출력"):
    """비밀들이 하나도 출력에 없다 — 샌 것이 있으면 그 번호(1부터)·모양·위치만 적고 실패한다."""
    for number, secret in enumerate(secrets, start=1):
        hit = find_leak(secret, output)
        if hit is not None:
            kind, position = hit
            case.fail(f"{what}: 비밀 {number}번이 새어 나왔습니다 — 모양 '{kind}'·{position}번째 글자 근처(출력 {len(output if isinstance(output, str) else str(output))}자). 값은 이 메시지에 적지 않습니다")


def failure_message(secret, output, what="출력"):
    """`assert_no_secret` 이 실패할 때의 메시지(시험 실패 출력에 비밀이 있는지 확인하려고 — 실패하지 않으면 None)."""
    class _Recorder:
        message = None

        def fail(self, text):
            self.message = text

    recorder = _Recorder()
    assert_no_secret(recorder, secret, output, what)
    return recorder.message


class MaskingTextTestResult(unittest.TextTestResult):
    """실패·오류 글(호출 흔적·단언 메시지)과 시험 설명(`subTest` 값 포함)을 공통 경계(`mask_block`)로 가려서 낸다."""

    @staticmethod
    def _masked(text):
        from chanceblog_desktop.security.boundary import mask_block          # 늦게 가져온다(이 도우미가 소스 경로를 정하기 전에 불리지 않게)
        return mask_block(text)

    def _exc_info_to_string(self, err, test):
        return self._masked(super()._exc_info_to_string(err, test))

    def getDescription(self, test):
        return self._masked(super().getDescription(test))


class MaskingTextTestRunner(unittest.TextTestRunner):
    resultclass = MaskingTextTestResult
