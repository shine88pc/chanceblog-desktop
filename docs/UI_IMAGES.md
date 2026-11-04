# 사진 출처(Unsplash)와 내 사진(로컬 이미지) 규격

> 이미지 선택 화면('i' 묶음)이 쓰는 부품의 규격을 여기서 정한다. 화면 기초 묶음(G0)에서는 **출처 표시 부품**(`AttributionRow`)·규칙(`ui/core/attribution.py`·`ui/core/imagerules.py`)·Qt 검사(`ui/qt/imagecheck.py`)까지 만들었고 이미지 검색·선택 창 자체는 다음 묶음이다. 운영자 기준은 2026-11-03 22:27 채팅이고 원문은 비공개라 값만 옮겼다([`DECISIONS.md`](DECISIONS.md) D-32).

## 1. 출처 복사 — 두 줄

| 줄 | 내용 |
|---|---|
| ① | `Photo by [사진작가 이름] on Unsplash` |
| ② | **그 사진의 Unsplash 사진 페이지 주소 + UTM**(`?utm_source=chanceblog_desktop&utm_medium=referral`) |

- 둘째 줄은 **사진작가 프로필 주소가 아니라 사진 페이지 주소**다.
- **사진 페이지 주소와 사진작가 프로필 주소는 내부 메타데이터에 각각 따로 저장한다**(`PhotoCredit.metadata()` → `photo_page_url`·`photographer_profile_url`).
- 복사한 뒤 `출처 복사됨` 안내(토스트)를 보인다(`AppShell.copy_credit`). 클립보드를 못 쓰면 `복사하지 못했어요. 다시 시도해 주세요.` 만 알린다.
- 표시 부품은 `Photo by 작가 on Unsplash` 에서 작가 이름은 프로필 링크, `Unsplash` 는 Unsplash 홈 링크이고 둘 다 UTM 이 붙는다. 링크는 **Unsplash 의 https 주소만** 연다(`check_url` — 로그인 정보·포트·다른 도메인·공백 거절).
- 외부(Unsplash 응답)에서 온 이름·주소는 '데이터' 다 — 이름은 제어·보이지 않는 글자를 공백으로 바꾸고 80자로 줄인다.
- `utm_source` 값은 기본 `chanceblog_desktop` 이다(Unsplash 앱 등록 이름이 정해지면 `attribution.UTM_SOURCE` 한 곳만 바꾼다).

## 2. 내 사진(로컬 이미지)

| 규칙 | 값 | 구현 |
|---|---|---|
| 지원 형식 | **JPG·JPEG·PNG·WebP 만** | `imagerules.SUPPORTED_EXTENSIONS`·`SUPPORTED_FORMATS` |
| 진짜 이미지인가 | **확장자만 보지 않고** `QImageReader.canRead()` 로 읽을 수 있는지 + 읽은 **실제 형식**이 위 넷인지 | `imagecheck.probe` → `imagerules.judge` |
| 회전 | EXIF 회전 정보를 **자동 적용**(`setAutoTransform(True)`) — 90°·270° 면 가로·세로가 바뀐 크기로 판정·썸네일 | `imagecheck.shown_size`·`make_thumbnail` |
| 원본 | **절대 수정하지 않는다**(읽기만 — 시험이 해시·수정 시각·폴더 목록을 비교). 표시용 썸네일은 메모리에서 따로 만든다(긴 변 640px 이하 — JPEG·WebP 는 읽는 도중 줄여 읽고 **PNG 는 전체 크기로 읽은 뒤 줄인다**, §6) | `make_thumbnail` |
| 최대 파일 크기 | 기본 **20MB**(넘으면 거절 — 내용을 읽기 전에) | `MAX_BYTES` |
| 긴 변 | **12,000px 초과는 경고**(쓸 수는 있다) | `LONG_SIDE_WARN` |
| 지원하지 않는 파일 | 사용자용 안내 문구(기술 용어·영문 코드 없음): `지원하지 않는 파일이에요. JPG·PNG·WebP 사진만 쓸 수 있어요.` 등 | `T["img_local_*"]` |

판정 순서: 이름의 확장자 → 파일이 있는가·크기 → 진짜 이미지인가 → 실제 형식 → 긴 변 경고. 읽기 도구가 예외를 내도 앱은 멈추지 않고 `사진을 읽지 못했어요.` 로 안내한다. 진짜 PNG 를 `.jpg` 이름으로 주면 실제 형식이 허용 형식이라 받는다(이름이 아니라 내용을 믿는다).

## 3. 형식별 로딩 시험표 (`python scripts/ui_image_check.py` — 이 PC, PySide6 6.12.0 / Python 3.12, offscreen)

| 종류 | 이름 | 읽을 수 있나(`canRead`) | 실제 형식 | 크기(회전 적용) | 판정 | 경고 | 기대와 같음 | 원본 불변 |
|---|---|---|---|---|---|---|---|---|
| JPG | photo.jpg | 예 | jpeg | 64x48 | ok | - | 예 | 예 |
| JPEG | photo.jpeg | 예 | jpeg | 64x48 | ok | - | 예 | 예 |
| PNG | photo.png | 예 | png | 64x48 | ok | - | 예 | 예 |
| WebP | photo.webp | 예 | webp | 64x48 | ok | - | 예 | 예 |
| GIF(지원하지 않는 형식) | anim.gif | 예 | gif | 1x1 | unsupported | - | 예 | 예 |
| BMP(지원하지 않는 형식) | plain.bmp | 예 | bmp | 8x8 | unsupported | - | 예 | 예 |
| 가짜(글자 파일을 `.png` 로) | fake_text.png | **아니오** | - | - | not_image | - | 예 | 예 |
| 가짜(GIF 를 `.jpg` 로) | fake_gif.jpg | 예 | **gif** | 1x1 | unsupported | - | 예 | 예 |
| PNG 를 `.jpg` 로 | png_named.jpg | 예 | png | 16x16 | ok | - | 예 | 예 |
| 20MB 초과 | toobig.jpg | 아니오 | - | - | too_big | - | 예 | (큰 파일 — 크기·수정 시각 불변) |
| 긴 변 12,001px(PNG) | wide.png | 예 | png | 12001x8 | ok | **있음** | 예 | 예 |
| 긴 변 13,000px(WebP) | tall.webp | 예 | webp | 8x13000 | ok | **있음** | 예 | 예 |
| EXIF 회전 없음(40×20) | plain_exif.jpg | 예 | jpeg | 40x20 | ok | - | 예 | 예 |
| EXIF 회전 6(40×20 으로 저장) | rotated.jpg | 예 | jpeg | **20x40** | ok | - | 예 | 예 |

`QImageReader.supportedImageFormats()` = bmp, cur, gif, icns, ico, jfif, jpeg, jpg, pbm, pgm, png, ppm, svg, svgz, tga, tif, tiff, wbmp, webp, xbm, xpm — **JPEG·PNG·WebP 모두 읽는다.**

## 4. 설치 파일(Installer)에서 확인할 것 — 설치 마무리 단계의 시험 항목

JPEG·WebP 읽기는 Qt 이미지 형식 **플러그인**(`PySide6/plugins/imageformats/` 의 `qjpeg`·`qwebp`)이 한다(PNG 는 Qt 본체). 개발용 가상환경(`C:\ccgui\v`)에는 `qgif·qicns·qico·qjpeg·qpdf·qsvg·qtga·qtiff·qwbmp·qwebp` 가 모두 있다. 설치 파일(PyInstaller `--onedir` 등)을 만든 뒤 **설치된 환경에서** 다음을 확인한다 — ① `imageformats` 폴더에 `qjpeg`·`qwebp` 가 들어 있는가 ② 설치된 앱에서 `imagecheck.supported_formats()`(`QImageReader.supportedImageFormats()`)에 `jpeg`·`png`·`webp` 가 있는가(`missing_required_formats()` 가 비어 있어야 함) ③ 위 3절의 표와 같은 결과가 나오는가(`scripts/ui_image_check.py`). 지금은 가상환경에서 같은 확인을 먼저 했고 결과는 위 표와 같다.

## 5. 이미지가 없어도 멈추지 않는다

사진을 못 받거나 고르지 않아도 글 만들기는 멈추지 않는다 — 주제 이미지 자리 표시(`ImagePlaceholder`)로 대신한다. 이미지 검색 한도·네트워크·저장 정책은 이미지 선택 화면 묶음에서 다룬다.
이미지 자리 표시의 접근 이름·툴팁은 **분야를 아는 후보에만** `생활·집 주제의 이미지 자리 표시` 처럼 분야를 말한다. 실제 후보는 분야를 모르고(아이콘은 돌려 쓰는 장식이다) 그냥 `이미지 자리 표시` 다 — 예전에는 장식 아이콘에 맞춰 `생활·에너지` 같은 분야를 지어내 붙였다(독립 검증이 '지어내지 않는다' 와 어긋난다고 지적해 고쳤다).

## 6. 알려 둔 한계 — 헤더만 큰 PNG('폭탄')

`judge` 는 파일 크기(20MB)와 헤더의 가로·세로만 보고 **그림 전체를 읽지는 않는다**. 그래서 몇백 KB 짜리 PNG 가 헤더에 아주 큰 크기를 적어 두면(잘 압축되는 단색 그림) 판정은 곧바로 `ok`(+ 긴 변 12,000px 초과 경고)이지만, 썸네일을 만들 때 **PNG 는 읽는 도중 줄여 읽을 수 없어** 전체 크기로 읽은 뒤 줄이므로 메모리를 크게 쓴다. 독립 검증자 측정(이 PC, PySide6 6.12.0): 5,000²·7,000²·8,000² RGB 는 순간 +100~250MB, 8,000² 회색은 +366MB, 12,000² 이상(11,000² 회색 포함)은 Qt 의 이미지 할당 한도(256MB)에 걸려 읽기에 실패해 `make_thumbnail` 이 None 을 돌려주고 화면은 `사진을 읽지 못했어요` 로 안내한다. 즉 **메모리 폭주는 Qt 의 할당 한도가 막아 주지만, 그 아래 크기의 PNG 는 일시적으로 100~250MB 를 쓴다.** JPEG·WebP 는 읽는 도중 줄여 읽어 가볍다. 예전 코드 주석의 '읽는 도중에 줄여 메모리 절약' 은 JPEG·WebP 에만 맞는 말이었다(고침).
이 묶음은 PNG 의 가로×세로 상한을 읽기 전에 따로 막지 않는다 — 이미지 선택 창('i' 묶음)이 면적 상한 같은 거절 규칙을 둘지 그때 정한다. 그 밖에 알려 둔 것: 끝이 잘린 PNG·JPEG 는 머리만 보고 `ok` 가 되고(썸네일 단계에서 읽기에 실패하면 None), 경로가 260자를 넘으면 파일이 있어도 '파일을 찾지 못했어요' 로 안내한다(`\\?\` 로 시작하는 긴 경로 표기는 통과).
