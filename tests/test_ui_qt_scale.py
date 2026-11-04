"""화면 배율 검증 시험 — 필수 1366×768/100%·1920×1080/100%·1920×1080/125%, 조건부 1920×1080/150%(핵심 기능을 쓸 수 있는지만). PySide6 가 없거나 윈도가 아니면 건너뛴다.

**이 시험은 실제 윈도 배율 설정이 아니라 Qt 자체의 High DPI 경로(`QT_SCALE_FACTOR`, 자식 프로세스의 환경 변수 — 앱 코드에는 없다)로 흉내 낸 것이다.** 실제 윈도 125·150% 렌더·한글 입력기·화면 읽기는
운영자 PC 검증으로 남는다(docs/UI_VISUAL_QA.md). `scripts/ui_capture.py --check` 가 환경마다 홈·여섯 상태·서랍·대화상자·토스트에서 글자 잘림·누르는 칸 36px·가로 스크롤·서랍/대화상자가 창 안에 들어오는지 본다.
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HAVE = importlib.util.find_spec("PySide6") is not None
ENVIRONMENTS = {"1366x768@100": (1366, 768, 1.0), "1920x1080@100": (1920, 1080, 1.0), "1920x1080@125": (1920, 1080, 1.25), "1920x1080@150": (1920, 1080, 1.5)}


def check(environment):
    command = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "ui_capture.py"), "unused", "--env", environment, "--check"]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"), timeout=240, creationflags=0x08000000 if os.name == "nt" else 0)
    if done.returncode != 0:
        raise AssertionError(done.stderr[-400:])
    return json.loads(done.stdout)[0]


@unittest.skipUnless(HAVE and os.name == "nt", "PySide6 와 윈도 글꼴이 있어야 한다(글자 잘림은 글꼴에 달렸다)")
class ScaleTest(unittest.TestCase):
    def test_each_environment_has_no_clipped_text_no_small_targets_and_no_horizontal_scroll(self):
        for environment, (width, height, scale) in ENVIRONMENTS.items():
            with self.subTest(environment=environment):
                report = check(environment)
                self.assertEqual(report["env"], environment)
                self.assertEqual(float(report["scale_factor_env"]), scale)
                for name in ("home", "loading", "empty", "error", "partial", "offline", "drawer", "dialog", "tooltip", "toast"):
                    size = report["shots"][name]
                    self.assertEqual((size[0], size[1]), (width, height), name)                       # 물리 픽셀 = 화면 크기(논리 크기 × 배율)
                    self.assertEqual(size[2], scale, name)
                for name, found in report["checks"].items():
                    self.assertEqual(found.get("clipped"), [], f"{environment} {name}")
                    self.assertFalse(found.get("horizontal_scroll", False), f"{environment} {name} 가로 스크롤")
                    self.assertTrue(found.get("fits_window", True), f"{environment} {name} 창 안에 안 들어옴")
                self.assertEqual(report["fonts"][0], report["fonts"][0].strip())


if __name__ == "__main__":
    unittest.main()
