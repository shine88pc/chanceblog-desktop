"""가린 시험 러너 — 시험 실패 출력에서 비밀 모양을 가려서 낸다(PCSEC1 H1: 옛 시험의 `assertNotIn(비밀, 출력)` 도 실패할 때 출력 전체를 찍지 않게).

사용(작업 폴더에서): `python -X utf8 tests/run_masked.py discover -s tests -p "test_service_cli.py"` — 인자는 `python -m unittest` 와 같다. 실패·오류 글과 시험 설명(`subTest` 값 포함)을
공통 경계(`security/boundary.py` 의 `mask_block`)로 가린다. 시험 결과(통과·실패 개수·종료 코드)는 그대로다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import secret_support  # noqa: E402

if __name__ == "__main__":
    unittest.main(module=None, argv=["run_masked", *sys.argv[1:]], testRunner=secret_support.MaskingTextTestRunner)
