"""Package 문서 시험 — 운영자 개인 PC 시험지(`docs/PERSONAL_PC_TEST.md`)가 비개발자가 따라갈 수 있는 모양인지(단계·통과 문장·체크 칸·보고 표·지우는 법·가짜 키만), 개발자용 `docs/PACKAGE.md` 와
결정 기록(D-400 이후)·변경 이력·README·구조·보안 문서가 서로 어긋나지 않는지 본다. 물결표·주소 링크가 없고, 시험지가 부르는 화면 글자가 실제 앱 글자와 같다.
"""
import re
import unittest

import packaging_support as ps
from chanceblog_desktop.security import shape
from chanceblog_desktop.ui.core.text import T

TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


OWN_ROW = re.compile(r"^\| D-4(?:0\d|1\d) \|")                         # 이 묶음의 결정 번호 대역(400 에서 419) — 다른 묶음의 D-420 이후 행과 합쳐져도 그 행은 보지 않는다


def read(rel):
    return (ps.ROOT / rel).read_text(encoding="utf-8")


def own_rows(text):
    return [line for line in text.splitlines() if OWN_ROW.match(line)]


class PersonalPcTestDocTest(unittest.TestCase):
    def setUp(self):
        self.text = read("docs/PERSONAL_PC_TEST.md")

    def test_title_and_the_bold_notice_come_first(self):
        lines = [line for line in self.text.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("# 개인 PC 제한 시험 안내서"))
        self.assertEqual(lines[1], "**개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다**")
        self.assertIn(ps.VERSION, lines[0])

    def test_no_tilde_no_address_and_only_relative_links_to_real_files(self):
        self.assertNotIn(TILDE, self.text)
        self.assertIsNone(URL.search(self.text))
        for target in LINK.findall(self.text):
            self.assertFalse(re.match(r"^[a-z][a-z0-9+.-]*:", target), target)
            self.assertTrue((ps.ROOT / "docs" / target.split("#")[0]).exists(), target)

    def test_the_nine_numbered_steps_are_there_in_order_and_each_has_a_title(self):
        headings = re.findall(r"(?m)^## (\d)단계\. (.+)$", self.text)
        self.assertEqual([number for number, _title in headings], [str(n) for n in range(9)])
        for _number, title in headings:
            self.assertGreaterEqual(len(title.strip()), 4)

    def test_the_things_the_operator_asked_to_check_are_each_named(self):
        for needle in ("표준 사용자", "관리자 권한", "UAC", "SmartScreen", "추가 정보", "압축 풀기", "블로그", "Seed", "후보", "초안", "저장", "다시 열", "백업", "복원", "Credential 제외됨",
                       "키 등록", "삭제", "미등록", "TEST-KEY-NOT-REAL", "다른 일반 Windows 계정", "액세스 거부", "cmdkey /list", "ChanceBlogDesktop:", "AppData", "ChanceblogDesktop",
                       "자격 증명 관리자", "설치 폴더 위치", "데이터 폴더 위치", "Get-FileHash", "SHA256SUMS", "PACKAGE_INFO.md", "해당 없음", "스마트 앱 컨트롤", "Microsoft Defender"):
            self.assertIn(needle, self.text, needle)

    def test_every_step_says_what_passing_looks_like_and_has_check_boxes(self):
        self.assertGreaterEqual(self.text.count("이렇게 보이면 통과") + self.text.count("**통과**"), 12)
        self.assertGreaterEqual(self.text.count("- [ ] "), 30)
        for step in re.split(r"(?m)^## ", self.text):
            if re.match(r"[0-6]단계", step):
                self.assertTrue("통과" in step, step.splitlines()[0])
                self.assertIn("[ ]", step, step.splitlines()[0])

    def test_the_report_table_has_a_row_for_every_checked_item_and_the_three_columns(self):
        table = self.text.split("## 7단계. 결과 보고")[1].split("## 8단계")[0]
        rows = [line for line in table.splitlines() if re.match(r"^\| (\d)(-\d)? \|", line)]
        self.assertEqual([row.split("|")[1].strip() for row in rows], ["0-1", "0-2", "0-3", "1-1", "1-2", "1-3", "1-4", "2", "3", "4", "5", "6-1", "6-2", "6-3", "6-4"])
        for row in rows:
            self.assertEqual(row.count("|"), 5, row)
        self.assertIn("| 번호 | 확인한 것 | 결과 | 적어 둘 말 |", table)
        for needle in ("통과", "실패", "해당 없음", "Windows 버전", "화면 배율", "스마트 앱 컨트롤", "화면 사진", "Windows` 키 + `Shift` + `S"):
            self.assertIn(needle, table)

    def test_the_key_is_deleted_only_after_the_other_account_was_checked(self):
        step5 = self.text.split("## 5단계")[1].split("## 6단계")[0]
        step6 = self.text.split("## 6단계")[1].split("## 7단계")[0]
        self.assertIn("키는 아직 지우지 마세요", step5)
        self.assertNotIn("`삭제`", step5)                                              # 5단계에서는 지우지 않는다 — 6-2 가 의미를 가지려면 키가 남아 있어야 한다
        self.assertLess(step6.index("6-2."), step6.index("6-4."))
        self.assertIn("첫 계정으로 돌아와 키 지우기", step6)
        self.assertIn("`삭제`", step6.split("6-4.")[1])
        self.assertIn("키가 남아 있어야", step5)

    def test_the_cleanup_step_names_all_three_places_and_the_second_account(self):
        cleanup = self.text.split("## 8단계")[1].split("## 막혔을 때")[0]
        for needle in ("앱 폴더", "데이터 폴더", "자격 증명 관리자", "ChanceBlogTest", "%LOCALAPPDATA%", "ChanceblogDesktop", "ChanceBlogDesktop:", "두 계정 모두", "시험용 계정"):
            self.assertIn(needle, cleanup, needle)

    def test_five_stuck_points_are_listed(self):
        stuck = self.text.split("## 막혔을 때")[1]
        numbered = re.findall(r"(?m)^(\d)\. ", stuck)
        self.assertEqual(numbered, ["1", "2", "3", "4", "5"])

    def test_the_dangerous_button_and_the_stop_conditions_are_warned_about(self):
        for needle in ("`계속` 단추", "누르지 마세요", "멈추고 바로 알릴 일", "진짜 키·비밀번호·토큰은 어디에도 넣지 않습니다", "관리자 계정이면 안 됩니다", "AppData` 폴더 안"):
            self.assertIn(needle, self.text, needle)

    def test_there_is_no_real_secret_or_key_shape_and_the_only_fake_key_is_the_agreed_text(self):
        self.assertIsNone(re.search("|".join(ps.pkgcommon.KEY_SHAPES), self.text))
        self.assertEqual(set(re.findall(r"TEST-KEY-NOT-REAL(?:-TEST-KEY-NOT-REAL)?", self.text)), {"TEST-KEY-NOT-REAL", "TEST-KEY-NOT-REAL-TEST-KEY-NOT-REAL"})

    def test_the_fake_key_passes_the_apps_own_key_field_rules_and_does_not_look_like_a_real_one(self):
        short, long = "TEST-KEY-NOT-REAL", "TEST-KEY-NOT-REAL-TEST-KEY-NOT-REAL"
        self.assertEqual(len(short), 17)
        for value, max_len in ((short, 256), (short, 128), (long, 128), (long, 256)):
            self.assertEqual(shape.value_problem(value, min_len=16, max_len=max_len), "", value)
        self.assertFalse(shape.looks_secret(short))
        self.assertNotEqual(shape.value_problem(short[:15], min_len=16, max_len=256), "")               # 16자 미만이면 '너무 짧습니다' — 그래서 시험지가 17자 값을 쓴다
        self.assertIn("너무 짧습니다", self.text)

    def test_the_screen_words_the_paper_tells_the_operator_to_press_are_the_real_app_words(self):
        labels = ("홈", "주제 후보", "초안 작성", "Seed 관리", "블로그 관리", "설정", "새 Seed 등록", "승인하기", "후보 만들기", "만들기", "이 주제로 만들기", "키 등록", "삭제", "제목 복사",
                  "네이버 글쓰기 열기", "저장", "정보", "다음", "표시 이름", "블로그 ID 또는 주소", "Seed 낱말", "대분류", "중분류", "중요도", "대상 유형", "소속", "승인 전으로 등록", "AI 보조",
                  "별칭", "저장된 키")
        real = set(T.values())
        for label in labels:
            self.assertIn(label, real, f"시험지가 부르는 '{label}' 이 앱의 화면 글자에 없다")
            self.assertIn(label, self.text, label)
        self.assertIn("{slot} 등록", T["blogs_form_new"])

    def test_the_save_and_backup_words_the_paper_uses_are_the_real_words_of_the_merged_save_and_backup_features(self):
        """저장한 초안(LOCALSAVE)·전체 백업·복원(BACKUPUI)이 합쳐진 앱의 실제 글 — 시험지가 단추·창·안내 글로 부르는 말이 앱의 문구표에 그대로 있다(이 시험은 두 기능이 있는 트리에서만 의미가 있다)."""
        real = set(T.values())
        for label in ("저장됨", "저장한 초안", "계속 고치기", "저장 안 하고 닫기", "지금 백업", "복원", "복원하기", "Credential 제외됨", "백업·복원", "완료", "저장하지 않은 내용이 있어요", "이 백업으로 복원할까요?"):
            self.assertIn(label, real, f"시험지가 부르는 '{label}' 이 앱의 화면 글자에 없다")
            self.assertIn(label, self.text, label)
        every_text = "\n".join(value for value in T.values() if isinstance(value, str))
        for phrase in ("백업을 만들었어요", "복원을 마쳤어요", "복원 직전 사본"):                              # 안내 글의 앞부분 — 문구표의 긴 글 속에 그대로 있다
            self.assertIn(phrase, every_text, phrase)
            self.assertIn(phrase, self.text, phrase)
        step3 = self.text.split("## 3단계")[1].split("## 4단계")[0]
        self.assertNotIn("'고친 내용이 사라져요'", self.text)                                                # 저장 기능이 없을 때의 옛 두 갈래 창 — 저장 기능이 있는 앱은 세 갈래 창('저장하지 않은 내용이 있어요')을 띄운다
        self.assertIn("저장하지 않은 내용이 있어요", step3)
        self.assertIn("`저장 안 하고 닫기`", step3)                                                        # 단추 이름은 단추로 적는다
        step4 = self.text.split("## 4단계")[1].split("## 5단계")[0]
        self.assertNotIn("복원이 '완료'", step4)                                                          # '완료' 는 백업 줄의 상태 글이지 복원 결과 글이 아니다
        self.assertIn("복원을 마쳤어요", step4)
        self.assertIn("`복원하기`", step4)                                                                 # 확인 창의 단추(안내 글 속의 '복원하기 직전' 과 다르다)
        self.assertIn("('이 백업으로 복원할까요?')", step4)                                                 # 확인 창의 이름

    def test_the_key_card_and_the_key_field_the_paper_names_are_the_real_service_registry_entries(self):
        from chanceblog_desktop.service import connections as cn
        purpose = cn.PURPOSES["ai_assist"]
        self.assertEqual(purpose.label, "AI 보조(선택)")
        self.assertEqual([field.label for field in purpose.fields], ["API 키"])
        self.assertEqual((purpose.fields[0].min_len, purpose.fields[0].secret), (16, True))
        for needle in ("`AI 보조(선택)` 카드", "`API 키` 칸", "`별칭` 칸"):
            self.assertIn(needle, self.text, needle)

    def test_the_two_accounts_and_the_public_folder_trick_are_explained(self):
        for needle in ("C:\\Users\\Public\\Documents", "표준 사용자 계정이 **하나 더** 필요", "압축 파일 옮기기", "첫 계정의 데이터 폴더 열기 시도"):
            self.assertIn(needle, self.text, needle)

    def test_creating_and_removing_the_second_account_needs_the_admin_password_and_the_paper_says_what_to_do(self):
        head = self.text.split("## 시험하는 것 한눈에 보기")[0]
        stop = next(line for line in head.splitlines() if line.startswith("**멈추고 바로 알릴 일**"))
        self.assertIn("앱을 열거나 쓰는 중에", stop)                                      # 멈추고 알릴 일 ① 은 앱을 쓰다 뜬 창만 가리킨다
        self.assertIn("6단계", stop)                                                    # 계정 만들기·지우기의 관리자 암호 창은 해당하지 않는다고 적었다
        self.assertIn("관리자 암호가 필요", self.text.split("## 시험하는 것 한눈에 보기")[1].split("## 0단계")[0])
        step6 = self.text.split("## 6단계")[1].split("## 7단계")[0]
        prepare = step6.split("**두 번째 계정으로 로그인한 뒤**")[0]
        for needle in ("관리자 권한(암호)이 필요합니다", "관리자 계정의 이름과 암호", "앱 때문에 생긴 문제가 아닙니다", "관리자 암호를 모르거나 관리자 계정이 없으면", "`실패(권한 없음)`", "6-1·6-2·6-3",
                       "6-4 의 키 지우기는 첫 계정에서 그대로", "어디에도 적지 않습니다"):
            self.assertIn(needle, prepare, needle)
        self.assertIn("이미 첫 계정입니다", step6.split("6-4.")[1])                       # 둘째 계정을 건너뛴 사람도 6-4 의 키 지우기는 한다
        report = self.text.split("## 7단계. 결과 보고")[1].split("## 8단계")[0]
        self.assertIn("실패(권한 없음)", report)
        cleanup = self.text.split("## 8단계")[1].split("## 막혔을 때")[0]
        for needle in ("관리자 계정의 이름과 암호", "지우지 말고 그대로 두고", "시험용 계정이 남아 있다"):
            self.assertIn(needle, cleanup, needle)
        self.assertIn("관리자 암호를 묻는 창이 뜨는 것은 정상", self.text.split("## 막혔을 때")[1])
        self.assertNotIn("앱의 실패가 아니다", self.text)

    def test_unzip_advice_keeps_the_app_out_of_the_data_folder_and_cloud_folders(self):
        for needle in ("`ChanceBlogTest`", "Program Files", "OneDrive", "100글자"):
            self.assertIn(needle, self.text, needle)

    def test_the_paper_names_the_package_it_is_for_and_sends_trial_builds_away(self):
        head = self.text.split("## 시험하는 것 한눈에 보기")[0]
        for needle in ("어느 Package 용인가요", "정식 시험용 Package", "`TESTBUILD`", "시험 빌드", "이 시험지로 시험하지 말고", "화면 글자가 이 문서와 다르면"):
            self.assertIn(needle, head, needle)
        self.assertGreaterEqual(self.text.count("TESTBUILD"), 2)
        self.assertIn("TESTBUILD", self.text.split("## 0단계")[1].split("## 1단계")[0])
        self.assertIn("시험 빌드 — 개인 PC 로 보내지 않는 빌드예요", self.text.split("### 1-3.")[1].split("## 2단계")[0])
        self.assertIn("받은 압축 파일의 이름", self.text.split("## 7단계. 결과 보고")[1].split("## 8단계")[0])

    def test_a_missing_save_or_backup_is_a_failure_and_not_applicable_belongs_only_to_optional_lines(self):
        for needle in ("'실패(기능 없음)'", "저장 단추가 화면에 없으면", "백업·복원 기능이 화면에 없으면", "'해당 없음'을 쓸 수 없습니다", "(선택)"):
            self.assertIn(needle, self.text, needle)
        for stale in ("'해당 없음(기능 없음)'", "해당 없음(기능 없음)", "실패가 아닙니다"):
            self.assertNotIn(stale, self.text, stale)
        for line in self.text.splitlines():
            if "해당 없음" in line:
                self.assertTrue(any(word in line for word in ("쓸 수 없습니다", "아니라", "(선택)", "없습니다")), line)       # 필수 칸에 '해당 없음' 을 허용하는 문장이 되살아나지 않게

    def test_the_two_register_key_buttons_are_told_apart_and_the_empty_blog_card_words_are_the_real_ones(self):
        from chanceblog_desktop.service import connections as cn
        step5 = self.text.split("## 5단계")[1].split("## 6단계")[0]
        self.assertEqual(cn.PURPOSES["naver_apihub"].label, "NAVER API HUB 검색어 트렌드")
        self.assertIn("NAVER API HUB 검색어 트렌드", step5)
        self.assertIn("그것이 아닙니다", step5)
        self.assertIn("`AI 보조(선택)` 카드의 것을 누릅니다", step5)
        for key in ("blogs_card_empty_title", "blogs_card_empty_desc", "blogs_status_empty", "blogs_status_registered"):
            self.assertIn(T[key], self.text, key)
        self.assertNotIn("눌러서 등록", self.text)                                         # 접근성 읽기 이름이지 화면 글자가 아니다(`blogs_card_a11y_empty`)

    def test_the_cmdkey_line_shape_the_second_account_steps_and_the_data_folder_warning_are_there(self):
        for needle in ("LegacyGeneric:target=ChanceBlogDesktop:", "Microsoft 계정이 없는 사용자 추가", "로컬 계정", "이 사람의 로그인 정보가 없습니다"):
            self.assertIn(needle, self.text, needle)
        cleanup = self.text.split("## 8단계")[1].split("## 막혔을 때")[0]
        for needle in ("진짜로 쓰는 중이라면", "지우지 마세요"):
            self.assertIn(needle, cleanup, needle)

    def test_the_first_account_cleanup_and_deletion_do_not_depend_on_the_developer_tools(self):
        for word in ("python", "pip ", "git ", "PyInstaller", "pyinstaller", "venv"):
            self.assertNotIn(word, self.text, word)


class PackageDocTest(unittest.TestCase):
    def setUp(self):
        self.text = read("docs/PACKAGE.md")

    def test_title_notice_and_clean_text_rules(self):
        lines = [line for line in self.text.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("# 개인 PC 제한 시험용 Package"))
        self.assertEqual(lines[1], "**개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다**")
        self.assertNotIn(TILDE, self.text)
        self.assertIsNone(URL.search(self.text))
        for target in LINK.findall(self.text):
            self.assertTrue((ps.ROOT / "docs" / target.split("#")[0]).exists(), target)

    def test_the_ten_sections_are_there(self):
        headings = re.findall(r"(?m)^## (\d+)\. (.+)$", self.text)
        self.assertEqual([number for number, _title in headings], [str(n) for n in range(1, 11)])

    def test_it_documents_the_build_options_the_artifacts_and_the_determinism_recipe(self):
        for needle in ("--out-dir", "--skip-scan", "--allow-missing-gate", "release_eligible", "ChanceBlogDesktop-0.1.0-preview.1-win64.zip", "SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json",
                       "PYTHONHASHSEED=0", "SOURCE_DATE_EPOCH", "X utf8", "--onedir", "--windowed", "깨끗한 작업 트리", "python packaging/build_package.py", "requirements-package.txt", "--hash", "다른 운영체제에서는 빌드가 처음에 거절한다"):
            self.assertIn(needle, self.text, needle)

    def test_it_keeps_the_virtual_environment_outside_the_repository_and_explains_the_new_guards(self):
        self.assertNotIn("python -m venv .venv-package", self.text)
        for needle in ("저장소 밖에 만든다", "..\\chanceblog-package-venv", ".chanceblog-package-out", "TESTBUILD", "--exclude-module PySide6.QtNetwork", "git 이 무시하는 파일", "D-415", "D-416", "D-417", "D-419"):
            self.assertIn(needle, self.text, needle)
        determinism = self.text.split("## 5.")[1].split("## 6.")[0]
        self.assertIn("묶음에 들어가는 DLL 이 같은 곳", determinism)
        self.assertNotIn("같은 커밋·같은 도구 버전·같은 Python 이면 같은 압축 파일", self.text)
        self.assertNotIn("백업 기능이 있다", self.text)

    def test_the_eight_things_and_the_two_info_copies_are_explained(self):
        for needle in ("Version", "Git Commit", "SHA-256", "Dependency 목록", "Build 방법", "Malware 검사 결과", "서명 여부", "SmartScreen 예상 동작", "inner", "outer", "-DisableRemediation",
                       "검사 안 함 — 이유"):
            self.assertIn(needle, self.text, needle)

    def test_every_selftest_check_name_is_in_the_documents_table(self):
        table = self.text.split("## 6. 자가 점검")[1].split("## 7.")[0]
        for key in ps.SELFTEST_KEYS:
            self.assertIn(f"`{key}`", table, key)
        self.assertEqual(len(re.findall(r"(?m)^\| `[a-z_0-9]+` \|", table)), len(ps.SELFTEST_KEYS))

    def test_the_third_party_section_is_careful_it_is_not_legal_advice(self):
        section = self.text.split("## 8. 제3자 고지")[1].split("## 9.")[0]
        for needle in ("법률 판단이 아니다", "LGPL", "LGPL-3.0", "동적 링크", "바꿔 끼울", "소스", "GPL-3.0.txt", "PSF License", "한 글자도 바꾸지 않고 복사", "대조는 하지 못했다", "D-13"):
            self.assertIn(needle, section, needle)

    def test_the_removal_and_the_limits_are_there(self):
        self.assertIn("%LOCALAPPDATA%\\ChanceblogDesktop", self.text.split("## 9.")[1].split("## 10.")[0])
        limits = self.text.split("## 10.")[1]
        for needle in ("서명이 없다", "스마트 앱 컨트롤", "아이콘이 없다", "업데이트·롤백", "T3", "workflow_dispatch", "windows-latest", "14일", "비밀 값 0", "서명 단계 없음", "D-32"):
            self.assertIn(needle, limits, needle)

    def test_the_limits_of_the_build_guards_and_of_the_gate_check_are_written_down_and_the_new_guards_are_explained(self):
        limits = self.text.split("## 10.")[1]
        for needle in ("묶음 점검의 한계", "정션", "낯선 이름", "상태 캐시"):
            self.assertIn(needle, limits, needle)
        boundary = self.text.split("## 7. 외부 쓰기 경계")[1].split("## 8.")[0]
        for needle in ("`EXTERNAL_WRITE`·`BLOGGER_OAUTH_INPUT`", "상수 두 개", "require_external_write"):
            self.assertIn(needle, boundary, needle)
        making = self.text.split("## 2.")[1].split("## 3.")[0]
        for needle in ("skip-worktree", "assume-unchanged", "git ls-files", "130자", "예약 이름", "공백이나 점으로 끝나거나"):
            self.assertIn(needle, making, needle)

    def test_the_package_doc_says_the_apps_user_data_file_names_are_refused_inside_the_bundle(self):
        building = self.text.split("## 2.")[1].split("## 3.")[0]
        for needle in ("앱이 정의한 사용자 데이터 파일 이름", "보관함·설정·백업 표지", ".bak", ".tmp", "D-446"):
            self.assertIn(needle, building, needle)

    def test_it_says_which_part_of_the_external_write_boundary_belongs_to_whom(self):
        section = self.text.split("## 7. 외부 쓰기 경계")[1].split("## 8.")[0]
        for needle in ("시작 파일이 명령줄을 열지 않고", "capabilities", "보안 수정 묶음의 몫", "--allow-missing-gate"):
            self.assertIn(needle, section, needle)


class DecisionRowsTest(unittest.TestCase):
    def rows(self):
        return own_rows(read("docs/DECISIONS.md"))

    def test_rows_of_other_bundles_in_the_neighbouring_number_band_are_not_taken_for_this_bundles_own(self):
        sample = "\n".join(f"| D-{number} | 2026-11-11 | x | y |" for number in (399, 400, 409, 414, 419, 420, 429, 430, 499))
        self.assertEqual([line.split()[1] for line in own_rows(sample)], ["D-400", "D-409", "D-414", "D-419"])
        merged = read("docs/DECISIONS.md") + "\n" + "\n".join(f"| D-{number} | 2026-11-11 | 다른 묶음 | 다른 묶음 |" for number in range(420, 430))
        self.assertEqual(own_rows(merged), self.rows())                                  # 다른 묶음의 행이 합쳐져도 이 묶음의 시험은 같은 행만 본다

    def test_the_rows_are_this_bundles_own_numbers_in_order_unique_and_well_formed(self):
        rows = self.rows()
        numbers = [int(re.match(r"^\| D-(\d+) \|", row).group(1)) for row in rows]
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all(400 <= number <= 419 for number in numbers), numbers)
        self.assertEqual(numbers, sorted(set(numbers)))
        for row in rows:
            self.assertEqual(row.count(" | "), 3, f"표의 칸은 넷이다(글 속에 세로줄이 없다): {row[:40]}")
            self.assertTrue(row.rstrip().endswith("|"))
            self.assertTrue(row.split("|")[2].strip().startswith("2026-11-"), row[:30])
            self.assertNotIn(TILDE, row)
            self.assertIsNone(URL.search(row))

    def test_each_decision_says_its_own_topic(self):
        text = "\n".join(self.rows())
        for needle in ("packaging/", "0.1.0-preview.1", "--selftest", "PACKAGE_INFO", "SHA-256", "결정적", "requirements-package.txt", "LGPL", "Defender", "--allow-missing-gate", "package.yml", "PERSONAL_PC_TEST.md",
                       "TEST-KEY-NOT-REAL", "capabilities", "T3", "TESTBUILD", "QtNetwork", ".chanceblog-package-out", "GATE_MISSING_TEXT", "COLLECT-00.toc"):
            self.assertIn(needle, text, needle)

    def test_the_rows_do_not_pin_other_bundles_decision_numbers_or_the_overall_maximum(self):
        for row in self.rows():
            for number in re.findall(r"\bD-(\d{3})\b", row):
                self.assertTrue(int(number) < 400 or 400 <= int(number) <= 419, row[:30])


LATER_ROW = re.compile(r"^\| D-44\d \|")                                   # 독립 검증 2차(PCKITV2) 뒤의 결정 — 자기 대역 시험(OWN_ROW)은 이 행들을 보지 않으므로 따로 본다


class LaterDecisionRowsTest(unittest.TestCase):
    def lines(self):
        return read("docs/DECISIONS.md").splitlines()

    def rows(self):
        return [line for line in self.lines() if LATER_ROW.match(line)]

    def test_the_later_rows_are_in_the_same_table_in_order_and_well_formed(self):
        lines, rows = self.lines(), self.rows()
        numbers = [int(re.match(r"^\| D-(\d+) \|", row).group(1)) for row in rows]
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual(numbers, list(range(440, 440 + len(rows))))
        first = lines.index(rows[0])
        self.assertEqual(lines[first:first + len(rows)], rows)                                   # 빈틈 없이 이어진다
        last_own = max(index for index, line in enumerate(lines) if OWN_ROW.match(line))
        self.assertTrue(all(line.startswith("| D-") for line in lines[last_own:first]))          # D-419 행과 같은 표 — 사이에 끊김이 없다(다른 묶음의 행이 끼어도 된다)
        for row in rows:
            self.assertEqual(row.count(" | "), 3, row[:40])
            self.assertTrue(row.rstrip().endswith("|"))
            self.assertTrue(row.split("|")[2].strip().startswith("2026-11-"), row[:30])
            self.assertNotIn(TILDE, row)
            self.assertIsNone(URL.search(row))
            self.assertIsNone(OWN_ROW.match(row))                                                # 자기 대역 정규식을 넓히지 않았다

    def test_each_later_decision_says_its_own_topic(self):
        by_number = {re.match(r"^\| (D-\d+) \|", row).group(1): row for row in self.rows()}
        topics = {"D-440": ("out_path_problem", "plain_text", "130자", "CON", "clean_out_dir"),
                  "D-441": ("git_hidden_changes", "skip-worktree", "assume-unchanged", "--untracked-files=all", "상태 캐시"),
                  "D-442": ("실패(권한 없음)", "관리자 암호", "6-4", "Package Gate"),
                  "D-443": ("qtuiotouchplugin.dll", "ntpath.normpath", "같은 Python", "capabilities", "## 11. 버전"),
                  "D-445": ("M056", "git apply --3way", "충돌 셋", "D-330 에서 D-467", "저장하지 않은 내용이 있어요", "복원을 마쳤어요"),
                  "D-446": ("calendar.json", "restore-in-progress.json", ".bak", ".tmp", "앱 코드가 정의한")}
        for number, needles in topics.items():
            for needle in needles:
                self.assertIn(needle, by_number[number], (number, needle))


class OtherDocsTest(unittest.TestCase):
    def test_the_changelog_first_section_is_the_version_and_names_this_bundle(self):
        text = read("CHANGELOG.md")
        first = re.search(r"(?m)^## \[([^\]]+)\] — (.+)$", text)
        self.assertEqual(first.group(1), read("VERSION").strip())
        section = text.split(first.group(0))[1].split("\n## [")[0]
        for needle in ("packaging/", "PACKAGE_INFO", "--selftest", "docs/PERSONAL_PC_TEST.md", "docs/PACKAGE.md", "T3", "D-400"):
            self.assertIn(needle, section, needle)
        self.assertNotIn(TILDE, section)
        self.assertIsNone(URL.search(section))

    def test_no_document_or_script_keeps_the_old_overclaim_that_the_same_input_always_gives_the_same_zip(self):
        for rel in ("CHANGELOG.md", "docs/SECURITY.md", "docs/PACKAGE.md", "docs/ARCHITECTURE.md", "packaging/make_manifest.py", "packaging/build_package.py"):
            body = read(rel)
            self.assertNotIn("같은 입력이면 같은 압축 파일", body, rel)
            self.assertNotIn("같은 도구 버전·같은 Python 이면 같은 압축 파일", body, rel)
        self.assertIn("DLL 이 같은 곳", read("CHANGELOG.md"))
        self.assertIn("DLL 이 같은 곳", read("docs/SECURITY.md"))
        for rel in ("CHANGELOG.md", "docs/SECURITY.md", "docs/PACKAGE.md", "packaging/make_manifest.py"):
            self.assertIn("같은 Python", read(rel), rel)                                  # 같은 Python 조건이 빠진 문장이 되살아나지 않게(N6 — 측정은 한 PC·같은 Python)
            self.assertIn("같은 잠금 파일의 도구", read(rel), rel)

    def test_the_explanation_of_why_the_qt_network_dll_stays_names_the_touch_plugin_everywhere(self):
        code = read("packaging/build_package.py")
        self.assertIn("qtuiotouchplugin.dll", code)
        self.assertNotIn("어느 묶음 DLL 도 가져오지 않지만", code)
        row = next(line for line in read("docs/DECISIONS.md").splitlines() if line.startswith("| D-415 |"))
        self.assertIn("qtuiotouchplugin.dll", row)
        self.assertNotIn("어느 묶음 DLL 도 가져오지 않지만", row)

    def test_the_readme_lists_both_new_documents(self):
        readme = read("README.md")
        for name in ("docs/PACKAGE.md", "docs/PERSONAL_PC_TEST.md"):
            self.assertIn(name, readme)

    def test_the_architecture_and_security_documents_have_this_bundles_sections(self):
        architecture, security = read("docs/ARCHITECTURE.md"), read("docs/SECURITY.md")
        heading = "\n## 개인 PC 제한 시험용 Package — `packaging/`"
        self.assertEqual(architecture.count(heading), 1)
        self.assertNotIn("## 12. 개인 PC 제한 시험용 Package", architecture)                      # 번호는 다른 묶음(LOCALSAVE·BACKUPUI)과 겹쳐 쓰지 않는다(N9)
        self.assertLess(architecture.index(heading), architecture.index("\n## 11. 버전"))         # 다른 가지들이 문서 끝에 절을 붙이는 자리와 떨어져 있다(D-443)
        section = architecture.split(heading)[1].split("\n## ")[0]
        for needle in ("gui_entry.py", "build_package.py", "make_manifest.py", "requirements-package.txt", "LICENSES", "T3", "PACKAGE.md", "PERSONAL_PC_TEST.md"):
            self.assertIn(needle, section, needle)
        self.assertIn("## 개인 PC 제한 시험용 Package(`packaging/`) — 보안 경계와 한계", security)
        part = security.split("## 개인 PC 제한 시험용 Package(`packaging/`)")[1]
        for needle in ("asInvoker", "SHA-256", "명령줄이 열려 있지 않다", "스마트 앱 컨트롤", "-DisableRemediation", "공급망 한계"):
            self.assertIn(needle, part, needle)
        for text in (section, part):
            self.assertNotIn(TILDE, text)
            self.assertIsNone(URL.search(text))

    def test_the_new_docs_use_only_decision_numbers_that_exist(self):
        defined = set(re.findall(r"(?m)^\| (D-\d+) \|", read("docs/DECISIONS.md")))
        for rel in ("docs/PACKAGE.md", "docs/PERSONAL_PC_TEST.md"):
            for number in re.findall(r"\bD-\d{2,3}\b", read(rel)):
                if number != "D-400":
                    self.assertIn(number, defined, f"{rel}: {number}")


if __name__ == "__main__":
    unittest.main()
