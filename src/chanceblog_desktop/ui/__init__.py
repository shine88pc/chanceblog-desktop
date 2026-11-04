"""화면(GUI) 층 — 디자인 토큰·아이콘·문구·뷰모델·작업 스레드(`ui/core/`, PySide6 없이도 불러올 수 있다)와 PySide6 화면(`ui/qt/`).

규칙: ① 화면 도구 PySide6 는 **선택 의존성**이다 — 명령줄·서비스 층은 PySide6 없이 동작하고, `ui/core/` 도 PySide6 를 불러오지 않는다.
② 색·크기·글자 값은 `ui/core/tokens.py` 한 곳에서만 정한다(화면 코드에 직접 쓰지 않는다 — 시험이 지킨다).
③ 화면은 서비스 층을 직접 부르지 않고 `ui/core/services.py` 의 인터페이스 뒤에서 가짜 서비스(예시 데이터)나 얇은 어댑터(`ui/adapters.py`)를 쓴다.
구조 설명은 docs/ARCHITECTURE.md 의 '화면 층' 절, 값과 부품 설명은 docs/UI_*.md.
"""
