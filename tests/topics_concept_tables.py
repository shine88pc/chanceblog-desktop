"""안전 표시 개념군 표의 **값 못박기 자료**(시험 도우미 — 시험 모듈이 아니다). 표는 초기값 — 전략 원문 확인 전이다. `concepts.py` 의 표를 고치면 이 자료도 의식적으로 함께 고친다.
운영자 요청서의 낱말을 시작 목록으로 두고 넓힌 값이며 모두 지어낸 일반 낱말이다(실제 씨앗·블로그 글 제목이 아니다).
"""

TABLES = {
    # EXPERIENCE_GENRE_STRONG_KO — 7
    'EXPERIENCE_GENRE_STRONG_KO': ('사용기', '체험기', '사용후기', '구매후기', '방문후기', '체험후기', '언박싱'),
    # EXPERIENCE_GENRE_WEAK_KO — 2
    'EXPERIENCE_GENRE_WEAK_KO': ('후기', '리뷰'),
    # EXPERIENCE_MARKERS_KO — 11
    'EXPERIENCE_MARKERS_KO': ('직접', '솔직', '실사용', '내돈내산', '내 돈 주고', '장기', '한 달', '개월', '일주일', '몇 주', '몇달'),
    # EXPERIENCE_MASKS_KO — 13
    'EXPERIENCE_MASKS_KO': ('사용기간', '사용기록', '사용기준', '사용기한', '체험기간', '체험기한', '코드 리뷰', '코드리뷰', '리뷰어', '후기 쓰는', '후기 작성법', '리뷰 보는', '후기 믿'),
    # EXPERIENCE_PHRASES_EN — 19
    'EXPERIENCE_PHRASES_EN': ('i used', 'i have used', 'i tried', 'i have tried', 'my experience', 'after using', 'when i visited', 'i visited', 'i have visited', 'i bought', 'i have bought', 'i tested', 'i have tested', 'in my own use', 'we used', 'we tried', 'we tested', 'we visited', 'we bought'),
    # GENERAL_WORDS — 57
    'GENERAL_WORDS': ('비교', '모델', '추천', '구매', '구입', '가격', '최저가', '순위', '가성비', '제품', '브랜드', '신제품', '스펙', '후기', '리뷰', '광고', '방법', '정리', '관리', '설정', '설치', '성능', '비용', '가이드', '기준', '선택', '장점', '단점', '자동화', '도구', '서비스', '협업', '이벤트', 'compare', 'comparison', 'model', 'review', 'reviews', 'best', 'vs', 'buy', 'buying', 'price', 'prices', 'brand', 'specs', 'unboxing', 'ad', 'ads', 'advertisement', 'paid', 'treat', 'supplement', 'symptom', 'symptoms', 'disease', 'dosage'),
    # HEALTH_ASSERT_EFFECT_EN — 10
    'HEALTH_ASSERT_EFFECT_EN': ('will cure', 'guaranteed results', 'guaranteed to work', 'guaranteed to cure', 'guaranteed relief', 'instant relief', 'disappears', 'vanish*', 'gone forever', 'works instantly'),
    # HEALTH_ASSERT_EFFECT_KO — 19 (의도적 갱신 D-292: 마지막 셋 — `해결 보장`·`치유 보장`·`호전 보장`)
    'HEALTH_ASSERT_EFFECT_KO': ('효과 있', '효과가 있', '효과 만점', '효과 보장', '효과 확실', '효과를 본', '낫는다', '낫게', '없어진다', '없어집니다', '사라진다', '사라집니다', '치료된다', '치료됩니다', '치료가 된다', '완치된다', '해결 보장', '치유 보장', '호전 보장'),
    # HEALTH_ASSERT_EN — 10
    'HEALTH_ASSERT_EN': ('guaranteed', 'guarantee', 'guarantees', 'completely', 'miracle', 'permanently', 'surefire', 'foolproof', 'always works', 'never fails'),
    # HEALTH_ASSERT_KO — 12
    'HEALTH_ASSERT_KO': ('확실', '완전', '무조건', '100퍼센트', '백퍼센트', '백프로', '반드시', '틀림없', '장담', '보장', '보증', '단언'),
    # HEALTH_ASSERT_SOFT_EN — 5
    'HEALTH_ASSERT_SOFT_EN': ('instantly', 'immediately', 'overnight', 'in minutes', 'right away'),
    # HEALTH_ASSERT_SOFT_KO — 7
    'HEALTH_ASSERT_SOFT_KO': ('즉시', '즉각', '바로', '단숨에', '순식간', '당장', '즉효'),
    # HEALTH_DISEASE_EN — 26
    'HEALTH_DISEASE_EN': ('diabetes', 'diabetic', 'cancer', 'cholesterol', 'depression', 'obesity', 'arthritis', 'alzheimer*', 'dementia', 'hypertension', 'asthma', 'allergy', 'allergies', 'eczema', 'blood pressure', 'blood sugar', 'immunity', 'immune system', 'inflammation', 'adhd', 'autism', 'osteoporosis', 'migraine', 'insomnia', 'thyroid', 'anemia'),
    # HEALTH_DISEASE_KO — 76 (의도적 갱신 D-291: 마지막 다섯 — 손목터널증후군·오십견·두드러기·구내염·치주염)
    'HEALTH_DISEASE_KO': ('수면 장애', '불면증', '당뇨', '고혈압', '저혈압', '혈압', '혈당', '콜레스테롤', '고지혈증', '지방간', '염증', '알레르기', '아토피', '관절염', '치매', '우울증', '공황장애', '불안장애', '탈모', '비만', '항암', '유방암', '위암', '폐암', '대장암', '간암', '췌장암', '갑상선', '골다공증', '빈혈', '심장병', '협심증', '뇌졸중', '천식', '비염', '식도염', '위염', '장염', '피부염', '통풍 발작', '통풍 환자', '요산', '허리디스크', '목디스크', '디스크 탈출', '추간판', '척추측만', '파킨슨', '암 환자', '암 예방', '암 검진', '암 진단', '암 재발', '암 수술', '암 증상', '암세포', '발암', '면역력', '감염병', '독감', '코로나 후유증', '수술 후유증', '백신 후유증', '역류성', '과민성', '갱년기', '난임', '불임', 'ADHD', '자폐', '섭식장애', '손목터널증후군', '오십견', '두드러기', '구내염', '치주염'),
    # HEALTH_EFFECT_EN — 13
    'HEALTH_EFFECT_EN': ('relief', 'relieve*', 'recover*', 'recovery', 'improv*', 'prevent*', 'reduc*', 'boost*', 'ease', 'eliminat*', 'lower*', 'increas*', 'fix'),
    # HEALTH_EFFECT_KO — 34
    'HEALTH_EFFECT_KO': ('회복', '개선', '완화', '예방', '교정', '감량', '증진', '향상', '해소', '강화', '극복', '효과', '효능', '도움', '좋아지', '나아지', '낮추', '낮아지', '높이', '높아지', '줄이', '풀어', '풀리', '늘리', '올리', '키우', '되찾', '없애', '없어지', '사라지', '다스리', '낫는', '돕는', '도와'),
    # HEALTH_MASKS_EN — 11
    'HEALTH_MASKS_EN': ('economic depression', 'great depression', 'pain point*', 'treat yourself', 'supplement your', 'diet of', 'blood pressure monitor*', 'blood sugar monitor*', 'stress test*', 'supplements to the', 'weight of'),
    # HEALTH_MASKS_KO — 64 (의도적 갱신 D-307, WP-B5 3차 수정: 한 낱말 마스크 둘 — 한눈에·첫눈에 — 을 지웠다. 마스크가 글을 갈라 기준이 중지로 읽던 글을 낮췄다) · 66 (의도적 갱신 D-298, WP-B5 수정 라운드: D-291 마스크 다섯(빨리감기·되감기·경기침체·이명박·건설사)을 지우고 열다섯을 더함 — 줄 감기·태엽 감기·붕대 감기·전선 감기·케이블 감기·목도리 감기·목에 감기는·손에 감기는·배추 저림·건조한 눈빛·건조한 눈길·건조한 눈매·건조한 눈동자·건조한 눈썹·첫눈에) · 56 (D-291) · 48 (D-140: ARM·게임·장비 문맥 암 여덟 더함)
    'HEALTH_MASKS_KO': ('소화기', '소화전', '혈압계', '체중계', '처방전', '자세히', '자세한', '자세하게', '스트레스 테스트', '불확실', '완전 정복', '완전 초보', '완전판', '완전 자동', '완전 무료', '보장성', '보장 범위', '보장금', '보장 내용', '보증금', '보증서', '보증 기간', '보증보험', '디지털 디톡스', '스마트폰 디톡스', 'SNS 디톡스', '알림 피로', '피로도', '불안정', '바로잡', '바로가기', '바로미터', '불완전', '보험 보장', '모니터 암', '모니터암', '로봇 암', '로봇암', '암 거치대', '암거치대', '암 프로세서', '암 기반', '암 아키텍처', '암 서버', '암 레벨', '암 클라이밍', '암 모양', '로봇 팔 암', '머리 감기', '착 감기', '줄 감기', '태엽 감기', '붕대 감기', '전선 감기', '케이블 감기', '목도리 감기', '목에 감기는', '손에 감기는', '배추 저림', '건조한 눈빛', '건조한 눈길', '건조한 눈매', '건조한 눈동자', '건조한 눈썹'),
    # HEALTH_MEDICAL_EN — 11
    'HEALTH_MEDICAL_EN': ('cure*', 'treatment*', 'therapy', 'heal', 'heals', 'healed', 'healing', 'remedy', 'remedies', 'prescription*', 'prescribe*'),
    # HEALTH_MEDICAL_KO — 6
    'HEALTH_MEDICAL_KO': ('치료', '완치', '처방', '시술', '수술', '투약'),
    # HEALTH_PRODUCT_EN — 22
    'HEALTH_PRODUCT_EN': ('supplements', 'supplement for', 'dietary supplement*', 'vitamin', 'vitamins', 'probiotic*', 'multivitamin*', 'medication', 'medications', 'medicine', 'medicines', 'diet pill*', 'weight loss pill*', 'fat burner*', 'detox tea', 'detox juice', 'detox cleanse', 'posture corrector*', 'medical device*', 'collagen', 'melatonin', 'creatine'),
    # HEALTH_PRODUCT_KO — 45 (D-137: 처방약 낱말 일곱 더함) (D-133: 처방약 낱말 넷을 더했다 — 시험을 의식적으로 함께 고침)
    'HEALTH_PRODUCT_KO': ('영양제', '건강기능식품', '건강식품', '보충제', '비타민', '유산균', '프로바이오틱스', '오메가3', '루테인', '콜라겐', '홍삼', '밀크씨슬', '크레아틴', '의료기기', '자세교정기', '다이어트 제품', '다이어트 약', '다이어트 보조제', '다이어트 식품', '운동 처방', '식이요법', '해독 주스', '해독주스', '해독차', '디톡스', '의약품', '한약', '보약', '민간요법', '자연치유', '치료제', '진통제', '수면제', '항생제', '해열제', '스테로이드', '처방약', '항우울제', '혈압약', '당뇨약', '인슐린', '항암제', '피임약', '항응고제', '스타틴'),
    # HEALTH_SYMPTOM_EN — 15
    'HEALTH_SYMPTOM_EN': ('fatigue', 'stress', 'anxiety', 'pain', 'headache', 'sleep', 'weight loss', 'weight', 'diet', 'burnout', 'bloating', 'acne', 'constipation', 'posture', 'focus'),
    # HEALTH_SYMPTOM_KO — 59 (의도적 갱신 D-298, WP-B5 수정 라운드: 마지막 일곱 — 복통·인후통·치통·관절통·콧물·무좀·습진) · 52 (D-291: 마지막 열셋 — 요통·몸살·감기·눈 건강·건조한 눈·시력·설사·기침·가려움·저림·생리통·코골이·이명)
    'HEALTH_SYMPTOM_KO': ('피로', '불면', '통증', '붓기', '부종', '두통', '소화', '체중', '집중력', '불안', '스트레스', '숙면', '수면', '활력', '컨디션', '근육통', '어깨 결림', '거북목', '체형', '자세', '속쓰림', '더부룩', '변비', '소화불량', '여드름', '피부 트러블', '어지럼', '안구건조', '입냄새', '무기력', '번아웃', '기억력', '다이어트', '속 편한', '속이 편한', '장 건강', '위 건강', '질환', '질병', '요통', '몸살', '감기', '눈 건강', '건조한 눈', '시력', '설사', '기침', '가려움', '저림', '생리통', '코골이', '이명', '복통', '인후통', '치통', '관절통', '콧물', '무좀', '습진'),
    # HEALTH_WARNING_EN — 11
    'HEALTH_WARNING_EN': ('myth', 'myths', 'scam', 'scams', 'fake', 'misleading', 'fraud', 'debunk*', 'red flags', 'too good to be true', 'exaggerat*'),
    # HEALTH_WARNING_KO — 19
    'HEALTH_WARNING_KO': ('과장', '허위', '거짓', '사기', '속지', '속는', '속아', '오해', '함정', '낚시', '믿어도', '믿을수', '진짜일까', '사실일까', '진실', '근거없', '팩트체크', '구별', '구분하는'),
    # NEGATION_TOKENS_EN — 5
    'NEGATION_TOKENS_EN': ('no', 'not', 'never', 'without', 'cannot'),
    # SPONSOR_MARKERS_EN — 8
    'SPONSOR_MARKERS_EN': ('received', 'provided', 'free', 'gifted', 'earn*', 'paid', 'disclosure', 'compensat*'),
    # SPONSOR_MARKERS_KO — 18
    'SPONSOR_MARKERS_KO': ('제공받', '지원받', '협찬받', '지급받', '수령', '받았', '받음', '받은', '받아 작성', '받고 작성', '받아서 작성', '대가로', '조건으로', '무상으로', '공짜로', '작성했', '작성한', '소정의'),
    # SPONSOR_MASKS_KO — 15
    'SPONSOR_MASKS_KO': ('광고 차단', '광고차단', '광고 수익', '광고 크리에이티브', '광고 단가', '광고 효과', '수수료 비교', '수수료 계산', '수수료 면제', '수수료 없', '제휴 카드', '제휴카드', '제휴 할인', '제휴할인', '제휴 사'),
    # SPONSOR_STRONG_EN — 23
    'SPONSOR_STRONG_EN': ('sponsored', 'sponsored post', 'paid partnership', 'paid promotion', 'paid review', 'affiliate link*', 'affiliate commission*', 'referral code*', 'referral link*', 'free sample*', 'press sample*', 'provided for free', 'received for free', 'ppl', 'in exchange for a review', 'gifted by', 'gifted to me', 'was gifted', 'contains ads', 'includes ads', 'contains an ad', 'this is an ad', 'this is an advertisement'),
    # SPONSOR_STRONG_KO — 54
    'SPONSOR_STRONG_KO': {'goods': ('제품 협찬', '협찬품', '체험단', '서포터즈', '무료로 제공받', '제공받아 작성', '지원받아 작성', '제공받아 쓴', '지원받아 쓴'), 'service': ('무료 숙박 제공', '무료 식사 제공', '시사회 초대받', '초청받아 작성'), 'payment': ('원고료', '원고비', '소정의 대가', '소정의 원고료', '소정의 수수료', '대가를 받', '대가로 작성', '원고 제공', '유료광고', '광고비를 받', '활동비를 받', '제작비를 받'), 'affiliate': ('파트너 링크', '제휴 링크', '추천인 코드', '구매 수수료', '성과 수수료', '쿠팡 파트너스', '파트너스 활동', '어필리에이트 링크', '제휴 마케팅 링크', '수수료를 받', '수수료를 지급', '수수료 수령', '커미션을 받'), 'reward': ('우수 후기', '후기 이벤트', '리뷰 이벤트', '추첨 보상', '조건부 보상', '후기 작성 시', '후기 작성 리워드', '리뷰 작성 리워드'), 'general': ('협찬', '협찬 광고', '광고 포함', '광고를 포함', '광고가 포함', '광고입니다', '경제적 대가', '경제적 이해관계')},
    # SPONSOR_WEAK_EN — 7
    'SPONSOR_WEAK_EN': ('affiliate', 'commission*', 'sponsor', 'sponsors', 'coupon*', 'reward*', 'points'),
    # SPONSOR_WEAK_KO — 30
    'SPONSOR_WEAK_KO': {'goods': ('제품 제공', '무료 제공', '무상 제공', '샘플 제공', '증정품', '체험 제품', '제품 지원', '샘플', '사은품'), 'service': ('숙박권', '식사권', '초대권', '체험권', '이용권', '무료 체험', '서비스 제공', '숙박 제공'), 'payment': ('광고비', '활동비', '제작비', '대가'), 'affiliate': ('커미션', '수수료', '제휴', '어필리에이트', '파트너'), 'reward': ('리워드', '포인트', '쿠폰', '적립금')},
}
