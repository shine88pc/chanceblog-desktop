"""개념군 표 · 일치 도구 · 신호 계산 — 건강·협찬·경험의 **신호**를 글에서 계산한다(P2b 보완, D-50~D-52 — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

이 모듈은 상태(일반 생활정보 / 건강 정보 확인 필요 / 의료·효과 단정 위험)·표시·알림을 정하지 않는다 — 그것은 `safety.py` 의 일이다. 여기서는 표(낱말·문구)와 일치 규칙으로 신호를 센다.

**표는 모두 초기값 — 전략 원문 확인 전이다.** 전략 원문의 건강·협찬 표기 규칙 표가 이 PC 에 없어서 운영자 요청서의 개념군 낱말을 시작 목록으로 두고 상식으로 넓혔다. 원문에 맞춰 고칠 때는 이 파일의 표 한 곳만 고치고
시험(`test_topics_concepts` 의 값 못박기)을 의식적으로 함께 고친다. 표 이름: 건강 `HEALTH_SYMPTOM_KO`·`HEALTH_DISEASE_KO`·`HEALTH_EFFECT_KO`·`HEALTH_MEDICAL_KO`·`HEALTH_PRODUCT_KO`·`HEALTH_ASSERT_KO`·
`HEALTH_ASSERT_EFFECT_KO`·`HEALTH_ASSERT_SOFT_KO`·`HEALTH_MASKS_KO`·`HEALTH_WARNING_KO`(영어는 `_EN`) / 협찬 `SPONSOR_STRONG_KO`·`SPONSOR_WEAK_KO`·`SPONSOR_MARKERS_KO`·`SPONSOR_MASKS_KO`(영어는 `_EN`) /
경험 `EXPERIENCE_GENRE_STRONG_KO`·`EXPERIENCE_GENRE_WEAK_KO`·`EXPERIENCE_MARKERS_KO`·`EXPERIENCE_MASKS_KO`·`EXPERIENCE_PHRASES_EN` / 일반 낱말 금지 목록 `GENERAL_WORDS`.

판단 원칙 둘: ① 그것만으로 뜻이 한쪽인 말(질환명·건강 제품·의료 효능어·협찬 전용어·경험 장르 강한 말·영어 문구)만 **단독 신호 표**에 둔다. ② 일상어와 겹치는 말(일상 증상·일반 효과어·단정 낱말·협찬 약한 말·'후기'·'리뷰')은
**약한 표**에 두고 다른 개념군과 함께 있을 때만 쓴다. **일반 낱말(비교·모델·추천·구매·가격·순위·제품·브랜드·스펙·광고 …)은 어느 표에도 단독 신호로 넣지 않는다**(`GENERAL_WORDS` 와 시험이 지킨다).
일치 규칙: 정규화(`fold` — 보이지 않는 글자 지움·NFKC·소문자·한자 낱말·퍼센트) → 글자·숫자만 이어 붙임(`compact_marked` — 띄어쓰기·기호 무시, 낱말이 시작하는 자리는 기억) → 마스크 낱말을 가려 놓고 → 표 항목(조사 하나가 선택적으로 끼는 정규식)을 찾는다.
낱말 경계 규칙(D-58): 띄어쓰기 없는 표 항목이 **띄어쓴 낱말들에 걸쳐** 찾아지면 `reads_as_one_word` 가 거른다 — 첫 조각이 낱말 처음부터 시작하고 뒤 조각이 한글 한 글자가 아닐 때만 읽는다(그래서 두 글자 항목은 낱말 안에서만 읽힌다. `설치 매뉴얼` 의 ‘치매’ 같은
우연한 일치를 막음). 띄어쓰기가 든 항목과 받음 표지(`SPONSOR_MARKERS_KO`)는 예전처럼 찾는다.
영어는 소문자 낱말 열(`english_tokens`)에서 **문구(낱말 열)** 로 찾는다 — 하이픈 낱말이나 두 낱말 문구를 낱말 하나와 견주던 옛 규칙의 죽은 항목(`hands-on`·`my experience`)이 다시 생기지 않게 시험이 표 항목마다 도달을 확인한다.
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
                     "다이어트 보조제", "다이어트 식품", "운동 처방", "식이요법", "해독 주스", "해독주스", "해독차", "디톡스", "의약품", "한약", "보약", "민간요법", "자연치유", "치료제", "진통제", "수면제", "항생제")        # 34
HEALTH_ASSERT_KO = ("확실", "완전", "무조건", "100퍼센트", "백퍼센트", "백프로", "반드시", "틀림없", "장담", "보장", "보증", "단언")        # 12
HEALTH_ASSERT_EFFECT_KO = ("효과 있", "효과가 있", "효과 만점", "효과 보장", "효과 확실", "효과를 본", "낫는다", "낫게", "없어진다", "없어집니다", "사라진다", "사라집니다", "치료된다", "치료됩니다", "치료가 된다", "완치된다")        # 16
HEALTH_ASSERT_SOFT_KO = ("즉시", "즉각", "바로", "단숨에", "순식간", "당장", "즉효")        # 7
HEALTH_MASKS_KO = ("소화기", "소화전", "혈압계", "체중계", "처방전", "자세히", "자세한", "자세하게", "스트레스 테스트", "불확실", "완전 정복", "완전 초보", "완전판", "완전 자동", "완전 무료", "보장성", "보장 범위", "보장금", "보장 내용",
                   "보증금", "보증서", "보증 기간", "보증보험", "디지털 디톡스", "스마트폰 디톡스", "SNS 디톡스", "알림 피로", "피로도", "불안정", "바로잡", "바로가기", "바로미터", "불완전")        # 33
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
    mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(HEALTH_MASKS_KO), key=lambda word: (-len(word), word)))
    sp_mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(SPONSOR_MASKS_KO), key=lambda word: (-len(word), word)))
    exp_mask = tuple(phrase_regex(word) for word in sorted(dict.fromkeys(EXPERIENCE_MASKS_KO), key=lambda word: (-len(word), word)))
    s_weak, s_strong, e_gen, e_med, p, a_strong, a_effect, a_soft = (compile_table(x) for x in (HEALTH_SYMPTOM_KO, HEALTH_DISEASE_KO, HEALTH_EFFECT_KO, HEALTH_MEDICAL_KO, HEALTH_PRODUCT_KO, HEALTH_ASSERT_KO, HEALTH_ASSERT_EFFECT_KO, HEALTH_ASSERT_SOFT_KO))
    sp_strong = {group: compile_table(words) for group, words in SPONSOR_STRONG_KO.items()}
    sp_weak = {group: compile_table(words) for group, words in SPONSOR_WEAK_KO.items()}
    sp_marker = compile_table(SPONSOR_MARKERS_KO, loose=True)        # 받음 표지는 어미가 띄어 쓰이는 일이 흔하다(제공 받았다·작성 했다) — 경계 규칙 없이 예전처럼 찾는다
    g_strong, g_weak, g_mark = compile_table(EXPERIENCE_GENRE_STRONG_KO), compile_table(EXPERIENCE_GENRE_WEAK_KO), compile_table(EXPERIENCE_MARKERS_KO)
    warn = compile_table(HEALTH_WARNING_KO)


def blank(text, patterns):
    for pattern in patterns:
        text = pattern.sub(lambda match: SEP * len(match.group(0)), text)
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

    def key(self):
        symptom = bool(self.symptom or self.disease)
        effect = bool(self.effect or self.medical or self.assert_effect)
        target = bool(self.product or self.disease or self.medical)
        strong = bool(self.assert_strong or self.assert_effect) and not self.warned
        asserting = strong or (bool(self.assert_soft) and target and not self.warned)
        return (int(symptom), int(effect), int(target), int(asserting))


def health_signals(texts):
    folded = [fold(text) for text in texts]
    joined, starts = compact_marked(folded)
    joined = blank(joined, Tables.mask)
    tokens = []
    for one in folded:
        tokens += mask_en(english_tokens(one), HEALTH_MASKS_EN) + [SEP]
    percent = ["100%"] if any("100퍼센트" in one for one in folded) else []
    return HealthSignals(
        symptom=tuple(find_ko(joined, starts, Tables.s_weak) + find_en(tokens, HEALTH_SYMPTOM_EN)),
        disease=tuple(find_ko(joined, starts, Tables.s_strong) + find_en(tokens, HEALTH_DISEASE_EN)),
        effect=tuple(find_ko(joined, starts, Tables.e_gen) + find_en(tokens, HEALTH_EFFECT_EN)),
        medical=tuple(find_ko(joined, starts, Tables.e_med) + find_en(tokens, HEALTH_MEDICAL_EN)),
        product=tuple(find_ko(joined, starts, Tables.p) + find_en(tokens, HEALTH_PRODUCT_EN)),
        assert_strong=tuple(find_assert(joined, starts, Tables.a_strong) + find_en(tokens, HEALTH_ASSERT_EN, negation_guard=True) + percent),
        assert_effect=tuple(find_assert(joined, starts, Tables.a_effect) + find_en(tokens, HEALTH_ASSERT_EFFECT_EN, negation_guard=True)),
        assert_soft=tuple(find_assert(joined, starts, Tables.a_soft) + find_en(tokens, HEALTH_ASSERT_SOFT_EN, negation_guard=True)),
        warned=bool(find_ko(joined, starts, Tables.warn)) or bool(find_en(tokens, HEALTH_WARNING_EN)))



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
]
