# 공통 부품 — 화면은 부품만 쓴다 (PySide6)

> 화면(`ui/qt/screens.py`·`shell.py`)은 Qt 기본 위젯(`QPushButton`·`QLabel`·`QLineEdit`·`QCheckBox` …)을 **직접 만들지 않고** `ui/qt/components.py` 의 부품만 쓴다(UI-C0 의 새 부품은 `ui/qt/gauges.py`·`ui/qt/bars.py` 에도 있고 홈의 새 구역 부품은 `ui/qt/board.py` 에 있다 — 점수 링 `ScoreWithLabel` 과 `ToneSwatch` 는 UI-C1d 의 홈이 쓰고 나머지 새 부품은 아직 어떤 화면에도 연결하지 않았다) — 시험이 소스에서 막는다. 색·크기·글자는 토큰([`UI_DESIGN_SPEC.md`](UI_DESIGN_SPEC.md) §2)에서만 오고, 부품 안에서도 `setStyleSheet` 로 색을 쓰지 않는다(속성 `role`·`kind`·`badge`·`tone`·`card` 만 붙이면 `ui/qt/theme.py` 의 스타일시트가 입힌다).

## 1. 계층

```text
tokens.py(값) → theme.py(스타일시트·글꼴·SVG 아이콘 엔진·그림자 효과) → components.py·gauges.py·bars.py(부품) → screens.py(화면 조립) → shell.py(앱 틀·서랍·대화상자·토스트·포커스·작업 스레드 연결)
core/text.py(문구) ─┘                                                       ▲ core/app_state.py(뷰모델) 가 만든 딕셔너리를 그리기만 한다
core/gauges.py·part_rules.py(점수·막대·사용량·행동 줄·탭의 순수 계산 — PySide6 없이 시험) ─ ui/qt/gauges.py·bars.py 가 이 값만 그린다
core/board_view.py(홈 새 구역 — Naver A·B 추천·작성 중 초안·최근 발행·KPI·연결 요약의 뷰모델, UI-C1c) ─ ui/qt/board.py 가 그 값을 그리기만 한다(`KpiCard`·구역 카드·`BoardRow`·`ListRow`·구역 안내·연결 한 줄, UI-C1d)
core/gallery_data.py(예시 값) + scripts/ui_gallery.py(개발용 부품 모음 — 사용자 화면·메뉴에 없다, `ui_capture.py --gallery` 와 시험이 쓴다)
```

## 2. 부품 표

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `Button(kind, …)` | `primary`(채움)·`secondary`(테두리)·`ghost`(글자)·`danger` 4종(`danger` 의 배경은 `danger_fill` `#CE4646` + 흰 글자 4.58 — 문서 값이 아니라 운영자 결정 값, 접근성 보완·D-170). 높이 표준 40, 큰 주 단추(`size="lg"`) 44, 작은 단추(`size="sm"`) 보이는 34·누르는 칸 36. 아이콘은 글자 앞(또는 `RightToLeft` 로 뒤) | 접근 이름=글자(또는 지정), Tab·**Enter·Space**, 포커스 링(채움 단추는 어두운 링 — 단추 종류마다 포커스 전후의 모양·테두리 색을 시험이 잰다), 윈도 기본 포커스 사각형은 `outline: none` 으로 끈다 |
| `IconButton` | 36×36 아이콘만 있는 단추 | **접근 이름+툴팁 필수**, 툴팁은 키보드 포커스에도 보임 |
| `NavButton`·`LinkButton` | 사이드바 메뉴(높이 44·모서리 8, 현재 메뉴는 `nav_current_bg` 바탕 + `nav_current_text` 글자·아이콘)·글자 링크 | 접근 이름 `○○ 메뉴로 이동` |
| `TopBar`(`ui/qt/topbar.py`) | 상단 앱 바(높이 60) — 잎 아이콘·`ChanceBlog`(20px)·한 줄 소개(13px)·오른쪽 날짜·시간. **단추가 없다.** 시계는 주입(`clock.now()`)·분 경계까지 한 번 기다리는 단발 타이머·좁은 폭에서 소개 문구를 먼저 숨기고 날짜를 줄임(`clock.plan_topbar`, 글자 폭을 실제로 잼) | 앱 바 이름·`현재 날짜와 시간 …`(늘 전체 날짜) |
| `Sidebar`·`SoonItem`(`ui/qt/sidebar.py`) | 사이드바(폭 208) — 묶음 이름(실제 메뉴가 있는 묶음만)·실제 메뉴(홈·주제 후보·Seed 관리·블로그 관리·설정 — 묶음 사이·'다음 단계' 앞 빈 칸 8px 셋은 `gap()` 이라 세로가 모자라면 0 까지 줄어든다, D-230 ⑤)·**'다음 단계' 목록**(이름 + `준비 중` 배지, 글자·아이콘은 바탕과 55% 섞은 `soon_text`, 단추 아님·`NoFocus`·기본 커서·가리켜도 변화 없음)·하단 브랜드와 버전 | 목록 `준비 중 — 아직 열 수 없는 화면`, 항목 `○○, 준비 중` |
| `FilterChip`·`KeywordChip` | 칩(보이는 34·누르는 36)·키워드 칩(24) — 홈은 UI-C1d 부터 쓰지 않는다(후보 목록 화면이 쓴다) | 칩은 켜짐 상태가 있는 단추, 접근 이름 `전체 6` |
| `Badge`·`BlogBadge`·`SampleBadge` | 배지(24). 홈의 두 구역 배지(A·B)는 **색+글자**(글자는 이름의 끝 숫자 — 기본 이름 `네이버 블로그 1` 이면 `1`, 별명이면 첫 글자). 상태 배지는 종류 `ok`·`warning`·`danger`·`info`·`muted` — 설정 화면의 '준비'·'연결' 배지와 접이식 머리의 요약 칩(색만으로 구분하지 않고 늘 글자를 함께). `예시 데이터` 는 눌러서 설명 대화상자(화면마다 설명이 다르다 — 홈은 주제·숫자, 설정은 키 이름·사용량 숫자) | 접근 이름=글자, 예시 데이터는 툴팁 |
| `Card`·`set_card_state` | 카드(테두리+옅은 면 — 종류 `true`(흰 면)·`plain`(보조 면)·`warm`(초록 옅은 면)·`quiet`(꺼진 바탕 — 설정 화면의 준비 중 카드)). `set_card_state(card, 상태)` 는 카드 상태(기본·가리킴·선택)의 테두리와 그림자를 입히고, **포커스를 받으면 2px 파란 테두리가 상태 색을 이긴다**(UI-C1d, D-200). 홈에서는 KPI 카드·구역 카드·연결 한 줄에만 기본 그림자를 입힌다(옛 `SummaryCard` 는 `KpiCard` 로 바뀌었다) | 눌리는 틀은 `Pressable`(Enter·Space) |
| `Pressable` | 눌러서(마우스·Enter·Space) 여는 틀 — 포커스 링은 스타일시트(`:focus`)가 그리고 가리키면 바탕만 바뀐다. 홈의 추천 줄(`BoardRow`)이 쓴다(옛 `TopicRow`·`QuickAction` 은 UI-C1d 에서 없어졌다) | 접근 이름 필수, 포커스·Enter/Space |
| `KpiCard`(`ui/qt/board.py`) | 홈 KPI 카드 — 아이콘 바탕(`ToneSwatch` 40×40) + 이름 13px + 숫자 28px 굵게(또는 모르는 값 `연결 전`·`집계 전` 17px 굵은 글) + 보조 글 12px. 카드 전체에 강한 색 없음 | 눌리지 않는다(포커스·손 모양 없음), 접근 이름 `추천 주제 9개` |
| `section_card`·`finish_section`·`BoardRow`·`ListRow`·`section_note`·`connection_strip`(`ui/qt/board.py`) | 구역 카드(머리: 채널 이름(`ElidedLabel`)·후보 수·`꺼짐` 배지) 안에 **추천 줄**(점수 링 44 + 구간 이름 + 변화량 + 제목(줄바꿈) + 최근 관심도 + 채널 열쇠 A·B + `예시` 꼬리표, 점수가 없으면 링 없이 `점수 계산 전`)·**글 줄**(작성 중 초안·최근 발행 — 연한 면)·구역 안내(빈 상태·꺼짐·못 읽음 — 쓰기 단추 없음)·연결 한 줄. 부품은 뷰모델의 값을 그리기만 한다 | 추천 줄은 포커스·Enter/Space 로 서랍을 연다(접근 이름 `제목, 점수 92, 우선 추천, 4 상승, 관심도 상승, 예시`·`누르면 상세 정보가 열려요.`), 글 줄·KPI 는 포커스 없음 |
| `TextInput`·`Toggle` | 입력(높이 40, 포커스 링 2px)·스위치(44×26, 글자와 함께) | 접근 이름 필수, Space 로 켜고 끔 |
| `Tooltip`(`with_tooltip`) | 마우스 올림 + **키보드(Tab) 포커스에도** 보임(포커스 이벤트가 끝난 다음 차례에 띄움) | 포커스가 빠지면 숨김 |
| `Toast` | 아래 가운데, **3.5초**, 한 번에 하나, **같은 안내는 쌓지 않고 보이는 시간만 늘림**(`core/notify.py` 규칙), 좁은 창에서도 창 안에 | 화면 읽기 프로그램에 알림(Alert) 이벤트 |
| `Skeleton` | 불러오는 중 — 줄 모양 자리 표시(전체 스피너 없음) | 접근 이름은 화면마다 다르다(홈 `후보를 불러오는 중`, 설정 `연결 상태를 읽는 중`) |
| `StateCard`(빈·오류)·`Banner`(일부만·오프라인)·`Disclosure`(진단 정보) | 아이콘+한 줄 원인+다음 행동 단추. 영문 코드는 접어 둔 진단 정보에만(고정폭). `Disclosure` 의 단추는 가운데(기본) 또는 `left=True` 로 왼쪽 | [`UI_STATES.md`](UI_STATES.md) |
| `Accordion`(접이식) | 머리 한 줄(높이 52 이상 — 제목 + 요약 칩)과 몸(펼치면 보이는 위젯). `Disclosure` 와 같은 여닫기 규칙(기본 접힘·머리를 누르거나 Enter·Space·아이콘이 위·아래로 바뀜)을 제목·칩이 있는 머리 한 줄로 넓힌 것이다. 칩은 마우스를 받지 않아 칩을 눌러도 머리가 눌리고, 펴고 접으면 화면을 다시 그리지 않고 `toggled(이름, 펼침)` 만 알린다 | 머리는 단추 하나(Tab 정거장 하나 — **새 키보드 규칙 없음**), 접근 이름 `데이터, 준비 중 2 · 연결 확인 필요 1, 접혀 있어요`(제목·요약·상태), 다시 그려도 `focus_key` 로 포커스가 돌아온다 |
| `Drawer` | 오른쪽에서 밀려 나옴(200ms), 폭 420(창의 92% 이하), 안쪽 스크롤, 바깥(막)·Esc·닫기 단추로 닫음 | 열리면 포커스가 닫기 단추로, Tab 은 서랍 안에서만, 닫으면 눌렀던 곳으로 |
| `Dialog` | 가운데, 폭 480(창의 94% 이하), 창 위에 겹침(별도 창 아님), 처음 포커스는 기본 단추 | Esc 로 닫음(서랍보다 먼저), Tab 은 안에서만 |
| `DialogBody`(`components.py` — `show_dialog`·`show_choice_dialog` 의 본문) | 확인창의 본문 칸 — 창에 들어갈 때는 본문 글만 있던 때와 똑같이 보이고(높이·모양 불변) 안 들어갈 때만 세로로 스크롤된다(제목과 단추는 고정·단추는 늘 창 안). 가로 스크롤 없음 | 스크롤 범위가 있을 때만 Tab 으로만 닿는 정거장(마우스로 눌러도 단추의 포커스를 안 뺏는다 — 접근 이름은 본문 글)·방향키·PageUp/PageDown·Home/End |
| `ImagePlaceholder` | 주제 색 그라디언트+아이콘(64 또는 16:9). 깨진 그림 아이콘을 쓰지 않는다. 홈은 UI-C1d 부터 쓰지 않는다(이미지 없는 카드 — 후보 목록·이미지 화면이 쓴다) | 접근 이름: 분야를 아는 후보(예시 데이터)는 `생활·집 주제의 이미지 자리 표시. …`, 분야를 모르는 실제 후보는 `이미지 자리 표시. …`(아이콘은 돌려 쓰는 장식이라 분야를 지어내지 않는다) |
| `AttributionRow`(출처 표시) | `Photo by 작가 on Unsplash`(작가=프로필, Unsplash=홈, 둘 다 UTM) + `출처 복사` 단추 | 링크는 Unsplash 의 https 만 연다, 복사하면 `출처 복사됨` ([`UI_IMAGES.md`](UI_IMAGES.md)) |
| `Label`·`ElidedLabel` | 글자 역할(Typography Token) 하나. 줄바꿈 글은 행간 토큰 적용·**HTML 이스케이프**. 고정폭은 `mono=True`. `ElidedLabel` 은 한 줄로 보여 주고 넘치면 …(줄임표)로 줄이며 툴팁에는 **받은 글**이 나온다(뷰모델이 가린 뒤 이미 줄인 글 — 블로그 이름은 어댑터가 30자 + …까지라 40자 이름은 라벨도 툴팁도 29자 + …, 한 줄 설명은 300자까지. 긴 원문을 툴팁에 다 싣지 않는다: 가린 뒤에 자르는 원칙) — 오른쪽 패널의 블로그 이름(한글 14자쯤부터 카드 밖으로 잘리던 것)과 추천 행의 한 줄 설명에 쓴다 | 긴 이름이 카드 밖으로 안 나감·툴팁은 받은 글(40자 이름 → 30자) |
| `FlowLayout`·`chip_row`·`FlowGrid` | 칩 줄바꿈·열 수가 바뀌는 격자. `FlowGrid` 의 열 수는 `part_rules.grid_columns` 의 순수 규칙이 정한다(홈: KPI 한 칸 190·추천 한 칸 480·글 구역 한 칸 400 — D-202). 옛 `ResponsiveBody`(본문+오른쪽 패널)는 UI-C1d 에서 없어졌다 | 가로 스크롤 없음 |

## 2-2. C-Type 공통 부품 (UI-C0 — 어떤 화면에도 아직 연결하지 않았다)

샘플 값으로만 시험하고 사진을 찍은 독립 부품이다. 표시 규칙(값·구간·경계)은 [`UI_DESIGN_SPEC.md`](UI_DESIGN_SPEC.md) §2-2, 순수 계산은 `ui/core/gauges.py`·`part_rules.py`, 부품 모음 사진은 [`UI_VISUAL_QA.md`](UI_VISUAL_QA.md) §7 이다. 색·글자 크기·여백은 토큰에서만 오고(여백은 `K.SPACE`) 부품 안에 `setStyleSheet`·직접 색·숫자 간격이 없다(시험이 새 파일을 훑는다).

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `ScoreRing(score, size)` (`ui/qt/gauges.py`) | 원형 점수 링 — 지름 카드용 44·상세용 72(`"card"`·`"detail"`, 숫자는 40~80 으로 맞춘다), 선 두께 지름의 11%, 빈 길 `track`, 호 = 점수 구간색(80 이상 초록·65~79 파랑·50~64 노랑·0~49 빨강). **링 안에는 숫자만**(18·22 굵게). **데이터 부족(없음·소수·범위 밖)은 아무것도 그리지 않는다 — 0점이 아니다** | 접근 이름 `점수 92, 우선 추천`, 같은 글이 툴팁. 보기 부품이라 Tab 정거장은 아님 |
| `ScoreWithLabel(score, delta, layout, missing_text=None)` | 링 + 구간 이름 라벨 + 변화량 라벨. `card`: 링 오른쪽에 구간 이름, 그 아래 줄에 `▲ +12`. `detail`: 링 아래에 구간 이름과 변화량(가운데). 이름은 구간별 진한 글자색, 변화량은 상승 초록·하락 빨강·`― 변화 없음` 회색(글자 ▲▼― 가 함께). 데이터 부족이면 링 없이 글만(기본 `데이터 부족`, 홈의 추천 줄은 `missing_text` 로 `점수 계산 전`) | 접근 이름 `점수 92, 우선 추천, 12 상승`(데이터 부족은 `점수 데이터 부족`) |
| `BarGauge(items, total_label, total, signed)` | 구성 막대 — 높이 12·모서리 6, 구성마다 고정색(`base`·`data`·`trend`·`other`), 길이는 양수 구성끼리의 비율, 아래에 색 표시·이름·숫자(첫 구성은 그대로·나머지는 부호), 오른쪽에 `최종 점수` 와 큰 총점. 구성이 없으면 `구성 정보 없음` | 접근 이름 `점수 구성: 기존 점수 55, …, 최종 점수 92`. 이름은 `ElidedLabel` 이라 길면 …로 줄고 툴팁은 받은 글 |
| `UsageBar(used, limit, unit, title, tag)` | 사용량 막대 — 높이 8·모서리 4, `이번 달 12,400 / 27,000회` + `46%`(숫자와 단위 함께). 표시한 퍼센트가 80 이상이면 경고색+`주의`, 90 이상이면 위험색+`위험`, 한도를 넘으면 `한도 넘음`. **모르면 막대(빈 길 포함)를 만들지 않고** `확인할 수 없어요` 글만(UI-C1b 에서 고침 — 옛 부품은 빈 길을 그려 0% 로 읽혔다). `tag` 는 줄 끝 꼬리표(예시 값이면 `예시`). **설정 화면의 용도 카드가 기간마다 하나씩 쓴다**(UI-C1b) | 접근 이름 `이번 달 12,400 / 27,000회, 46%`(경고·위험이면 뒤에 `, 주의`·`, 위험`, 꼬리표가 있으면 끝에 `, 예시`). 막대는 누르는 곳이 아니라 Tab 정거장이 아니다 |
| `SemanticBadge(kind, text)` (`components.py`) | 의미별 배지 11종 — 색과 글자 함께·한 줄·높이 24. 글자 수가 16자를 넘으면 …로 줄이고 전체 글은 툴팁에 둔다. 모르는 종류는 오류 | 접근 이름 = 종류 이름(글이 다르면 `종류: 글`) |
| `TabBar(tabs, current)` (`ui/qt/bars.py`) | 밑줄형 탭 줄 — 높이 46, 고른 탭은 `primary_700` 글자 + 2px 밑줄, 아래에 가는 구분선. 고르면 `changed(열쇠)` | Tab 정거장은 고른 탭 하나, ←·→(한 바퀴)·Home·End 로 이동하고 포커스도 따라간다. 접근 이름 `개요 탭, 4개 중 1번째` |
| `ActionBar(actions, more_items)` | 아래 고정 행동 줄 — 주요 1(큰 단추 44)·보조 ≤3(40)·3차 여러 개(글자만)·위험 3차 ≤1(`danger_ghost`)·`더보기 ⋮`. 규칙을 어기면 오류. 폭이 모자라면 위험·3차 → 보조 순서로 `더보기` 메뉴(위쪽으로 열림)로 접히고, 더 좁으면 주요 1개만. 누르면 `triggered(열쇠)` | 단추는 접근 이름=글자·Enter/Space·포커스 링. `⋮` 는 접근 이름 `더보기 메뉴 열기` + 툴팁(키보드 포커스에도 보임). 꺼진 행동은 `disable(열쇠, 이유)` 로 이유를 툴팁에 |
| `set_card_state(frame, state, layout)` (`components.py`)·`theme.shadow_effect`·`theme.card_look` | 기존 `Card` 틀에 상태(`default`·`hover`·`selected` — 선택은 2px 파란 테두리)와 그림자 3종(`QGraphicsDropShadowEffect` — 카드 틀 하나에만)을 입힌다. 선택 때 테두리가 두꺼워진 만큼 안쪽 여백을 줄인다. 번짐이 잘리지 않게 부모에 여백이 필요하다 | 시각만(상태 이름은 부품을 쓰는 쪽이 접근 이름에 넣는다) |
| `Button` 의 `kind="danger_ghost"` | 위험한 3차 행동 — 배경 없는 빨간 글자(`danger_text`), 가리키면 옅은 빨강 면 | 다른 단추와 같다 |

**바뀐 기존 부품의 값**(구조는 그대로): 보조 단추(`secondary`)는 테두리 `secondary_border`·글자 `secondary_text`(가리키면 파란 테두리·누르면 옅은 파랑 면)이고, 주 단추는 가리키면 `primary_700`·누르면 `primary_pressed` 이며, 꺼진 주·위험 단추는 `disabled_fill` 채움 + 흰 글자다(보조·고스트의 꺼짐은 그대로 `disabled_bg` + `text_disabled`). 안내 배지 `info` 는 `info_100`·`info_text` 를 쓴다(값은 같다). 칩·카드·행·입력 칸은 새 토큰 값(색·모서리)만 따라간다.

## 3. 키보드·포커스 규칙(시험이 지킴)

- Tab 한 바퀴: 메뉴 → 본문의 모든 눌리는 곳(홈은 예시 데이터·다시 불러오기·추천 줄 — 예시 데이터에서 메뉴 다섯을 포함해 16곳(UI-C1d 때는 13곳 — P4b 가 블로그 관리, Seed 관리가 Seed 관리, P4d 가 주제 후보 메뉴를 더했다), 읽는 순서로 Naver A 다음 Naver B. 설정 화면은 예시 표시·새로 읽기·접이식 머리 다섯 — '정보' 를 펴면 진단 정보 단추 하나가 더 — 용도 카드와 사용량 막대 안에는 눌리는 것이 없다) → 다시 처음. 모든 정거장에 접근 이름이 있고 같은 곳을 두 번 지나지 않는다(스크롤 영역은 Tab 정거장이 아니다 — 포커스가 간 곳이 보이도록 Qt 가 스크롤해 준다).
- 화면이 다시 그려져도(서랍을 닫을 때·다시 불러올 때) 포커스는 `focus_key` 가 같은 위젯으로 돌아온다 — 서랍을 닫으면 그것을 연 추천 줄(`detail:<번호>`)로 돌아온다.
- 서랍·대화상자가 열린 동안 그 밖의 위젯은 Tab 에서 빠지고, 닫으면 원래 포커스 방식으로 복구된다.

## 3-2. 블로그 관리 화면 부품 (P4b — `ui/qt/blog_parts.py`·`blog_screen.py`, 이 앱에서 파일에 쓰는 첫 화면)

화면은 뷰모델(`ui/core/blogs_view.py` 가 만든 딕셔너리)을 공통 부품으로 조립하기만 하고 **이 파일들에는 쓰기 호출이 없다** — 단추를 누르면 셸(`shell.blog_*`)이 상태(`BlogsController`)와 어댑터(`ui/blogs_adapter.py`)를 거쳐 서비스(`service/blog_profiles.py` — 파일에 쓰는 곳은 그 거래 한 군데)를 부른다(시험이 소스를 훑는다). 색·크기·글은 토큰·문구표(`core/blog_text.py`)에서만 오고 부품 안에 직접 색·인라인 스타일·고정 크기·글꼴 이름이 없다.

```text
core/blog_form.py(칸 표·값 다듬기·칸 옆 쉬운 문장·변경 감지·칸 사이 규칙(우선·제외 키워드 겹침) — 서비스 생성자와 같은 판정) → core/blogs_view.py(BlogsController — 슬롯별 초안·낡은 판이면 다시 읽기·쓰기 중복 거절·뷰모델)
qt/blog_parts.py(부품) → qt/blog_screen.py(화면 조립) → qt/shell.py(읽기·쓰기 작업 스레드·확인창·이미지 선택기 연결)      ui/blogs_adapter.py → service/blog_profiles.py(저장·복제·삭제의 거래 한 곳)
```

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `SlotCard`(`blog_parts.py`) | 블로그 카드 — 윗줄(**별명**(없으면 종류 + 번호 — 슬롯 이름은 보이지 않는다) + 저장 전 변경 배지 + 상태 배지 `등록됨`·`등록 전`)·이름·블로그 ID·`종류 · 언어 · 후보 만들기 상태`·채널 역할(없으면 주요 주제 앞 셋). **등록한 블로그만** 카드다(새로 연결하는 중이면 `새 블로그` 카드). 전체가 누르는 칸이고 선택은 2px 테두리, 채널 색은 왼쪽 줄·테두리에만 쓴다. **카드의 최소 높이를 따로 정하지 않고** 같은 줄의 옆 카드가 길면 남는 높이는 아래로 간다(정하면 배치가 안쪽 필요 높이를 무시하고 눌러 배지가 반쯤 잘린다 — `ui_offscreen.find_squeezed` 와 시험이 지킨다) | 접근 이름 `예시 별명, 등록됨, 예시 블로그 가, 선택됨`, Enter·Space 로 선택, 다시 그려도 그 카드로 포커스가 돌아온다 |
| `AddCard`·`KindCard`(`blog_parts.py`) | `AddCard` — 목록 맨 끝의 `블로그 추가` 카드(점선 테두리·플러스 아이콘, 속성 `addcard`). 누르면 종류 고르기가 열린다. `KindCard` — 종류 고르기의 카드 하나(이름·`연결 N개 · 남은 자리 N개`·설명, 자리가 없으면 속성 `kindfull` 로 흐린 바탕 + 이유 글). 누르면 `chosen(종류)`, 자리가 없으면 눌러도 아무 일이 없다 | 둘 다 Enter·Space·Tab 정거장이고 접근 이름이 있다(막힌 종류의 접근 이름에 `더 연결할 수 없음` 이 있어 키보드로도 이유를 안다), 누르는 칸 36px 이상 |
| `IgnoreDoubleClick`(`blog_parts.py`) | 이벤트 필터 — 블로그 관리 행동 줄의 `취소`·`되돌리기`·`삭제` 단추가 더블클릭의 두 번째 눌림(`MouseButtonDblClick`)을 받지 않게 한다(첫 클릭으로 화면이 다시 그려져 같은 자리에 다른 카드의 `되돌리기` 가 생겨도 그 카드의 입력이 확인 없이 사라지지 않게). 눌림과 뗌이 한 번씩인 보통 클릭은 그대로다 | 키보드(Space·Enter)·접근 이름에는 영향이 없다 |
| `FieldView`(`blog_parts.py`) | 폼 칸 하나 — 이름(+ `필수`)·입력·안내·주의·오류. 종류 일곱(글·ID·낱말 목록·경로·하나만 고르기·**여럿 고르는 칩**(협찬 분야·선호 글 유형 — 칸마다 고를 수 있는 값이 다르고 칩을 누르면 `toggled_choice(칸 이름, 값)` 신호, P4c)·스위치). **blogsel(D-494)이 직접 입력 칸을 보기로 바꿨다**: ① 낱말 칸(주요 주제·카테고리·우선·제외 키워드)은 **제안 칩이 먼저**(`toggled_choice`)이고 직접 추가 입력 칸이 그 아래 보조다 — 한도에 닿았거나 다른 키워드 칸에서 이미 고른 낱말이면 칩이 꺼지고 이유가 툴팁·접근 설명에 있다(다른 칸에서 고른 낱말 때문에 꺼진 칩이 있으면 칸 아래 한 줄 `다른 키워드 칸에서 이미 고른 낱말은 흐리게 보여요 …` 로도 보인다 — BLOGSEL-2 ⑤, 한도는 원래 `N개까지 고를 수 있어요` 줄이 있다). ② 보기가 있는 한 줄 칸(채널 역할·대상 독자·문체)은 보기 칩 + `직접 입력` 칩(`chose_option`·`opened_custom`)이고 입력 칸은 직접 입력일 때만 보인다. ③ 별명·소개글은 입력 칸 아래 `제안` 문장과 `쓰기` 단추(`used_suggestion`)가 있다. ④ 이미지 칸은 **읽기 전용** 칸 + `파일 고르기`·`지우기`. ⑤ **칩 묶음의 키보드**(`ChipGroup`, BLOGSEL-2 ② — 낱말 제안·보기·여럿 고르기): 묶음 하나가 Tab 정거장 하나(고른 첫 칩 — 없으면 첫 칩 — 이고 마지막에 쓴 칩으로 이어진다)이고 화살표 키·Home·End 는 칩 사이를 **옮기기만** 한다(Space·Enter 로 켜고 끈다·꺼진 칩은 건너뛴다·끝에서는 반대 끝으로·Ctrl 같은 조합 키는 건드리지 않는다·옮긴 칩이 보이게 스크롤한다). Seed 서랍의 채널 칩도 같은 칸 부품이라 같다. 하나만 고르는 묶음(언어·색)은 라디오 규칙(고른 칩만 정거장·화살표가 옮기며 고른다) 그대로다. 새 열쇠가 없는 뷰모델(Seed 관리의 칸)은 그대로 그려진다(`vm.get`). 고치는 동안 **다시 그리지 않고** `update_from(뷰모델)` 이 오류 글·꺼짐·값만 그 자리에서 바꾼다(한글 조합·커서 보존, 값이 같으면 건드리지 않는다). 주의·오류 줄과 '목록에 없는 분야' 글은 **처음 필요할 때** 만든다(칸마다 거의 늘 숨어 있는 부품을 매번 만들지 않아 페이지를 다시 그리는 시간이 0.58→0.34초). 경로 칸은 읽기 전용이고 `파일 고르기`·`지우기` 단추가 함께 있다(위치 글만 — 파일을 읽지도 복사하지도 않는다). 색 프리셋은 견본 아이콘이 든 칩(`정하지 않음` 포함 — 색 직접 입력 칸은 없다) | 모든 입력에 접근 이름(칸 이름)과 접근 설명(오류 → 주의 → 꺼진 이유 → 안내 순), 누르는 칸 36px 이상. 하나만 고르는 칩 묶음(언어·색)은 **고른 칩만** Tab 정거장이고 나머지는 화살표 키로 옮긴다(Tab 으로 들어가 Space 를 눌러도 값이 안 바뀐다) |
| `NoticeBar`(`blog_parts.py`) | 마지막 동작의 결과 한 줄 — `ok`(저장했어요)·`info`·`warning`·`error`, 아이콘 + 글(색만으로 알리지 않는다) | 접근 이름 = 글 |
| `FormScroll`(`blog_parts.py`) | 폼 칸들이 들어가는 안쪽 스크롤. **기본 크기는 내용 높이가 아니라 최소 높이** — 줄바꿈 글이 있는 배치는 바깥 스크롤 영역의 부분 크기를 합쳐 구하므로 내용 높이를 주면 페이지가 창보다 길어져 아래 고정 행동 줄이 밀려난다. 가로 스크롤 없음 | 포커스가 간 칸은 보이는 곳으로 스크롤 |
| `SwatchIconEngine`·`swatch_icon(preset)` | 색 프리셋의 Primary·Secondary·Accent 를 나란한 네모로 그린 아이콘(`정하지 않음` 은 속이 빈 네모) — 그릴 때마다 토큰 색으로 그려 어느 배율에서도 선명하다 | 칩의 접근 이름은 글자(`색 프리셋: 따뜻한 생활 톤`) |
| `BlogsBody`(`blog_screen.py`) | 블로그 목록(폭 320 — 카드와 `블로그 추가` 카드)과 폼 또는 종류 고르기 — 본문 폭 780px 이상이면 나란히, 아니면 목록이 폼 위(목록 스크롤 최대 300). 목록은 폭에 맞춰 열 수를 정한다 | — |
| `ActionBar.set_enabled(key, enabled, reason)`(`bars.py`) | 기존 아래 고정 행동 줄(저장 주요·되돌리기·복제 보조·삭제 위험)에 더한 메서드 — 폼을 고치는 동안 화면을 다시 그리지 않고 단추를 켜고 끈다. 꺼진 이유(또는 복제해 넣을 슬롯 안내)는 툴팁·접근 설명으로 | 기존과 같다 |

**Tab 순서**: 메뉴 → 예시 표시·새로 읽기 → 블로그 카드(등록한 것만) → `블로그 추가` 카드 → 폼 칸(필수 넷·선택·주제 설정·모양 — 여럿 고르는 칩·제안 칩·보기 칩은 묶음 하나가 정거장 하나이고 화살표 키로 묶음 안을 옮긴다 — 이름 칸에서 저장 단추까지 Tab 이 등록한 폼은 140번에서 29번으로, 새 GitHub 폼은 134번에서 23번으로 줄었다) 또는 종류 고르기 카드 → 행동 줄의 켜진 단추. 숨은 입력 칸(`직접 입력` 이 아닐 때)과 한도·겹침으로 꺼진 칩은 정거장이 아니다. 모든 정거장에 접근 이름이 있고 같은 곳을 두 번 지나지 않는다(시험이 한 바퀴를 돈다). **하지 않는 것**: 자동 저장·색 직접 입력·이미지 복사·미리 보기·다섯 슬롯을 넘는 블로그 추가·눌러도 아무 일 없는 스위치(후보 만들기를 못 켜는 블로그는 꺼진 채 이유를 보인다).

## 3-3. Seed 관리 화면 부품 (Seed 관리 — `ui/qt/seed_parts.py`·`seed_screen.py`, 이 앱에서 파일에 쓰는 두 번째 화면)

화면은 뷰모델(`ui/core/seeds_view.py` 가 만든 딕셔너리)을 공통 부품으로 조립하기만 하고 **이 파일들에는 쓰기 호출이 없다** — 단추를 누르면 셸(`shell.seed_*`)이 상태(`SeedsController`)와 어댑터(`ui/seeds_adapter.py`)를 거쳐 서비스(`service/seed_manage.py` — 파일에 쓰는 곳은 그 거래 한 군데)를 부른다(시험이 소스를 훑는다). 확인창이 먼저인 두 쓰기(여러 개 바꾸기·제안 파일 등록)는 셸의 확인 콜백(`seed_bulk_confirmed`·`seed_import_confirmed`)에서만 시작된다(시험이 소스를 훑는다).

```text
core/seed_form.py(칸 표·값 다듬기·칸 옆 쉬운 문장 — 서비스 Seed 생성자와 같은 판정) · core/seed_rules.py(거르기·개수·채널별 쓸 수 있는 수·일괄 변경 대상과 미리 보기)
  → core/seeds_view.py(SeedsController — 씨앗별 초안·쓰기 중복 거절·확인 잠금·뷰모델) → qt/seed_parts.py(부품) → qt/seed_screen.py(화면 조립) → qt/shell.py(읽기·쓰기 작업 스레드·확인창·파일 선택기 연결)
ui/seeds_adapter.py → service/seed_manage.py(상태 바꾸기·고치기·등록·불러오기의 거래 한 곳)
```

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `SeedRow`·`SeedList`(`seed_parts.py`) | Seed 한 줄 — 고르는 상자·낱말(`h3`)·상태 배지(글자 `제안(승인 전)`·`사용 중`·`쉬는 중`)·보조 배지(`쉬게 할까요?`·`저장 전 변경`)·`대분류 › 중분류`·`소속 · 중요도 · 대상 유형`·`허용 채널 …`과 표시(우선·계절·지역·브랜드). 줄 전체가 누르는 칸이고 서랍이 열린 줄은 2px 파란 테두리·고른 줄은 옅은 파랑(스타일시트 `seedrow`·`checked`·`selected` 속성). 고름·서랍 열림은 줄을 다시 짓지 않고 `update_from` 이 그 자리에서 바꾼다. 목록은 40개씩 `40개 더 보기` | 줄 이름에 낱말·상태·소속·중요도(+ 쉬게 할까요·저장 전 변경), 설명 `누르면 자세한 내용이 열려요`. Tab·Enter·Space 로 열고 닫으면 포커스가 그 줄로 돌아온다 |
| `CheckBox`(`components.py`) | 고르는 상자 — 글자 없이 20px 상자(토큰 `SIZE["check_box"]`)를 36×36 누르는 칸 가운데에 직접 그린다(색은 토큰 팔레트 `theme.colors()` 에서 온다). 줄을 열지 않고 고르기만 한다 | 접근 이름 `○○ 고르기`, Space 로 켜고 끈다, 포커스 링 |
| `SeedFieldView`(`seed_parts.py`) | 서랍의 폼 칸 — 블로그 관리의 `FieldView` 와 같고 포커스 이름(`seeds:field:…`)만 다르다. 고치는 동안 다시 그리지 않고 `update_from` 이 오류 글·꺼짐·값만 바꾼다 | 같다 |
| `Drawer.set_content(widget, footer)`(`components.py`) | 서랍 안쪽은 스크롤 안에, `footer`(아래 고정 행동 줄 `ActionBar`)는 스크롤 밖 아래에 붙인다 — 칸이 길어도 늘 보인다. 줄을 바꿀 때 옛 줄은 숨기고 부모에서 떼어 지워지기 전에도 보이거나 Tab 이 가지 않는다. 서랍 틀과 스크롤 영역의 읽기용 이름은 안의 내용 이름(`Seed 상세와 고치기`·`새 Seed 등록 입력`)을 따른다(홈의 주제 상세로 돌아오면 `주제 상세`) | 서랍이 열린 동안 Tab 은 서랍 안(닫기 → 칸 → 행동 줄의 켜진 단추 → 스크롤 영역)에서만 돈다 |
| `gap(layout)`(`sidebar.py`) | 사이드바의 묶음 사이·'다음 단계' 앞 빈 칸 — 보통 8px 이고 세로가 모자라면 0 까지 줄어든다(남는 높이는 아래 늘림 칸이 가져가므로 보통 크기의 모양은 그대로) | — |
| `NoticeBar`·`ActionBar`·`chip_row`(재사용) | 알림 줄(마지막 동작의 결과)·아래 고정 행동 줄(`set_enabled` 로 단추를 켜고 끈다)·일괄 변경 줄(폭이 모자라면 칩처럼 다음 줄로 넘어간다 — 최소 창에서 가로 스크롤이 생기지 않게) | 기존과 같다 |

**Tab 순서**: 메뉴 → 머리(예시 표시·제안 파일 불러오기·새 Seed 등록·다시 읽기) → 개수 요약 카드(상태 칩·검색 칸·더 거르기·거르기 풀기·모두 고르기·고른 것 풀기·일괄 변경 단추 — 꺼진 것은 건너뜀) → Seed 줄과 그 고르는 상자(줄마다 둘 다 정거장) → 더 보기. 서랍·확인창이 열리면 그 안에서만 돈다. 모든 정거장에 접근 이름이 있고 같은 곳을 두 번 지나지 않는다(시험이 한 바퀴를 돈다). **하지 않는 것**: 삭제 단추·자동 승인·눌러도 아무 일 없는 단추(꺼진 단추는 이유를 툴팁·접근 설명으로 보인다).

## 3-4. 키 연결 부품 (P4f — `ui/qt/key_parts.py`, 설정 카드의 키 행동)

화면은 뷰모델(`ui/core/keys_view.py` 의 `KeysController.card_keys`·`RegisterDraft.vm`)을 공통 부품으로 조립하기만 하고 **이 파일에는 쓰기 호출도 보관소 호출도 없다** — 단추를 누르면 셸(`shell.key_*`)이 컨트롤러와 어댑터(`ui/keys_adapter.py`)를 거쳐 서비스(`service/connections.py`)를 부른다(시험이 소스를 훑는다). 키 글은 마스킹 입력 칸에만 있고 칸의 글을 상태·신호에 싣지 않는다(키 칸에는 `textChanged`·`textEdited` 를 잇지 않는다).

```text
core/key_rules.py(느슨한 입력 규칙)·core/key_text.py(문구) → core/keys.py(SecretBox·KeysWriter·가짜 공급자) → core/keys_view.py(KeysController·RegisterDraft)
qt/key_parts.py(KeyRow·key_section·KeyDialog·RenameForm) → qt/screens.py(purpose_card) → qt/shell.py(쓰기 작업 스레드·확인창·클립보드 정리)      ui/keys_adapter.py → service/connections.py
```

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `SecretInput`(`components.py`) | 키 입력 칸 — 마스킹(`Password`)·플레이스홀더·툴팁 없음. Qt 가 예측 입력·자동 대문자·민감 정보 표시를 켠다. 복사·잘라내기는 글을 클립보드에 내보내지 않는다 | 접근 이름 `○○ 입력(글자는 가려져요)`·접근 값은 점뿐이다(입력하는 동안 글자 수만큼 — 키 글자는 아니다, 시험이 훑는다. 비운 뒤엔 없다) |
| `wipe_input(칸)`(`components.py`) | 칸을 비운다 — `clear()` 가 아니라 `setText("")`(되돌리기·다시 하기 기록까지 지운다) | — |
| `Dialog.clear()`·`cleanups`(`components.py`) | 안쪽 배치(단추 줄)의 부품까지 재귀로 치우고(치우는 위젯은 바로 숨긴다) 정리 훅을 먼저 부른다 — 옛 확인창의 단추가 새 대화상자에 남지 않는다(F-H1) | 닫힘·교체·창 닫힘 어느 길로든 훅이 한 번 불린다 |
| `KeyRow`(`key_parts.py`) | 키 한 줄 — 별칭·배지(글자 동행)·작은 글 줄·이 줄만의 안내·행동 단추(폭이 모자라면 다음 줄로) | 행 이름 `별칭, 사용`·단추 이름 `행동 — 별칭`·36px 이상·꺼진 까닭은 툴팁·접근 설명 |
| `key_section`(`key_parts.py`) | 카드의 키 구역 — 저장소 안내·`키 없음` 안내·행들·`키 등록` 단추(자리가 없을 때 까닭이 글로 보인다) | 단추 이름 `○○ 키 등록` |
| `KeyDialog`·`DialogScroll`(`key_parts.py`) | 키 등록 대화상자 — 입력 단계·확인 단계(요약에는 키 없음 — 안내 글은 입력 단계에만)·둘째 키 약관 스위치·제공자 칩. 몸의 키만큼 열리고(`DialogScroll` 이 폭에 따른 높이를 알려 준다 — 기본 스크롤 영역은 그것이 없어 최소 크기로 쪼그라든다) 단계가 바뀌면 `_refit` 이 키를 다시 맞춘다. 낮은 창에서만 스크롤되고 단추 줄은 늘 보인다. 저장·취소·닫기·교체 때 칸을 비우고 클립보드를 정리한다 | Tab 은 대화상자 안에서만 돈다·처음 포커스는 입력 단계 = 첫 키 칸, 확인 단계 = 취소 |
| `RenameForm`(`key_parts.py`) | 별칭 바꾸기 입력 | 처음 포커스 = 입력 칸 |
| `qt_clipboard_wipe`(`shell.py`) | 클립보드의 글이 붙여 넣은 키와 (줄바꿈·앞뒤 공백을 뺀 뒤) 같으면 비운다 — 다른 글은 건드리지 않는다 | — |

**Tab 순서**: 메뉴 → 새로 읽기 → 접이식 머리 → 카드마다 (행: 행동 단추들 → `키 등록`). 대화상자가 열려 있는 동안은 그 안에서만 돈다(별칭 → 제공자 칩 → 키 칸들 → 취소 → 다음). **하지 않는 것**: 키 보이기·키 복사·자동 저장·눌러도 아무 일 없는 단추.

## 3-5. 주제 후보 화면 부품 (P4d — `ui/qt/candidate_parts.py`·`candidate_screen.py`, 주제 엔진 보관함에 쓰는 첫 화면)

화면은 뷰모델(`ui/core/candidates_view.py` 가 만든 딕셔너리)을 공통 부품으로 조립하기만 하고 **이 파일들에는 쓰기 호출이 없다**(파일 열기·네트워크·서비스·엔진 보관소를 부르지 않는다 — 시험이 소스를 훑는다). 단추를 누르면 셸(`shell.cand_*`)이 상태(`CandidatesController`)와 어댑터(`ui/candidates_adapter.py`)를 거쳐 서비스(`service/topics.py` — 읽기 `list_candidates`·`plan_candidates`, 쓰기 `generate_candidates` 한 번)를 부른다. 확인창이 먼저인 쓰기는 셸의 확인 콜백(`cand_make_confirmed`)에서만 시작된다(시험이 소스를 훑는다 — 이 함수를 확인창의 `만들기` 말고 어디서도 쓰지 않고, 그 확인창은 미리 보기가 끝났을 때만 뜬다).

```text
core/candidate_text.py(문구) · core/candidate_rules.py(카드·상세 글·거르기·찾기·정렬·빈 화면·고정↔서랍 선택) · core/candidates.py(값·공급자 틀·가짜 공급자)
  → core/candidates_view.py(CandidatesController — 읽기·거르기·선택·미리 보기·확인 잠금·뷰모델) → qt/candidate_parts.py(부품) → qt/candidate_screen.py(화면 조립) → qt/shell.py(읽기·쓰기 작업 스레드·확인창·상세 창 연결)
ui/candidates_adapter.py → service/topics.py(list_candidates·plan_candidates·generate_candidates)·service/topic_files.py(프로필·Seed 읽기)
```

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `CandidateCard`(`candidate_parts.py`) | 후보 한 장 — 이미지 자리(`CardImage` — 주제 아이콘 + 그라디언트·위 왼쪽에 배지 최대 둘)·제목(`ClampedLabel` 2줄)·요약(3줄)·키워드 칩(`CardChip` 셋 + `+N`, 폭이 모자라면 다음 줄)·푸터(`ChannelAvatar`·채널 이름·점수 링 `ScoreWithLabel`). 전체가 누르는 칸이고 선택된 카드는 2px 파란 테두리 + 그림자 하나(스타일시트 `candcard`·`selected` 속성 — 선택은 카드를 다시 짓지 않고 `update_from` 이 그 자리에서 바꾼다) | 접근 이름 `제목, 채널, 점수 N점 구간 이름`(점수가 없으면 `점수 계산 전`), 설명 `작업 상태 …, 누르면 점수와 이유가 열려요.`. Tab 정거장 하나(안의 글·배지·링은 정거장이 아니다)·Enter·Space 로 열고 닫으면 포커스가 그 카드로 돌아온다 |
| `CandidateGrid` | 카드 격자 — 열 수는 규칙(`part_rules.detail_layout`)이 정한다. 3열에서는 폭 300 이하·가운데. 같은 번호의 카드는 갱신하고 사라진 것만 지운다. 비면 안내 카드 하나(`empty_card` — 아이콘·제목·설명, 거른 결과가 없을 때만 보조 단추 `거르기 풀기`), 더 있으면 `N개 더 보기` 단추 하나. 거르기·검색으로 카드를 줄였다 늘려도 Tab 순서가 화면의 읽는 순서가 되게 격자가 정거장을 다시 이어 준다 | 격자 이름 `후보 카드 목록` |
| `DetailPane` | 창 오른쪽에 붙는 고정 상세 창(`middle` 가로 틀의 본문 오른쪽 형제 — 서랍처럼 겹치지 않는다). 안쪽은 스크롤되고 가로 스크롤은 끈다. 서랍과 같은 내용 부품(`candidate_screen.detail_content`)을 쓴다. **아래 고정 행동 줄**(P4e — `set_content(…, footer=)`)이 스크롤 밖에 있다 | 이름 `후보 상세 정보`. 스크롤 영역은 상세가 있을 때만 이름 있는 정거장(키보드로 내려 본다), 안내만 있을 때는 정거장이 아니다 |
| `FactorRow` | 점수 구성 한 줄 — 항목 이름·점수 글(`85점`)·가는 막대(`Track` — 색은 `bar_base` 하나, 80·90 에서 경고·위험색으로 바뀌지 않는다)·가중치 작은 글. **평가하지 못한 항목은 막대 없이 `평가 전`**(0점 막대가 아니다) | 이름 `채널 적합도 95점, 가중치 25`(평가 전이면 `채널 적합도 평가 전`) |
| `ClampedLabel` | 여러 줄 글을 `lines` 줄까지만 보이고 넘치면 마지막 줄 끝을 `…` 로 줄인다(`heightForWidth`). 전체 글은 툴팁 | 읽는 글이 아니라 카드 이름이 대신 읽힌다 |
| `ChannelAvatar` | 안에 글자 하나(이름의 끝 숫자 — 기본 이름 `네이버 블로그 1` 이면 `1`, 별명이면 첫 글자)가 있는 원 — 채널 색은 테두리와 바탕에만 쓰고 글자색은 `text_strong`. 글자가 늘 함께 있어 색만으로 구분하지 않는다 | 장식(이름은 옆 글이 말한다) |
| `ScoreWithLabel`(재사용) | 홈의 점수 링과 같은 부품 — 카드는 링 44, 상세는 72 | 접근 이름 `점수 92, 우선 추천` |
| `NoticeBar`·`chip_row`·`Card`·`StateCard`·`Disclosure`·`FilterChip`·`TextInput`(재사용) | 알림 줄·칩 줄(폭이 모자라면 다음 줄로 넘어가 가로 스크롤이 없다)·카드·상태 카드·진단 정보 | 기존과 같다 |
| 셸의 `detail_pane`·`drawer` | 창 논리 폭이 정한다 — 고정 방식이면 `DetailPane`, 아니면 기존 `Drawer`(`Drawer.set_content`) | 서랍이 열린 동안 Tab 은 서랍 안에서만 돈다 |

**Tab 순서**: 메뉴 → 머리(예시 표시·`후보 만들기`·다시 읽기) → 거르기 카드(채널·작업 상태 칩 → 검색 칸 → `더 거르기` → (열렸으면 점수 구간·주제 묶음 칩) → `거르기 풀기`) → 카드(위→아래·왼쪽→오른쪽, 카드마다 정거장 하나) → `N개 더 보기` → 상세 창(스크롤 영역 → 닫기 → 번호 복사 → 아래 줄의 `이 주제로 만들기`). 서랍·확인창이 열리면 그 안에서만 돈다. 모든 정거장에 접근 이름이 있고 같은 곳을 두 번 지나지 않는다(시험이 한 바퀴를 돈다). **하지 않는 것**: 즐겨찾기 별(저장할 곳이 없다)·사진 썸네일·후보 삭제·상태 바꾸기·눌러도 아무 일 없는 단추(꺼진 단추는 이유를 툴팁·접근 설명으로 보인다 — P4e 가 상세 아래 고정 줄에 주요 단추 `이 주제로 만들기` 하나를 더했다, §3-6).

## 3-6. 초안 작성 화면 부품 (P4e — `ui/qt/draft_parts.py`·`draft_screen.py`, 파일에 쓰지 않고 클립보드에만 복사하는 화면)

화면은 뷰모델(`ui/core/drafts_view.py` 의 `DraftsController` 가 만든 딕셔너리)을 공통 부품과 이 화면의 부품으로 조립하기만 하고 **이 파일들에는 쓰기·복사·네트워크·서비스 호출이 없다**(시험이 소스를 훑는다). 단추를 누르면 셸(`shell.drf_*`)이 상태를 거쳐 어댑터(`ui/drafts_adapter.py` — 서비스 `make_body_for_engine` 하나만 부른다)와 클립보드를 부른다. **클립보드에 쓰는 곳은 셸의 `_drf_do_copy` 하나**이고 복사 관문(D-284)이 '복사해도 된다' 고 한 글이나 확인창의 `그래도 복사` 를 거친 글만 받는다(시험이 소스를 훑는다). 주소를 여는 곳(`drf_open`)도 한 곳이다.

```text
core/draft_text.py(문구) · core/draft_rules.py(확인 권장 가르기·고친 정도·검사·복사 관문·열기 주소·선택 입력) · core/drafts.py(값·공급자 틀·가짜 공급자) · core/draft_garbage.py(글 모양 점검 — 위치 문구·가림·무시 기억·세대 번호·카드 뷰모델, 복사 관문을 모른다)
  → core/drafts_view.py(DraftsController — 상태·편집·검사·관문·뷰모델) → qt/draft_parts.py(부품) → qt/draft_screen.py(화면 조립) → qt/shell.py(작업 스레드·확인창·클립보드·주소 열기·떠나기 막기)
ui/drafts_adapter.py → service/draft_engine.py(make_body_for_engine — 읽기 전용)
```

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `TextArea`(`draft_parts.py`) | 여러 줄 편집기(`QPlainTextEdit`) — 본문 편집기와 선택 입력의 여러 줄 칸. 한글 입력기 조합이 끊기지 않게 글자를 칠 때마다 화면을 다시 그리지 않는다(`edited(글)` 신호만). **Tab 은 들여쓰기가 아니라 다음 칸으로 간다**(`setTabChangesFocus`). 모서리·테두리·포커스 링은 스타일시트(`QPlainTextEdit[editor]`). 새 초안을 만드는 동안(다시 만들기)에는 본문 편집기와 제목 입력 칸이 **읽기 전용**이다(`setReadOnly` — 친 글이 새 초안에 덮이지 않게, D-297) | 이름이 있고(본문 편집기·`… 입력(선택)`) 키보드 정거장 하나. 읽기 전용일 때 접근 설명 `새 초안을 만드는 동안에는 고칠 수 없어요.` |
| `TitlePick` | 제목 후보 한 줄 — `후보 1` + 제목 글(둘째 줄까지) + 고른 것에 `선택됨` 표시. 전체가 누르는 칸(Enter·Space). 스타일시트 `QFrame[draftpick]`(선택·hover·포커스) | 이름 `제목 후보 1: …`·정거장 하나(새 초안을 만드는 동안에는 꺼진다) |
| `InspectCard` | 검사 결과 — 상태 글 하나와 줄 목록(검사 전·고침 표시·키 모양과 걸린 자리·건강 효과 단정·확인이 필요한 곳·직접 쓴 글의 건강 낱말·거의 안 고침·**본 범위를 밝히는 초록 문구**). 글을 칠 때 그 자리에서 바뀐다 | 상태 글을 읽는다 |
| `GarbageCard` | 글 모양 점검 카드(N-2)의 글 — 상태 줄(안내 파랑·흐린 회색뿐)·`본문이 변경됨` 줄·종류별 묶음(이름·`N건`·이유 한 번)과 항목 줄 + 항목마다 `무시`, 보이면 `모두 무시(N건)`·`무시한 N건 다시 보기`. 모양이 그대로면 아무것도 다시 만들지 않아 글을 칠 때마다 불려도 가볍다. 단추는 항목마다 새로 만들어 접근 이름(`‘종류’ 경고 N번 무시하기`)·열쇠 `drf-garbage:…` 를 달고 `stops()` 가 지금 Tab 에 걸리는 단추를 돌려주어 화면이 `검사하기` 다음으로 Tab 순서를 다시 잇는다. 이 부품에는 글을 고치거나 복사하는 코드가 없다(경고만) | `무시` 단추마다 접근 이름·정거장 하나, 누른 단추가 사라지면 포커스는 이웃 단추(없으면 `검사하기`)로 간다 |
| `lines_box`·`set_copy_look` | 줄 목록 상자·복사 단추의 `✓ … 복사됨` 모양(성공 색 + 글자가 함께 — 스타일시트 `QPushButton[copied="true"]`, 끝나면 원래 글로) | 접근 이름도 `✓ 본문 복사됨` 으로 함께 바뀌어 화면 읽기 프로그램이 읽는다(끝나면 원래 이름 `본문 복사`) |
| `ActionBar`(`bars.py`, 재사용) | 아래 고정 행동 줄 — 안쪽 스크롤 밖. 복사 셋(보조 둘·주요 `전체 복사`)·`네이버 글쓰기 열기`(보조). 폭이 모자라면 `더보기 ⋮` 로 접힌다. 후보 상세의 아래 고정 줄(`이 주제로 만들기`)도 같은 부품이다 | 꺼진 단추의 까닭은 툴팁·접근 설명(키보드로도 읽힌다) |
| `Accordion`(재사용) | 확인 권장 — 카드 맨 위의 작은 글자 한 줄(`출처: … · 확인 필요 N건`) 아래에 `이 글에만 해당`(펼침)·`모든 글 공통`(접힘), 건수 칩. 펼침 상태는 컨트롤러가 기억한다 | 머리 단추가 정거장·열쇠 `drf-checks:specific`·`drf-checks:common` |
| `CardChip`·`chip_row`·`Card`·`StateCard`·`Skeleton`·`Disclosure`·`FilterChip`·`TextInput`·`NoticeBar`·`SampleBadge`(재사용) | 키워드·태그 칩·카드·상태 카드·줄 모양 자리 표시·진단 정보·블로그/글 유형 칩·제목 입력 칸·알림 줄·예시 표시 | 기존과 같다 |
| 셸의 `DetailPane` 아래 칸·`Drawer` 아래 칸 | 주제 후보 상세의 아래 고정 줄(`candidate_screen.detail_footer`) — `DetailPane.set_content(내용, footer=)`·`stops()` 가 이 줄의 단추를 읽는 순서 끝에 잇는다(줄 안에서 숨겨 둔 `더보기` 는 정거장이 아니다) | 정거장 `act:make` |

**Tab 순서**: 메뉴 → 머리(`← 주제 후보`) → `만드는 방법 바꾸기` → (펼쳤다면 블로그·글 유형 칩 → 선택 입력 칸들 → `다시 만들기`) → 제목 입력 → 제목 후보 셋 → 본문 편집기 → `검사하기` → `키워드 복사` → `태그 복사` → `요약 복사` → 이미지 단추 → `이 글에만 해당` → `모든 글 공통` → 아래 줄(`제목 복사` → `본문 복사` → `전체 복사` → `네이버 글쓰기 열기`). 확인창이 열리면 그 안에서만 돈다(처음 포커스는 취소). 모든 정거장에 접근 이름이 있고 같은 곳을 두 번 지나지 않는다(시험이 한 바퀴를 돈다). **하지 않는 것**: 눌러도 아무 일 없는 단추·이미지 검색 단추·썸네일·초안 저장 단추·AI 단추·발행 단추.

## 3-7. 내 글 문체 참고값 보기 부품 (N-3a — `ui/qt/style_dialog.py`, 저장도 AI 도 네트워크도 없는 읽기 전용 대화상자)

화면은 뷰모델(`ui/core/style_view.py` 의 `StyleStudy.view` 가 만든 딕셔너리)을 공통 부품으로 조립하기만 하고 **이 파일들에는 저장·복사·네트워크·서비스 호출이 없다**(시험이 소스를 훑는다). 파일 검사와 계산은 공급자(`ui/style_adapter.py` 의 `ServiceStyleProvider` — 읽기 기반 `read_own_files`·`check_pasted_text` 와 순수 계산 `analyze`·`summarize` 네 함수만 부른다)가 작업 스레드에서 한다.

```text
core/style_text.py(문구 — T 에 합쳐진다) · core/style_view.py(StyleStudy — 상태·세대 번호·뷰모델, StyleProvider 틀·FakeStyleProvider, 숫자 서식)
  → qt/style_dialog.py(style_entry_card·PasteBox·StyleDialog) → qt/shell.py(style_open·style_pick·style_compute·style_again·결과·실패 받기·버리기)
ui/style_adapter.py → service/own_posts.py(읽기 전용) · content/style_stats.py(순수 계산)
```

| 부품 | 모양·규칙 | 접근성·키보드 |
|---|---|---|
| `style_entry_card`(`style_dialog.py`) | 설정 화면 맨 아래의 일반 카드 — 제목·한 줄 설명·`열기`(보조 단추). 카드 틀에는 접근 이름을 달지 않는다(안의 단추가 이름을 가진다). 속성 `style_entry` 로 시험이 찾는다 | 단추 이름 `내 글 문체 참고값 보기 열기`·Tab 정거장 `style-open` |
| `PasteBox` | 붙여 넣기 칸(`QPlainTextEdit`) — 평문뿐, **Tab 은 글자가 아니라 다음 칸으로**(`setTabChangesFocus`), 최소 높이 110px. 비울 때는 `wipe`(되돌리기·다시 하기 기록까지 지운다). 읽기 전용·꺼진 동안은 입력기가 확정한 글도 받지 않는다 | 이름 `붙여 넣을 글`·글자 수 줄의 이름 `붙여 넣은 글자 수 N자`·정거장 `style:paste` |
| `StyleDialog` | 대화상자의 안쪽 — 고르기 모습(안내·`파일 고르기`·고른 글 줄·붙여 넣기 칸·거절 문장·상태)·결과 모습(표 카드·센 개수·안내)·아래 단추 줄. 모습은 컨트롤러가 정하고 `refresh()` 가 그린다. 표는 뷰모델의 모양(서명)이 바뀔 때만 다시 만든다 | 몸(`DialogScroll`)이 이름 `문체 참고값 대화상자 내용` 의 정거장·단추마다 이름 |
| `DialogScroll`(`key_parts.py`, 재사용) | 몸의 스크롤 — 창이 낮을 때만 스크롤되고 키보드(방향키)로 스크롤된다 | 정거장 `style:scroll` |
| `Dialog`(`shell.py` 의 창 안 대화상자, 재사용) | 폭 760px(창 논리 폭의 94% 를 넘지 않는다)·정리 훅(`cleanups`) — 닫는 어느 길로든 `StyleDialog.discard` 가 입력 칸·고른 글·결과를 비운다 | Esc 로 닫으면 포커스가 `열기` 로 돌아간다·Tab 은 대화상자 안에서만 돈다 |
| `UI.Card`·`UI.label`·`UI.Button`(재사용) | 진입 카드·표 카드·글·단추 | 기존과 같다 |

**Tab 순서**: 몸(스크롤) → `파일 고르기` → `빼기`들 → 붙여 넣기 칸 → `다른 글로 다시 하기`(결과 모습만) → `닫기` → `계산하기`(고르기 모습만). 안 보이거나 꺼진 부품은 Qt 가 건너뛴다. 열면 `파일 고르기`, 결과가 나오면 몸(스크롤), 고른 뒤에는 `파일 고르기`(꺼졌으면 `계산하기`, 그것도 꺼졌으면 `닫기`)에 포커스가 간다.

## 3-8. 참고 글 보관함 부품 (D-489·D-490 — `ui/qt/references_dialog.py`, 파일에 쓰는 대화상자)

화면은 컨트롤러(`ui/core/references_view.py` 의 `ReferenceLibrary`)의 뷰모델을 공통 부품으로 조립하기만 하고 **이 화면 코드에는 파일을 쓰거나 지우는 호출이 없다** — 서비스 호출은 공급자(`ui/references_adapter.py` 의 `ServiceReferencesProvider`)가 **화면 스레드에서 곧바로** 하고(작업 스레드가 아니다 — 50편이 모두 10만 자일 때 열기 0.7초·저장 0.39초 안팎이라 스레드를 두지 않았다, `UI_STATES.md` 5-6d), 파일을 바꾸는 일은 `service/references.py` 한 곳이 한다. 진입은 `ui/qt/style_dialog.py` 의 문체 보기 대화상자 안의 `참고 글 보관함 열기` 단추 하나다(다른 화면은 바뀌지 않는다).

```text
core/references_view.py(ReferenceLibrary — 상태·세대 번호·뷰모델, ReferencesProvider 틀·FakeReferencesProvider)
  → qt/references_dialog.py(ReferencesDialog) ← qt/style_dialog.py 안의 `참고 글 보관함 열기`
ui/references_adapter.py(ServiceReferencesProvider) → service/references.py(저장·읽기·지우기 — 화면 없음)
```

**Tab 순서**: 몸(스크롤) → 목록의 `열기`들 → `다시 읽기`(목록을 못 읽었을 때만 보인다) → 제목 칸 → 본문 칸 → 확인 줄 단추 → `지우기` → `파일에서 올리기` → `새 글` → `닫기` → `저장`. 안 보이거나 꺼진 부품은 Qt 가 건너뛰고, 실제로 Tab·Shift+Tab 을 눌러 이 순서와 대화상자 밖으로 새지 않음을 시험이 본다. 글을 열면 편집 칸(제목 칸)이 보이는 곳으로 스크롤되고 포커스가 제목 칸에 간다. 열린 글 줄은 파랑과 '지금 편집 중' 글자·접근 이름 둘 다로 표시한다.

문구는 `ui/core/text.py` 의 `T` 가 정본이다. 상태별 동작은 `UI_STATES.md` 5-6d, 화면 규칙은 `UI_DESIGN_SPEC.md` 4-9 에 있다. **Qt 부품은 offscreen 으로 띄워 확인했다**(실제 윈도 배율 렌더·한글 입력기·화면 읽기 프로그램은 운영자 PC — `UI_VISUAL_QA.md` 16절).

## 3-9. 사진 정리 부품 (D-499 — `ui/qt/photo_parts.py`·`photo_screen.py`, 사진 파일은 읽기만 하는 대화상자)

화면은 컨트롤러(`ui/core/photo_view.py` 의 `PhotoBoard`)의 뷰모델을 공통 부품(`UI.label`·`UI.Button`·`UI.FilterChip`·`UI.chip_row`·`UI.TextInput`·`UI.CheckBox`·`UI.Card`·`DialogScroll`)으로 조립하기만 하고 **이 화면 코드에는 파일을 쓰거나 지우는 호출·네트워크·하위 프로세스·표준 출력이 없다**(시험이 소스로 지킨다). 규칙(한도·확인이 풀리는 때·모두 확인의 확인 줄·순서·지우기와 되돌리기·못 넣은 파일·큰 PNG 판정·종류별 예시와 기본 들어갈 곳)은 모두 core 에 있다.

```text
core/photo_rules.py(규칙표·판정) · core/photo_text.py(문구) · core/photo_view.py(PhotoBoard — 상태·뷰모델, PhotoProvider 틀·FakePhotoProvider)
  → qt/photo_screen.py(PhotoSheet — 대화상자 안쪽·상태 줄·단추 줄·미리보기 차례 만들기) → qt/photo_parts.py(PhotoRowCard·FieldBox·ChipGroupKeys — 종류·장소 분위기 칩 묶음의 Tab 정거장 하나와 방향키)
core/drafts_view.py(DraftsController.photos) ← qt/draft_screen.py(`사진` 카드·`사진 넣기(선택)` 줄) · qt/shell.py(photos_open·photos_close·photos_escape·photos_pick·photos_relink)
ui/photo_adapter.py(ServicePhotoProvider) → service/photo_manifest.py(check_files — 읽기만) + qt/imagecheck.py(이미지 읽기 — 늦게 가져온다, PySide6 가 없어도 이 어댑터는 가져온다)
```

- **줄(`PhotoRowCard`)은 사진이 지워질 때까지 같은 부품**이다 — 창이 다시 그릴 때(`apply`) 칸의 글을 덮어쓰지 않고(포커스가 있거나 한도를 넘겨 반영하지 못한 글은 그대로), 칩은 고를 이름이 바뀐 때만 다시 만들어 클릭한 칸이 사라져 포커스를 잃는 일이 없다.
- **글 칸(`FieldBox`)**: 치는 동안은 글자 수와 한도 넘음 글만 그 자리에서 바꾸고, 칸을 떠나거나 Enter·닫기·다른 행동 앞에서 한 번 규칙(`PhotoBoard.set_text`)에 넘긴다. 한도를 넘기거나 검사에 걸린 글은 반영하지 않고 이유를 칸 아래에 보인다.
- **미리보기**는 한 장씩 차례로(`QTimer.singleShot`) 메모리에서만 만들고(`imagecheck.make_thumbnail` → 96px) 큰 PNG·없는 파일은 만들지 않는다. 시험이 `photo_preview_maker` 를 바꿔 끼운다.
- **파일 선택 창**(`qt_files_picker` — `QFileDialog.getOpenFileNames`)은 위치만 주고 시험은 가짜 선택기를 넣는다. 고른 위치 목록은 쓰고 나서 바로 놓는다(`paths = None`).
- 눌리는 곳의 `focus_key` 는 `pho:<이름>:<사진 번호>` 꼴이다(예: `pho:type:p001:간판`·`pho:confirm:p003`).

**Tab 순서**와 접근 이름·크기는 `UI_DESIGN_SPEC.md` 4-10 에 있고, 실제로 Tab·Shift+Tab 을 눌러 이 순서와 대화상자 밖으로 새지 않음을 시험이 본다(`tests/test_ui_qt_photo.py`·`test_ui_qt_photo_keys.py`·`test_ui_qt_photo_rows.py`). 상태별 동작은 `UI_STATES.md` 5-6e, **Qt 부품은 offscreen 으로 띄워 확인했다**(실제 윈도 배율 렌더·한글 입력기·화면 읽기 프로그램은 운영자 PC — `UI_VISUAL_QA.md` 18절).

**3단계(D-501)**: 초안 작성 화면의 사진 카드(`draft_screen.py`)에 `_photos_trash`(되돌릴 사본 줄 — `UI.label` 셋·`UI.Button("secondary", size="sm")` 둘을 세로로 쌓은 한 덩어리)와 `_apply_trash`(뷰모델에 맞춰 글·꺼짐·보임을 바꾸고 사라지는 단추에 포커스가 있었으면 `사진 정리 열기` 로 옮긴다)가 있다. `refresh_photos` 가 사진 수·고쳤어요·다시 만들기·되돌릴 사본을 같은 자리에서 바꾼다(화면 전체를 다시 그리지 않는다). 새 공통 부품은 없다.


## 4. 새 부품을 더할 때

① 색·크기는 `tokens.py` 에 키를 더하고 `theme.py` 스타일시트에서만 쓴다 ② 접근 이름·키보드·포커스 링 ③ `components.py` 에 한 곳으로(그리는 부품은 `gauges.py`, 줄 모양 부품은 `bars.py` — 새 파일도 직접 색·인라인 스타일 시험이 훑는다. 계산은 PySide6 없이 시험하도록 `ui/core/` 의 순수 모듈에 둔다) ④ 시험(접근 이름·36px·직접 색 없음은 자동으로 훑는다) ⑤ 이 표에 한 줄.

## 5. 하지 않는 것

화면에서 기본 위젯 직접 생성 · 부품 안의 인라인 색 · 글꼴 이름 지정 · 고정 폭·높이(틀의 기준 폭 — 사이드바 208·서랍·대화상자 폭(창 폭에 맞춰 줄임)과 그림 칸·아이콘 단추·행 최소 높이뿐) · 눌러도 아무 일 없는 단추 · 깨진 이미지 아이콘 · 이모지로 아이콘 대신하기.

## 6. 아직 만들지 않은 부품 (UI-C1 이후)

이번 묶음(UI-C0)은 아래를 **만들지 않았다**(운영자가 1단계 범위를 토큰·점수 링·구성 막대·사용량 막대·의미별 배지·탭·행동 줄로 정했다 — D-153): `TopicCard`(카드 격자의 한 칸 — 이미지 자리·배지 2개·제목 2줄·설명·키워드 칩 3개와 `+N`·채널·점수), `DetailPane`(오른쪽 상세 창 껍데기 — 탭 + 본문 스크롤 + 아래 고정 행동 줄, 좁으면 `Drawer`), 새 `FilterChip`·`TagChip`(지금의 칩·카드는 새 토큰 값만 따라간다), `StatusBanner`(안내·경고·오류·성공 + 제목·설명·행동), 검색 칸, 표(Data Grid). 새 틀(상단 앱 바·묶음 사이드바·오른쪽 고정 상세 창)과 화면 재구성도 UI-C1 이다. 위 부품들은 나중의 주제 조합·공공데이터·데이터 신호 화면에서도 그대로 쓸 수 있게 토큰과 부품만 준비했고, 그 화면과 공공데이터 배지 표·신호 표는 만들지 않았다.

## 7. 백업·복원 카드 부품 (BACKUPUI — `ui/qt/backup_parts.py`, 설정 화면의 카드)

새 토큰·새 공통 부품은 없다 — 기존 부품(`Badge`·`Button`·`Disclosure`·`StateCard`·`Skeleton`·`NoticeBar`·`Track`)을 조립하고 새 클래스 넷만 더했다. 인라인 스타일·직접 색·글자 크기 숫자 없이 속성(`card`·`kind`·`badge`·`role`)만 붙여 스타일시트가 입힌다.

| 부품 | 하는 일 |
|---|---|
| `ProgressTrack` | 진행 막대 — `Track` 의 채움을 `set_fraction` 으로 **제자리에서** 바꾼다(0에서 1) |
| `ProgressLine` | 진행 한 줄 — 글(`백업하는 중이에요… 40% — 파일을 담아요`)과 막대. 접근 이름은 글과 같다. `set_progress` 로 제자리 갱신(카드를 다시 그리지 않는다) |
| `BackupRow` | 백업 한 줄 — 이름(시각 + 종류, 한 줄 `ElidedLabel`)·배지(종류·상태·`Credential 제외됨` — 글자가 늘 함께)·작은 글 줄(크기·담긴 것·담지 못한 것)·`복원` 단추(누르는 칸 36px) |
| `BackupSection` | 카드 하나 — 머리(제목·`예시` 배지·`지금 백업`)·안내 글(백업 위치 — 글자로만, 마우스로 골라 복사·USB 복사 안내·남기는 수·Credential 안내)·결과 띠·진행 줄·접어 둔 '백업에 들어 있지 않은 것'·목록 또는 상태 카드. 위젯 참조(`create_button`·`rows`·`progress`·`notice`·`excluded`)를 들고 있어 시험과 포커스 복귀가 찾는다 |

**하지 않는 것**: 폴더 열기 단추·탐색기 호출·파일 선택 창(백업 위치는 글자뿐 — D-394)·'무시하고 백업' 단추. 포커스 열쇠는 `backup-create`·`backup-excluded`·`backup-restore:<폴더 이름>` 이고 확인창은 공통 `dialog-cancel`·`dialog-ok` 를 쓴다. 모든 눌리는 부품은 접근 이름과 36px 이상의 누르는 칸을 가지며 꺼진 단추는 까닭을 툴팁·접근 설명에 둔다.

**멈춘 복원 안내 부품(D-463)**: `BackupSection.interrupted`(`NoticeBar` 주의 수준)·`interrupted_lines`(시작한 때 줄)·`revert_button`(`secondary` 단추, 포커스 열쇠 `backup-revert`, 접근 이름 '멈춘 복원을 안전 사본으로 되돌리기', 누르는 칸 36px 이상, 꺼진 까닭은 툴팁·접근 설명). 눌림은 `shell.backup_revert()`(확인창) → `backup_revert_confirmed()` 로만 넘긴다. 새 외부 호출은 없다.

## 8. 저장한 초안 부품 (LOCALSAVE — `ui/qt/draft_parts.py`·`draft_screen.py`·`shell.py`)

- `SavedRowCard`(`draft_parts.py`): 저장한 초안 목록의 한 줄 — 제목·메타 글과 `열기`·`지우기` 단추. 줄은 아무것도 하지 않고 신호(`opened(번호)`·`deleted(번호)`)만 보낸다(번호는 열쇠일 뿐 글에 나가지 않는다). 단추 포커스 키 `drf-saved-open:<순번>`·`drf-saved-delete:<순번>`, 읽을 수 없는 초안은 `지우기` 만. `stops()` 가 Tab 에 걸리는 단추를 돌려준다.
- `draft_screen._saved_card`: 빈 화면 아래의 목록 카드(읽는 중·오류(`drf-saved-retry`)·비어 있음·줄들·위의 알림 한 줄). 읽기뿐이고 단추는 셸(`drf_saved_open`·`drf_saved_delete`·`drf_saved_retry`)에 신호를 보낸다.
- 저장 상태 줄(`DraftsUi.save_status`)과 `refresh_save`/`refresh_editor_status`: 글을 칠 때·저장이 끝났을 때 그 자리에서 바꾼다(편집기를 다시 그리지 않는다).
- 머리의 `저장한 초안` 단추(`DraftsUi.saved_list`, 포커스 키 `drf-saved-list`)와 아래 행동 줄의 `저장`(`act:save` — 공통 부품 `bars.ActionBar` 의 보조 단추).
- `AppShell.show_choice_dialog(제목, 본문, 선택들, first=열쇠, on_cancel=…)`: 여러 갈래 확인창의 한 곳 — 선택 `(열쇠, 글, 종류, 함수)`, 함수가 없는 선택(`계속 고치기`)은 취소·Esc 와 같다. 떠나기·`← 주제 후보`·`저장한 초안`·앱 닫기 앞의 세 갈래는 모두 `_show_leave_choices` 를 거친다(시험이 확인한다). 기존 `show_dialog`(두 갈래)는 그대로다.
- 홈: `screens._posts` 가 작성 중인 초안 구역의 머리 개수(`count_text`)와 `저장한 초안 보기`(`link`, 포커스 키 `home-drafts-link`)를 그린다 — 뷰모델에 `link` 가 있을 때만(전체 개수를 알고 그 개수가 1 이상인 공급자 — 그 단추가 부르는 셸 함수 `home_saved_drafts` 가 화면을 요청하는 호출 한 곳이고 화면 부품은 `go` 를 직접 부르지 않는다).

## 9. 후속 정리(POLISH-1, D-504·D-505)로 바뀐 공통 부품

| 부품 | 바뀐 것 | 규칙의 자리 |
|---|---|---|
| `FilterChip(text, count, active, focus_key, full=None)` | 개수가 있는 칩은 이름이 숫자로 끝나면 `이름 · 개수`(접근 이름 `이름, 개수`), 아니면 `이름  개수` 그대로. `full`(줄이기 전의 전체 이름)을 주면 접근 이름과 툴팁이 그것을 쓴다(`FilterChip` 은 Tab 으로 포커스가 닿으므로 키보드 포커스에도 툴팁이 보인다) | `core/part_rules.py` 의 `chip_caption`·`chip_accessible`(순수) |
| `Toast.show_message(text, level=None)` | `level` 이 `info`·`warning`·`error` 면 토스트 왼쪽에 그 상태색 줄이 보인다(`level` 속성 + 스타일시트 `QLabel#toast[level=…]` — 상태색 토큰 `info`·`warning`·`danger` 만). 수준이 없거나 `ok` 거나 모르는 값이면 예전 모양 그대로. 셸의 `notify(message, level=None)` 가 넘긴다 | `qt/components.py`·`qt/theme.py` |
| `Dialog.present` | 열린 확인창을 닫지 않고 바꿔 열 때만, 부품이 보이게 된 다음 차례에 틀을 한 번 더 놓는다(새로 여는 확인창은 그대로) — 옛 동작은 새 확인창이 44px 로 접혔다 | `qt/components.py` |
| 주 화면 채널 칩의 이름 | `channel_names.chip_label(key)` — 스무 자(`CHANNEL_CHIP_LIMIT`)까지, 줄이는 규칙은 서랍(`short_label` 열두 자)과 같은 `short_names`. 줄이면 뷰모델이 `tip`(전체 이름)을 싣고 화면이 `FilterChip(full=…)` 이나 툴팁으로 보인다. Seed 요약 칩은 포커스를 받지 않는 `Badge` 라 마우스를 올릴 때만 툴팁이 나온다(접근 이름은 전체 이름) | `ui/core/channel_names.py` |

## 진단 정보 복사 단추와 정보 카드 (L3 — `ui/qt/screens.py` 의 `info_card`·`ui/qt/shell.py` 의 `copy_diagnostics`, 결정 D-539 에서 D-541)

| 부품 | 바뀐 것 · 규칙 | 규칙의 자리 |
|---|---|---|
| `info_card(info, shell=None, with_diag=True)` | 버전 줄(+시험 안내) 아래에 접어 둔 진단 정보와 안내(`with_diag` 가 참일 때), 그 아래 `진단 정보 복사` 단추(`Button("ghost", …, "copy", size="sm", focus_key="diag-copy")`)와 담기는 것 안내 한 줄(`UI.label(…, "caption", wrap=True)`). 앱 틀(`shell`)이 없으면 단추와 안내가 없다 — 눌러도 할 일이 없는 단추는 만들지 않는다 | `qt/screens.py` |
| 설정 화면의 오류 상태 | 오류 카드(`StateCard`) 바로 아래에 `info_card(info, shell, with_diag=False)` — 접이식(`Accordion`)이 아니라 바로 보이는 카드 하나. 진단 정보 접이식·안내는 오류 카드의 것 하나뿐이다(한 화면에 `진단 정보 보기` 가 둘이 되지 않는다) | `qt/screens.py` |
| `AppShell.copy_diagnostics()` | `AppState.diagnostic_report(윈도 빌드, 배율)` 를 누르는 순간 만들어 기존 복사 길 `self.copy(text)` 로 클립보드에 쓰고 토스트를 보인다(성공: 평소 모양, 실패: 오류 색 줄). 윈도 빌드와 배율은 `_read_environment()` 가 읽는다 — 주입할 수 있는 `environment=` 인자(시험은 가짜): 이 창이 놓인 화면의 `devicePixelRatio` 와 `sys.getwindowsversion`. 못 읽으면 그 줄만 `unknown` | `qt/shell.py` |
| 뷰모델 `info["copy"]` | `{"text": 단추 글, "note": 담기는 것 안내}` 두 칸뿐 — 복사되는 글은 뷰모델에 없다. 오류 상태·데이터 없음에서도 칸이 있다 | `core/settings_view.py` |
| 키보드 · 접근 이름 · 크기 | 접근 이름 = 보이는 글(`진단 정보 복사`), Tab 정거장은 `진단 정보 보기` 다음, Space·Enter 로 눌린다, 누르는 칸 36 이상. 복사되는 글은 어느 위젯의 글·툴팁·접근 이름에도 없다. `copy_diagnostics` 는 이 단추를 누를 때만 불린다 — 소스 규칙 시험이 가리키는 곳(부름·이름 붙이기 포함)이 `src/` 전체에서 한 곳뿐이고 단추의 눌림 처리 안임을 PySide6 가 없는 CI 에서도 지킨다 | 시험 `tests/test_ui_qt_diagnostics.py`·`tests/test_source_rules_diagnostics.py` |

## 10. 앱 묶음 L2(D-534·D-535)로 더한 규칙 — Seed 닫기 질문과 복원 중 저장 막기(새 화면 부품은 없다)

새 위젯은 없다. 확인창은 기존 `show_dialog`(두 갈래, 처음 포커스는 취소)를 그대로 쓰고 안내는 기존 토스트(`notify`)를 쓴다 — `ui/qt/components.py` 는 고치지 않았다.

| 규칙 | 하는 일 | 자리 |
|---|---|---|
| `SeedsController.unsaved_targets()`·`has_unsaved()`·`close_dialog()` | 저장하지 않은 Seed 입력(고친 씨앗 `("seed", 번호)`·새 Seed 폼 `("new", None)`)을 센다. 서랍이 닫혀 있어도 센다. 지금 저장하는 중인 씨앗(또는 새 Seed 등록)은 세지 않고, 무슨 일인지 모르는 쓰기나 읽은 내용이 없어 견줄 수 없는 초안은 센다. `close_dialog()` 는 입력이 있을 때만 `{title, body, ok, cancel, seeds: True}`(두 갈래) | `ui/core/seeds_view.py` |
| `AppState.close_guard()` | 초안 → 블로그 관리 → Seed 관리 순서로 처음 만난 확인창의 글을 돌려준다. 화면 이동(`leave_guard`)은 초안만 묻는다 | `ui/core/app_state.py` |
| `AppShell._close_next(kinds)`·`_close_after_drafts`·`_close_after_blogs` | 앞의 확인(`저장 안 하고 닫기`·`닫기`)을 넘기면 남은 확인(블로그 → Seed)을 지금도 물을 입력이 있을 때만 이어서 띄우고, 없으면 닫는다. 처음 포커스는 늘 취소다 | `ui/qt/shell.py` |
| `save_gate.blocked_while_restoring` | 파일에 쓰는 일을 시작하는 컨트롤러 메서드(블로그 `start_save`·`start_clone`·`start_clear`, Seed `start_save`·`start_state`·`start_bulk`·`start_create`·`start_import_apply`, 후보 `start_make`, 초안 `start_save`·`start_delete`)에 붙는 데코레이터. 그 컨트롤러의 `save_gate()` 가 참(복원이 도는 중)이면 메서드를 부르지 않고 `("restoring", None)` 을 돌려준다. 읽기 시작 함수(`start_load`·`start_preview`·`start_import_preview`·`start_list` …)와 복원이 바꾸는 파일에 쓰지 않는 사진 되돌리기·사본 비우기에는 붙이지 않는다 | `ui/core/save_gate.py` |
| `BackupController.restoring` | 복원(또는 되돌리기)이 도는 중인가. `지금 백업` 은 세지 않는다 | `ui/core/backup_view.py` |
| `BackupController.writing_elsewhere()`·`start_restore`·`start_revert` 의 `("writing", None)` | 다른 화면의 저장이 도는 중이면(`restore_gate` = `AppState.writers_busy`) 복원을 시작하지 않는다 | `ui/core/backup_view.py`·`app_state.py` |
| `AppShell._notify_restoring()` | `restoring` 상태를 한 줄(`backup_blocks_save`)로 알린다. 확인창이 먼저인 일은 확인창을 띄우기 전에, 확인창이 떠 있는 사이에 복원이 시작됐으면 `확인` 뒤에 같은 줄을 보이고 '확인창을 보였다' 표시도 거둔다 | `ui/qt/shell.py` |
| `AppShell.close_dialog` 의 서랍 다시 가두기 | 확인창을 닫을 때 모든 가둠을 풀고 서랍이 열려 있으면(`self.drawer.is_open` — 홈 주제 상세·Seed·후보 어느 서랍이든) 서랍 안에 다시 가둔다. 옛 조건(홈 서랍 번호가 있을 때만)은 홈 서랍만 다시 가둬서 Seed·후보 서랍이 열린 채 `계속 고치기`·Esc 를 누르면 Tab 이 서랍 밖으로 샜다(D-538) | `ui/qt/shell.py` |

문구는 쉬운 한국어(해요체)로 `seed_text.py`(`seeds_close_title`·`seeds_close_body`·`seeds_close_ok`·`seeds_close_cancel`)와 `backup_text.py`(`backup_blocks_save`·`backup_wait_save`)의 문구 표에 더했다.

## 3-10. 글자 읽기 부품 (D-513 에서 D-519 — `ui/qt/photo_ocr_parts.py`·`ocr_runner.py`·`ocr_input.py`, 사진 정리 줄 안의 선택 칸)

사진 한 줄(`PhotoRowCard`) 안, 종류·장소 분위기 칩 아래와 `자리 정하기` 앞에 끼는 칸이다. **글자 읽기 컨트롤러가 붙은 창에서만 만들어진다**(`sheet.has_ocr()` — 도구가 없거나 `LOCAL_OCR` 가 꺼져 있으면 줄은 예전과 같은 위젯뿐이다). 뷰모델(`OcrPanel.view`)을 공통 부품으로 그리기만 하고, 색·글꼴·크기는 토큰과 스타일시트의 `ocrline` 속성에서만 온다(이 파일들도 사진 정리의 소스 규칙 시험 대상이다 — 파일 쓰기·네트워크·하위 프로세스·표준 출력·직접 색·`setFixedSize(숫자)` 없음).

| 부품 | 하는 일 | 키보드·접근성 |
|---|---|---|
| `OcrBlock` | 이름표·`글자 읽기`/`다시 읽기`·`작은 글씨라면 더 크게 다시 읽기`·`취소`·힌트 한 줄·상태 줄·다시 읽기 확인 줄·읽은 글(제목·안내·숫자 주의·알림·목록·`읽은 글 모두 맞아요`·`아래 줄과 합치기`·`뺀 줄 되돌리기`·모두 맞아요 확인 줄). 뷰모델이 `None` 이면 통째로 숨는다 | 단추마다 `사진 N …` 접근 이름. **포커스가 있던 단추가 사라지면 남은 부품으로 옮긴다**(읽기를 시작하면 취소 단추로, 끝나면 목록으로, 목록이 없으면 읽기 단추로). 확인 줄이 뜨면 처음 포커스는 `그만두기` |
| `OcrLines` | 읽은 글 목록 — 줄 위젯을 위치마다 하나씩 쥐고 내용만 바꾼다(줄이 사라져 포커스를 잃지 않는다) | **Tab 정거장은 하나**(줄이 60개여도). 위·아래 = 줄 이동(끝에서 멈춘다)·Home·End · Space = 맞아요 켜고 끄기 · Enter 또는 F2 = 글 고치기(Enter 로 반영하고 다음 줄로) · Esc = 고치기 그만두기 · Delete = 빼기(한 번 되돌릴 수 있다). **꾹 눌러도 Space·Delete·Enter 는 한 번만** 먹는다. 조합 키(Ctrl·Alt·Shift)는 건드리지 않는다. 접근 이름은 지금 고른 줄(`사진 3 읽은 글 12줄 중 4번째, 확인 전`)이고 접근 설명은 그 줄의 글 — 줄을 옮기거나 확인이 바뀌면 이름·설명이 같이 바뀐다. 키 안내는 목록 아래의 글 한 줄이다(툴팁은 긴 목록이면 화면 밖에 떠서 쓰지 않는다) |
| `OcrLineRow` | 한 줄 — 체크 상자(맞아요)·글(고치는 동안은 입력 칸)·`확인 전`/`확인함` 글·`고치기`·`빼기`. 확인 전은 **점선 테두리**, 확인함은 **실선 테두리와 체크**, 고른 줄은 파란 테두리, 포커스가 있으면 2px 포커스 테두리 — 어느 것도 색만으로 알리지 않는다(글이 늘 함께 있다) | 줄 안의 체크 상자·고치기·빼기는 마우스용(`ClickFocus`)이고 누르면 포커스가 곧 목록으로 돌아온다. 두 번 누르면 고치기 |
| `LineEditor` | 줄을 고치는 입력 칸 | Enter = 반영, Esc = 그만두기(**창의 Esc 단축키보다 먼저 받아 창이 닫히지 않는다**), 포커스를 잃으면 반영을 시도한다 |
| `OcrScroll` | 목록을 담는 스크롤 영역 — **높이 상한**(`LIST_MAX_HEIGHT` = 8줄 어림)이 있어 넘으면 목록 안에서 스크롤한다. 안쪽 배치가 바뀌면(`LayoutRequest`) `content_changed` 로 부모 배치에 알린다(안 알리면 부모가 줄이 없던 때의 높이 0 을 쥐고 있다) | 가로 스크롤 없음. 방향키로 옮긴 줄은 목록·창 몸의 두 스크롤을 모두 맞춰 보이게 한다 |
| `FlowRow`·`AskBar` | 폭이 모자라면 다음 줄로 넘어가는 단추 줄(보이는 것만 자리를 차지한다 — **부품은 처음부터 그 줄의 자식이다**: 부모 없는 위젯을 보이면 별도의 창으로 잠깐 떠서 앱 창의 활성·포커스를 빼앗고 윈도에서 작은 창이 번쩍인다)·확인 줄(글 + 진행·그만두기) | 확인 줄의 단추 순서는 (진행, 그만두기) — 마지막이 안전한 쪽. 확인 줄이 처음 뜰 때는 글자 읽기 칸(`OcrBlock`)이 배치가 자리를 잡은 뒤(바로·40ms 뒤·160ms 뒤)에 `reveal` 로 보이는 곳까지 스크롤한다 |
| `OcrRunner`(`ocr_runner.py`) | 읽기 요청을 작업 스레드에 한 장씩 맡기고 1초 시계로 초 글·시간 초과·취소 3초를 본다. 컨트롤러는 화면 스레드에서만 만지고 작업 스레드는 사진 위치 값만 본다 | — |
| `ocr_input.prepare` | 사진 한 장을 메모리에서 읽고 줄여 RGB 바이트로(경로·EXIF 는 넘기지 않는다) | — |

**새 문구 키**는 모두 `pho_ocr_*`(69개)이고 `ui/core/photo_text.py` 의 `PHOTO_OCR_T` 한 곳에 있다 — 시험이 키 목록을 못박고 모든 키가 쓰이는지 본다. 읽은 글(엔진이 읽은 글)은 어느 문구·접근 이름·오류에도 되풀이되지 않는다(줄 글은 목록 줄과 그 접근 설명에만 있다).
