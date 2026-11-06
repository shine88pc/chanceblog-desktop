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
"""
from __future__ import annotations

import re
import unicodedata
from types import MappingProxyType
from typing import NamedTuple


# ---- 건강 표(초기값 — 전략 원문 확인 전) ----------------------------------------------------------------------------------------------

HEALTH_SYMPTOM_KO = ("피로", "불면", "통증", "붓기", "부종", "두통", "소화", "체중", "집중력", "불안", "스트레스", "숙면", "수면", "활력", "컨디션", "근육통", "어깨 결림", "거북목", "체형", "자세", "속쓰림", "더부룩", "변비",
                     "소화불량", "여드름", "피부 트러블", "어지럼", "안구건조", "입냄새", "무기력", "번아웃", "기억력", "다이어트", "속 편한", "속이 편한", "장 건강", "위 건강", "질환", "질병")        # 39
HEALTH_DISEASE_KO = ("수면 장애", "불면증", "당뇨", "고혈압", "저혈압", "혈압", "혈당", "콜레스테롤", "고지혈증", "지방간", "염증", "알레르기", "아토피", "관절염", "치매", "우울증", "공황장애", "불안장애", "탈모", "비만", "항암",
                     "유방암", "위암", "폐암", "대장암", "간암", "췌장암", "갑상선", "골다공증", "빈혈", "심장병", "협심증", "뇌졸중", "천식", "비염", "식도염", "위염", "장염", "피부염", "통풍 발작", "통풍 환자", "요산",
                     "허리디스크", "목디스크", "디스크 탈출", "추간판", "척추측만", "파킨슨", "암 환자", "암 예방", "암 검진", "암 진단", "암 재발", "암 수술", "암 증상", "암세포", "발암", "면역력", "감염병", "독감", "코로나 후유증",
                     "수술 후유증", "백신 후유증", "역류성", "과민성", "갱년기", "난임", "불임", "ADHD", "자폐", "섭식장애")        # 71
HEALTH_EFFECT_KO = ("회복", "개선", "완화", "예방", "교정", "감량", "증진", "향상", "해소", "강화", "극복", "효과", "효능", "도움", "좋아지", "나아지", "낮추", "낮아지", "높이", "높아지", "줄이", "풀어", "풀리", "늘리",
                    "올리", "키우", "되찾", "없애", "없어지", "사라지", "다스리", "낫는", "돕는", "도와")        # 34
HEALTH_MEDICAL_KO = ("치료", "완치", "처방", "시술", "수술", "투약")        # 6
HEALTH_PRODUCT_KO = ("영양제", "건강기능식품", "건강식품", "보충제", "비타민", "유산균", "프로바이오틱스", "오메가3", "루테인", "콜라겐", "홍삼", "밀크씨슬", "크레아틴", "의료기기", "자세교정기", "다이어트 제품", "다이어트 약",
                     "다이어트 보조제", "다이어트 식품", "운동 처방", "식이요법", "해독 주스", "해독주스", "해독차", "디톡스", "의약품", "한약", "보약", "민간요법", "자연치유", "치료제", "진통제", "수면제", "항생제", "해열제", "스테로이드", "처방약", "항우울제", "혈압약", "당뇨약", "인슐린", "항암제", "피임약", "항응고제", "스타틴")        # 45 (D-133: 처방약 낱말 넷 + D-137: 일곱 더함)
HEALTH_ASSERT_KO = ("확실", "완전", "무조건", "100퍼센트", "백퍼센트", "백프로", "반드시", "틀림없", "장담", "보장", "보증", "단언")        # 12
HEALTH_ASSERT_EFFECT_KO = ("효과 있", "효과가 있", "효과 만점", "효과 보장", "효과 확실", "효과를 본", "낫는다", "낫게", "없어진다", "없어집니다", "사라진다", "사라집니다", "치료된다", "치료됩니다", "치료가 된다", "완치된다")        # 16
HEALTH_ASSERT_SOFT_KO = ("즉시", "즉각", "바로", "단숨에", "순식간", "당장", "즉효")        # 7
HEALTH_MASKS_KO = ("소화기", "소화전", "혈압계", "체중계", "처방전", "자세히", "자세한", "자세하게", "스트레스 테스트", "불확실", "완전 정복", "완전 초보", "완전판", "완전 자동", "완전 무료", "보장성", "보장 범위", "보장금", "보장 내용",
                   "보증금", "보증서", "보증 기간", "보증보험", "디지털 디톡스", "스마트폰 디톡스", "SNS 디톡스", "알림 피로", "피로도", "불안정", "바로잡", "바로가기", "바로미터", "불완전",
                   "보험 보장", "모니터 암", "모니터암", "로봇 암", "로봇암", "암 거치대", "암거치대",
                   "암 프로세서", "암 기반", "암 아키텍처", "암 서버", "암 레벨", "암 클라이밍", "암 모양", "로봇 팔 암")        # 48 (D-140: ARM·게임·장비 문맥 '암' 여덟 더함 — 렌즈 A2 중간 N-1) · 40 (D-134: 보험 '보장' 마스크는 `보험 보장` 하나만 둔다 — 둘째 검증이 `보장 한도·금액·기간·항목·혜택` 이 옛 중지 열 문장을 풀어 버림을 찾아 지웠다(D-138) + D-136: 기기 '암' 여섯 더함 — 한 글자 질환 `암` 단독 읽기가 모니터 암·로봇 암을 건드리지 않게)
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
_RESULT_NOUNS_KO = ("회복", "개선", "완화", "예방", "교정", "감량", "증진", "향상", "해소", "강화", "극복", "해결", "치유", "호전", "치료", "완치")        # 16 — '-하다·-되다·-시키다' 꼴로 효과 결과를 말하는 명사
_RESULT_ENDINGS_KO = ("하", "해", "한", "합", "할", "했", "시키", "되", "돼", "된", "됩", "될", "됐")        # 13 — 어미(‘-시기’ 와 겹치는 ‘시’ 는 뺐다)
HEALTH_RESULT_SCOPE_KO = (
    *(noun + ending for noun in _RESULT_NOUNS_KO for ending in _RESULT_ENDINGS_KO),        # 208
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
INVISIBLE_RANGES = ((0xAD, 0xAD), (0x34F, 0x34F), (0x61C, 0x61C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
                    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFFB), (0xE0000, 0xE0FFF))
_INVISIBLE = re.compile("[" + "".join(chr(low) + "-" + chr(high) for low, high in INVISIBLE_RANGES) + "]")
_PERCENT = re.compile(r"([0-9]+)\s*(?:%|퍼센트|프로)")
HANJA_WORDS = (("治療", "치료"), ("完治", "완치"), ("處方", "처방"), ("協贊", "협찬"), ("廣告", "광고"), ("保障", "보장"))
PARTICLE = "(?:을|를|이|가|은|는|도|만|의|에|로|으로|와|과|에서)?"
_OBLIGATION = re.compile(r"반드시(?=[가-힣0-9a-z]{0,6}?(?:해야|야할|알아야|지켜야|챙겨야|피해야|확인해야|기억해야|필요|하세요|해요|마세요|봐야))")
_NEGATION = re.compile(r"^(?:[가-힣]{0,2})?(?:하?지(?:는|도)?않|되지(?:는|도)?않|못|아니|아닙|불가)")
_QUESTION = re.compile(r"^(?:[가-힣]{0,2})?(?:는지|을까|ㄹ까|나요|는가|을지|느냐|인지|일까|한지|할까|될까|한가|있나|있을)")
_HASHTAG = re.compile(r"(?<![a-z0-9])#(?:ad|sponsored|gifted)(?![a-z0-9])")


def fold(text):
    text = _INVISIBLE.sub("", unicodedata.normalize("NFKC", str(text))).casefold()
    for old, new in HANJA_WORDS:
        text = text.replace(old, new)
    return _PERCENT.sub(lambda match: match.group(1) + "퍼센트", text)


def compact(folded):
    return "".join(char for char in folded if char.isalnum())


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
    return "".join(chars), frozenset(starts)


def phrase_regex(entry):
    return re.compile(PARTICLE.join(re.escape(compact(fold(word))) for word in entry.split()))


def compile_table(entries, *, loose=False):
    """표 → (항목, 정규식, 낱말 경계 규칙을 거나). 띄어쓰기가 든 항목(낱말 사이 경계를 스스로 가진 것)과 `loose` 표는 거짓 = 경계 규칙 없이 예전처럼 찾는다."""
    return tuple((entry, phrase_regex(entry), not loose and len(entry.split()) == 1) for entry in entries)


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


class Tables:
    """compiled once at import"""
    mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(HEALTH_MASKS_KO), key=lambda word: (-len(word), word)) if not word.startswith("암"))
    mask_start = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(HEALTH_MASKS_KO), key=lambda word: (-len(word), word)) if word.startswith("암"))        # 한 글자 질환 `암` 으로 시작하는 마스크는 낱말 처음에서 시작할 때만(D-140) — `유방암 모양` 속 ‘암’ 을 가리지 않게
    sp_mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(SPONSOR_MASKS_KO), key=lambda word: (-len(word), word)))
    exp_mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(EXPERIENCE_MASKS_KO), key=lambda word: (-len(word), word)))
    p_legacy = compile_table(tuple(word for word in HEALTH_PRODUCT_KO if word not in NEW_PRODUCT_SET))
    s_weak, s_strong, e_gen, e_med, p, a_strong, a_effect, a_soft = (compile_table(x) for x in (HEALTH_SYMPTOM_KO, HEALTH_DISEASE_KO, HEALTH_EFFECT_KO, HEALTH_MEDICAL_KO, HEALTH_PRODUCT_KO, HEALTH_ASSERT_KO, HEALTH_ASSERT_EFFECT_KO, HEALTH_ASSERT_SOFT_KO))
    sp_strong = {group: compile_table(words) for group, words in SPONSOR_STRONG_KO.items()}
    sp_weak = {group: compile_table(words) for group, words in SPONSOR_WEAK_KO.items()}
    sp_marker = compile_table(SPONSOR_MARKERS_KO, loose=True)        # 받음 표지는 어미가 띄어 쓰이는 일이 흔하다(제공 받았다·작성 했다) — 경계 규칙 없이 예전처럼 찾는다
    g_strong, g_weak, g_mark = compile_table(EXPERIENCE_GENRE_STRONG_KO), compile_table(EXPERIENCE_GENRE_WEAK_KO), compile_table(EXPERIENCE_MARKERS_KO)
    warn = compile_table(HEALTH_WARNING_KO)
    scoped = {kind: compile_table(words) for kind, words in ASSERT_SCOPED_KO.items()}
    result_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_RESULT_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    action_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_ACTION_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    forms = compile_table(HEALTH_ASSERT_FORMS_KO, loose=True)
    dose_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_DOSE_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    advice_start = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(HEALTH_ADVICE_SCOPE_KO), key=lambda word: (-len(word), word))) + ")")
    adverb_suffix = re.compile("^(?:" + "|".join(re.escape(compact(fold(word))) for word in sorted(dict.fromkeys(SCOPE_ADVERB_SUFFIX_KO), key=lambda word: (-len(word), word))) + ")")
    ask = re.compile("(" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_ASK_STEMS_KO) + ")(?:" + "|".join(re.escape(compact(fold(word))) for word in HEALTH_ASK_TAILS_KO) + ")")


def blank(text, patterns):
    for pattern in patterns:
        text = pattern.sub(lambda match: SEP * len(match.group(0)), text)
    return text


def blank_at_starts(text, starts, patterns):
    """`blank` 와 같되 **낱말 처음에서 시작하는 일치만** 가린다(D-140) — `암 모양` 마스크가 `유방암 모양` 속 ‘암’ 을 가리지 않는다. 가린 길이는 그대로라 `starts` 가 맞는다."""
    for pattern in patterns:
        text = pattern.sub(lambda match: SEP * len(match.group(0)) if match.start() in starts else match.group(0), text)
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


def find_ko(text, starts, table):
    return [entry for entry, pattern, strict in table if any(not strict or reads_as_one_word(text, starts, match.start(), match.end()) for match in pattern.finditer(text))]


def find_assert(text, starts, table):
    found = []
    for entry, pattern, strict in table:
        for match in pattern.finditer(text):
            if strict and not reads_as_one_word(text, starts, match.start(), match.end()):
                continue
            if entry == "반드시" and _OBLIGATION.match(text, match.start()):
                continue
            tail = text[match.end():match.end() + 8]
            if _NEGATION.match(tail) or _QUESTION.match(tail):
                continue
            found.append(entry)
            break
    return found


def _spans_ko(text, starts, table):
    """`find_ko` 와 같은 일치 규칙(낱말 경계 포함)으로 찾되 항목마다 **찾아진 자리** `[(시작, 끝)]` 를 돌려준다 — 찾지 못한 항목은 싣지 않는다."""
    found = {}
    for entry, pattern, strict in table:
        places = [(match.start(), match.end()) for match in pattern.finditer(text) if not strict or reads_as_one_word(text, starts, match.start(), match.end())]
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


def _pieces_after(text, starts, end):
    """단정 낱말이 끝나는 자리 `end` 뒤의 낱말 조각들 `(시작, 끝, 조각)` — 같은 글 안(`SEP` 앞)에서 띄어쓴 낱말 단위로 앞에서부터. 낱말에 붙여 쓴 어미(`확실히` 의 ‘히’)는 떼고, 남는 것이 없으면 건너뛴다."""
    stop = text.find(SEP, end)
    stop = len(text) if stop < 0 else stop
    cuts = [end, *sorted(place for place in starts if end < place < stop), stop]
    pieces = [(cuts[number], cuts[number + 1], text[cuts[number]:cuts[number + 1]]) for number in range(len(cuts) - 1)]
    if pieces and end not in starts:
        pieces[0] = (pieces[0][0], pieces[0][1], Tables.adverb_suffix.sub("", pieces[0][2], count=1))
    return [piece for piece in pieces if piece[2]]


def _scope_and_end(text, starts, end):
    """`scope_of` 와 같되 꾸밈을 읽은 서술어 낱말이 끝나는 자리도 함께 돌려준다 — (범위, 자리)."""
    for number, (_begin, stop, piece) in enumerate(_pieces_after(text, starts, end)[:3]):
        if Tables.advice_start.match(piece):
            return "action", stop
        if Tables.result_start.match(piece):
            return "effect", stop
        if Tables.dose_start.match(piece):
            return "dose", stop
        if Tables.action_start.match(piece):
            return "action", stop
        if number >= 2 or not (piece in SCOPE_SKIP_WORDS_KO or piece.endswith(SCOPE_PARTICLES_KO)):
            break
    return "none", end


def scope_of(text, starts, end):
    """단정 낱말(자리가 `end` 에서 끝남)이 **무엇을 꾸미는가**(D-130) — `effect`(효과 결과 서술어: 줄인다·없앤다·교정한다·치료된다 …) / `action`(행동 서술어: 확인한다·알기·먹는다·기록한다 …) / `none`(모르겠다 — 옛 규칙 그대로).
    낱말 바로 뒤 낱말을 읽고, 그 낱말이 목적어 꼴(조사 `을·를·에·로 …` 로 끝남)이거나 건너뛰는 부사(`SCOPE_SKIP_WORDS_KO` — 같이·함께·꼭·크게 …)이면 건너뛰어 그다음 낱말을 읽는다(`즉시 피로를 없애는`·`바로 같이 먹어도`). 건너뛰는 것은 최대 두 낱말이고
    세 낱말 안에서 서술어를 못 찾으면 `none` 이다(멀리 있는 서술어를 억지로 잇지 않는다)."""
    return _scope_and_end(text, starts, end)[0]


def _bare_diseases(text, starts):
    """한 글자 질환(`HEALTH_DISEASE_BARE_KO`)이 **낱말 단독이거나 조사만 붙은 꼴**로 찾아진 자리 `[(낱말, 시작, 끝)]` (D-136, D-58 경계 규칙의 한 글자 질환 몫) — `암호`·`암기`·`암벽` 속의 ‘암’ 은 읽지 않는다."""
    found = []
    for word in HEALTH_DISEASE_BARE_KO:
        piece = compact(fold(word))
        for match in re.finditer(re.escape(piece), text):
            if match.start() not in starts:
                continue
            stop = text.find(SEP, match.end())
            stop = len(text) if stop < 0 else stop
            ends = [place for place in starts if match.end() <= place < stop]
            rest = text[match.end():min(ends) if ends else stop]
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
    word = max((place for place in starts if place <= begin), default=0)
    lower = text.rfind(SEP, 0, word) + 1
    before = sorted(place for place in starts if lower <= place < word)
    window = max(lower, before[-2]) if len(before) >= 2 else lower
    return any(low < stop and high > window for low, high in spans)


def _scoped_ko(text, starts):
    """범위 낱말(`ASSERT_SCOPED_KO`)이 낱말 경계·의무 꼴·부정·의문 꼬리 규칙(`find_assert` 와 같음)을 지나 찾아진 **자리마다** `(낱말, 종류, 범위)`."""
    found, spans, diseases = [], None, None
    for kind, table in Tables.scoped.items():
        for entry, pattern, strict in table:
            for match in pattern.finditer(text):
                if strict and not reads_as_one_word(text, starts, match.start(), match.end()):
                    continue
                if entry == "반드시" and _OBLIGATION.match(text, match.start()):
                    continue
                tail = text[match.end():match.end() + 8]
                if _NEGATION.match(tail) or _QUESTION.match(tail):
                    continue
                scope, stop = _scope_and_end(text, starts, match.end())
                if scope == "effect":
                    spans = _health_spans(text, starts) if spans is None else spans
                    if not _has_health_object(text, starts, spans, match.start(), stop):
                        scope = "none"                                                     # 효과 서술어를 꾸미지만 대상이 건강 낱말이 아니다 — 모르는 꾸밈과 같게 둔다(옛 규칙 그대로)
                if scope == "none" and entry == "무조건":
                    diseases = _disease_spans(text, starts) if diseases is None else diseases
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
            spans = _health_spans(text, starts) if spans is None else spans
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
            if scope == "effect" or (medicine and scope in ("dose", "none", "far")) or (kind == "strong" and entry == "무조건" and scope == "none" and self.counted("disease")):
                words.append(entry)
        return tuple(dict.fromkeys(words))

    def assertion(self):
        return bool(self.counted_assert())

    def concept_key(self):
        """판정 단계표(`safety.HEALTH_MATRIX`)의 열쇠 — (증상 S, 질환 D, 제품 P, 의료 효능어 M, 효과 E, 단정 A) 여섯 값, 각각 0 또는 1(D-105·D-130).
        S·E·M 은 제품·기기 이름 속 조각을 뺀다(질환 이름 속 낱말은 센다). **D 는 처방약 이름 속 질환 낱말(`혈압약`·`당뇨약`·`항암제`)도 센다** — 옛 코드는 이 이름들을 질환 단독(B)으로 읽었고 새 판정이 그보다 낮아지지 않게 한다(D-137). 단정에서는 세지 않는다. **E** 는 효과 낱말·효과 단정 서술에, 건강 제품과 함께인 복용 허용 질문(D-131)과 단정 낱말이 꾸미는 효과 결과 서술어(D-130)를 더한 것이다.
        **A** 는 `counted_assert` — 단정 낱말이 글에 있다는 이유만이 아니라 효과 결과를 꾸미는지로 센다(옛 `key()` 의 단정은 `legacy_concept_key`·`floor_key` 에 그대로 있다)."""
        effect = bool(self.counted("effect") or self.assert_effect or (self.product and self.ask) or (not self.warned and any(scope == "effect" for _entry, _kind, scope in self.scoped)))
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
    joined = blank_at_starts(blank(joined, Tables.mask), starts, Tables.mask_start)
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
    return HealthSignals(
        symptom=raw["symptom"], disease=raw["disease"], effect=raw["effect"], medical=raw["medical"], product=raw["product"],
        assert_strong=tuple(find_assert(joined, starts, Tables.a_strong) + find_en(tokens, HEALTH_ASSERT_EN, negation_guard=True) + percent),
        assert_effect=tuple(find_assert(joined, starts, Tables.a_effect) + find_en(tokens, HEALTH_ASSERT_EFFECT_EN, negation_guard=True)),
        assert_soft=tuple(find_assert(joined, starts, Tables.a_soft) + find_en(tokens, HEALTH_ASSERT_SOFT_EN, negation_guard=True)),
        warned=bool(find_ko(joined, starts, Tables.warn)) or bool(find_en(tokens, HEALTH_WARNING_EN)),
        inside=_pieces_inside_products(joined, starts, tokens, raw), legacy_inside=_pieces_inside_products(joined, starts, tokens, raw, legacy=True), scoped=tuple(dict.fromkeys(_scoped_ko(joined, starts) + _scoped_forms(joined, starts) + _scoped_en(tokens))), cure=_cure_claim(joined) if "완치" in raw["medical"] else (), ask=_asks(joined))



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
]
