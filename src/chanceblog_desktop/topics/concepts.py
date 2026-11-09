"""개념군 표 · 일치 도구 · 신호 계산 — 건강·협찬·경험의 **신호**를 글에서 계산한다(P2b 보완, D-50~D-52·D-105 — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

이 모듈은 단계(일반 생활정보 / 건강 정보 확인 필요 — 표시만·근거 확인 필요 / 의료·효과 단정 위험)·표시·알림을 정하지 않는다 — 그것은 `safety.py` 의 일이다. 여기서는 표(낱말·문구)와 일치 규칙으로 신호를 세고,
단계표의 열쇠(`HealthSignals.concept_key` — 증상 S·질환 D·제품 P·의료 효능어 M·효과 E·단정 A 여섯 값)까지만 만든다.

**표는 초기값이다 — 건강 표의 증상·제품 낱말은 전략 원문 §21 과 대조했고, 나머지 낱말은 여전히 초기값 — 전략 원문 확인 전이다.** 운영자 요청서의 개념군 낱말을 시작 목록으로 두고 상식으로 넓혔다.
대조 결과(D-105): 원문 §21 이 든 여섯 낱말(피로·불면·통증·자세·체중·영양제)은 이미 증상 표와 제품 표에 모두 있어 **표는 바꾸지 않았고** 판정 단계와 감점 조건만 `safety.py`·`generate.py` 에서 바꿨다.
원문에 맞춰 고칠 때는 이 파일의 표 한 곳만 고치고 시험(`test_topics_concepts` 의 값 못박기)을 의식적으로 함께 고친다. 표 이름: 건강 `HEALTH_SYMPTOM_KO`·`HEALTH_DISEASE_KO`·`HEALTH_EFFECT_KO`·`HEALTH_MEDICAL_KO`·`HEALTH_PRODUCT_KO`·`HEALTH_ASSERT_KO`·
`HEALTH_ASSERT_EFFECT_KO`·`HEALTH_ASSERT_SOFT_KO`·`HEALTH_MASKS_KO`·`HEALTH_WARNING_KO`(영어는 `_EN`) / 협찬 `SPONSOR_STRONG_KO`·`SPONSOR_WEAK_KO`·`SPONSOR_MARKERS_KO`·`SPONSOR_MASKS_KO`(영어는 `_EN`) /
경험 `EXPERIENCE_GENRE_STRONG_KO`·`EXPERIENCE_GENRE_WEAK_KO`·`EXPERIENCE_MARKERS_KO`·`EXPERIENCE_MASKS_KO`·`EXPERIENCE_PHRASES_EN` / 일반 낱말 금지 목록 `GENERAL_WORDS`.

판단 원칙 둘: ① 그것만으로 뜻이 한쪽인 말(질환명·건강 제품·의료 효능어·협찬 전용어·경험 장르 강한 말·영어 문구)만 **단독 신호 표**에 둔다. ② 일상어와 겹치는 말(일상 증상·일반 효과어·단정 낱말·협찬 약한 말·'후기'·'리뷰')은
**약한 표**에 두고 다른 개념군과 함께 있을 때만 쓴다. **일반 낱말(비교·모델·추천·구매·가격·순위·제품·브랜드·스펙·광고 …)은 어느 표에도 단독 신호로 넣지 않는다**(`GENERAL_WORDS` 와 시험이 지킨다).
일치 규칙: 정규화(`fold` — 보이지 않는 글자 지움·NFKC·소문자·한자 낱말·퍼센트) → 글자·숫자만 이어 붙임(`compact_marked` — 띄어쓰기·기호 무시, 낱말이 시작하는 자리는 기억) → 마스크 낱말을 가려 놓고 → 표 항목(조사 하나가 선택적으로 끼는 정규식)을 찾는다.
낱말 경계 규칙(D-58): 띄어쓰기 없는 표 항목이 **띄어쓴 낱말들에 걸쳐** 찾아지면 `reads_as_one_word` 가 거른다 — 첫 조각이 낱말 처음부터 시작하고 뒤 조각이 한글 한 글자가 아닐 때만 읽는다(그래서 두 글자 항목은 낱말 안에서만 읽힌다. `설치 매뉴얼` 의 ‘치매’ 같은
우연한 일치를 막음). 띄어쓰기가 든 항목과 받음 표지(`SPONSOR_MARKERS_KO`)는 예전처럼 찾는다.
영어는 소문자 낱말 열(`english_tokens`)에서 **문구(낱말 열)** 로 찾는다 — 하이픈 낱말이나 두 낱말 문구를 낱말 하나와 견주던 옛 규칙의 죽은 항목(`hands-on`·`my experience`)이 다시 생기지 않게 시험이 표 항목마다 도달을 확인한다.

**단정 범위(scope, 2026-11-06 ~19:55 운영자 결정 — D-130~D-135)**: 단정 낱말이 글에 있다는 이유만으로 단정으로 세지 않는다 — 그 낱말이 **효과 결과 서술어**(줄인다·없앤다·교정한다·치료된다 …)를 꾸미는지 **행동 서술어**(확인한다·알기·먹는다·기록한다 …)를 꾸미는지 본다.
`100%·보장` 류(`ASSERT_SCOPED_KO` 밖의 단정 낱말)와 질환 곁의 `완치`(의료 효능어이기도 해서 질환이 없으면 옛 판정 그대로)는 늘 단정이고, `즉시·바로` 류(soft)는 효과 결과를 꾸밀 때만, `확실·완전·무조건·반드시` 류(strong)는 효과 결과를 꾸미거나 질환(무조건만)·처방약 곁에서 행동 서술어를 꾸미지 않을 때 단정이다.
꾸밈은 **낱말 바로 뒤의 낱말**(목적어 꼴이나 `SCOPE_SKIP_WORDS_KO` 의 부사는 최대 두 낱말 건너뜀)로 읽고 모르면 `none`(옛 규칙 그대로)이다 — 효과 결과를 꾸미는 경우는 그 대상이 건강 낱말(앞 세 낱말부터 서술어 끝)일 때만 센다 — 표 `HEALTH_RESULT_SCOPE_KO`·`HEALTH_ACTION_SCOPE_KO` 와 `scope_of`. 영양제·처방약 하위 종류 표(`HEALTH_SUPPLEMENT_*`·`HEALTH_MEDICINE_*`)와
복용·섭취·중단 허용 질문 표(`HEALTH_ASK_*`)도 초기값이다. 옛 중지(C)를 느슨하게 만들지 않는 **바닥**(`HealthSignals.floor_key`)은 영양제 + 행동 순서 `바로·즉시` 하나만 예외로 두고 `safety.py` 가 쓴다.

**미탐 보강(WP-B5, D-290–D-296 — 5채널 독립 검증이 찾은, 건강 C 의도 문장 52개 중 초안으로 나오던 10개)**: ① 의문 꼬리(`는지`·`는가`·`한가` …)가 띄어쓴 두 낱말에 걸쳐 우연히 이어 붙으면 의문이 아니다 — `없애는 지압법`·`없애는 가이드` 의 ‘는지’·‘는가’ 가 단정 낱말을 의문으로 읽어 끄고 있었다(`_asks_after`, D-290).
② 일상 증상 열세 개·질환 다섯 개·결과 보장 서술 셋(`해결 보장` 등)·마스크 여덟 개를 더했다(D-291·D-292 — `요통 100% 해결 보장` 은 `요통` 만 더해서는 표시만이다: `해결` 이 효과 낱말 표에 없다. 낱말을 표에 넣는 대신 `해결 보장` 같은 결과 보장 서술 셋을 효과 단정 표에 더했다).
③ 즉각 표현 `단번에`·`한 번에`·`한꺼번에`·`하루 만에`(`HEALTH_INSTANT_PHRASE_KO`, D-293) — 범위 낱말처럼 읽되 **옛 중지 바닥에는 넣지 않는다**(옛 코드가 모르던 낱말이라 `HEALTH_ASSERT_SOFT_KO` 에 없다). 서술어를 못 읽어도 효과 낱말이 뒤 세 낱말 안에 있고 질환·제품이 대상이면 센다(`하루 만에 당뇨 극복`), 그것도 아니면 `단번에`·`하루 만에` 만 제품 곁에서 센다(`HEALTH_INSTANT_UNKNOWN_KO`).
④ 처방약 + 복용을 끊는 표현 + 낫는 말(또는 `끊어도 되는 방법`)은 단정이다(`HEALTH_QUIT_*`, D-294 — 안전 우선 기본값). **이 문단의 새 낱말·표현은 모두 초기값 — 운영자 확인 전이다.**

**수정 라운드(WP-B5 2, D-298–D-306 — 독립 검증이 '조건부 통과'로 찾은 약점)**: ① 늘 단정 낱말(100%·백퍼센트·틀림없·장담·보장·보증)이 같은 글에 있고 건강 낱말이 앞 두 낱말 안에 있으면 `해결·치유·호전·제거·퇴치·차단·정복·잡아주·막아주`(`HEALTH_RESOLVE_KO`)를 효과로 읽는다(`요통 100% 해결`, D-298 — 효과 낱말 표에는 넣지 않는다). ② 서술어 읽기 보강(D-299): 효과 동사 어간 17·결과 명사 `탈출`·**글 끝 결과 명사**(`통증 즉시 완화`, `HEALTH_BARE_TAIL_KO`)·단정 낱말과 서술어 사이의 건강 낱말 조각 건너뛰기·`멈추`(`HEALTH_HALT_SCOPE_KO`)의 대상 구분·`풀어보는`(`HEALTH_INSTANT_ACTION_KO`, 새 즉각 표현 곁 행동) — 꾸밈을 모르면 제품 곁에서 세던 D-293 의 읽기(`HEALTH_INSTANT_UNKNOWN_KO`)는 쇼핑 문장까지 중지시켜 없앴다. ③ 즉각·기간 표현 보강(`HEALTH_INSTANT_MORE_KO`·`HEALTH_INSTANT_NUMBERED_KO`, D-300 — 효과 결과를 꾸밀 때만). ④ 의문 꼬리는 어미 뒤가 낱말 끝일 때만(`_question_closed`, D-301). ⑤ 처방약 복용 중단은 증상·질환 낱말이나 건강에서만 쓰는 낫는 말이 있을 때만이고 `끊어도 안전한 방법` 말투도 같은 단계다(`HEALTH_QUIT_CURE_KO`·`HEALTH_QUIT_OK_KO`, D-302). ⑥ 두 글자 증상(`HEALTH_SYMPTOM_START_KO`)은 **낱말 처음에서만**·`이명`(`HEALTH_SYMPTOM_BARE_KO`)은 낱말 끝이나 조사 앞에서만 읽고 진짜 합성어는 허용 목록(2차 수정 때의 모양 — 3차 수정이 증상별 앞 수식어 표 `HEALTH_SYMPTOM_PREFIX_KO` 로 바꿨다)·증상 일곱 더함·마스크 정리(D-303). ⑦ 병적 입력 속도(`_Starts`·`_SpanIndex`·`_Spans`, D-304). 남은 한계는 D-306 이다. **새 낱말·표현은 모두 초기값 — 운영자 확인 전이다.**

**3차 수정(WP-B5 3, D-307–D-311 — 델타 재검증이 '조건부 통과'로 찾은 약점)**: ① 한 낱말 마스크(`한눈에`·`첫눈에`)는 가린 글자를 `SEP` 로 바꿔 앞 두 낱말 대상 창과 서술어 읽기를 끊어 기준이 중지로 읽던 글을 낮췄다 — 두 마스크를 지우고 `눈 건강` 을 낱말 처음에서만 읽는다(`wordstart`, D-307). ② 낱말 처음 읽기(`start`·`bare`)는 일치 안에 낱말 시작 자리가 있으면(`설 사진`·`감 기르는 법`) 읽지 않는다(D-307). ③ 증상 앞 수식어 표(`HEALTH_SYMPTOM_PREFIX_KO`)가 허용 합성어 목록을 갈음한다 — 낱말 처음부터 증상 바로 앞까지가 그 증상의 수식어와 정확히 같을 때만 읽는다(`열감기` 는 읽고 `손목감기` 는 아니다, D-309). ④ 처방약 약 이름 + 복용 중단 + 결과어(`HEALTH_QUIT_OUTCOME_KO`)는 복용 중단 단정이고, 복용 중단 표현이 있으면 새 즉각·기간 표현도 모르는 서술어를 센다(`HealthSignals.stopping`, D-308). ⑤ 새 즉각 표현 곁 `풀어보는` 은 대상이 증상이면 효과다(D-310). ⑥ 한 글자 질환 읽기의 낱말 끝 찾기는 이분 탐색이다(D-307). 남은 한계·하락은 D-306 이다. **새 낱말·표현은 모두 초기값 — 운영자 확인 전이다.**
"""
from __future__ import annotations

import re
import unicodedata
from types import MappingProxyType
from typing import NamedTuple


# ---- 건강 표(초기값 — 전략 원문 확인 전) ----------------------------------------------------------------------------------------------

HEALTH_SYMPTOM_KO = ("피로", "불면", "통증", "붓기", "부종", "두통", "소화", "체중", "집중력", "불안", "스트레스", "숙면", "수면", "활력", "컨디션", "근육통", "어깨 결림", "거북목", "체형", "자세", "속쓰림", "더부룩", "변비",
                     "소화불량", "여드름", "피부 트러블", "어지럼", "안구건조", "입냄새", "무기력", "번아웃", "기억력", "다이어트", "속 편한", "속이 편한", "장 건강", "위 건강", "질환", "질병",
                     "요통", "몸살", "감기", "눈 건강", "건조한 눈", "시력", "설사", "기침", "가려움", "저림", "생리통", "코골이", "이명",
                     "복통", "인후통", "치통", "관절통", "콧물", "무좀", "습진")        # 59 (D-291: 52 까지 — 독립 검증 V1 이 `{증상}을 즉시 없애는 방법` 에서 일반으로 읽힌다고 찾은 낱말 가운데 일상 증상. 초기값 — 운영자 확인 전. `노안`·`체력` 은 일상어·게임 낱말과 겹쳐 일부러 뺐다. D-303: 마지막 일곱 개 — 겹침이 낮아 먼저 넣은 증상)
HEALTH_DISEASE_KO = ("수면 장애", "불면증", "당뇨", "고혈압", "저혈압", "혈압", "혈당", "콜레스테롤", "고지혈증", "지방간", "염증", "알레르기", "아토피", "관절염", "치매", "우울증", "공황장애", "불안장애", "탈모", "비만", "항암",
                     "유방암", "위암", "폐암", "대장암", "간암", "췌장암", "갑상선", "골다공증", "빈혈", "심장병", "협심증", "뇌졸중", "천식", "비염", "식도염", "위염", "장염", "피부염", "통풍 발작", "통풍 환자", "요산",
                     "허리디스크", "목디스크", "디스크 탈출", "추간판", "척추측만", "파킨슨", "암 환자", "암 예방", "암 검진", "암 진단", "암 재발", "암 수술", "암 증상", "암세포", "발암", "면역력", "감염병", "독감", "코로나 후유증",
                     "수술 후유증", "백신 후유증", "역류성", "과민성", "갱년기", "난임", "불임", "ADHD", "자폐", "섭식장애",
                     "손목터널증후군", "오십견", "두드러기", "구내염", "치주염")        # 76 (D-291: 마지막 다섯 개 — 이름 있는 질환. 초기값 — 운영자 확인 전)
HEALTH_EFFECT_KO = ("회복", "개선", "완화", "예방", "교정", "감량", "증진", "향상", "해소", "강화", "극복", "효과", "효능", "도움", "좋아지", "나아지", "낮추", "낮아지", "높이", "높아지", "줄이", "풀어", "풀리", "늘리",
                    "올리", "키우", "되찾", "없애", "없어지", "사라지", "다스리", "낫는", "돕는", "도와")        # 34
HEALTH_MEDICAL_KO = ("치료", "완치", "처방", "시술", "수술", "투약")        # 6
HEALTH_PRODUCT_KO = ("영양제", "건강기능식품", "건강식품", "보충제", "비타민", "유산균", "프로바이오틱스", "오메가3", "루테인", "콜라겐", "홍삼", "밀크씨슬", "크레아틴", "의료기기", "자세교정기", "다이어트 제품", "다이어트 약",
                     "다이어트 보조제", "다이어트 식품", "운동 처방", "식이요법", "해독 주스", "해독주스", "해독차", "디톡스", "의약품", "한약", "보약", "민간요법", "자연치유", "치료제", "진통제", "수면제", "항생제", "해열제", "스테로이드", "처방약", "항우울제", "혈압약", "당뇨약", "인슐린", "항암제", "피임약", "항응고제", "스타틴")        # 45 (D-133: 처방약 낱말 넷 + D-137: 일곱 더함)
HEALTH_ASSERT_KO = ("확실", "완전", "무조건", "100퍼센트", "백퍼센트", "백프로", "반드시", "틀림없", "장담", "보장", "보증", "단언")        # 12
HEALTH_ASSERT_EFFECT_KO = ("효과 있", "효과가 있", "효과 만점", "효과 보장", "효과 확실", "효과를 본", "낫는다", "낫게", "없어진다", "없어집니다", "사라진다", "사라집니다", "치료된다", "치료됩니다", "치료가 된다", "완치된다",
                         "해결 보장", "치유 보장", "호전 보장")        # 19 (D-292: 마지막 셋 — `효과 보장` 과 같은 결과 보장 서술. `해결`·`치유`·`호전` 은 결과 서술어 표(`_RESULT_NOUNS_KO`)에는 있는데 효과 낱말 표에는 없어 `요통 100% 해결 보장` 이 표시만이었다.
                                                                    #   낱말 자체를 효과 낱말 표에 넣으면 `영양제 오류 해결` 같은 평범한 글이 근거 확인 필요로 올라가(엔진이 만드는 후보 포함) 보장과 함께일 때만 센다. 초기값 — 운영자 확인 전)
HEALTH_ASSERT_SOFT_KO = ("즉시", "즉각", "바로", "단숨에", "순식간", "당장", "즉효")        # 7
HEALTH_MASKS_KO = ("소화기", "소화전", "혈압계", "체중계", "처방전", "자세히", "자세한", "자세하게", "스트레스 테스트", "불확실", "완전 정복", "완전 초보", "완전판", "완전 자동", "완전 무료", "보장성", "보장 범위", "보장금", "보장 내용",
                   "보증금", "보증서", "보증 기간", "보증보험", "디지털 디톡스", "스마트폰 디톡스", "SNS 디톡스", "알림 피로", "피로도", "불안정", "바로잡", "바로가기", "바로미터", "불완전",
                   "보험 보장", "모니터 암", "모니터암", "로봇 암", "로봇암", "암 거치대", "암거치대",
                   "암 프로세서", "암 기반", "암 아키텍처", "암 서버", "암 레벨", "암 클라이밍", "암 모양", "로봇 팔 암",
                   "머리 감기", "착 감기",
                   "줄 감기", "태엽 감기", "붕대 감기", "전선 감기", "케이블 감기", "목도리 감기", "목에 감기는", "손에 감기는", "배추 저림",
                   "건조한 눈빛", "건조한 눈길", "건조한 눈매", "건조한 눈동자", "건조한 눈썹")        # 64 (D-307: 한 낱말 마스크 둘 — `한눈에`·`첫눈에` — 을 지웠다. 마스크는 가린 글자를 `SEP` 로 바꾸는데 `SEP` 는 앞 두 낱말 창과 서술어 읽기를 끊는 경계이기도 해서 건강 낱말과 `즉시` 사이에 한 낱말 마스크가 끼면 기준이 중지로 읽던 `두통 한눈에 즉시 없애는 방법` 이 낮아졌다 — 대신 `눈 건강` 을 낱말 처음에서만 읽는다(`한눈에 건강` 속 `눈에건강` 은 낱말 한가운데라 읽히지 않는다)) · 66 (D-303(P-7): 51 까지 — 낱말 처음에서만 읽는 증상 낱말(`HEALTH_SYMPTOM_START_KO`·`HEALTH_SYMPTOM_BARE_KO`)이 붙여 쓴 합성어를 스스로 거르게 되어 D-291 마스크 다섯(`빨리감기`·`되감기`·`경기침체`·`이명박`·`건설사`)은 필요 없어져 지웠고(남은 셋: `머리 감기`·`착 감기`·`한눈에`), 띄어 쓴 일상 구절 속 `감기`(줄·태엽·붕대·전선·케이블·목도리를 감는 일, 목·손에 감기는)·`배추 저림`·`건조한 눈`·`눈 건강` 이 걸리는 일상 낱말(눈빛·눈길·눈매·눈동자·눈썹·첫눈에) 열다섯을 더했다. 초기값 — 운영자 확인 전) · 56 (D-291: 새 증상 낱말이 일상어 속에서 걸리지 않게 마스크 여덟 더함 — `머리 감기`·`착 감기`(손에 착 감기는 마우스)·`빨리감기`·`되감기`(영상·git)(감기)·`경기침체`(기침)·`이명박`(이명)·`건설사`(설사)·`한눈에 건강`(눈 건강). 초기값 — 운영자 확인 전) · 48 (D-140: ARM·게임·장비 문맥 '암' 여덟 더함 — 렌즈 A2 중간 N-1) · 40 (D-134: 보험 '보장' 마스크는 `보험 보장` 하나만 둔다 — 둘째 검증이 `보장 한도·금액·기간·항목·혜택` 이 옛 중지 열 문장을 풀어 버림을 찾아 지웠다(D-138) + D-136: 기기 '암' 여섯 더함 — 한 글자 질환 `암` 단독 읽기가 모니터 암·로봇 암을 건드리지 않게)
HEALTH_WARNING_KO = ("과장", "허위", "거짓", "사기", "속지", "속는", "속아", "오해", "함정", "낚시", "믿어도", "믿을수", "진짜일까", "사실일까", "진실", "근거없", "팩트체크", "구별", "구분하는")        # 19
HEALTH_SYMPTOM_EN = ("fatigue", "stress", "anxiety", "pain", "headache", "sleep", "weight loss", "weight", "diet", "burnout", "bloating", "acne", "constipation",
                     "posture", "focus")        # 15
HEALTH_DISEASE_EN = ("diabetes", "diabetic", "cancer", "cholesterol", "depression", "obesity", "arthritis", "alzheimer*", "dementia", "hypertension", "asthma",
                     "allergy", "allergies", "eczema", "blood pressure", "blood sugar", "immunity", "immune system", "inflammation", "adhd", "autism", "osteoporosis",
                     "migraine", "insomnia", "thyroid", "anemia")        # 26
HEALTH_EFFECT_EN = ("relief", "relieve*", "recover*", "recovery", "improv*", "prevent*", "reduc*", "boost*", "ease", "eliminat*", "lower*", "increas*", "fix")        # 13
HEALTH_MEDICAL_EN = ("cure*", "treatment*", "therapy", "heal", "heals", "healed", "healing", "remedy", "remedies", "prescription*", "prescribe*")        # 11
HEALTH_PRODUCT_EN = ("supplements", "supplement for", "dietary supplement*", "vitamin", "vitamins", "probiotic*", "multivitamin*", "medication", "medications",
                     "medicine", "medicines", "diet pill*", "weight loss pill*", "fat burner*", "detox tea", "detox juice", "detox cleanse", "posture corrector*",
                     "medical device*", "collagen", "melatonin", "creatine")        # 22
HEALTH_ASSERT_EN = ("guaranteed", "guarantee", "guarantees", "completely", "miracle", "permanently", "surefire", "foolproof", "always works", "never fails")        # 10
HEALTH_ASSERT_EFFECT_EN = ("will cure", "guaranteed results", "guaranteed to work", "guaranteed to cure", "guaranteed relief", "instant relief", "disappears", "vanish*",
                           "gone forever", "works instantly")        # 10
HEALTH_ASSERT_SOFT_EN = ("instantly", "immediately", "overnight", "in minutes", "right away")        # 5
HEALTH_MASKS_EN = ("economic depression", "great depression", "pain point*", "treat yourself", "supplement your", "diet of", "blood pressure monitor*",
                   "blood sugar monitor*", "stress test*", "supplements to the", "weight of")        # 11
HEALTH_WARNING_EN = ("myth", "myths", "scam", "scams", "fake", "misleading", "fraud", "debunk*", "red flags", "too good to be true", "exaggerat*")        # 11
NEGATION_TOKENS_EN = ("no", "not", "never", "without", "cannot")        # 5

# ---- 건강 하위 종류·단정 범위 표(운영자 2026-11-06 ~19:55 결정 ①②③ — **구현자 초기값**, D-130~D-135) ------------------------------------------------
# 제품 표(`HEALTH_PRODUCT_*`)의 하위 종류 둘: 영양제(건강기능식품 같은 먹는 보충 제품)와 처방약(의약품 낱말). 두 표 모두 제품 표 안의 낱말이다(시험이 지킨다). 제품 표에 있되 둘 어디에도 없는 낱말(의료기기·한약·식이요법 …)은 '그 밖의 제품'이다.
HEALTH_SUPPLEMENT_KO = ("영양제", "건강기능식품", "건강식품", "보충제", "비타민", "유산균", "프로바이오틱스", "오메가3", "루테인", "콜라겐", "홍삼", "밀크씨슬", "크레아틴")        # 13
HEALTH_SUPPLEMENT_EN = ("supplements", "supplement for", "dietary supplement*", "vitamin", "vitamins", "probiotic*", "multivitamin*", "collagen", "creatine")        # 9
HEALTH_MEDICINE_KO = ("수면제", "항생제", "진통제", "해열제", "스테로이드", "처방약", "항우울제", "의약품", "치료제", "혈압약", "당뇨약", "인슐린", "항암제", "피임약", "항응고제", "스타틴")        # 16 (D-137: 일곱 더함)
HEALTH_MEDICINE_EN = ("medication", "medications", "medicine", "medicines", "melatonin")        # 5
SUPPLEMENT_SET = frozenset(HEALTH_SUPPLEMENT_KO + HEALTH_SUPPLEMENT_EN)
MEDICINE_SET = frozenset(HEALTH_MEDICINE_KO + HEALTH_MEDICINE_EN)
NEW_PRODUCT_KO = ("해열제", "스테로이드", "처방약", "항우울제", "혈압약", "당뇨약", "인슐린", "항암제", "피임약", "항응고제", "스타틴")        # 11 — 옛 코드(`d5dcb8c`)의 제품 표에 없던 낱말(D-133·D-137). 옛 중지 바닥의 열쇠(`legacy_concept_key`)는 이 낱말을 제품으로도, 이름 속 조각을 가리는 이름으로도 세지 않는다 — 옛 코드는 `처방약` 속 `처방`(의료 효능어)을 따로 셌다(D-140)
NEW_PRODUCT_SET = frozenset(NEW_PRODUCT_KO)
# 복용·섭취·중단 허용 질문 — 건강 제품과 함께 있으면 효능 주장에 준하는 신호(E)로 센다(`영양제를 식후 바로 먹어도 될까` = B). 소프트웨어·생활 문장(`영양제 복용 시간 알림 앱 만들기`)은 질문 꼴이 아니라 해당 없음.
HEALTH_ASK_STEMS_KO = ("먹어도", "복용해도", "섭취해도", "끊어도", "중단해도", "마셔도", "먹어야", "복용해야", "섭취해야", "끊어야", "중단해야")        # 11 (D-137: 다섯 더함)
HEALTH_ASK_TAILS_KO = ("될까", "되나", "돼", "되죠", "됩니까", "좋을까", "안전한가", "문제없", "될는지", "되나요", "되는지", "되는가", "돼요", "될지", "괜찮", "되는", "하나요", "할까", "하는지")        # 19 (D-137: 열한 개 더함)
# 단정 범위 낱말 — 이 낱말들은 늘 단정이 아니라 **무엇을 꾸미는지** 에 따라 단정이다(`scope_of`). 이 밖의 단정 낱말(100퍼센트·보장·보증·장담·단언·틀림없·즉효 …)은 늘 단정이다.
ASSERT_SCOPED_KO = MappingProxyType({
    "soft": ("즉시", "즉각", "바로", "단숨에", "순식간", "당장"),        # 6
    "strong": ("확실", "완전", "무조건", "반드시"),        # 4
})
ASSERT_ALWAYS_SOFT_KO = ("즉효",)        # '즉시·바로' 표 안에 있지만 낱말 자체가 즉각적 효과를 말한다 — 범위와 상관없이 단정
# 꾸밈을 읽는 서술어 시작 조각(구현자 초기값). 낱말 바로 뒤 낱말이 이 조각으로 시작하면 그 종류다. 명사로도 쓰이는 낱말(`높이`·`교정기`·`예방접종`·`치료 시기`)이 서술어로 읽히지 않게 서술어 꼴(어미 포함)만 둔다.
_RESULT_NOUNS_KO = ("회복", "개선", "완화", "예방", "교정", "감량", "증진", "향상", "해소", "강화", "극복", "해결", "치유", "호전", "치료", "완치", "탈출")        # 17 — '-하다·-되다·-시키다' 꼴로 효과 결과를 말하는 명사(D-299: `탈출` 을 더했다 — `변비 하루 만에 탈출하는 방법`)
_RESULT_ENDINGS_KO = ("하", "해", "한", "합", "할", "했", "시키", "되", "돼", "된", "됩", "될", "됐")        # 13 — 어미(‘-시기’ 와 겹치는 ‘시’ 는 뺐다)
HEALTH_RESULT_SCOPE_KO = (
    *(noun + ending for noun in _RESULT_NOUNS_KO for ending in _RESULT_ENDINGS_KO),        # 221 (D-299: 명사 17 × 어미 13)
    "날려", "날리", "날린", "날립", "날렸", "가라앉", "고치", "고쳐", "고친", "고칩", "고쳤", "빠지", "빠져", "빠진", "빠집", "빠졌", "멎",        # D-299(P-4): 서술어 표에 없던 효과 동사 17 — `단숨에 날려버리는`·`속쓰림 즉시 가라앉히는`·`코골이 한 번에 고치는`·`체중 무조건 빠지는`·`기침 즉시 멎는`. `멈추` 는 복용 중단 낱말과 겹쳐 따로 읽는다(`HEALTH_HALT_SCOPE_KO`)
    "완쾌", "효과", "효능", "도움이", "도움을", "도움되", "도움돼", "도움주", "좋아지", "좋아진", "좋아져", "좋아질", "좋아집", "좋아졌", "나아지", "나아진", "나아져", "나아질", "나아집", "나아졌",
    "낮추", "낮춰", "낮춘", "낮춥", "낮아지", "낮아진", "낮아져", "낮아질", "낮아집", "낮아졌", "높이는", "높이고", "높이기", "높이면", "높이려", "높이도록", "높여", "높인", "높입", "높아지", "높아진", "높아져", "높아질", "높아집", "높아졌",
    "풀어", "풀리", "풀린", "풀립", "풀렸", "풀릴", "되찾", "없애", "없앤", "없앱", "없어지", "없어진", "없어집", "없어졌", "사라지", "사라진", "사라집", "사라졌", "다스리", "다스린", "다스립",
    "낫는", "낫게", "낫습", "낫다", "낫도록", "나았", "돕는", "도와", "돕습", "줄일", "줄였", "없앨", "없앴", "낮출", "낮췄", "사라질", "사라져", "없어질", "없어져", "풀려", "올릴", "키울", "늘릴", "나을", "나아요", "줄이", "줄여", "줄어", "줄인", "줄입", "늘리", "늘려", "늘린", "늘립", "늘어", "올리는", "올리고", "올리기", "올려", "올린", "올립",
    "키우는", "키우고", "키우기", "키워", "키운", "키웁", "빼는", "빼준", "빼줍", "빼낸", "빼내", "뺍니", "뺀", "잡아주", "잡아준", "잡아줍", "막아주", "막아준", "막아줍", "해독", "씻어", "녹여", "태워",
)
HEALTH_ACTION_SCOPE_KO = ("하는", "가기", "보는", "사는", "사기", "넣", "담", "꺼내", "끝내", "설명", "피하", "피해", "들어", "듣", "봐", "가야", "확인", "알기", "알아", "알고", "알면", "알려", "알리", "아는", "먹는", "먹어", "먹기", "먹고", "먹으", "먹을", "먹도록", "먹지", "먹습", "먹은", "먹었", "먹게", "복용", "섭취",
                          "마시는", "마시기", "마시고", "마시면", "마셔", "마실", "마십", "마신", "마셨", "시작", "정리", "기록", "점검", "확보", "설정", "챙기", "챙겨", "사용", "적용", "해보", "해봐", "따라", "체크", "준비", "실천",
                          "선택", "구매", "구입", "신청", "예약", "저장", "공유", "비교", "찾는", "찾아", "찾기", "찾으", "찾을", "찾습", "찾았", "찾은", "고르는", "고르기", "고르면", "고를", "골라", "고릅", "고른", "골랐",
                          "읽는", "읽기", "읽고", "읽어", "읽을", "읽습", "읽은", "보기", "배우", "하기", "해야", "끊어", "끊는", "끊기", "끊고", "끊으", "끊습", "끊은", "끊었", "중단", "멈추", "멈춰", "바꾸", "바꿔", "바꾼", "바꿉",
                          "시도", "도전", "받는", "받아", "받기", "받고", "받으", "받을", "받도록", "받습", "받은", "받았", "보내", "만들", "만드는", "만든", "만듭", "자동화", "고민", "결정", "판단", "정하", "정해", "정한", "정합", "관리", "보관",
                          "쓰는", "쓰기", "쓰고", "써", "쓴", "씁", "입력", "작성", "적어", "적는", "가져", "건너뛰", "건너뛴", "미루", "미뤄", "지키", "지켜", "열어", "열기", "여는", "방문", "가는", "가서", "물어", "묻는", "묻기",
                          "상담", "문의", "검색", "조회", "분석", "계산", "측정", "등록", "신고", "발급", "다운", "설치", "연결", "백업", "주문", "취소", "해지", "결제", "배송", "반품", "환불", "교환", "추가", "삭제", "변경", "수정", "가입", "탈퇴", "구독", "연장", "갱신", "드시", "드세", "드실", "추천", "소개", "질문",
                          "마련", "나누", "나눠", "정지", "메모", "복사", "출력", "인쇄", "업로드", "계획", "참고", "활용", "이용", "전달", "전송", "복습", "클릭", "누르", "할인", "적립", "발송", "출고", "도착", "입금", "접수", "답변",
                          "종료", "마감", "발행", "지급", "충전")
# D-137(A-8): 복용·중단·용량 변경을 말하는 행동 서술어 — 행동 서술어 조각 가운데 복용·중단·용량을 말하는 것이다(`투여`·`증량` 두 낱말은 행동 표에 따로 없고 `_scope_and_end` 가 이 표를 행동 표보다 먼저 읽는다). 처방약 곁에서는 이 행동이면 단정(C 유지), 그 밖의 행동 순서(알기·정리·보관·서류 …)는 단정이 아니다. 영양제 곁에서는 둘 다 행동 순서다.
HEALTH_DOSE_SCOPE_KO = ("복용", "섭취", "먹는", "먹어", "먹기", "먹고", "먹으", "먹을", "먹도록", "먹지", "먹습", "먹은", "먹었", "먹게", "마시는", "마시기", "마시고", "마시면", "마셔", "마실", "마십", "마신", "마셨",
                        "끊어", "끊는", "끊기", "끊고", "끊으", "끊습", "끊은", "끊었", "중단", "투여", "증량", "바꾸", "바꿔", "바꾼", "바꿉", "변경", "멈추", "멈춰")        # 41
# D-136(A-2): 일반 수량 동사의 의무 꼴(`줄여야 하는 음식`)은 건강 결과가 아니라 권고다 — 행동 서술어처럼 읽는다(결과 서술어 조각보다 먼저 본다)
HEALTH_ADVICE_SCOPE_KO = ("줄여야", "늘려야", "낮춰야", "높여야", "올려야", "키워야")        # 6
# D-136(운영자 직접 기준 22:2x): 효과 결과 동사의 **단정 종결 활용형 Phrase** — 단정 낱말이 없어도 `피로를 줄여 줍니다`·`줄일 수 있습니다` 는 효과 단정이다. 띄어 쓰기·붙여 쓰기는 같다(띄어쓰기 없는 꼴로 적는다 — `줄일 수도 있다` 같은 어림 꼴은 아니다). 대상이 건강 낱말(앞 두 낱말)일 때만 센다.
_FORM_NOUNS_KO = ("해소", "완화", "개선", "교정", "치료", "회복", "예방", "감량", "극복")        # 9
HEALTH_ASSERT_FORMS_KO = (
    "줄일수있다", "줄일수있습니다", "줄일수있어요", "줄여줍니다", "줄여준다", "줄여줘요", "없앨수있다", "없앨수있습니다", "없앨수있어요", "없애줍니다", "없애준다", "없애줘요",
    "낮출수있다", "낮출수있습니다", "낮출수있어요", "낮춰줍니다", "낮춰준다", "낮춰줘요", "풀어줍니다", "풀어준다", "풀어줘요",
    *(noun + ending for noun in _FORM_NOUNS_KO for ending in ("할수있다", "할수있습니다", "할수있어요", "해줍니다", "해준다", "해줘요", "시켜줍니다", "시켜준다", "시켜줘요")),
)        # 102 (효과 동사 12 + 명사형 9 × 9)
CURE_NEUTRAL_KO = ("후", "율", "판정", "사례", "기준", "통계", "여부")        # D-137(A-9): '완치' 바로 뒤에 이것이 오면 중립 표현(`완치 후 식단`·`완치율`)이라 질환 곁이어도 단정이 아니다
HEALTH_DISEASE_BARE_KO = ("암",)        # D-136(A-3): 한 글자 질환 — 낱말 단독이거나 조사만 붙었을 때만 질환으로 읽는다(`암호`·`암기`·`암벽`·`암시`·`암컷` 은 질환이 아니다)
BARE_DISEASE_PARTICLES_KO = ("을", "를", "이", "가", "은", "는", "의", "과", "와", "도", "에", "만")
SCOPE_SKIP_WORDS_KO = ("같이", "함께", "꼭", "미리", "따로", "한꺼번에", "한번에", "다시", "또", "먼저", "우선", "계속", "천천히", "크게", "많이", "조금", "더", "좀", "잘", "제대로", "쉽게", "빠르게", "정확히")        # 23 — 단정 낱말과 서술어 사이에 끼는 흔한 부사: 꾸밈을 읽을 때 건너뛴다(`바로 같이 먹어도`·`즉시 크게 줄이는`)
SCOPE_PARTICLES_KO = ("을", "를", "에", "에서", "으로", "로", "와", "과")        # 이 조사로 끝나는 첫 낱말은 목적어 꼴로 보고 한 낱말만 건너뛴다(`즉시 피로를 없애는`). 'ㄴ·는' 은 서술어 어미와 겹쳐 넣지 않았다
SCOPE_ADVERB_SUFFIX_KO = ("에는", "에도", "에", "히", "하게", "한", "하다", "하고", "하며", "적으로", "적인", "적", "으로")        # 단정 낱말에 붙여 쓴 어미(확실히·완전한·무조건적으로 …) — 꾸밈을 읽기 전에 뗀다

# ---- 건강 미탐 보강 표(WP-B5, D-293·D-294 — **구현자 초기값, 운영자 확인 전**) --------------------------------------------------------------------------
# 즉각 표현 보강(D-293) — 범위 낱말(`ASSERT_SCOPED_KO["soft"]`)처럼 **무엇을 꾸미는지**로 읽는다. 단 `HEALTH_ASSERT_SOFT_KO` 에는 넣지 않았다: 그 표는 옛 중지 바닥(`floor_key`)의 바탕이라 옛 코드가 모르던 낱말이 들어가면
# `당뇨 예방 식단 한 번에 정리하기` 같은 평범한 글이 옛 규칙으로 중지가 된다. `곧바로` 는 `바로` 가 낱말 속에서 이미 읽혀(`피로를 곧바로 줄이는 방법` 중지) 따로 더하지 않았다.
HEALTH_INSTANT_PHRASE_KO = ("단번에", "한 번에", "한꺼번에", "하루 만에")        # 4
# 서술어를 못 읽어도(`none`) 효과 낱말이나 건강 결과 서술어가 즉각 표현 바로 뒤 세 낱말 안에 있고 질환·제품이 대상이면 효과 결과를 꾸미는 것으로 읽는다(`하루 만에 당뇨 극복`·`영양제 먹고 하루 만에 살 빠지는 법` — `_effect_within`).
# (D-293 이 두었던 '꾸밈을 모르면 `단번에`·`하루 만에` 를 제품 곁에서 센다'는 보수적 읽기 `HEALTH_INSTANT_UNKNOWN_KO` 는 D-299 가 없앴다 — `영양제 하루 만에 품절되는 이유` 같은 쇼핑 문장까지 중지가 됐다(독립 검증 P-8).)
# 처방약 복용 중단(D-294 — 안전 우선 기본값, 운영자가 정하지 않은 항목): 처방약 낱말(`HEALTH_MEDICINE_*`)이 있고 복용을 끊는 표현(`HEALTH_QUIT_KO`)이 낫는 말(건강 제품·기기 이름 속이 아닌 효과 낱말 — `낫는`·`극복`·`줄이` …)과 함께 있거나
# `끊어도 되는 방법` 꼴(`HEALTH_QUIT_ALLOW_KO` + `되는` + `HEALTH_QUIT_HOWTO_KO` 낱말 하나로 끝남)이면 단정이다. 질문 꼴(`끊어도 되나요`)·`없이`(`수면제 없이 잠드는 방법`)·방법 안내가 없는 중단(`끊는 방법`)은 지금대로다.
# (처방약 + 의료 효능어 `치료`·`완치` 나 효과 단정 서술은 단계표가 이미 단정 위험이라 따로 두지 않는다.)
HEALTH_QUIT_KO = ("끊고", "끊어도", "끊으면", "안 먹고", "안 먹어도", "먹지 않고", "먹지 않아도", "중단하고", "중단해도", "복용하지 않고", "복용하지 않아도", "그만 먹고", "멈추고")        # 13
HEALTH_QUIT_ALLOW_KO = ("끊어도", "안 먹어도", "먹지 않아도", "중단해도", "복용하지 않아도")        # 5 — `HEALTH_QUIT_KO` 의 부분집합: 끊어도 된다는 허용 꼴
HEALTH_QUIT_HOWTO_KO = ("방법", "비법", "비결", "노하우", "요령", "법")        # 6 — `되는` 바로 뒤에 낱말 하나로 올 때만(`되는 법적 …` 은 아니다)

# ---- 건강 미탐 보강 2차 표(WP-B5 수정 라운드, D-298–D-306 — **구현자 초기값, 운영자 확인 전**) -------------------------------------------------------------
# P-7: 두 글자 증상은 붙여 쓴 일상 합성어 속에서 걸린다(`체감기온`·`시설사용료`·`수요통계`·`장기침체`·`정치통계`·`실습진행`). 아래 낱말은 **낱말 처음에서만** 읽는다(앞에 한글이 붙은 합성어는 건너뛴다) — `HEALTH_SYMPTOM_KO` 의 부분집합.
HEALTH_SYMPTOM_START_KO = ("감기", "설사", "요통", "기침", "복통", "치통", "습진", "무좀", "눈 건강")        # 9 (D-307: `눈 건강` 을 더했다 — 두 낱말 항목은 낱말 처음에서 시작할 때만 읽는다(`한눈에 건강`·`첫눈에 건강` 은 아니다))
# `이명` 은 이름(`이명희`·`이명수`)과 겹쳐 낱말 처음에서 시작하고 **낱말이 거기서 끝나거나 이어지는 말이 조사·`증` 으로 시작할 때만** 읽는다(`HEALTH_DISEASE_BARE_KO` 의 `암` 과 같은 방식) — `HEALTH_SYMPTOM_KO` 의 부분집합.
HEALTH_SYMPTOM_BARE_KO = ("이명",)        # 1
BARE_SYMPTOM_REST_KO = BARE_DISEASE_PARTICLES_KO + ("증", "으", "처", "현상", "소리", "소음", "치료", "개선", "완화", "극복", "원인", "해결", "검사", "클리닉", "환자")        # `이명` 뒤에 붙을 수 있는 말의 **시작**(조사·`증`·`으로`·`처럼`과 낱말 `현상`·`소리`·`치료` …, D-307) — 띄어쓰기 없이 이어 쓴 글(`이명을즉시줄이는방법`)과 `이명현상`·`이명치료` 도 읽고 이름(`이명희`·`이명수`)은 읽지 않는다
# 앞에 한글이 붙어도 진짜 증상인 합성어 — 증상 낱말 **앞에 붙는 수식어**(D-309, 허용 합성어 25개 목록을 이것으로 갈음했다): 낱말이 시작하는 자리부터 증상 낱말 바로 앞까지가 **이 표의 수식어와 정확히 같을 때만** 읽는다(`열감기`·`심한설사`·`주부습진`·`손습진`).
# 앞 글자가 수식어가 아니면(`체감기온`·`시설사용료`·`수요통계`·`정치통계`·`손목감기`) 읽지 않는다. 증상마다 따로 둔다 — `머리감기`(머리를 감는 일)가 읽히지 않게 `머리` 는 `무좀` 에만 있다.
HEALTH_SYMPTOM_PREFIX_KO = MappingProxyType({
    "감기": ("목", "코", "열", "속", "봄", "여름", "가을", "겨울", "환절기", "늦", "초기", "잔", "만성", "급성", "만성적", "심한", "독한", "잦은", "위장", "장염", "바이러스", "유아", "아기", "아이", "소아", "어린이", "성인", "노인", "임산부", "산후"),
    "설사": ("물", "묽은", "심한", "잦은", "배탈", "급성", "만성", "새벽", "아침", "식후", "식중독", "장염", "바이러스", "감염성", "과민성", "항생제", "스트레스", "우유", "여행자", "유아", "아기", "아이", "소아", "어린이", "노인", "임산부"),
    "요통": ("심한", "급성", "만성", "만성적", "산후", "임신", "임산부", "디스크", "허리", "근막", "기능성", "운동후", "아침", "새벽", "척추", "노인", "직업성"),
    "기침": ("마른", "잔", "밤", "가래", "심한", "잦은", "독한", "급성", "만성", "새벽", "아침", "야간", "알레르기", "천식", "역류성", "지속", "바이러스", "목", "아이", "아기", "소아", "어린이", "노인"),
    "복통": ("급성", "만성", "심한", "식후", "아랫배", "윗배", "위장", "생리", "소아", "아이", "아기", "장염", "변비", "경련성", "배탈"),
    "치통": ("심한", "급성", "만성", "어금니", "사랑니", "충치", "잇몸", "야간", "신경", "아이", "치아"),
    "습진": ("주부", "손", "발", "발바닥", "손바닥", "접촉성", "한포진", "지루성", "아토피", "건성", "화폐상", "땀띠", "기저귀", "아기", "소아", "급성", "만성", "알레르기성", "자극성"),
    "무좀": ("발", "손", "발톱", "사타구니", "머리", "심한", "만성", "물집", "각질", "아이"),
    "이명": ("만성", "급성", "이석", "소아", "돌발성", "소음성", "노인성", "편측성"),
})        # 증상 9 · 수식어 합계는 시험이 못박는다
HEALTH_MASKS_WORD_KO = ("바로잡",)        # 마스크 가운데 **한 낱말 안에서만** 가리는 것(D-303, P-12) — 띄어 쓴 `바로 잡아주는` 의 ‘바로’ 를 `바로잡` 마스크가 가리지 않게
# P-1: 늘 단정 낱말(`100퍼센트`·`백퍼센트`·`백프로`·`틀림없`·`장담`·`보장`·`보증`·`단언`)이 같은 글에 있고 **앞 두 낱말부터 이 낱말 끝까지 증상·질환·제품 낱말이 걸쳐 있을 때만** 효과 낱말로 읽는 결과 서술어.
# 효과 낱말 표에 넣지 않았다 — `영양제 오류 해결`·`체중 앱 오류 해결` 같은 평범한 글(엔진 후보 포함)이 근거 확인 필요로 올라가고 `체중 앱 오류 100% 해결` 이 중지가 된다.
HEALTH_RESOLVE_KO = ("해결", "치유", "호전", "제거", "퇴치", "차단", "정복", "잡아주", "잡아준", "잡아줍", "잡아줘", "막아주", "막아준", "막아줍", "막아줘")        # 15
# P-4: 효과 결과 명사(`_RESULT_NOUNS_KO`)가 **낱말 하나로 서술어 자리에 와서 글(또는 방법 안내 낱말 하나)이 거기서 끝날 때**도 효과 결과로 읽는다(`통증 즉시 완화`·`하루 만에 불면 극복`·`한 번에 유방암 치료`) —
# 뒤에 다른 낱말이 더 오면(`치료 바로 시작하기`·`스트레스 해소 여행 코스`) 읽지 않는다. 대상은 명사보다 앞에 있는 건강 낱말이어야 한다.
HEALTH_BARE_TAIL_KO = ("방법", "법", "비법", "비결", "노하우", "요령", "팁", "가이드", "루틴", "비밀")        # 10
# P-4: `멈추` 는 복용 중단 낱말(`HEALTH_DOSE_SCOPE_KO`)과 겹친다 — 대상이 증상·질환일 때만(제품·처방약이 없을 때) 효과 결과로 읽는다(`설사 즉시 멈추는 방법` 대 `영양제 바로 멈추는 법`).
HEALTH_HALT_SCOPE_KO = ("멈추", "멈춰", "멈춘", "멈춥", "멈췄", "멈출")        # 6
# P-3: 즉각·기간 표현 보강 — `HEALTH_INSTANT_PHRASE_KO` 와 같은 방식(범위 낱말처럼 읽고 옛 중지 바닥에는 넣지 않는다)이되 **효과 결과를 꾸밀 때만** 센다(서술어를 못 읽으면 세지 않는다 — 쇼핑 문장 `배송 일주일 만에` 과 부딪히지 않게).
HEALTH_INSTANT_MORE_KO = ("먹자마자", "마시자마자", "하룻밤", "한방에", "금세", "이틀 만에", "사흘 만에", "일주일 만에", "열흘 만에", "며칠 만에", "한 달 만에")        # 11 — `한방에` 는 `한방에서`(한방 치료)가 아닐 때만. `한 주 만에` 는 아래 숫자 표현(`주 만에`)이 읽는다
# 앞에 숫자(또는 한·두·세·네·몇)가 있을 때만 읽는 기간 표현(`5분 만에`·`3일 만에`·`몇 시간 만에`) — `분만에`(분만에 필요한 …)가 우연히 걸리지 않게.
HEALTH_INSTANT_NUMBERED_KO = ("분 만에", "시간 만에", "일 만에", "주 만에", "개월 만에")        # 5
# P-12: 즉각·기간 표현(`HEALTH_INSTANT_PHRASE_KO`·`HEALTH_INSTANT_MORE_KO`·`HEALTH_INSTANT_NUMBERED_KO`) 곁에서는 결과 서술어 조각으로 읽지 않고 행동 서술어로 읽는 조각 — 단 **대상이 증상 낱말이 아닐 때만**(D-310, 독립 검증 D6: `어깨 결림을 한 번에 풀어보는 스트레칭` 은 효과다) —
# `풀어보는`(퀴즈·문제·체크리스트를 풀어 보는 일)이 `풀어`(긴장을 풀어 준다)로 읽혀
# `크레아틴 단번에 풀어보는 템플릿` 이 중지가 됐다. 옛 범위 낱말(즉시·바로 …)은 옛 코드대로 둔다 — 그 곁의 판정을 낮추지 않는다.
HEALTH_INSTANT_ACTION_KO = ("풀어보",)        # 1
# P-6: 처방약 복용 중단 + 낫는 말 — 일반 효과 낱말(줄이·낮추 …)만 있으면 증상·질환 낱말이 함께 있어야 한다(`의약품 구독 끊고 비용 줄이는 방법` 은 아니다). 건강에서만 쓰는 낫는 말은 증상·질환 낱말 없이도 읽는다.
HEALTH_QUIT_CURE_KO = ("낫는", "나아지", "극복", "회복")        # 4
# D5(D-308): 처방약 **약 이름**(일반 낱말 `의약품`·`처방약`·`치료제` 가 아닌 이름 — 수면제·항생제·진통제·스테로이드 …)이 있고 복용을 끊는 표현이 함께 있으면 증상·질환 낱말이 없어도 이 결과 서술어(`좋아지`·`사라지`·`개선`·`해소`·`해결` …)를 낫는 말로 센다.
# 일반 낱말 곁(`의약품 구독 끊고 비용 개선하는 방법`)은 지금대로 센 적이 없다 — 그 하락(1차 수정 머리 대비)은 한계다(D-306).
HEALTH_QUIT_OUTCOME_KO = ("좋아지", "사라지", "없어지", "개선", "해소", "해결", "완화", "호전", "치유")        # 9
HEALTH_MEDICINE_GENERIC_KO = ("의약품", "처방약", "치료제")        # 3 — 약 이름이 아닌 일반 낱말(`HEALTH_MEDICINE_KO` 의 부분집합)
# P-6: `끊어도 되는 방법` 의 `되는` 자리에 오는 허용 말투(안전 우선 기본값 — 모두 같은 단계)
HEALTH_QUIT_OK_KO = ("되는", "안전한", "괜찮은", "가능한", "문제없는", "좋은")        # 6


# ---- 협찬 표(초기값 — 전략 원문 확인 전) ----------------------------------------------------------------------------------------------

SPONSOR_MARKERS_KO = ("제공받", "지원받", "협찬받", "지급받", "수령", "받았", "받음", "받은", "받아 작성", "받고 작성", "받아서 작성", "대가로", "조건으로", "무상으로", "공짜로", "작성했", "작성한", "소정의")        # 18
SPONSOR_MASKS_KO = ("광고 차단", "광고차단", "광고 수익", "광고 크리에이티브", "광고 단가", "광고 효과", "수수료 비교", "수수료 계산", "수수료 면제", "수수료 없", "제휴 카드", "제휴카드", "제휴 할인", "제휴할인", "제휴 사")        # 15
SPONSOR_STRONG_EN = ("sponsored", "sponsored post", "paid partnership", "paid promotion", "paid review", "affiliate link*", "affiliate commission*", "referral code*",
                     "referral link*", "free sample*", "press sample*", "provided for free", "received for free", "ppl", "in exchange for a review", "gifted by",
                     "gifted to me", "was gifted", "contains ads", "includes ads", "contains an ad", "this is an ad", "this is an advertisement")        # 23
SPONSOR_WEAK_EN = ("affiliate", "commission*", "sponsor", "sponsors", "coupon*", "reward*", "points")        # 7
SPONSOR_MARKERS_EN = ("received", "provided", "free", "gifted", "earn*", "paid", "disclosure", "compensat*")        # 8
SPONSOR_STRONG_KO = MappingProxyType({
    "goods": ("제품 협찬", "협찬품", "체험단", "서포터즈", "무료로 제공받", "제공받아 작성", "지원받아 작성", "제공받아 쓴", "지원받아 쓴"),
    "service": ("무료 숙박 제공", "무료 식사 제공", "시사회 초대받", "초청받아 작성"),
    "payment": ("원고료", "원고비", "소정의 대가", "소정의 원고료", "소정의 수수료", "대가를 받", "대가로 작성", "원고 제공", "유료광고", "광고비를 받", "활동비를 받", "제작비를 받"),
    "affiliate": ("파트너 링크", "제휴 링크", "추천인 코드", "구매 수수료", "성과 수수료", "쿠팡 파트너스", "파트너스 활동", "어필리에이트 링크", "제휴 마케팅 링크", "수수료를 받", "수수료를 지급", "수수료 수령", "커미션을 받"),
    "reward": ("우수 후기", "후기 이벤트", "리뷰 이벤트", "추첨 보상", "조건부 보상", "후기 작성 시", "후기 작성 리워드", "리뷰 작성 리워드"),
    "general": ("협찬", "협찬 광고", "광고 포함", "광고를 포함", "광고가 포함", "광고입니다", "경제적 대가", "경제적 이해관계"),
})        # 54
SPONSOR_WEAK_KO = MappingProxyType({
    "goods": ("제품 제공", "무료 제공", "무상 제공", "샘플 제공", "증정품", "체험 제품", "제품 지원", "샘플", "사은품"),
    "service": ("숙박권", "식사권", "초대권", "체험권", "이용권", "무료 체험", "서비스 제공", "숙박 제공"),
    "payment": ("광고비", "활동비", "제작비", "대가"),
    "affiliate": ("커미션", "수수료", "제휴", "어필리에이트", "파트너"),
    "reward": ("리워드", "포인트", "쿠폰", "적립금"),
})        # 30

SPONSOR_GROUPS = ("goods", "service", "payment", "affiliate", "reward")


# ---- 경험 표(초기값 — 전략 원문 확인 전) ----------------------------------------------------------------------------------------------

EXPERIENCE_GENRE_STRONG_KO = ("사용기", "체험기", "사용후기", "구매후기", "방문후기", "체험후기", "언박싱")        # 7
EXPERIENCE_GENRE_WEAK_KO = ("후기", "리뷰")        # 2
EXPERIENCE_MARKERS_KO = ("직접", "솔직", "실사용", "내돈내산", "내 돈 주고", "장기", "한 달", "개월", "일주일", "몇 주", "몇달")        # 11
EXPERIENCE_MASKS_KO = ("사용기간", "사용기록", "사용기준", "사용기한", "체험기간", "체험기한", "코드 리뷰", "코드리뷰", "리뷰어", "후기 쓰는", "후기 작성법", "리뷰 보는", "후기 믿")        # 13
EXPERIENCE_PHRASES_EN = ("i used", "i have used", "i tried", "i have tried", "my experience", "after using", "when i visited", "i visited", "i have visited", "i bought",
                         "i have bought", "i tested", "i have tested", "in my own use", "we used", "we tried", "we tested", "we visited", "we bought")        # 19


# ---- 일반 낱말 금지 목록(어느 단독 신호 표에도 넣지 않는다 — 시험이 지킨다) ------------------------------------------------------------------

GENERAL_WORDS = ("비교", "모델", "추천", "구매", "구입", "가격", "최저가", "순위", "가성비", "제품", "브랜드", "신제품", "스펙", "후기", "리뷰", "광고", "방법", "정리", "관리", "설정", "설치", "성능", "비용",
                 "가이드", "기준", "선택", "장점", "단점", "자동화", "도구", "서비스", "협업", "이벤트", "compare", "comparison", "model", "review", "reviews", "best", "vs", "buy", "buying", "price", "prices",
                 "brand", "specs", "unboxing", "ad", "ads", "advertisement", "paid", "treat", "supplement", "symptom", "symptoms", "disease", "dosage")        # 57


GROUP_KO = MappingProxyType({"symptom": "증상·상태", "effect": "효과·결과", "product": "제품·행위", "assertion": "단정·보장",
                             "goods": "현물 제공", "service": "서비스 제공", "payment": "금전 제공", "affiliate": "제휴·수수료", "reward": "조건부 보상"})

# ---- 일치 도구와 신호 계산 ----------------------------------------------------------------------------------------------------------------

SEP = chr(0)


def bisect_left(order, value):
    """정렬된 목록 `order` 에서 `value` 이상인 첫 자리(이분 탐색 — 이 계층은 허용한 표준 모듈만 쓰므로 `bisect` 를 가져오지 않고 직접 짰다)."""
    low, high = 0, len(order)
    while low < high:
        middle = (low + high) // 2
        if order[middle] < value:
            low = middle + 1
        else:
            high = middle
    return low


def bisect_right(order, value):
    """정렬된 목록 `order` 에서 `value` 보다 큰 첫 자리."""
    low, high = 0, len(order)
    while low < high:
        middle = (low + high) // 2
        if value < order[middle]:
            high = middle
        else:
            low = middle + 1
    return low
INVISIBLE_RANGES = ((0xAD, 0xAD), (0x34F, 0x34F), (0x61C, 0x61C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
                    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFFB), (0xE0000, 0xE0FFF))
_INVISIBLE = re.compile("[" + "".join(chr(low) + "-" + chr(high) for low, high in INVISIBLE_RANGES) + "]")
_PERCENT = re.compile(r"(?<![0-9])([0-9]+)\s*(?:%|퍼센트|프로)")        # 앞이 숫자가 아닐 때만 — 숫자만 4,000자인 글이 자리마다 끝까지 훑어 제곱으로 느려지지 않게(D-304, 뜻은 같다)
HANJA_WORDS = (("治療", "치료"), ("完治", "완치"), ("處方", "처방"), ("協贊", "협찬"), ("廣告", "광고"), ("保障", "보장"))
PARTICLE = "(?:을|를|이|가|은|는|도|만|의|에|로|으로|와|과|에서)?"
_OBLIGATION = re.compile(r"반드시(?=[가-힣0-9a-z]{0,6}?(?:해야|야할|알아야|지켜야|챙겨야|피해야|확인해야|기억해야|필요|하세요|해요|마세요|봐야))")
_NEGATION = re.compile(r"^(?:[가-힣]{0,2})?(?:하?지(?:는|도)?않|되지(?:는|도)?않|못|아니|아닙|불가)")
_QUESTION_ENDINGS = ("는지", "을까", "ㄹ까", "나요", "는가", "을지", "느냐", "인지", "일까", "한지", "할까", "될까", "한가", "있나", "있을")        # 의문 꼬리의 어미 — 모두 두 글자(앞에 한글 0–2글자가 붙을 수 있다)
_QUESTION_AFTER = ("요", "도", "는", "를", "을", "가", "이", "만", "에", "죠", "다", "고", "라")        # 의문 어미 바로 뒤에 붙어도 의문으로 읽는 한 글자(조사·종결) — 그 뒤가 낱말 끝일 때만(D-301)
_HASHTAG = re.compile(r"(?<![a-z0-9])#(?:ad|sponsored|gifted)(?![a-z0-9])")


def fold(text):
    text = _INVISIBLE.sub("", unicodedata.normalize("NFKC", str(text))).casefold()
    for old, new in HANJA_WORDS:
        text = text.replace(old, new)
    return _PERCENT.sub(lambda match: match.group(1) + "퍼센트", text)


def compact(folded):
    return "".join(char for char in folded if char.isalnum())


class _Starts(frozenset):
    """낱말이 새로 시작하는 자리의 집합 — 앞에서부터 센 정렬 목록(`order`)을 함께 들고 있어 '이 자리 다음 낱말 처음'을 이분 탐색으로 찾는다(P-11, D-304). 집합으로는 보통의 `frozenset` 과 같다."""
    __slots__ = ("order",)

    def __new__(cls, places=()):
        self = super().__new__(cls, places)
        self.order = tuple(sorted(self))
        return self


def _order(starts):
    """낱말이 시작하는 자리들의 정렬 목록 — `compact_marked` 가 만든 집합이면 이미 들고 있고, 그냥 `frozenset` 이면 그때그때 정렬한다."""
    order = getattr(starts, "order", None)
    return order if order is not None else tuple(sorted(starts))


def compact_marked(folded_texts):
    """`compact` 와 같게 글자·숫자만 이어 붙이되(글 사이는 `SEP`) **낱말이 새로 시작하는 자리**(앞에 띄어쓰기·기호가 있던 자리)를 함께 돌려준다 — 표 낱말이 낱말 경계를 넘어 우연히 이어 붙는 것을 가려내는 데 쓴다(D-58)."""
    chars, starts = [], set()
    for number, folded in enumerate(folded_texts):
        if number:
            chars.append(SEP)
        fresh = True
        for char in folded:
            if char.isalnum():
                if fresh:
                    starts.add(len(chars))
                    fresh = False
                chars.append(char)
            else:
                fresh = True
    return "".join(chars), _Starts(starts)


def phrase_regex(entry):
    return re.compile(PARTICLE.join(re.escape(compact(fold(word))) for word in entry.split()))


def compile_table(entries, *, loose=False, start=(), bare=()):
    """표 → (항목, 정규식, 낱말 경계 규칙을 거나). 띄어쓰기가 든 항목(낱말 사이 경계를 스스로 가진 것)과 `loose` 표는 거짓 = 경계 규칙 없이 예전처럼 찾는다.
    `start` 의 항목은 `"start"`(낱말 처음에서 시작하거나 앞 글자가 허용한 수식어일 때만 읽는다 — D-307: 일치가 둘째 낱말로 넘어가면 읽지 않는다), 띄어쓰기가 든 `start` 항목은 `"wordstart"`(낱말 처음에서 시작할 때만 — `눈 건강`), `bare` 의 항목은 `"bare"`(낱말 처음에서 시작하고 낱말이 거기서 끝나거나 이어지는 말이 조사·`증` 으로 시작할 때만 읽는다) — 붙여 쓴 일상 합성어 속 두 글자 증상을 거른다(D-303, P-7)."""
    return tuple((entry, phrase_regex(entry), "bare" if entry in bare else (("start" if len(entry.split()) == 1 else "wordstart") if entry in start else (not loose and len(entry.split()) == 1))) for entry in entries)


def english_tokens(folded):
    text = re.sub(r"(?<=[a-z])'(ve|m|re|ll|d)\b", lambda match: " " + {"ve": "have", "m": "am", "re": "are", "ll": "will", "d": "would"}[match.group(1)], folded)
    return re.findall(r"[a-z0-9]+", text.replace("n't", " not"))


def _token_match(tokens, start, want):
    return all(token == word or (word.endswith("*") and token.startswith(word[:-1])) for token, word in zip(tokens[start:start + len(want)], want, strict=True))


def find_en(tokens, entries, *, negation_guard=False):
    found = []
    for entry in entries:
        want = entry.split()
        for start in range(len(tokens) - len(want) + 1):
            if _token_match(tokens, start, want) and not (negation_guard and any(token in NEGATION_TOKENS_EN for token in tokens[max(0, start - 3):start])):
                found.append(entry)
                break
    return found


def mask_en(tokens, entries):
    tokens = list(tokens)
    for entry in entries:
        want = entry.split()
        for start in range(len(tokens) - len(want) + 1):
            if _token_match(tokens, start, want):
                tokens[start:start + len(want)] = [SEP] * len(want)
    return tokens


def _instant_table():
    """범위 낱말 표(`soft`)에 더하는 즉각·기간 표현(D-293 넷 + D-300 보강) — 낱말 처음 규칙이 필요한 것(`한방에` 는 `한방에서` 가 아니어야 하고, 기간 표현은 숫자가 앞에 있어야 한다)은 따로 짠다."""
    plain = compile_table(HEALTH_INSTANT_PHRASE_KO + tuple(word for word in HEALTH_INSTANT_MORE_KO if word != "한방에"))
    special = (("한방에", re.compile(phrase_regex("한방에").pattern + "(?!서)"), True),)
    numbered = tuple((entry, re.compile("(?:[0-9]{1,4}|[한두세네몇])" + phrase_regex(entry).pattern), False) for entry in HEALTH_INSTANT_NUMBERED_KO)
    return plain + special + numbered


class Tables:
    """compiled once at import"""
    mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(HEALTH_MASKS_KO), key=lambda word: (-len(word), word)) if not word.startswith("암") and word not in HEALTH_MASKS_WORD_KO)
    mask_word = tuple(phrase_regex(word) for word in HEALTH_MASKS_WORD_KO)                                       # 한 낱말 안에서만 가리는 마스크(D-303, P-12)
    mask_start = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(HEALTH_MASKS_KO), key=lambda word: (-len(word), word)) if word.startswith("암"))        # 한 글자 질환 `암` 으로 시작하는 마스크는 낱말 처음에서 시작할 때만(D-140) — `유방암 모양` 속 ‘암’ 을 가리지 않게
    sp_mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(SPONSOR_MASKS_KO), key=lambda word: (-len(word), word)))
    exp_mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(EXPERIENCE_MASKS_KO), key=lambda word: (-len(word), word)))
    p_legacy = compile_table(tuple(word for word in HEALTH_PRODUCT_KO if word not in NEW_PRODUCT_SET))
    s_weak, s_strong, e_gen, e_med, p, a_strong, a_effect, a_soft = (compile_table(x) for x in (HEALTH_SYMPTOM_KO, HEALTH_DISEASE_KO, HEALTH_EFFECT_KO, HEALTH_MEDICAL_KO, HEALTH_PRODUCT_KO, HEALTH_ASSERT_KO, HEALTH_ASSERT_EFFECT_KO, HEALTH_ASSERT_SOFT_KO))
    s_weak = compile_table(HEALTH_SYMPTOM_KO, start=HEALTH_SYMPTOM_START_KO, bare=HEALTH_SYMPTOM_BARE_KO)
    symptom_prefix = MappingProxyType({entry: frozenset(compact(fold(word)) for word in words) for entry, words in HEALTH_SYMPTOM_PREFIX_KO.items()})        # 증상 → 허용 수식어(띄어쓰기를 지운 모양)        # D-303: 두 글자 증상은 낱말 처음에서만, 진짜 합성어는 허용 목록으로
    resolve = compile_table(HEALTH_RESOLVE_KO)                                                                       # 늘 단정 낱말 곁에서만 효과로 읽는 결과 서술어(D-298, P-1)
    sp_strong = {group: compile_table(words) for group, words in SPONSOR_STRONG_KO.items()}
    sp_weak = {group: compile_table(words) for group, words in SPONSOR_WEAK_KO.items()}
    sp_marker = compile_table(SPONSOR_MARKERS_KO, loose=True)        # 받음 표지는 어미가 띄어 쓰이는 일이 흔하다(제공 받았다·작성 했다) — 경계 규칙 없이 예전처럼 찾는다
    g_strong, g_weak, g_mark = compile_table(EXPERIENCE_GENRE_STRONG_KO), compile_table(EXPERIENCE_GENRE_WEAK_KO), compile_table(EXPERIENCE_MARKERS_KO)
    warn = compile_table(HEALTH_WARNING_KO)
    scoped = {kind: compile_table(words) + (_instant_table() if kind == "soft" else ()) for kind, words in ASSERT_SCOPED_KO.items()}        # 즉각 표현 보강(D-293·D-300)은 범위 낱말 표(`ASSERT_SCOPED_KO`)가 아니라 여기서만 더한다 — 그 표는 옛 코드의 낱말이다
    instant_all = frozenset(HEALTH_INSTANT_PHRASE_KO + HEALTH_INSTANT_MORE_KO + HEALTH_INSTANT_NUMBERED_KO)          # 즉각·기간 표현 전부 — 서술어를 못 읽을 때 효과 낱말을 찾아보는 보충(`_effect_within`)과 처방약 보수적 읽기 제외의 기준
    bare_result = frozenset(compact(fold(noun)) for noun in _RESULT_NOUNS_KO)                                       # 낱말 하나로 서술어 자리에 와도 효과 결과로 읽는 명사(D-299)
    bare_tail = frozenset(compact(fold(word)) for word in HEALTH_BARE_TAIL_KO)
    halt_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_HALT_SCOPE_KO) + ")")
    quiz_words = tuple(compact(fold(word)) for word in HEALTH_INSTANT_ACTION_KO)                                   # `풀어보` — 효과 낱말 표의 `풀어` 가 그 안에서 찾아지지 않게(D-299)
    quiz_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_INSTANT_ACTION_KO) + ")")                      # 즉각·기간 표현 곁에서 결과로 읽지 않는 서술어 조각(D-299)
    result_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_RESULT_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    action_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_ACTION_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    forms = compile_table(HEALTH_ASSERT_FORMS_KO, loose=True)
    dose_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_DOSE_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    advice_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_ADVICE_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    adverb_suffix = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(SCOPE_ADVERB_SUFFIX_KO), key=lambda word: (-len(word), word))) + ")")
    ask = re.compile("(" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_ASK_STEMS_KO) + ")(?:" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_ASK_TAILS_KO) + ")")
    quit_outcome = compile_table(HEALTH_QUIT_OUTCOME_KO)                                                              # 약 이름 곁 복용 중단과 함께 낫는 말로 세는 결과 서술어(D-308)
    quit_stop = compile_table(HEALTH_QUIT_KO)                                                                        # 복용을 끊는 표현(D-294)
    quit_allow = MappingProxyType({compact(fold(word)): word for word in HEALTH_QUIT_ALLOW_KO})                      # 띄어쓰기를 지운 모양 → 표의 항목(알림에 보이는 말)
    quit_howto = re.compile("(" + "|".join(re.escape(piece) for piece in sorted(quit_allow, key=lambda piece: (-len(piece), piece))) + ")(?:" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_QUIT_OK_KO) + ")(" + "|".join(re.escape(compact(fold(word))) for word in sorted(HEALTH_QUIT_HOWTO_KO, key=lambda word: (-len(word), word))) + ")")


def blank(text, patterns):
    for pattern in patterns:
        text = pattern.sub(lambda match: SEP * len(match.group(0)), text)
    return text


def blank_at_starts(text, starts, patterns):
    """`blank` 와 같되 **낱말 처음에서 시작하는 일치만** 가린다(D-140) — `암 모양` 마스크가 `유방암 모양` 속 ‘암’ 을 가리지 않는다. 가린 길이는 그대로라 `starts` 가 맞는다."""
    for pattern in patterns:
        text = pattern.sub(lambda match: SEP * len(match.group(0)) if match.start() in starts else match.group(0), text)
    return text


def blank_within_words(text, starts, patterns):
    """`blank` 와 같되 **한 낱말 안의 일치만** 가린다(D-303, P-12) — 일치 한가운데에서 낱말이 새로 시작하면(`바로 잡아주는` 속 `바로잡`) 가리지 않는다. 가린 길이는 그대로라 `starts` 가 맞는다."""
    for pattern in patterns:
        text = pattern.sub(lambda match: match.group(0) if any(place in starts for place in range(match.start() + 1, match.end())) else SEP * len(match.group(0)), text)
    return text


def reads_as_one_word(text, starts, start, end):
    """띄어쓰기 없는 표 항목이 글에서 찾아진 자리 `[start, end)` 가 그 낱말로 읽히는가 — 글자·숫자만 이어 붙인 글에서는 낱말 경계를 넘어 우연히 이어진 일치(`설치 매뉴얼` 의 ‘치매’)가 생기기 때문이다.
    ① 낱말 하나 안에서 찾았으면 읽는다(붙여 쓴 복합어 `초기치매`·조사 `치매가` 포함). ② 띄어쓴 낱말들에 걸쳤으면 **첫 조각이 낱말 처음부터 시작**하고 **뒤 조각이 한글 한 글자가 아닐 때**만 읽는다
    (`허리 디스크`·`건강 식품`·`오메가 3` 은 읽고 `설치 매뉴얼`·`지방 간 택배`·`수면 제품` 은 읽지 않는다 — 두 글자 항목은 걸치면 뒤 조각이 늘 한 글자라 낱말 안에서만 읽힌다).
    글자를 하나씩 띄운 우회(`영 양 제`)와 한 글자 꼬리를 띄운 이름(`대장 암`)은 읽지 않는 대신 정상 주제가 막히지 않게 한 것이다."""
    cuts = [start, *(place for place in range(start + 1, end) if place in starts), end]
    if len(cuts) == 2:
        return True
    if start not in starts:
        return False
    return all(not (cuts[number + 1] - cuts[number] == 1 and "가" <= text[cuts[number]] <= "힣") for number in range(1, len(cuts) - 1))


def _word_rest(text, starts, end):
    """`end` 부터 그 낱말이 끝나는 자리(다음 낱말 처음·다른 글·글 끝)까지의 글자 — 낱말 속에서 찾은 항목 뒤에 붙은 말이다."""
    stop = text.find(SEP, end)
    stop = len(text) if stop < 0 else stop
    order = _order(starts)
    index = bisect_left(order, end)
    if index < len(order) and order[index] < stop:
        stop = order[index]
    return text[end:stop]


def _word_start(starts, place):
    """`place` 가 든 낱말이 시작하는 자리(글의 처음이면 0)."""
    order = _order(starts)
    index = bisect_right(order, place)
    return order[index - 1] if index else 0


def _reads(text, starts, mode, match, entry=""):
    """표 항목 `entry` 의 일치 `match` 를 읽는가 — `mode` 가 거짓이면 늘, `"wordstart"`(두 낱말 항목)면 낱말 처음에서 시작할 때만, `"start"`·`"bare"`(한 낱말 증상)면 ① **일치가 둘째 낱말로 넘어가지 않을 때**(`설 사진`·`감 기르는 법` 은 아니다 — D-307)
    ② 낱말 처음에서 시작하거나 앞 글자가 `HEALTH_SYMPTOM_PREFIX_KO` 의 그 증상 수식어와 정확히 같을 때(`열감기`는 읽고 `체감기온`·`손목감기` 는 아니다), `"bare"` 는 거기에 더해 ③ 낱말이 거기서 끝나거나 이어지는 말이 조사·`증`·`현상`·`치료` 등으로 시작할 때만 읽는다. 그 밖(참)은 낱말 경계 규칙(`reads_as_one_word`)을 지났을 때만 읽는다."""
    if not mode:
        return True
    if mode == "wordstart":
        return match.start() in starts
    if mode in ("start", "bare"):
        if any(place in starts for place in range(match.start() + 1, match.end())):
            return False
        lead = text[_word_start(starts, match.start()):match.start()]
        if lead and lead not in Tables.symptom_prefix.get(entry, ()):
            return False
        if mode == "start":
            return True
        rest = _word_rest(text, starts, match.end())
        return rest == "" or rest.startswith(BARE_SYMPTOM_REST_KO)
    return reads_as_one_word(text, starts, match.start(), match.end())


def find_ko(text, starts, table):
    return [entry for entry, pattern, strict in table if any(_reads(text, starts, strict, match, entry) for match in pattern.finditer(text))]


def _asks_after(text, starts, end):
    """단정 낱말이 끝나는 자리 `end` 뒤가 **의문 꼬리**(`줄일까`·`줄이는지` — 한글 0–2글자 + `_QUESTION_ENDINGS`)인가.
    띄어쓰기를 지우고 읽으므로 **띄어쓴 두 낱말의 끝과 처음이 우연히 어미 꼴로 이어 붙은 것**(`없애는 지압법` 의 ‘는지’·`없애는 가이드` 의 ‘는가’·`해소한 가이드` 의 ‘한가’)은 의문이 아니다 —
    어미 두 글자 사이에 낱말이 새로 시작하는 자리가 끼면 읽지 않는다(D-290). 이 틈 때문에 `두통을 바로 없애는 지압법` 이 표시만으로 내려가 있었다. 어미가 한 낱말 안에 있으면 예전처럼 읽는다."""
    tail = text[end:end + 8]
    for size in (2, 1, 0):
        if all("가" <= char <= "힣" for char in tail[:size]) and tail[size:size + 2] in _QUESTION_ENDINGS and end + size + 1 not in starts and (tail[size:size + 2] == "있을" or _question_closed(text, starts, end + size + 2)):
            return True                                                                        # `있을` 은 `있을까`·`있을지` 의 앞부분이라 뒤를 따지지 않는다
    return False


def _question_closed(text, starts, place):
    """의문 어미가 끝난 자리 `place` 가 낱말 끝인가 — 조사·종결 한 글자(`_QUESTION_AFTER`)가 붙은 뒤 끝이어도 읽는다(`줄이는지를`·`줄일까요`). 어미 뒤에 다른 글자가 이어 붙은 것(`없애는지압법` 의 ‘는지’+`압법`, `없애는가이드` 의 ‘는가’+`이드`)은
    붙여 쓴 다른 낱말이라 의문이 아니다(D-301, P-2). 붙여 쓴 진짜 의문(`줄이는지알아보기`)은 단정으로 읽힌다 — 안전한 쪽의 한계(D-306)."""
    def boundary(at):
        return at >= len(text) or at in starts or text[at] == SEP
    return boundary(place) or (text[place] in _QUESTION_AFTER and boundary(place + 1))


def find_assert(text, starts, table):
    found = []
    for entry, pattern, strict in table:
        for match in pattern.finditer(text):
            if strict and not reads_as_one_word(text, starts, match.start(), match.end()):
                continue
            if entry == "반드시" and _OBLIGATION.match(text, match.start()):
                continue
            tail = text[match.end():match.end() + 8]
            if _NEGATION.match(tail) or _asks_after(text, starts, match.end()):
                continue
            found.append(entry)
            break
    return found


def _spans_ko(text, starts, table):
    """`find_ko` 와 같은 일치 규칙(낱말 경계 포함)으로 찾되 항목마다 **찾아진 자리** `[(시작, 끝)]` 를 돌려준다 — 찾지 못한 항목은 싣지 않는다."""
    found = {}
    for entry, pattern, strict in table:
        places = [(match.start(), match.end()) for match in pattern.finditer(text) if _reads(text, starts, strict, match, entry)]
        if places:
            found[entry] = places
    return found


def _spans_en(tokens, entries):
    """`find_en`(부정 보호 없이)과 같은 규칙으로 항목마다 모든 자리 `[(시작, 끝)]`(낱말 번호)를 돌려준다."""
    found = {}
    for entry in entries:
        want = entry.split()
        places = [(start, start + len(want)) for start in range(len(tokens) - len(want) + 1) if _token_match(tokens, start, want)]
        if places:
            found[entry] = places
    return found


def _only_inside(found, covers):
    """`found`(항목 → 자리들) 가운데 **모든 자리가** `covers`(더 긴 낱말이 찾아진 자리들)의 어느 하나 안에 들어 있는 항목 — 제품·기기 이름의 일부일 뿐이라 따로 세지 않는다(D-105)."""
    return [entry for entry, places in found.items() if all(any(low <= start and end <= high and high - low > end - start for low, high in covers) for start, end in places)]


def _pieces_inside_products(joined, starts, tokens, raw, legacy=False):
    """건강 제품·기기 이름 안에서만 찾아진 증상·효과·의료 낱말 — `((칸 이름, 항목), …)`. 제품 이름이 없거나 그 안에 들어갈 낱말이 없으면 계산하지 않는다(보통의 글은 비용이 늘지 않는다).
    `자세교정기` 속 ‘자세’·‘교정’, `치료제` 속 ‘치료’, `다이어트 제품` 속 ‘다이어트’ 같은 것이다 — 제품 이름 하나를 두 개념군으로 세면 `영양제` 단독(표시만)과 `치료제` 단독(단정 위험)이 갈리는 모순이 생긴다(D-105).
    **질환 이름에는 적용하지 않는다**(수정 1차) — `암 예방`·`암 수술`·`수술 후유증` 은 질환(D)이면서 안쪽의 효과(‘예방’)·의료 효능어(‘수술’)도 예전처럼 센다. 그래서 `암 예방 100% 보장` 은 질환 + 효과 + 단정이라 단정 위험(중지)이다."""
    if not raw["product"] or not (raw["symptom"] or raw["effect"] or raw["medical"] or (raw["disease"] and not legacy)):
        return ()
    ko_covers = [place for places in _spans_ko(joined, starts, Tables.p_legacy if legacy else Tables.p).values() for place in places]
    en_covers = [place for places in _spans_en(tokens, HEALTH_PRODUCT_EN).values() for place in places]
    inside = []
    fields = (("symptom", Tables.s_weak, HEALTH_SYMPTOM_EN), ("effect", Tables.e_gen, HEALTH_EFFECT_EN), ("medical", Tables.e_med, HEALTH_MEDICAL_EN))
    for field, table, words in fields if legacy else fields + (("disease", Tables.s_strong, HEALTH_DISEASE_EN),):        # 질환 낱말도: `혈압약`·`당뇨약`·`항암제` 속 ‘혈압’·‘당뇨’·‘항암’ 은 약 이름 하나다(D-137)
        inside += [(field, entry) for entry in _only_inside(_spans_ko(joined, starts, table), ko_covers) + _only_inside(_spans_en(tokens, words), en_covers)]
    return tuple(inside)


def _pieces_after(text, starts, end, limit=6):
    """단정 낱말이 끝나는 자리 `end` 뒤의 낱말 조각들 `(시작, 끝, 조각)` — 같은 글 안(`SEP` 앞)에서 띄어쓴 낱말 단위로 앞에서부터 **최대 `limit` 개**(P-11: 아주 긴 글에서 일치마다 글 끝까지 쪼개지 않는다).
    낱말에 붙여 쓴 어미(`확실히` 의 ‘히’)는 떼고, 남는 것이 없으면 건너뛴다."""
    stop = text.find(SEP, end)
    stop = len(text) if stop < 0 else stop
    order = _order(starts)
    inner = [place for place in order[bisect_right(order, end):][:limit] if place < stop]
    cuts = [end, *inner] if len(inner) == limit else [end, *inner, stop]
    pieces = [(cuts[number], cuts[number + 1], text[cuts[number]:cuts[number + 1]]) for number in range(len(cuts) - 1)]
    if pieces and end not in starts:
        pieces[0] = (pieces[0][0], pieces[0][1], Tables.adverb_suffix.sub("", pieces[0][2], count=1))
    return [piece for piece in pieces if piece[2]]


def _bare_ends(rest):
    """효과 결과 명사 낱말 뒤에 남은 낱말 조각들 `rest` 가 없거나 방법 안내 낱말(`HEALTH_BARE_TAIL_KO`) 하나뿐인가 — 명사가 글의 끝 말인지(D-299, P-4)."""
    return not rest or (len(rest) == 1 and rest[0][2] in Tables.bare_tail)


def _walk(pieces, spans):
    """단정 낱말 뒤 낱말 조각들 `pieces` 에서 꾸밈을 읽는다 — (범위, 자리, 서술어 낱말) 또는 `None`. `spans`(건강 낱말 자리를 돌려주는 함수)가 있으면 건강 낱말 조각도 건너뛴다(`즉시 눈 건강을 회복하는`·`하루 만에 불면 극복`).
    효과 결과 명사가 낱말 하나로 와서 글이 거기서 끝나면 효과 결과다(`통증 즉시 완화`) — 이때 자리는 명사가 **시작하는** 곳이라 대상 검사가 명사 자신을 대상으로 세지 않는다(D-299)."""
    for number, (begin, stop, piece) in enumerate(pieces[:3]):
        if Tables.advice_start.match(piece):
            return "action", stop, piece
        if Tables.result_start.match(piece):
            return "effect", stop, piece
        if Tables.dose_start.match(piece):
            return "dose", stop, piece
        if Tables.action_start.match(piece):
            return "action", stop, piece
        if Tables.halt_start.match(piece):
            return "halt", stop, piece                                      # `멈춘`·`멈춥`·`멈췄`·`멈출` — 복용 중단 낱말 표(`멈추`·`멈춰` 만 있다)에 없어 대상을 보고 가른다(D-299)
        if piece in Tables.bare_result and _bare_ends(pieces[number + 1:]):
            return "effect", begin, piece
        if number >= 2 or not (piece in SCOPE_SKIP_WORDS_KO or piece.endswith(SCOPE_PARTICLES_KO) or (spans is not None and spans().covers(begin, stop))):
            break
    return None


def _scope_and_end(text, starts, end, spans=None):
    """`scope_of` 와 같되 꾸밈을 읽은 서술어 낱말이 끝나는 자리와 그 낱말도 함께 돌려준다 — (범위, 자리, 서술어 낱말).
    ① 앞 세 낱말을 건너뛰는 낱말(목적어 꼴·부사)만 건너뛰며 읽는다 ② 그래도 모르면(`none`) `spans` 가 있을 때 건강 낱말 조각도 건너뛰며 한 번 더 읽되 **효과 결과일 때만** 받아들인다 — 행동·복용으로 읽히던 글을 건너뛰기로 바꾸지 않는다(옛 중지가 풀리지 않게)."""
    pieces = _pieces_after(text, starts, end)
    found = _walk(pieces, None)
    if found is None and spans is not None:
        found = _walk(pieces, spans)
        if found is not None and found[0] != "effect":
            found = None
    return found if found is not None else ("none", end, "")


def scope_of(text, starts, end):
    """단정 낱말(자리가 `end` 에서 끝남)이 **무엇을 꾸미는가**(D-130) — `effect`(효과 결과 서술어: 줄인다·없앤다·교정한다·치료된다 …) / `action`(행동 서술어: 확인한다·알기·먹는다·기록한다 …) / `none`(모르겠다 — 옛 규칙 그대로).
    낱말 바로 뒤 낱말을 읽고, 그 낱말이 목적어 꼴(조사 `을·를·에·로 …` 로 끝남)이거나 건너뛰는 부사(`SCOPE_SKIP_WORDS_KO` — 같이·함께·꼭·크게 …)이면 건너뛰어 그다음 낱말을 읽는다(`즉시 피로를 없애는`·`바로 같이 먹어도`). 건너뛰는 것은 최대 두 낱말이고
    세 낱말 안에서 서술어를 못 찾으면 `none` 이다(멀리 있는 서술어를 억지로 잇지 않는다)."""
    scope = _scope_and_end(text, starts, end)[0]
    return "none" if scope == "halt" else scope        # 건강 낱말 조각을 건너뛰는 둘째 읽기(D-299)는 건강 낱말 자리가 필요해 `_scoped_ko` 안에서만 한다


def _bare_diseases(text, starts):
    """한 글자 질환(`HEALTH_DISEASE_BARE_KO`)이 **낱말 단독이거나 조사만 붙은 꼴**로 찾아진 자리 `[(낱말, 시작, 끝)]` (D-136, D-58 경계 규칙의 한 글자 질환 몫) — `암호`·`암기`·`암벽` 속의 ‘암’ 은 읽지 않는다."""
    found = []
    for word in HEALTH_DISEASE_BARE_KO:
        piece = compact(fold(word))
        for match in re.finditer(re.escape(piece), text):
            if match.start() not in starts:
                continue
            rest = _word_rest(text, starts, match.end())                                    # D-307(D10): 낱말 끝을 이분 탐색으로 — `암 ` 을 수천 번 되풀이한 글에서 제곱으로 느려지지 않게
            if rest == "" or rest in BARE_DISEASE_PARTICLES_KO:
                found.append((word, match.start(), match.end()))
    return found


def _disease_spans(text, starts):
    spans = [place for places in _spans_ko(text, starts, Tables.s_strong).values() for place in places]
    return spans + [(begin, end) for _word, begin, end in _bare_diseases(text, starts)]


def _health_spans(text, starts):
    """글에서 건강 대상 낱말(증상·질환·건강 제품·의료 효능어)이 찾아진 자리들 `[(시작, 끝)]` — `find_ko` 와 같은 낱말 경계 규칙(한 글자 질환 포함)."""
    spans = _disease_spans(text, starts)
    for table in (Tables.s_weak, Tables.p, Tables.e_med):
        for places in _spans_ko(text, starts, table).values():
            spans += places
    return spans


def _cure_claim(text):
    """`완치` 가 **중립 꼬리**(`CURE_NEUTRAL_KO` — 후·율·판정·사례·기준·통계·여부)가 아닌 자리에서 한 번이라도 나오면 `("완치",)`(D-137)."""
    return ("완치",) if any(not text[match.end():match.end() + 2].startswith(CURE_NEUTRAL_KO) for match in re.finditer("완치", text)) else ()


def _has_health_object(text, starts, spans, begin, stop):
    """효과 결과를 꾸미는 단정 낱말의 **대상이 건강 낱말인가** — 단정 낱말이 든 낱말의 앞 두 낱말부터 서술어가 끝나는 자리까지 건강 대상 낱말이 걸쳐 있으면 참(`피로를 즉시 줄이는`·`즉시 피로를 줄이는`).
    `다이어트 앱 로딩 속도를 바로 줄이는` 처럼 효과 서술어의 대상이 건강과 상관없는 것(앞 두 낱말 안에 건강 낱말이 없음)은 거짓이다 — 소프트웨어·생활 문장을 단정 위험으로 올리지 않는다."""
    order = _order(starts)
    index = bisect_right(order, begin)
    word = order[index - 1] if index else 0
    lower = text.rfind(SEP, 0, word) + 1
    first = bisect_left(order, lower)
    window = order[index - 3] if index and index - 1 - first >= 2 else lower        # 낱말 앞 두 낱말의 처음(같은 글 안에서)
    if isinstance(spans, _SpanIndex):
        return spans.overlaps(window, stop)
    return any(low < stop and high > window for low, high in spans)


def _effect_within(text, starts, end):
    """즉각 표현이 끝나는 자리 `end` 뒤 **세 낱말 안**(같은 글 조각)에서 효과 낱말(`HEALTH_EFFECT_KO`)이 처음 끝나는 자리 — 없으면 `None`(D-293). 꾸밈 서술어를 못 읽을 때(`하루 만에 당뇨 극복`)의 보충이다 —
    효과 낱말이 즉각 표현보다 **앞**에 있는 글(`당뇨 예방 식단 하루 만에 완성`)은 이 규칙에 걸리지 않는다."""
    pieces = _pieces_after(text, starts, end)[:3]
    if not pieces:
        return None
    low, high = pieces[0][0], pieces[-1][1]
    best = None
    for _entry, pattern, strict in Tables.e_gen:
        for match in pattern.finditer(text, low, high):
            if strict and not reads_as_one_word(text, starts, match.start(), match.end()):
                continue
            if text.startswith(Tables.quiz_words, match.start()):
                continue                                                                     # D-299: `문제 풀어보는` 의 ‘풀어’ 는 퀴즈를 푸는 일이다
            best = match.end() if best is None else min(best, match.end())
            break
    for _begin, stop, piece in pieces:
        if Tables.result_start.match(piece) and not Tables.quiz_start.match(piece):          # D-299(P-8): 낱말 처음에 건강 결과 서술어가 있으면(`살 빠지는`·`피로가 풀리는`) 그것도 효과 낱말이다 — 모르는 서술어를 제품 곁에서 세던 옛 보충을 이것으로 갈음했다
            best = stop if best is None else min(best, stop)
            break
    return best


def _object_spans(text, starts):
    """질환·건강 제품 낱말이 찾아진 자리들 `[(시작, 끝)]` — 즉각 표현의 보충 읽기(`_effect_within`)는 대상이 증상뿐인 글(`하루 만에 스트레스 해소 여행`)을 읽지 않는다."""
    spans = _disease_spans(text, starts)
    for places in _spans_ko(text, starts, Tables.p).values():
        spans += places
    return spans


class _SpanIndex:
    """건강 낱말 자리 `[(시작, 끝)]` — 시작 순으로 정렬하고 끝의 앞쪽 최댓값을 함께 들어 둬 '이 구간에 걸친 자리가 있는가'를 이분 탐색으로 답한다(P-11, D-304). 목록처럼 돌릴 수도 있다."""
    __slots__ = ("items", "lows", "highs")

    def __init__(self, spans):
        self.items = sorted(spans)
        self.lows = [low for low, _high in self.items]
        top, self.highs = 0, []
        for _low, high in self.items:
            top = max(top, high)
            self.highs.append(top)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def overlaps(self, window, stop):
        """`any(low < stop and high > window)` — 효과 결과를 꾸미는 낱말의 대상 창에 걸친 자리가 있는가."""
        index = bisect_left(self.lows, stop)
        return index > 0 and self.highs[index - 1] > window

    def covers(self, begin, stop):
        """`any(low <= begin and stop <= high)` — 낱말 조각 `[begin, stop)` 이 어느 한 자리 안에 통째로 들어 있는가."""
        index = bisect_right(self.lows, begin)
        return index > 0 and self.highs[index - 1] >= stop


class _Spans:
    """한 글 안의 건강 낱말 자리 목록 — 요구가 처음 올 때 한 번만 계산해 둔다(P-11: 즉각 표현이 일치할 때마다 다시 계산하면 `하루 만에 당뇨 극복 ` 을 천 번 되풀이한 글에서 0.04초가 5.9초로 늘었다)."""
    __slots__ = ("text", "starts", "_cache")

    def __init__(self, text, starts):
        self.text, self.starts, self._cache = text, starts, {}

    def _get(self, name, make):
        if name not in self._cache:
            self._cache[name] = make()
        return self._cache[name]

    def health(self):
        return self._get("health", lambda: _SpanIndex(_health_spans(self.text, self.starts)))

    def object(self):
        return self._get("object", lambda: _SpanIndex(_object_spans(self.text, self.starts)))

    def disease(self):
        return self._get("disease", lambda: _SpanIndex(_disease_spans(self.text, self.starts)))

    def plain_symptom(self):
        return self._get("plain_symptom", lambda: _SpanIndex([place for places in _spans_ko(self.text, self.starts, Tables.s_weak).values() for place in places]))

    def symptom(self):
        return self._get("symptom", lambda: _SpanIndex(list(self.disease()) + [place for places in _spans_ko(self.text, self.starts, Tables.s_weak).values() for place in places]))

    def product(self):
        return self._get("product", lambda: _SpanIndex([place for places in _spans_ko(self.text, self.starts, Tables.p).values() for place in places]))


def _scoped_ko(text, starts):
    """범위 낱말(`ASSERT_SCOPED_KO`)과 즉각·기간 표현(`HEALTH_INSTANT_*`)이 낱말 경계·의무 꼴·부정·의문 꼬리 규칙(`find_assert` 와 같음)을 지나 찾아진 **자리마다** `(낱말, 종류, 범위)`."""
    found, spans = [], _Spans(text, starts)
    for kind, table in Tables.scoped.items():
        for entry, pattern, strict in table:
            for match in pattern.finditer(text):
                if strict and not reads_as_one_word(text, starts, match.start(), match.end()):
                    continue
                if entry == "반드시" and _OBLIGATION.match(text, match.start()):
                    continue
                tail = text[match.end():match.end() + 8]
                if _NEGATION.match(tail) or _asks_after(text, starts, match.end()):
                    continue
                scope, stop, piece = _scope_and_end(text, starts, match.end(), spans.health)
                if scope in ("dose", "halt") and Tables.halt_start.match(piece):
                    if _has_health_object(text, starts, spans.symptom(), match.start(), stop) and not _has_health_object(text, starts, spans.product(), match.start(), stop):
                        scope = "effect"                                                   # D-299(P-4): `멈추` 는 증상·질환이 대상일 때만 효과 결과다(`설사 즉시 멈추는 방법`) — 제품·처방약 곁은 복용 중단이다(`영양제 바로 멈추는 법`)
                    elif scope == "halt":
                        scope = "none"                                                     # 복용 중단 낱말 표에 없는 활용형은 대상을 못 읽으면 모르는 꾸밈이다(옛 규칙 그대로)
                if scope == "effect" and entry in Tables.instant_all and Tables.quiz_start.match(piece) and not _has_health_object(text, starts, spans.plain_symptom(), match.start(), stop):
                    scope = "action"                                                       # D-299(P-12): `풀어보는`(퀴즈·문제를 풀어 보는 일)은 새 즉각·기간 표현 곁에서 행동 순서다
                if scope == "none" and entry in Tables.instant_all:
                    later = _effect_within(text, starts, match.end())                    # D-293: 서술어를 못 읽어도 뒤 세 낱말 안에 효과 낱말이 있고 질환·제품이 대상이면 효과 결과를 꾸미는 것으로 읽는다
                    if later is not None and _has_health_object(text, starts, spans.object(), match.start(), later):
                        scope, stop = "effect", later
                if scope == "effect" and not _has_health_object(text, starts, spans.health(), match.start(), stop):
                    scope = "none"                                                         # 효과 서술어를 꾸미지만 대상이 건강 낱말이 아니다 — 모르는 꾸밈과 같게 둔다(옛 규칙 그대로)
                if scope == "none" and entry == "무조건":
                    diseases = spans.disease()
                    near = any(high <= match.start() <= high + 1 and (match.start() == high or text[high] in BARE_DISEASE_PARTICLES_KO) for _low, high in diseases)
                    if diseases and not near:
                        scope = "far"                                                       # 질환은 있는데 ‘무조건’ 이 질환 낱말 바로 뒤가 아니고 꾸밈도 모른다 — 질환 + 무조건(D-136)을 걸지 않는다(질환 단독)
                found.append((entry, kind, scope))
    return found


def _scoped_forms(text, starts):
    """효과 결과 동사의 단정 종결 활용형 Phrase(`HEALTH_ASSERT_FORMS_KO`)가 찾아진 자리마다 `(Phrase, "form", 범위)` — 건강 낱말이 대상이면 `effect`(센다), 아니면 `none`(D-136)."""
    found, spans = [], None
    for entry, pattern, _strict in Tables.forms:
        for match in pattern.finditer(text):
            spans = _SpanIndex(_health_spans(text, starts)) if spans is None else spans
            found.append((entry, "form", "effect" if _has_health_object(text, starts, spans, match.start(), match.end()) else "none"))
    return found


_EN_RESULT_WORDS = tuple(word for word in HEALTH_EFFECT_EN + HEALTH_MEDICAL_EN if " " not in word)


def _scoped_en(tokens):
    """영어 가벼운 단정(`HEALTH_ASSERT_SOFT_EN`)의 범위 — 뒤 세 낱말 안에 효과·의료 낱말이 있으면 `effect`, 아니면 `none`(영어는 행동 서술어 판정이 없어 옛 규칙 그대로 남긴다). 부정 보호는 `find_en` 과 같다."""
    found = []
    for entry in HEALTH_ASSERT_SOFT_EN:
        want = entry.split()
        for start in range(len(tokens) - len(want) + 1):
            if _token_match(tokens, start, want) and not any(token in NEGATION_TOKENS_EN for token in tokens[max(0, start - 3):start]):
                after = tokens[start + len(want):start + len(want) + 3]
                effect = any(_token_match([token], 0, [word]) for token in after for word in _EN_RESULT_WORDS)
                found.append((entry, "soft", "effect" if effect else "none"))
    return found


def _asks(text):
    """복용·섭취·중단 허용 질문(`먹어도 될까`·`끊어도 되나요` …)의 앞부분 — 마스크를 가린 글에서 찾는다."""
    return tuple(dict.fromkeys(match.group(1) for match in Tables.ask.finditer(text)))


def _ends_a_word(text, starts, end):
    """`되는 방법` 의 방법 낱말이 끝나는 자리 `end` 가 낱말 끝인가 — 글 끝·낱말이 새로 시작하는 자리·다른 글(`SEP`) 앞이거나 조사 한 글자 뒤가 그렇다(`되는 법적 …` 의 ‘법’ 은 아니다)."""
    def boundary(place):
        return place >= len(text) or place in starts or text[place] == SEP
    return boundary(end) or (text[end] in BARE_DISEASE_PARTICLES_KO and boundary(end + 1))


def _quit_claims(text, starts, signals):
    """처방약 복용 중단 단정(D-294) — 처방약 낱말이 있을 때만 계산한다(보통의 글은 비용이 늘지 않는다). ① 복용을 끊는 표현(`HEALTH_QUIT_KO`)이 낫는 말(건강 제품·기기 이름 속이 아닌 효과 낱말)과 함께 있다(`당뇨약 안 먹고 낫는 방법`)
    ② 끊어도 된다는 허용 꼴 + `되는` + 방법 안내 낱말 하나(`고혈압약 끊어도 되는 방법`). 걸린 표현(표의 항목)을 돌려주고(없으면 `()`) 단정(A)으로 센다. 질문 꼴(`끊어도 되나요`)·방법 안내가 없는 중단(`끊는 방법`)·`없이` 는 해당 없다."""
    if not signals.medicines():
        return ()
    found = []
    effects = signals.counted("effect")
    named = any(medicine not in HEALTH_MEDICINE_GENERIC_KO for medicine in signals.medicines())
    if (effects and (signals.counted("symptom") or signals.disease or any(word in HEALTH_QUIT_CURE_KO for word in effects))) or (named and find_ko(text, starts, Tables.quit_outcome)):        # D-302(P-6): 일반 효과 낱말(`비용 줄이는`)만으로는 읽지 않는다 — 증상·질환 낱말이 있거나 건강에서만 쓰는 낫는 말이어야 한다
        found += find_ko(text, starts, Tables.quit_stop)
    for match in Tables.quit_howto.finditer(text):
        if _ends_a_word(text, starts, match.end()):
            found.append(Tables.quit_allow[match.group(1)])
    return tuple(dict.fromkeys(found))


def _quit_stops(text, starts, signals):
    """처방약 낱말이 있는 글에서 복용을 끊는 표현(`HEALTH_QUIT_KO`)이 찾아진 것(D-308) — 낫는 말이 함께 있는지는 따지지 않는다. 없으면 `()`."""
    if not signals.medicines():
        return ()
    return tuple(find_ko(text, starts, Tables.quit_stop))


def _resolve_claims(text, starts, signals):
    """늘 단정 낱말 곁의 결과 서술어(D-298, P-1) — 늘 단정 낱말(`ASSERT_SCOPED_KO` 밖의 단정 낱말: 100퍼센트·백퍼센트·틀림없·장담·보장·보증·단언)이 같은 글에 있고(경고 낱말이 없고) 결과 서술어(`HEALTH_RESOLVE_KO`)의
    **앞 두 낱말부터 서술어 끝까지** 건강 낱말(증상·질환·제품·의료 효능어)이 걸쳐 있을 때만 찾아진 서술어를 돌려준다(없으면 `()`). `통증 100% 해결하는 방법`·`요통 100% 제거` 는 읽고 `체중 앱 오류 100% 해결`(건강 낱말이 세 낱말 앞)·`서버 오류 100% 해결` 은 읽지 않는다."""
    scoped_names = {entry for words in ASSERT_SCOPED_KO.values() for entry in words}
    if signals.warned or not any(entry not in scoped_names for entry in signals.assert_strong):
        return ()
    found, spans = [], None
    for entry, pattern, strict in Tables.resolve:
        for match in pattern.finditer(text):
            if not _reads(text, starts, strict, match):
                continue
            spans = _SpanIndex(_health_spans(text, starts)) if spans is None else spans
            if _has_health_object(text, starts, spans, match.start(), match.end()):
                found.append(entry)
                break
    return tuple(found)


class HealthSignals(NamedTuple):
    symptom: tuple
    disease: tuple
    effect: tuple
    medical: tuple
    product: tuple
    assert_strong: tuple
    assert_effect: tuple
    assert_soft: tuple
    warned: bool
    inside: tuple = ()               # ((칸 이름, 항목), …) — 제품·기기 이름 **안에서만** 찾아진 증상·효과·의료 낱말(D-105, 질환 이름은 해당 없음). 위 여덟 칸의 낱말은 그대로 두고 단계표의 열쇠에서만 뺀다
    scoped: tuple = ()               # ((낱말, 종류 soft·strong, 범위 effect·action·none), …) — 범위 낱말(즉시·바로·확실·무조건 …)이 찾아진 자리마다 그 낱말이 무엇을 꾸미는지(D-130). 위 여덟 칸은 그대로 두고 단정(A) 계산에서만 쓴다
    cure: tuple = ()                 # 중립 꼬리(후·율·판정·사례·기준·통계·여부)가 아닌 자리에 `완치` 가 있으면 ("완치",)(D-137) — 질환 곁의 ‘완치’ 가 단정이 되는 조건
    ask: tuple = ()                  # 복용·섭취·중단 허용 질문의 앞부분(먹어도·끊어도 …)이 찾아진 것(D-131) — 건강 제품과 함께일 때만 효능 주장에 준하는 신호(E)로 센다
    legacy_inside: tuple = ()        # `inside` 와 같되 **옛 제품 표(`d5dcb8c`)만** 이름으로 본 판(질환 칸 없음, D-140) — 옛 중지 바닥의 열쇠가 옛 코드의 의료어·증상·효과 계산 그대로이게 한다(`처방약` 속 `처방` 은 세어진다)
    quit: tuple = ()                 # 처방약 복용 중단 단정으로 찾아진 표현(`HEALTH_QUIT_KO` 의 항목 — 안 먹고·끊어도 …, D-294) — `counted_assert` 가 단정(A)으로 센다. 처방약 낱말이 없거나 낫는 말·`되는 방법` 이 함께 없으면 `()`
    stopping: tuple = ()             # 처방약 낱말이 있는 글에서 찾아진 복용을 끊는 표현(`HEALTH_QUIT_KO` 의 항목 — 끊고·안 먹고 …, D-308) — 낫는 말이 없어도 채운다. `counted_assert` 가 이 표현이 있는 글에서는 즉각·기간 표현의 모르는 서술어도 처방약 곁에서 센다
    resolve: tuple = ()              # 늘 단정 낱말 곁에서 건강 낱말을 대상으로 찾아진 결과 서술어(`HEALTH_RESOLVE_KO` 의 항목 — 해결·치유·제거 …, D-298) — `concept_key` 가 효과(E)로 센다. 늘 단정 낱말이 없거나 건강 대상이 없으면 `()`

    def key(self):
        symptom = bool(self.symptom or self.disease)
        effect = bool(self.effect or self.medical or self.assert_effect)
        target = bool(self.product or self.disease or self.medical)
        strong = bool(self.assert_strong or self.assert_effect) and not self.warned
        asserting = strong or (bool(self.assert_soft) and target and not self.warned)
        return (int(symptom), int(effect), int(target), int(asserting))

    def counted(self, field):
        """칸(`symptom`·`effect`·`medical`)의 낱말 가운데 **따로 센** 것 — 제품·기기 이름 안에서만 찾아진 것은 뺀다(D-105)."""
        return tuple(entry for entry in getattr(self, field) if (field, entry) not in self.inside)

    def legacy_counted(self, field):
        """`counted` 의 옛 코드 판 — 옛 제품 표에 있던 이름 속 조각만 뺀다(D-140). `처방약` 은 옛 제품이 아니라 그 속 `처방`(의료 효능어)도 센다."""
        return tuple(entry for entry in getattr(self, field) if (field, entry) not in self.legacy_inside)

    def legacy_product(self):
        """찾아진 제품 낱말 가운데 **옛 제품 표에 있던 것**(`NEW_PRODUCT_SET` 에 없는 것) — 옛 코드의 제품 칸(D-140)."""
        return tuple(entry for entry in self.product if entry not in NEW_PRODUCT_SET)

    def supplements(self):
        """찾아진 제품 낱말 가운데 영양제 하위 종류(`HEALTH_SUPPLEMENT_*`)."""
        return tuple(entry for entry in self.product if entry in SUPPLEMENT_SET)

    def medicines(self):
        """찾아진 제품 낱말 가운데 처방약 하위 종류(`HEALTH_MEDICINE_*`) — 처방약 곁의 즉시·바로·확실·무조건은 행동 순서여도 단정이다(D-133)."""
        return tuple(entry for entry in self.product if entry in MEDICINE_SET)

    def counted_assert(self):
        """단계표의 단정(A)으로 **실제로 센** 낱말들(D-130) — 늘 단정인 낱말(100퍼센트·보장·즉효 …)·효과 단정 서술, 그리고 범위 낱말 가운데 **효과 결과를 꾸미는 것**(`피로를 즉시 줄이는`).
        처방약이 있으면 행동 순서를 꾸며도 센다(`수면제 바로 끊어도 될까`), 무조건은 질환 곁에서 꾸밈을 모를 때도 센다(`당뇨 무조건 …`). 경고 낱말이 있으면 아무것도 세지 않는다(옛 규칙 그대로).
        알림에 보이는 단정 낱말도 이것이다 — 세지 않은 `영양제 바로 알기` 의 ‘바로’ 는 보이지 않는다."""
        if self.warned:
            return ()
        scoped_names = {entry for words in ASSERT_SCOPED_KO.values() for entry in words}
        words = [entry for entry in self.assert_strong if entry not in scoped_names] + list(self.assert_effect) + [entry for entry in self.assert_soft if entry in ASSERT_ALWAYS_SOFT_KO]
        if self.counted("disease") and self.cure and "완치" in self.counted("medical"):
            words.append("완치")                                                  # 질환 곁의 ‘완치’ 는 효과 동사가 없어도 늘 강한 단정이다(운영자 ③) — 의료 효능어(M)이기도 해서 질환이 없으면 옛 판정(M)대로 둔다
        medicine = bool(self.medicines())
        for entry, kind, scope in self.scoped:
            if scope == "effect" or (medicine and (scope == "dose" or (scope in ("none", "far") and (entry not in Tables.instant_all or self.stopping)))) or (kind == "strong" and entry == "무조건" and scope == "none" and self.counted("disease")):
                words.append(entry)                                                  # D-299: 즉각·기간 표현은 꾸밈을 모르면 처방약 곁에서도 세지 않는다(효과 결과를 꾸밀 때와 복용·중단 동사를 꾸밀 때만) — 쇼핑 문장(`영양제 하루 만에 품절되는 이유`)이 중지가 되지 않게. 단 같은 글에 복용을 끊는 표현이 있으면 옛 낱말(즉시·바로)처럼 센다(D-308 — `항우울제 끊고 하루 만에 건강해진 비결`)
        words += self.quit                                                         # D-294: 처방약 복용 중단 + 낫는 말·`되는 방법`
        return tuple(dict.fromkeys(words))

    def assertion(self):
        return bool(self.counted_assert())

    def concept_key(self):
        """판정 단계표(`safety.HEALTH_MATRIX`)의 열쇠 — (증상 S, 질환 D, 제품 P, 의료 효능어 M, 효과 E, 단정 A) 여섯 값, 각각 0 또는 1(D-105·D-130).
        S·E·M 은 제품·기기 이름 속 조각을 뺀다(질환 이름 속 낱말은 센다). **D 는 처방약 이름 속 질환 낱말(`혈압약`·`당뇨약`·`항암제`)도 센다** — 옛 코드는 이 이름들을 질환 단독(B)으로 읽었고 새 판정이 그보다 낮아지지 않게 한다(D-137). 단정에서는 세지 않는다. **E** 는 효과 낱말·효과 단정 서술에, 건강 제품과 함께인 복용 허용 질문(D-131)과 단정 낱말이 꾸미는 효과 결과 서술어(D-130)를 더한 것이다.
        **A** 는 `counted_assert` — 단정 낱말이 글에 있다는 이유만이 아니라 효과 결과를 꾸미는지로 센다(옛 `key()` 의 단정은 `legacy_concept_key`·`floor_key` 에 그대로 있다)."""
        effect = bool(self.counted("effect") or self.assert_effect or self.resolve or (self.product and self.ask) or (not self.warned and any(scope == "effect" for _entry, _kind, scope in self.scoped)))
        return (int(bool(self.counted("symptom"))), int(bool(self.disease)), int(bool(self.product)), int(bool(self.counted("medical"))), int(effect), int(self.assertion()))

    def legacy_concept_key(self):
        """D-105 시점(`d5dcb8c`)의 열쇠 그대로 — 단정은 `key()` 의 계산(범위를 보지 않음)이다. 옛 중지 바닥(`floor_key`)의 바탕이다."""
        target = bool(self.legacy_product() or self.disease or self.medical)
        strong = bool(self.assert_strong or self.assert_effect) and not self.warned
        asserting = strong or (bool(self.assert_soft) and target and not self.warned)
        return (int(bool(self.legacy_counted("symptom"))), int(bool(self.disease)), int(bool(self.legacy_product())), int(bool(self.legacy_counted("medical"))),
                int(bool(self.legacy_counted("effect") or self.assert_effect)), int(asserting))

    def relaxed_words(self):
        """결정으로 **단정에서 빼는** 범위 낱말(D-131·D-137·D-138): ① 제품이 영양제·처방약 하위 종류뿐이고 낱말이 찾아진 모든 자리가 행동 순서를 꾸밀 때 — 영양제는 복용 행동도 행동 순서이고 처방약이 함께 있으면 복용·중단 행동은 아니어야 한다(soft 도 strong 도)
        ② 제품·질환 없이 의료 낱말이 `치료` 뿐인 글의 가벼운 단정(`치료 바로 시작하기`). 모르는 꾸밈(`none`·`far`)이 하나라도 있으면 빼지 않는다(옛 규칙 그대로)."""
        if self.product:
            if any(entry not in SUPPLEMENT_SET and entry not in MEDICINE_SET for entry in self.product):
                return frozenset()
            allowed, kinds = (("action",) if self.medicines() else ("action", "dose")), ("soft", "strong")
        elif not self.counted("disease") and tuple(self.counted("medical")) == ("치료",):
            allowed, kinds = ("action",), ("soft",)          # 복용·중단 행동(`치료 바로 끊어도 될까`)은 풀지 않는다 — 치료 중단은 위험한 행동(D-138)
        else:
            return frozenset()
        names = {entry for entry, kind, _scope in self.scoped if kind in kinds}
        return frozenset(entry for entry in names if all(scope in allowed for name, kind, scope in self.scoped if name == entry and kind in kinds))

    def relaxed_soft(self):
        """운영자 결정 ①(영양제 + 단순 시간·순서 표현 = 중지 아님)로 **단정에서 빼는** 가벼운 단정 낱말 — 제품 낱말이 영양제 하위 종류뿐이고(처방약·그 밖의 제품이 없다) 그 낱말이 찾아진 **모든 자리가 행동 서술어를 꾸밀 때**만이다.
        모르는 꾸밈(`none`)이나 효과 꾸밈이 하나라도 있으면 빼지 않는다(옛 규칙 그대로)."""
        return frozenset(entry for entry in self.relaxed_words() if entry in ASSERT_SCOPED_KO["soft"])

    def floor_key(self):
        """**옛 중지 바닥**의 열쇠(D-130) — `legacy_concept_key` 와 같되 `relaxed_soft` 의 낱말은 단정에서 뺀다. 이 열쇠가 옛 단계표에서 중지이면 새 판정이 낮아도 중지로 둔다(`safety.LEGACY_STOP_KEYS`)."""
        relaxed = self.relaxed_words()
        soft = [entry for entry in self.assert_soft if entry not in relaxed]
        strong = [entry for entry in self.assert_strong if entry not in relaxed]
        target = bool(self.legacy_product() or self.disease or self.medical)
        asserting = (bool(strong or self.assert_effect) and not self.warned) or (bool(soft) and target and not self.warned)
        return (*self.legacy_concept_key()[:5], int(asserting))


def health_signals(texts):
    folded = [fold(text) for text in texts]
    joined, starts = compact_marked(folded)
    joined = blank_within_words(blank_at_starts(blank(joined, Tables.mask), starts, Tables.mask_start), starts, Tables.mask_word)
    tokens = []
    for one in folded:
        tokens += mask_en(english_tokens(one), HEALTH_MASKS_EN) + [SEP]
    percent = ["100%"] if any("100퍼센트" in one for one in folded) else []
    raw = {
        "symptom": tuple(find_ko(joined, starts, Tables.s_weak) + find_en(tokens, HEALTH_SYMPTOM_EN)),
        "disease": tuple(find_ko(joined, starts, Tables.s_strong) + [word for word, _begin, _end in _bare_diseases(joined, starts)] + find_en(tokens, HEALTH_DISEASE_EN)),
        "effect": tuple(find_ko(joined, starts, Tables.e_gen) + find_en(tokens, HEALTH_EFFECT_EN)),
        "medical": tuple(find_ko(joined, starts, Tables.e_med) + find_en(tokens, HEALTH_MEDICAL_EN)),
        "product": tuple(find_ko(joined, starts, Tables.p) + find_en(tokens, HEALTH_PRODUCT_EN)),
    }
    signals = HealthSignals(
        symptom=raw["symptom"], disease=raw["disease"], effect=raw["effect"], medical=raw["medical"], product=raw["product"],
        assert_strong=tuple(find_assert(joined, starts, Tables.a_strong) + find_en(tokens, HEALTH_ASSERT_EN, negation_guard=True) + percent),
        assert_effect=tuple(find_assert(joined, starts, Tables.a_effect) + find_en(tokens, HEALTH_ASSERT_EFFECT_EN, negation_guard=True)),
        assert_soft=tuple(find_assert(joined, starts, Tables.a_soft) + find_en(tokens, HEALTH_ASSERT_SOFT_EN, negation_guard=True)),
        warned=bool(find_ko(joined, starts, Tables.warn)) or bool(find_en(tokens, HEALTH_WARNING_EN)),
        inside=_pieces_inside_products(joined, starts, tokens, raw), legacy_inside=_pieces_inside_products(joined, starts, tokens, raw, legacy=True), scoped=tuple(dict.fromkeys(_scoped_ko(joined, starts) + _scoped_forms(joined, starts) + _scoped_en(tokens))), cure=_cure_claim(joined) if "완치" in raw["medical"] else (), ask=_asks(joined))
    quitting = _quit_claims(joined, starts, signals)
    stopping = _quit_stops(joined, starts, signals)
    resolving = _resolve_claims(joined, starts, signals)
    if quitting:
        signals = signals._replace(quit=quitting)
    if stopping:
        signals = signals._replace(stopping=stopping)
    return signals._replace(resolve=resolving) if resolving else signals



class SponsorSignals(NamedTuple):
    strong: tuple
    weak_groups: tuple
    marker: tuple
    groups: tuple
    english: tuple
    hashtag: bool

    @property
    def suspected(self):
        return bool(self.strong or self.english or self.hashtag or (self.weak_groups and self.marker))


def sponsor_signals(texts):
    folded = [fold(text) for text in texts]
    joined, starts = compact_marked(folded)
    joined = blank(joined, Tables.sp_mask)
    strong, groups = [], []
    for group in SPONSOR_GROUPS + ("general",):
        found = find_ko(joined, starts, Tables.sp_strong[group])
        if found:
            strong += found
            groups.append(group)
    marker = find_ko(joined, starts, Tables.sp_marker)
    weak = [group for group in SPONSOR_GROUPS if find_ko(joined, starts, Tables.sp_weak[group])]
    tokens = [english_tokens(one) for one in folded]
    english = [word for one in tokens for word in find_en(one, SPONSOR_STRONG_EN)]
    weak_en = [word for one in tokens for word in find_en(one, SPONSOR_WEAK_EN)]
    marker_en = [word for one in tokens for word in find_en(one, SPONSOR_MARKERS_EN)]
    hashtag = any(_HASHTAG.search(one) for one in folded)
    english = english + (weak_en if weak_en and marker_en else [])
    return SponsorSignals(tuple(strong), tuple(weak), tuple(marker), tuple(groups + [group for group in weak if marker and group not in groups]), tuple(english), hashtag)


class ExperienceSignals(NamedTuple):
    genre: tuple
    marked: bool
    phrases: tuple


def experience_signals(texts):
    folded = [fold(text) for text in texts]
    joined, starts = compact_marked(folded)
    joined = blank(joined, Tables.exp_mask)
    phrases = []
    for one in folded:
        phrases += find_en(english_tokens(one), EXPERIENCE_PHRASES_EN)
    return ExperienceSignals(tuple(find_ko(joined, starts, Tables.g_strong)), bool(find_ko(joined, starts, Tables.g_weak) and find_ko(joined, starts, Tables.g_mark)), tuple(phrases))



__all__ = [
    "EXPERIENCE_GENRE_STRONG_KO", "EXPERIENCE_GENRE_WEAK_KO", "EXPERIENCE_MARKERS_KO", "EXPERIENCE_MASKS_KO", "EXPERIENCE_PHRASES_EN", "ExperienceSignals", "GENERAL_WORDS", "GROUP_KO",
    "HEALTH_ASSERT_EFFECT_EN", "HEALTH_ASSERT_EFFECT_KO", "HEALTH_ASSERT_EN", "HEALTH_ASSERT_KO", "HEALTH_ASSERT_SOFT_EN", "HEALTH_ASSERT_SOFT_KO", "HEALTH_DISEASE_EN", "HEALTH_DISEASE_KO",
    "HEALTH_EFFECT_EN", "HEALTH_EFFECT_KO", "HEALTH_MASKS_EN", "HEALTH_MASKS_KO", "HEALTH_MEDICAL_EN", "HEALTH_MEDICAL_KO", "HEALTH_PRODUCT_EN", "HEALTH_PRODUCT_KO", "HEALTH_SYMPTOM_EN",
    "HEALTH_SYMPTOM_KO", "HEALTH_WARNING_EN", "HEALTH_WARNING_KO", "HealthSignals", "INVISIBLE_RANGES", "NEGATION_TOKENS_EN", "SEP", "SPONSOR_GROUPS", "SPONSOR_MARKERS_EN", "SPONSOR_MARKERS_KO",
    "SPONSOR_MASKS_KO", "SPONSOR_STRONG_EN", "SPONSOR_STRONG_KO", "SPONSOR_WEAK_EN", "SPONSOR_WEAK_KO", "SponsorSignals", "compact", "compact_marked", "compile_table", "english_tokens", "experience_signals",
    "fold", "health_signals", "reads_as_one_word", "sponsor_signals",
    "ASSERT_ALWAYS_SOFT_KO", "ASSERT_SCOPED_KO", "HEALTH_ACTION_SCOPE_KO", "HEALTH_ASK_STEMS_KO", "HEALTH_ASK_TAILS_KO", "HEALTH_MEDICINE_EN", "HEALTH_MEDICINE_KO", "HEALTH_RESULT_SCOPE_KO",
    "HEALTH_SUPPLEMENT_EN", "HEALTH_SUPPLEMENT_KO", "MEDICINE_SET", "SCOPE_ADVERB_SUFFIX_KO", "SCOPE_PARTICLES_KO", "SCOPE_SKIP_WORDS_KO", "SUPPLEMENT_SET", "scope_of",
    "BARE_DISEASE_PARTICLES_KO", "CURE_NEUTRAL_KO", "HEALTH_ASSERT_FORMS_KO", "NEW_PRODUCT_KO", "NEW_PRODUCT_SET", "HEALTH_ADVICE_SCOPE_KO", "HEALTH_DISEASE_BARE_KO", "HEALTH_DOSE_SCOPE_KO",
    "HEALTH_INSTANT_PHRASE_KO", "HEALTH_QUIT_ALLOW_KO", "HEALTH_QUIT_HOWTO_KO", "HEALTH_QUIT_KO",
    "BARE_SYMPTOM_REST_KO", "HEALTH_BARE_TAIL_KO", "HEALTH_HALT_SCOPE_KO", "HEALTH_INSTANT_ACTION_KO", "HEALTH_INSTANT_MORE_KO", "HEALTH_INSTANT_NUMBERED_KO", "HEALTH_MASKS_WORD_KO", "HEALTH_QUIT_CURE_KO", "HEALTH_QUIT_OK_KO", "HEALTH_QUIT_OUTCOME_KO", "HEALTH_MEDICINE_GENERIC_KO",
    "HEALTH_RESOLVE_KO", "HEALTH_SYMPTOM_BARE_KO", "HEALTH_SYMPTOM_PREFIX_KO", "HEALTH_SYMPTOM_START_KO",
]
