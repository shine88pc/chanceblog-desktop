"""`python -m chanceblog_desktop <명령>` — 명령줄 진입점(사용법은 `--help`, 설명은 README.md 의 '명령줄로 써 보기'). `gui` 는 화면을 연다(`ui/launcher.py`, PySide6 가 있을 때만).
진입점 맨 앞에서 공통 경계(`security/boundary.py`)를 한 번 깐다 — 표준 출력·오류·로그·처리하지 못한 예외(`--debug` 의 추적 포함)·Qt 메시지가 비밀 모양을 가린 채 나간다(PCSEC1 H1).
화면 진입점은 둘이다 — 이 파일과, 묶음 실행 파일이 이 파일을 거치지 않고 바로 부르는 `ui/launcher.main`. 둘 다 맨 앞에서 설치하고 설치는 멱등이라 두 번 불려도 한 번만 깔린다(PCKIT 독립 검증 D2)."""
import sys

if __name__ == "__main__":
    from .security import boundary
    boundary.install()
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        from .ui import launcher
        if launcher.has_pyside6():
            boundary.install_qt_message_handler()          # Qt 가 직접 찍는 메시지도 가려서 표준 오류로(PySide6 가 없으면 launcher 가 쉬운 안내로 끝낸다)
        sys.exit(launcher.main(sys.argv[2:]))
    from .service.cli import main
    sys.exit(main())
