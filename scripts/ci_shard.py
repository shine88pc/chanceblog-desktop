"""CI 시험을 몇 조각으로 나눠 한 조각만 돌린다(D-220) — `python -m unittest discover -s tests -v` 와 같은 시험을 같은 방식으로 찾아 시험 파일(모듈) 단위로 나눈다.

왜: 시험이 6천 개를 넘고, git 과 프로세스를 진짜로 쓰는 몇 파일(`test_pages_publish`·`test_service_recovery`·`test_service_repolock` 등)이 전체 시간의 약 3/4 를 차지한다.
    윈도 칸이 21~29분 걸려 병합 부탁이 그만큼 늦어졌다. 조각을 서로 다른 러너에서 동시에 돌리면 칸 하나가 약 1/3(10분 안팎)이 된다.
사용: python scripts/ci_shard.py <조각 번호 1..N> <조각 수 N> [--list] [--tests-dir=폴더]
      인자 대신 환경 변수 CI_SHARD·CI_SHARD_TOTAL 로도 준다(ci.yml 이 쓰는 방식). 둘 다 없으면 조각 하나(= 전체, `discover` 와 같다)로 돈다.
      --list 는 그 조각에 들어갈 시험 파일 이름만 보여 주고 끝난다. --tests-dir 는 시험을 시험하려고 둔 것이다.
규칙(`tests/test_ci_shard.py` 가 지킨다):
  · 모든 시험 파일은 조각 하나에만 들어간다(빠지거나 겹치지 않는다). 불러오기에 실패한 파일도 어느 조각에 들어가 그 조각을 빨갛게 만든다(삼키지 않는다).
  · 나누는 방법은 정해져 있다(같은 입력이면 늘 같은 조각). 무거운 파일은 아래 WEIGHTS 의 대략의 시간(초, 개발 PC 에서 잰 값)으로, 나머지는 DEFAULT_WEIGHT 로 쳐서
    무거운 파일부터 지금 가장 가벼운 조각에 넣는다. 새 시험 파일은 자동으로 어느 조각에 들어간다(표에 없어도 된다).
  · 조각이 비면(조각 수가 파일 수보다 큰 경우 등) 실패로 끝난다 — 아무것도 안 돌고 초록이 되는 일이 없게.
  · 시험이 하나라도 실패하면(불러오기 실패 포함) 종료 코드가 0 이 아니다.
  · 환경 변수 CI_REQUIRE_QT=1(정식 CI 의 Qt 칸 — `ci.yml` 의 `qt` 잡, D-710·D-712)이면 'PySide6 가 안 깔려 화면(Qt) 시험이 모두 건너뛰어졌는데 초록' 이 되는 일을 막는다:
    ① 시작 전에 PySide6 를 못 찾으면 종료 코드 3 ② 끝난 뒤 건너뛴 시험 중 이유에 PySide6(대소문자 무시)가 든 것이 하나라도 있으면 종료 코드 1 과 시험 파일별 개수
    ③ 건너뜀 이유별 개수와 시험 파일별 걸린 시간을 정보로 찍는다(다른 이유의 건너뜀은 알림만 — 첫 실행 뒤 허용 목록으로 굳힌다. 걸린 시간은 Qt 칸의 무게 표 `QT_WEIGHTS` 를 고칠 때 쓴다).
    5초 넘게 걸린 시험 파일은 끝나는 즉시 `[걸린 시간] 파일 초` 한 줄도 찍는다(칸이 시간 한도에 잘려도 로그에 남게).
    값은 1(켬)이거나 0·없음(끔)뿐이고 그 밖의 값은 종료 코드 2 다 — 오타로 가드가 꺼진 채 초록이 되지 않게. 없으면 이 규칙들은 모두 오늘과 같다(정식 CI 의 열두 칸).
  · 환경 변수 CI_WEIGHTS(`ci.yml` 의 `qt` 잡만 준다, D-717)는 조각을 나누는 무게 표를 고른다: 없음·빈 값이면 기본 표(`WEIGHTS`·`DEFAULT_WEIGHT` — 정식 CI 의 열두 칸, 오늘과 똑같다),
    `qt` 면 Qt 칸 전용 표(`QT_WEIGHTS`·`QT_DEFAULT_WEIGHT` — Qt 시험이 든 파일까지 윈도 러너에서 잰 초). 그 밖의 값은 종료 코드 2 다 — 오타로 기본 표를 쓴 채 조각이 쏠려 시간 한도에 걸리지 않게.
    `assign` 은 표를 인자로 받는 순수 함수라 환경에 기대지 않는다(표를 안 주면 기본 표). `--list` 도 같은 표로 나눈다. 표를 다시 재는 법은 docs/CI_QT.md.
"""
from __future__ import annotations

import heapq
import importlib.util
import os
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
MAX_SHARDS = 99
QT_FLAG = "CI_REQUIRE_QT"
WEIGHTS_FLAG = "CI_WEIGHTS"   # 어느 무게 표로 조각을 나눌지 — 없음·빈 값이면 기본 표(WEIGHTS, 열두 칸), `qt` 면 Qt 칸 전용 표(QT_WEIGHTS, D-717)
QT_WORD = "pyside6"           # 건너뜀 이유에 이 낱말이 있으면(대소문자 무시) 'PySide6 가 없어 건너뜀' 으로 본다 — 새 Qt 시험 파일은 건너뜀 문구에 PySide6 를 적는다(test_ci_shard 가 지킨다)
REASON_LIMIT = 10             # 정보로 찍는 건너뜀 이유의 가짓수 상한
TIME_LIMIT = 15               # 정보로 찍는 시험 파일별 걸린 시간의 줄 수 상한
PROGRESS_SECONDS = 5          # 한 시험 파일이 이만큼 이상 걸렸으면 그 파일이 끝나는 즉시 한 줄 찍는다 — 칸이 시간 한도에 잘려도 어느 파일이 얼마나 걸렸는지 로그에 남는다
FILE_LIMIT = 60               # 실패 때 찍는 시험 파일별 개수의 줄 수 상한
DEFAULT_WEIGHT = 4            # 20초 미만인 파일 125개의 평균(약 4초)
# 개발 PC(부하 있음)에서 파일마다 따로 돌려 잰 초(2026-11-07, 143개 파일 6,454개 시험 합계 약 60분). 20초 이상인 파일만 적는다 — 대략의 균형용일 뿐 정확할 필요는 없다.
WEIGHTS = {
    "test_pages_publish": 780,
    "test_service_recovery": 460,
    "test_service_repolock": 430,
    "test_pages_repo": 265,
    "test_service_unpushed": 225,
    "test_service_candidates_process": 180,
    "test_service_echo": 135,
    "test_service_pages_git": 130,
    "test_auto_pr_workflow": 100,
    "test_vendor_core": 90,
    "test_service_keys_cli": 75,
    "test_service_suggest_process": 55,
    "test_service_draft_process": 40,
    "test_content_migration": 40,
    "test_service_pushed_post": 40,
    "test_topics_generate": 30,
    "test_service_lock": 25,
    "test_topicdb_backup": 25,
}
# Qt 칸(`ci.yml` 의 `qt` 잡 — 환경 변수 `CI_WEIGHTS=qt`, D-717) 전용 무게 표: 시험 파일(모듈) 이름 → 윈도 러너(파이썬 3.12·PySide6)에서 잰 걸린 초. 위 `WEIGHTS`(개발 PC 에서 잰 20초 이상의 큰 파일)는 열두 칸용이고 이 표는 Qt 칸에서만 쓴다.
# 출처: 2026-11-26 Qt 시간 진단 3차(병합 금지 가지 NO-MERGE-diag-qtt3, 실행 45720452621 — 앞선 실행 45715001306 은 조각별 시간만) — 지금 모양(열두 조각)으로 돌려 조각마다 시험 파일 전부의 걸린 초를 주석으로 뽑았다.
# 시험 파일 354개 전부가 들어 있다(측정 합계 10,549초). 값은 `max(1, round(초))` 정수라 1초 미만은 1초로 올려 쳐서 표 합계는 10,641초이고, 이 표로 열두 조각을 나누면 조각마다 886–887초(측정 초로 더하면 875–883초)다.
# 한 번의 실행값이라 같은 조각도 실행마다 ±30% 흔들린다(러너 속도 차이). 다시 재는 법과 조각 수·시간 한도의 근거는 docs/CI_QT.md. 표에 없는 파일(새 시험 파일)은 QT_DEFAULT_WEIGHT(측정 중앙값 약 3초)로 친다 — 다음 진단 뒤 표에 넣는다.
# 시험 파일이 없어지거나 이름이 바뀌면 표의 낡은 이름을 지운다 — test_ci_shard 의 QtWeightsTableTest 가 지키므로, 병합 때 다른 갈래가 시험 파일을 옮기거나 지우면 이 시험이 빨개지고 낡은 이름을 모두 보여 준다.
QT_DEFAULT_WEIGHT = 3
QT_WEIGHTS = {
    "test_ui_qt_polish1": 747,
    "test_ui_qt_photo": 605,
    "test_ui_qt_photo_ocr": 544,
    "test_ui_qt_posts": 508,
    "test_ui_qt_blogs": 459,
    "test_ui_qt_drafts": 455,
    "test_ui_qt_keys": 385,
    "test_ui_qt_scale": 380,
    "test_ui_qt_references": 330,
    "test_ui_qt_seeds": 310,
    "test_ui_qt_candidates": 284,
    "test_ui_qt_photo_save": 246,
    "test_ui_qt_polish2": 229,
    "test_ui_qt_settings": 197,
    "test_ui_qt_blogs_add": 180,
    "test_ui_qt_photo_ocr_flow": 176,
    "test_ui_qt_cdesign": 169,
    "test_ui_qt": 166,
    "test_ui_qt_backup": 166,
    "test_ui_qt_photo_rows": 165,
    "test_ui_qt_photo_unsavable": 158,
    "test_pages_publish": 157,
    "test_ui_qt_l2": 154,
    "test_ui_qt_style": 148,
    "test_ui_qt_photo_keys": 112,
    "test_ui_qt_drafts_save": 106,
    "test_service_recovery": 104,
    "test_service_candidates_process": 99,
    "test_ui_qt_names": 93,
    "test_ui_qt_c1d": 89,
    "test_service_echo": 87,
    "test_service_repolock": 80,
    "test_ui_qt_photo_dialog": 78,
    "test_ui_qt_photo_leave": 76,
    "test_service_backup_flow": 74,
    "test_ui_qt_c1a": 70,
    "test_ui_qt_blogs_topic": 61,
    "test_service_keys_cli": 60,
    "test_pages_repo": 59,
    "test_ui_qt_diagnostics": 57,
    "test_ui_qt_photo_interplay": 56,
    "test_content_schema_guard": 45,
    "test_service_backup_restore": 45,
    "test_service_unpushed": 44,
    "test_service_draft_store": 41,
    "test_ui_qt_drawer_names": 41,
    "test_topicdb_backup": 38,
    "test_ui_ocr_adapter": 37,
    "test_ui_qt_chip_keys": 37,
    "test_content_draft_body": 34,
    "test_service_backup_interrupt": 34,
    "test_service_backup_secrets": 34,
    "test_service_backup_structure": 33,
    "test_service_suggest_process": 32,
    "test_topics_generate": 32,
    "test_service_backup_live_structure": 30,
    "test_net_tls": 27,
    "test_auto_pr_workflow": 25,
    "test_service_draft_process": 25,
    "test_topics_health_stages": 24,
    "test_vendor_core": 24,
    "test_service_pages_git": 23,
    "test_service_quota_legacy_locale": 23,
    "test_service_backup_gaps": 22,
    "test_content_migration": 20,
    "test_topics_health_coverage": 20,
    "test_external_write_gate": 19,
    "test_service_pages_flow": 19,
    "test_ui_backup_adapter": 19,
    "test_service_backup_postcopy": 18,
    "test_ui_secret_places_speed": 18,
    "test_service_quota": 17,
    "test_content_candidates_store": 16,
    "test_release_check_scan": 16,
    "test_service_cli": 16,
    "test_service_topics": 16,
    "test_ui_sentence_color": 16,
    "test_check_claims_accuracy": 15,
    "test_packaging_build": 15,
    "test_packaging_manifest": 15,
    "test_service_cli_hardening": 15,
    "test_ui_drafts_core": 15,
    "test_net_allowlist": 14,
    "test_service_topics_cli": 14,
    "test_content_style_stats_perf": 13,
    "test_security_errorlog": 13,
    "test_security_scan": 13,
    "test_service_candidates": 13,
    "test_net_zero": 12,
    "test_service_gate_hardening": 12,
    "test_service_naver_hub_quota": 12,
    "test_single_instance": 12,
    "test_ui_candidates_service": 12,
    "test_ui_qt_error_wording": 12,
    "test_content_photo_text_body": 11,
    "test_content_store": 11,
    "test_service_candidates_cli": 11,
    "test_service_pushed_post": 11,
    "test_topics_health_context": 11,
    "test_ci_shard": 10,
    "test_security_mask_engine": 10,
    "test_service_draft_body": 10,
    "test_service_references": 10,
    "test_service_suggest_cli": 10,
    "test_service_suggestions": 10,
    "test_suggest": 10,
    "test_ui_core": 10,
    "test_ui_qt_plain_text": 10,
    "test_content_draft_plan": 9,
    "test_ocr_worker_guard": 9,
    "test_security_recent_shapes": 9,
    "test_service_backup_links": 9,
    "test_service_backup_paths": 9,
    "test_service_backup_saved_drafts": 9,
    "test_service_connections": 9,
    "test_installer_spike_flow": 8,
    "test_release_check": 8,
    "test_repo_layout": 8,
    "test_secret_shape_refusal": 8,
    "test_service_blog_profiles": 8,
    "test_service_lock": 8,
    "test_service_seed_manage": 8,
    "test_topics_hold_cleanup": 8,
    "test_ui_qt_backup_live_structure": 8,
    "test_ui_qt_c1c": 8,
    "test_check_claims": 7,
    "test_security_boundary": 7,
    "test_service_draft": 7,
    "test_ui_c1c_adapters": 7,
    "test_ui_photo_save_service": 7,
    "test_c2_fix_round": 6,
    "test_content_l5_wording": 6,
    "test_service_backup_deepjson": 6,
    "test_service_backup_wal": 6,
    "test_source_rules_output": 6,
    "test_topicdb_backup_limits": 6,
    "test_ui_imagegate": 6,
    "test_ui_ocr_provider": 6,
    "test_ui_photo_text_body": 6,
    "test_ui_seeds_core": 6,
    "test_check_garbage_perf": 5,
    "test_external_write_bare_repo": 5,
    "test_local_ocr_gate": 5,
    "test_packaging_entry": 5,
    "test_security_boundary_qt": 5,
    "test_service_photo_manifest": 5,
    "test_service_review": 5,
    "test_suggest_data": 5,
    "test_ui_backup_core": 5,
    "test_ui_posts_core": 5,
    "test_vendor_pin": 5,
    "test_check_garbage_normal": 4,
    "test_check_similarity": 4,
    "test_errors_catalog": 4,
    "test_installer_spike_measure": 4,
    "test_packaging_path": 4,
    "test_service_draft_engine": 4,
    "test_service_header_values": 4,
    "test_service_safety": 4,
    "test_source_rules_outgoing": 4,
    "test_topicdb_backup_links": 4,
    "test_topicdb_store": 4,
    "test_topics_season_order": 4,
    "test_topics_slots": 4,
    "test_ui_drafts_service": 4,
    "test_ui_launcher": 4,
    "test_ui_posts_adapter": 4,
    "test_content_body_library": 3,
    "test_content_photo_make": 3,
    "test_docs_entrance": 3,
    "test_ocr_addon_build_flow": 3,
    "test_ocr_addon_verify_release": 3,
    "test_security_decoded_scan": 3,
    "test_security_mask_sk": 3,
    "test_service_blog_profiles_topic": 3,
    "test_service_draft_backup_scan": 3,
    "test_service_draft_token": 3,
    "test_source_rules_diagnostics": 3,
    "test_source_rules_key_display": 3,
    "test_topics_brand": 3,
    "test_topics_corpus": 3,
    "test_ui_backup_live_structure": 3,
    "test_ui_candidates_core": 3,
    "test_ui_drafts_save_core": 3,
    "test_ui_drafts_save_service": 3,
    "test_ui_keys_adapter": 3,
    "test_ui_photo_core": 3,
    "test_ui_qt_ocr_input": 3,
    "test_backup_credential_note": 2,
    "test_c2b_pronoun_rule": 2,
    "test_content_draft_options": 2,
    "test_external_write_zero": 2,
    "test_net_client": 2,
    "test_net_switches": 2,
    "test_render_markdown": 2,
    "test_security_boundary_matrix": 2,
    "test_service_doctor": 2,
    "test_service_naver_hub_registry": 2,
    "test_service_orphan": 2,
    "test_service_own_posts": 2,
    "test_service_projects": 2,
    "test_topic_protect_suggest": 2,
    "test_topic_protect_ui": 2,
    "test_ui_adapters": 2,
    "test_ui_blogs_add": 2,
    "test_ui_blogs_core": 2,
    "test_ui_blogs_topic": 2,
    "test_ui_keys_core": 2,
    "test_ui_named_secret_gate": 2,
    "test_ui_photo_copy_core": 2,
    "test_ui_photo_save_core": 2,
    "test_ui_settings": 2,
    "test_blogger_input_off": 1,
    "test_c2_fix_round2": 1,
    "test_c2_mutants_other": 1,
    "test_c2_mutation_gaps": 1,
    "test_candidate_csv": 1,
    "test_check_claims_disguise": 1,
    "test_check_claims_mutants": 1,
    "test_check_claims_regression": 1,
    "test_check_garbage": 1,
    "test_check_garbage_mutants": 1,
    "test_check_profile_options": 1,
    "test_ci_qt_setup": 1,
    "test_ci_workflow_qt": 1,
    "test_content_body_lang": 1,
    "test_content_candidates": 1,
    "test_content_candidates_batch": 1,
    "test_content_model": 1,
    "test_content_photo_flow": 1,
    "test_content_photo_manifest": 1,
    "test_content_photo_ocr": 1,
    "test_content_polish1": 1,
    "test_content_post_types": 1,
    "test_content_saved_draft": 1,
    "test_content_style_stats": 1,
    "test_content_unc_uri": 1,
    "test_decision_index": 1,
    "test_errors_wording": 1,
    "test_installer_spike_apps": 1,
    "test_installer_spike_docs": 1,
    "test_installer_spike_fetch": 1,
    "test_installer_spike_workflow": 1,
    "test_l8_docs": 1,
    "test_l8b_docs": 1,
    "test_naver_profile_cli": 1,
    "test_naver_profile_options": 1,
    "test_naver_profiles": 1,
    "test_net_parse": 1,
    "test_ocr_addon_build_check": 1,
    "test_ocr_addon_build_rules": 1,
    "test_ocr_addon_docs_facts": 1,
    "test_ocr_addon_fetch": 1,
    "test_ocr_addon_merged_flow": 1,
    "test_ocr_addon_notices": 1,
    "test_ocr_netguard": 1,
    "test_ocr_protocol_same": 1,
    "test_package_ocr_workflow": 1,
    "test_packaging_common": 1,
    "test_packaging_docs": 1,
    "test_packaging_qt": 1,
    "test_packaging_version_info": 1,
    "test_packaging_workflow": 1,
    "test_pages_deploy": 1,
    "test_pages_render": 1,
    "test_render_naver": 1,
    "test_render_naver_polish2": 1,
    "test_reserved_device_names": 1,
    "test_season_match": 1,
    "test_security_as2b_docs": 1,
    "test_security_keystore": 1,
    "test_security_keystore_exists": 1,
    "test_security_mask": 1,
    "test_security_mask_boundary": 1,
    "test_security_mask_client_id": 1,
    "test_security_scan_docs": 1,
    "test_security_scan_shapes": 1,
    "test_security_shape": 1,
    "test_service_backup_rules": 1,
    "test_service_data_dir_profile": 1,
    "test_service_draft_address": 1,
    "test_service_gate": 1,
    "test_service_journal_deep": 1,
    "test_service_key_limits": 1,
    "test_service_ocr_addon": 1,
    "test_service_preview": 1,
    "test_service_seed_import": 1,
    "test_service_topic_files": 1,
    "test_service_workspace": 1,
    "test_service_write_json": 1,
    "test_source_rules_ui_text": 1,
    "test_suggest_assess": 1,
    "test_suggest_score": 1,
    "test_suggest_text": 1,
    "test_topic_protect_candidates": 1,
    "test_topicdb_rules": 1,
    "test_topics_channels": 1,
    "test_topics_concepts": 1,
    "test_topics_dedupe": 1,
    "test_topics_expand": 1,
    "test_topics_expand_exceptions": 1,
    "test_topics_feasibility": 1,
    "test_topics_history": 1,
    "test_topics_hold": 1,
    "test_topics_interest": 1,
    "test_topics_legacy_rules": 1,
    "test_topics_link": 1,
    "test_topics_messages": 1,
    "test_topics_model": 1,
    "test_topics_notice": 1,
    "test_topics_profile_v2": 1,
    "test_topics_review": 1,
    "test_topics_rules": 1,
    "test_topics_safety": 1,
    "test_topics_schedule": 1,
    "test_topics_score": 1,
    "test_topics_season_and_type": 1,
    "test_topics_seeds": 1,
    "test_topics_seeds_v2": 1,
    "test_topics_select": 1,
    "test_topics_target_rules": 1,
    "test_topics_trend": 1,
    "test_topics_wording": 1,
    "test_ui_backup_structure": 1,
    "test_ui_blog_options": 1,
    "test_ui_c1a_core": 1,
    "test_ui_c1c_core": 1,
    "test_ui_c1d_core": 1,
    "test_ui_cdesign_core": 1,
    "test_ui_channel_names": 1,
    "test_ui_diagnostics_core": 1,
    "test_ui_gate_branches": 1,
    "test_ui_home_saved_drafts": 1,
    "test_ui_l2_core": 1,
    "test_ui_photo_adapter": 1,
    "test_ui_photo_interplay": 1,
    "test_ui_photo_make_core": 1,
    "test_ui_photo_ocr_core": 1,
    "test_ui_photo_ocr_panel": 1,
    "test_ui_photo_ocr_regen": 1,
    "test_ui_photo_restore_reserve": 1,
    "test_ui_polish1_core": 1,
    "test_ui_polish2_core": 1,
    "test_ui_posts_matrix": 1,
    "test_ui_qt_imagegate": 1,
    "test_ui_qt_images": 1,
    "test_ui_references_adapter": 1,
    "test_ui_references_core": 1,
    "test_ui_style_core": 1,
    "test_ui_winroot": 1,
    "test_v1_docs": 1,
    "test_workflow_artifacts": 1,
    "test_workflow_golden": 1,
    "test_workflow_yaml_support": 1,
}


def module_of(test):
    """시험 한 개가 속한 시험 파일(모듈) 이름. 불러오기에 실패했거나 불러오다 건너뛴 파일은 클래스가 `unittest.loader` 안에 있고 파일 이름이 시험 이름에 들어 있다."""
    cls = type(test)
    if cls.__module__ == "unittest.loader":
        return getattr(test, "_testMethodName", cls.__name__)
    return cls.__module__


def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaves(item)
        else:
            yield item


def discover(tests_dir=TESTS):
    """`unittest discover -s tests` 와 같은 방식으로 시험을 찾아 {파일 이름: [시험, ...]}(이름 순)로 돌려준다."""
    sys.path.insert(0, str(ROOT))                          # `python -m unittest` 는 현재 폴더(저장소 맨 위)를 먼저 찾는다 — 같게
    suite = unittest.TestLoader().discover(str(tests_dir), pattern="test*.py", top_level_dir=str(tests_dir))
    found = {}
    for test in leaves(suite):
        found.setdefault(module_of(test), []).append(test)
    return dict(sorted(found.items()))


def weight_of(name, weights=None, default=None):
    """시험 파일 하나의 무게(초 어림) — 표를 안 주면 기본 표(`WEIGHTS`·`DEFAULT_WEIGHT`), 주면 그 표와 그 기본 무게(안 주면 `DEFAULT_WEIGHT`)만 쓴다."""
    table = WEIGHTS if weights is None else weights
    return table.get(name, DEFAULT_WEIGHT if default is None else default)


def weights_table(env):
    """환경 변수 CI_WEIGHTS 를 읽어 (표 이름, 무게 표, 기본 무게)를 돌려준다 — 없음·빈 값이면 ("", WEIGHTS, DEFAULT_WEIGHT)로 정식 CI 열두 칸의 오늘 동작과 같고, `qt` 면 ("qt", QT_WEIGHTS, QT_DEFAULT_WEIGHT)이며,
    그 밖의 값은 ValueError 다(오타로 기본 표를 쓴 채 Qt 칸 조각이 쏠려 시간 한도에 걸리지 않게)."""
    value = env.get(WEIGHTS_FLAG)
    if value in (None, ""):
        return "", WEIGHTS, DEFAULT_WEIGHT
    if value == "qt":
        return "qt", QT_WEIGHTS, QT_DEFAULT_WEIGHT
    raise ValueError(f"{WEIGHTS_FLAG} 는 qt 이거나 없어야 한다: {value!r}")


def assign(names, total, weights=None, default=None):
    """{파일 이름: 조각 번호(1..total)}. 무거운 파일부터(같으면 이름 순) 지금 가장 가벼운 조각(같으면 번호가 작은 쪽)에 넣는다 — 같은 입력이면 늘 같은 결과.
    무게 표(`weights`)와 그 기본 무게(`default`)를 주면 환경이나 모듈의 상수에 기대지 않는 순수 함수다(Qt 칸 — D-717). 안 주면 기본 표라 정식 CI 열두 칸의 오늘 동작과 같다."""
    heap = [(0, index) for index in range(1, total + 1)]
    heapq.heapify(heap)
    table = {}
    for name in sorted(names, key=lambda item: (-weight_of(item, weights, default), item)):
        load, index = heapq.heappop(heap)
        table[name] = index
        heapq.heappush(heap, (load + weight_of(name, weights, default), index))
    return table


def parse(argv, env):
    """(조각 번호, 조각 수, 옵션) — 잘못된 입력이면 ValueError."""
    options = {}
    words = []
    for item in argv:
        if item.startswith("--"):
            key, has_value, value = item.partition("=")
            if key not in ("--list", "--tests-dir"):
                raise ValueError(f"모르는 옵션: {key}")
            if (key == "--tests-dir") != bool(has_value) or (key == "--tests-dir" and not value):
                raise ValueError(f"옵션 모양이 틀리다: {item} (--list 는 값 없이, --tests-dir=폴더 는 값과 함께)")
            options[key] = value if has_value else True
        else:
            words.append(item)
    if len(words) not in (0, 2):
        raise ValueError("조각 번호와 조각 수를 둘 다 주거나 아무것도 주지 않는다")
    if words:
        shard_text, total_text = words
    else:
        shard_text, total_text = env.get("CI_SHARD"), env.get("CI_SHARD_TOTAL")
        if shard_text is None and total_text is None:
            shard_text = total_text = "1"                  # 아무것도 안 주면 조각 하나(= 전체)
        elif shard_text is None or total_text is None:
            raise ValueError("CI_SHARD 와 CI_SHARD_TOTAL 은 둘 다 있거나 둘 다 없어야 한다")
    try:
        shard, total = int(shard_text), int(total_text)
    except (TypeError, ValueError):
        raise ValueError(f"조각 번호·조각 수가 정수가 아니다: {shard_text!r} {total_text!r}") from None
    if not 1 <= total <= MAX_SHARDS or not 1 <= shard <= total:
        raise ValueError(f"조각 번호는 1~조각 수, 조각 수는 1~{MAX_SHARDS} 여야 한다: {shard}/{total}")
    return shard, total, options


def make_runner():
    """시험 실패·오류 글에서 비밀 모양을 가리는 러너(`tests/secret_support.MaskingTextTestRunner` — PCSEC1 H1: 옛 시험의 `assertNotIn(비밀, 출력)` 이 실패해도 비밀을 찍지 않는다).
    못 불러오면 보통 러너로 돌아가되 그 사실을 표준 오류로 알린다(시험 결과·종료 코드는 어느 쪽이든 같다)."""
    try:
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(TESTS))
        from secret_support import MaskingTextTestRunner
    except Exception as error:
        print(f"가리는 시험 러너를 불러오지 못해 보통 러너로 돌린다({type(error).__name__})", file=sys.stderr, flush=True)
        return unittest.TextTestRunner(verbosity=2)
    return MaskingTextTestRunner(verbosity=2)


def qt_required(env):
    """환경 변수 CI_REQUIRE_QT 를 읽는다 — 1 이면 켬(True), 없음·빈 값·0 이면 끔(False), 그 밖의 값은 ValueError(오타로 가드가 꺼진 채 초록이 되지 않게)."""
    value = env.get(QT_FLAG)
    if value in (None, "", "0"):
        return False
    if value == "1":
        return True
    raise ValueError(f"{QT_FLAG} 는 1(켬)이거나 없어야 한다(0 은 끔): {value!r}")


def qt_installed():
    """이 파이썬이 PySide6 를 찾을 수 있는가 — Qt 시험 파일이 건너뜀을 정할 때 쓰는 `find_spec("PySide6")` 와 같은 질문."""
    return importlib.util.find_spec("PySide6") is not None


def skipped_module(test):
    """건너뛴 시험이 속한 시험 파일 이름. `module_of` 에 더해 `setUpClass`·`setUpModule` 에서 건너뛴 것(설명이 `setUpClass (파일.클래스)` 인 자리 표시)도 읽는다."""
    description = getattr(test, "description", None)
    if type(test).__name__ == "_ErrorHolder" and isinstance(description, str):
        found = re.search(r"\(([^()\s]+)\)\s*$", description)
        return found.group(1).split(".")[0] if found else description
    return module_of(test)


def qt_skip_report(skipped):
    """(PySide6 이유로 건너뛴 시험의 {시험 파일: 개수}, 그 밖의 이유별 {이유: 개수}) — `result.skipped` 의 (시험, 이유) 목록에서."""
    qt_skips, other = {}, {}
    for test, reason in skipped:
        text = " ".join(str(reason).split())
        if QT_WORD in text.casefold():
            name = skipped_module(test)
            qt_skips[name] = qt_skips.get(name, 0) + 1
        else:
            other[text] = other.get(text, 0) + 1
    return dict(sorted(qt_skips.items())), other


def timed(result_class):
    """결과 클래스에 '시험 파일마다 걸린 시간'을 세는 기능을 더한다(Qt 칸에서 `QT_WEIGHTS` 를 고칠 값을 얻으려고). 시험의 실행·결과는 바꾸지 않는다.
    시간은 앞 시험이 끝난 때부터 이 시험이 끝난 때까지를 이 시험의 파일에 더한다 — 그래서 합이 조각의 실행 시간과 같고 클래스 준비·정리 시간은 다음 시험에 붙는다."""
    class Timed(result_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.module_seconds = {}
            self._mark = time.perf_counter()
            self._current = None

        def startTestRun(self):
            super().startTestRun()
            self._mark = time.perf_counter()

        def stopTest(self, test):
            super().stopTest(test)
            now = time.perf_counter()
            name = module_of(test)
            if self._current is not None and name != self._current and self.module_seconds.get(self._current, 0.0) >= PROGRESS_SECONDS:
                print(f"[걸린 시간] {self._current} {self.module_seconds[self._current]:,.1f}초", flush=True)         # 앞 파일이 끝났다 — 마지막 파일은 끝의 표가 맡는다
            self._current = name
            self.module_seconds[name] = self.module_seconds.get(name, 0.0) + now - self._mark
            self._mark = now
    return Timed


def print_qt_information(result, qt_skips, other):
    """Qt 칸의 정보 출력 — 건너뜀 이유별 개수와 시험 파일별 걸린 시간(표준 출력)."""
    print(f"건너뛴 시험 {len(result.skipped)}개 — PySide6 이유 {sum(qt_skips.values())}개(0 이어야 한다)·그 밖의 이유 {sum(other.values())}개(알림만, 첫 실행 뒤 허용 목록으로 굳힌다)", flush=True)
    for reason, count in sorted(other.items(), key=lambda item: (-item[1], item[0]))[:REASON_LIMIT]:
        print(f"  {count}개  {reason[:120]}", flush=True)
    if len(other) > REASON_LIMIT:
        print(f"  … 그 밖의 이유 {len(other) - REASON_LIMIT}가지", flush=True)
    seconds = getattr(result, "module_seconds", {})
    if seconds:
        ranked = sorted(seconds.items(), key=lambda item: (-item[1], item[0]))
        print(f"시험 파일별 걸린 시간(초, 이 조각 합계 {sum(seconds.values()):,.0f}초 — 오래 걸린 순 상위 {min(TIME_LIMIT, len(ranked))}개, `QT_WEIGHTS` 를 고칠 때 쓴다):", flush=True)
        for name, value in ranked[:TIME_LIMIT]:
            print(f"  {name} {value:,.1f}", flush=True)


def qt_guard(result):
    """Qt 칸의 건너뜀 가드 — PySide6 이유로 건너뛴 시험이 하나라도 있으면 1(그 개수를 시험 파일별로 찍는다), 없으면 0. 정보도 함께 찍는다."""
    qt_skips, other = qt_skip_report(result.skipped)
    print_qt_information(result, qt_skips, other)
    if not qt_skips:
        return 0
    print(f"Qt 칸: PySide6 가 없다는 이유로 건너뛴 시험이 {sum(qt_skips.values())}개 있다 — 화면(Qt) 시험이 돌지 않은 채 초록이 되는 것을 막으려고 이 칸을 빨갛게 한다. 시험 파일별 개수:", file=sys.stderr, flush=True)
    for name, count in list(qt_skips.items())[:FILE_LIMIT]:
        print(f"  {name}: {count}개", file=sys.stderr, flush=True)
    if len(qt_skips) > FILE_LIMIT:
        print(f"  … 그 밖의 시험 파일 {len(qt_skips) - FILE_LIMIT}개", file=sys.stderr, flush=True)
    return 1


def main(argv=None, env=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    try:
        shard, total, options = parse(argv, env)
    except ValueError as error:
        print(f"조각을 정하지 못했다: {error}", file=sys.stderr)
        return 2
    try:
        require_qt = qt_required(env)
    except ValueError as error:
        print(f"Qt 칸 표시를 읽지 못했다: {error}", file=sys.stderr)
        return 2
    try:
        table_name, weights, default = weights_table(env)
    except ValueError as error:
        print(f"무게 표를 읽지 못했다: {error}", file=sys.stderr)
        return 2
    if require_qt and "--list" not in options and not qt_installed():
        print(f"{QT_FLAG}=1 인데 PySide6 를 찾지 못했다 — 이대로 돌면 화면(Qt) 시험이 모두 건너뛰어져 초록이 된다. 이 칸의 설치 단계(scripts/ci_qt_setup.py)를 확인하라", file=sys.stderr)
        return 3
    tests_dir = Path(options["--tests-dir"]) if isinstance(options.get("--tests-dir"), str) else TESTS
    found = discover(tests_dir)
    table = assign(found, total, weights, default)
    if sorted(table) != sorted(found):
        print("조각 나누기가 시험 파일을 빠뜨리거나 겹쳤다 — 나누는 코드의 오류", file=sys.stderr)
        return 2
    mine = [name for name in found if table[name] == shard]
    if "--list" in options:
        print("\n".join(mine))
        return 0
    if not mine:
        print(f"조각 {shard}/{total} 에 들어갈 시험 파일이 없다(시험 파일 {len(found)}개) — 조각 수를 줄여라", file=sys.stderr)
        return 1
    tests = [test for name in mine for test in found[name]]
    everything = sum(len(items) for items in found.values())
    plan = f" — 무게 표 {table_name}: 이 조각 {sum(weight_of(name, weights, default) for name in mine):,}초" if table_name else ""         # Qt 칸에서만 — 계획과 아래 실제 시간을 로그에서 견준다
    print(f"조각 {shard}/{total}: 시험 파일 {len(mine)}개·시험 {len(tests):,}개 (전체 {len(found)}개 파일·{everything:,}개 시험){plan}", flush=True)
    runner = make_runner()
    if require_qt:
        runner.resultclass = timed(runner.resultclass)
    result = runner.run(unittest.TestSuite(tests))
    code = 0 if result.wasSuccessful() else 1
    if require_qt:
        code = max(code, qt_guard(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
