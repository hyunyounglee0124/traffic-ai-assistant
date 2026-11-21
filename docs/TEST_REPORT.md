# 테스트·검증 결과

## 1. 자동 테스트 (pytest)

실제 Codyssey 서버는 호출하지 않고, `httpx.MockTransport`로 가짜 응답을 돌려주면서 **우리 앱이 보내는 요청 형식**과 **응답 처리**를 검사합니다. 테스트마다 임시 DB를 새로 만들어 서로 영향을 주지 않습니다.

```bash
pytest -v
```

| 파일 | 대상 기능 | 테스트 |
|---|---|---|
| `tests/test_records.py` | ② CRUD | 추가→조회→수정→삭제 전체 흐름 + 변경 시 분석 자동 저장, 입력 검증 6가지(422), 중복 날짜(409)·없는 id(404), 기간·메모 검색·페이지·CSV, SQL 인젝션 |
| `tests/test_analysis.py` | ③ 분석·저장 | 요약 통계 값(최고·이상치·추세·요일·7일 평균), 빈 데이터, 시드 분석 저장·재실행·이력, 7일 이동평균 계산 |
| `tests/test_chat.py` | ① 채팅 · ④ 기록 | OpenAI 호환 요청(주소·Bearer 헤더·모델·시스템 프롬프트에 요약과 관련 기록 포함), Anthropic 호환 요청(x-api-key·anthropic-version·system), 이어지는 질문에 이전 대화 포함, 키 없음·401 오류·시간 초과 시 대체 답변, **키가 응답·기록·상태 API에 노출되지 않음**, 질문 검증, 대화 기록 조회·삭제, 날짜 표현 해석 9가지, 메모 검색어 |

### 실행 결과 (Python 3.13, 최신 버전)
```
tests/test_analysis.py::test_summary_values PASSED                       [  5%]
tests/test_analysis.py::test_summary_text_and_empty PASSED               [ 10%]
tests/test_analysis.py::test_snapshot_saved_and_refresh PASSED           [ 15%]
tests/test_analysis.py::test_series_moving_average PASSED                [ 20%]
tests/test_chat.py::test_openai_compatible_request_format PASSED         [ 25%]
tests/test_chat.py::test_anthropic_compatible_request_format PASSED      [ 30%]
tests/test_chat.py::test_previous_turns_are_sent_for_follow_up PASSED    [ 35%]
tests/test_chat.py::test_fallback_without_key PASSED                     [ 40%]
tests/test_chat.py::test_fallback_on_server_error_and_no_key_leak PASSED [ 45%]
tests/test_chat.py::test_fallback_on_timeout PASSED                      [ 50%]
tests/test_chat.py::test_question_validation PASSED                      [ 55%]
tests/test_chat.py::test_chat_history_crud PASSED                        [ 60%]
tests/test_chat.py::test_find_ranges_parsing PASSED                      [ 65%]
tests/test_chat.py::test_memo_keyword_context PASSED                     [ 70%]
tests/test_chat.py::test_index_and_health PASSED                         [ 75%]
tests/test_records.py::test_create_read_update_delete PASSED             [ 80%]
tests/test_records.py::test_validation_errors PASSED                     [ 85%]
tests/test_records.py::test_duplicate_date_and_missing PASSED            [ 90%]
tests/test_records.py::test_filter_search_paging_export PASSED           [ 95%]
tests/test_records.py::test_sql_injection_is_harmless PASSED             [100%]
============================== 20 passed in 1.65s ==============================
```

### 최소 버전 환경 재현
Python **3.10.20** + fastapi 0.110.0 · pydantic 2.6.0 · httpx 0.27.0 · uvicorn 0.29.0 · python-dotenv 1.0.0 · pandas 2.2.0 · pytest 8.0.0 (`requirements.txt`의 하한 버전)
```
20 passed
```

## 2. 화면 동작 확인 (브라우저 자동화)
실제 서버를 띄우고 Chrome으로 기능별로 조작해 캡처했습니다(`docs/screenshots/`).

| 확인 항목 | 결과 |
|---|---|
| 질문 전송 중 로딩 표시(점 애니메이션, 경과 초, 버튼 비활성화) | ✅ 캡처 00 |
| 키 없음 → 데이터 요약 답변, '근거 보기' 펼치기 | ✅ 캡처 01, 02 |
| AI 서버 응답 지연(6초 초과) → 원인 표시 + 대체 답변 | ✅ 캡처 13 |
| 대시보드: 요약 카드·이동평균 차트·월별·요일별·이상치·분석 저장 이력, 기간 바꾸기 | ✅ 캡처 03, 04 |
| CRUD: 추가 → 수정 → 중복 날짜 오류 → 삭제 → 메모 검색, 변경마다 "분석 결과 #N 저장" 안내 | ✅ 캡처 05~11 |
| 대화 기록 목록·삭제 버튼 | ✅ 캡처 12 |
| 브라우저 콘솔 오류 | 의도한 409(중복 날짜 테스트) 외 없음 |

## 3. 보안 점검
| 항목 | 결과 |
|---|---|
| 저장소 전체에서 키 형태 문자열(`sk-cody-live…`) 검색 | 없음 (테스트용 가짜 키만 존재) |
| `.env` 파일 포함 여부 | 미포함, `.gitignore`에 등록 |
| 키를 출력·로그·저장하는 코드 | 없음. `scripts/check_api.py`도 앞 12자·뒤 4자만 가려서 표시 |

## 4. 직접 확인해야 하는 것
- **실제 AI 응답**: 작업 환경에서 `copa.codyssey.kr`에 접속할 수 없어 실제 호출은 하지 못했습니다. `.env`에 키를 넣고 `python scripts/check_api.py` → `uvicorn app.main:app` 순서로 확인하세요.
