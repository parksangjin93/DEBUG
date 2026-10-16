# QA Automation - 실시간 로그 판정기

SecureCRT 로 테스트하면서 나오는 디버그 로그를 실시간으로 읽어
TC 규칙에 따라 PASS / FAIL / TIMEOUT 을 자동 판정하고 엑셀 리포트를 만든다.

**전제**: 테스트 조작(전원, 설정 변경 등)은 사람이 한다. 이 프로그램은 판정만 한다.

---

## 설치

```
pip install openpyxl
```

## 안 될 때 제일 먼저

```
python main.py --check
```

경로/규칙파일/TC 선택이 올바른지 전부 검사해서 문제만 짚어준다.
`run.bat --check` 로도 된다.

```
 [XVM508]
   rules    : OK  tc/common.csv
   [NG] log_dir 폴더 없음: C:\Users\psj\Desktop\LOG\XVM508
```

**배포된 `config/products.ini` 는 예시 경로가 들어 있다. 본인 환경에 맞게 고쳐야 한다.**

## 폴더 구조

```
qa_auto/
  qa_gui.py                   GUI 실행 진입점  <- 여기서 시작
  run_gui.bat                 GUI 실행 (더블클릭)
  main.py                     CLI 실행 진입점
  run.bat                     CLI 실행
  config/products.ini         제품별 프로파일 (로그 폴더 + TC 파일)
  core/
    profile.py                프로파일 로더
    runner.py                 제품 1개 = 파이프라인 1세트
    log_event.py              라인 정제(ANSI 제거) + 타임스탬프 파싱 + Clock
    log_source.py             폴더/파일 감시, 리플레이
    step.py                   Step / TCDefinition 모델
    verdict.py                판정 결과 모델
    tc_engine.py              TCEngine(시퀀스) / EventWatcher(단일 키워드)
    tc_manager.py             라우팅, 근거 문맥, 룰 충돌 검사
    rule_loader.py            CSV/XLSX 규칙 로더
    console.py                화면 출력
  report/
    report_generator.py       JSONL + 엑셀 리포트
  tc/
    common.csv                전 제품 공통 TC
    XVM508.csv                제품 전용 TC
    KP2S.csv
    tc_rules.csv              통합본(단일 제품용)
  tools/
    make_test_log.py          검증용 가짜 로그 생성
    selftest.py               분석기 자체 회귀 검증
  output/<제품명>/            리포트 저장 위치 (제품별 분리)
```

---

## GUI (권장 - 마우스로만 조작)

```
run_gui.bat        더블클릭
```
또는
```
python qa_gui.py
```

CLI(`main.py`)와 **완전히 같은 엔진**을 쓴다. GUI 는 껍데기라서
GUI 에서 저장한 설정은 CLI 에서도 그대로 돌아간다 (`config/products.ini` 공유).

### 사용 순서

1. **제품** 콤보에서 제품 선택. 처음이면 `[새 제품]` → 제품명 입력
2. **디버그 로그 폴더** → `[폴더 선택]` 으로 SecureCRT 로그가 쌓이는 폴더 지정
3. **TC 규칙 파일** → `[파일 추가]` 로 그 제품의 TC csv/xlsx 선택
   (여러 개 넣으면 위에서부터 병합. 공통 TC 먼저, 제품 전용 TC 나중에)
4. 아래 목록에서 **이번에 판정할 TC 만 체크**
   (`전체 선택` / `전체 해제` / 태그 입력 후 `태그로 선택`)
5. `[설정 저장]` → 다음부터는 제품만 고르면 위 내용이 그대로 복원된다
6. `[감시 시작]`

### 화면 구성

| 영역 | 내용 |
|---|---|
| 제품 | 프로파일 선택 / 새로 만들기 / 저장 / 삭제, 테스터·FW |
| 로그 / TC 설정 | 로그 폴더, 파일 패턴, TC 규칙 파일 목록 |
| TC 선택 | 체크박스 목록. 시나리오 / 이벤트감시 구분 표시, 태그 표시 |
| 실행 | 감시 시작 / 중지 / 저장된 로그 재분석 / 리포트 폴더 열기 |
| 진행 상황 | 현재 대기 중인 STEP 과 남은 시간, 판정 결과(색상 구분) |

TC 목록과 진행 상황 사이 경계선은 드래그해서 크기를 조절할 수 있다.

### 버튼 설명

- **감시 시작** : 지정한 폴더를 실시간 감시. 새 세션 로그가 생기면 자동 전환
- **중지** : 감시를 멈추고 리포트 저장
- **저장된 로그 재분석** : 장비 없이 기존 로그 파일로 판정 (TC 수정 후 검증용)
- **리포트 폴더 열기** : 해당 제품의 결과 폴더를 탐색기로 연다
- **원본 로그도 표시** : 체크하면 들어오는 로그 원문도 화면에 흐른다

### 룰 충돌 경고

시작할 때 같은 문구를 기다리는 TC 가 둘 이상이면 확인 창이 뜬다.

```
아래 TC 들이 같은 로그 문구를 기다립니다.
동시에 감시하면 오탐(잘못된 PASS / 허위 TIMEOUT)이 날 수 있습니다.

시작 트리거 중복 ['TC004', 'TC006'] : 'dvr: (osd) Format start!!'

그래도 진행할까요?
```

**"아니오" 를 누르고 한쪽 체크를 푸는 것이 맞다.** 이건 규칙 자체의 문제라
프로그램이 대신 판단해줄 수 없다.

### GUI 가 안 뜰 때

- `tkinter is missing` : 파이썬 설치 관리자에서 "tcl/tk and IDLE" 을 켜고 재설치
- 창이 떴다 바로 닫힘 : `python qa_gui.py` 로 직접 실행해서 오류 메시지 확인
- 한글이 깨짐 : 윈도우 기본 글꼴(맑은 고딕)이 없는 환경. 시스템 글꼴로 자동 대체됨

---

## CLI

## 제품이 여러 개일 때 (핵심)

제품마다 로그 폴더도 다르고 TC 파일도 다르므로, `config/products.ini` 에 등록해두고
이름으로 부른다. 명령어에 경로를 매번 적지 않아도 되고, **A 제품 로그에 B 제품 TC 를
잘못 물리는 사고**를 막을 수 있다.

```ini
[XVM508]
log_dir  = C:\Users\psj\Desktop\LOG\XVM508
rules    = tc\common.csv, tc\XVM508.csv
tc       = TC001,TC002
tester   = psj

[KP2S]
log_dir  = C:\Users\psj\Desktop\LOG\KP2S
rules    = tc\common.csv, tc\KP2S.csv
tag      = boot
tester   = psj
```

역슬래시를 그대로 쓰면 되고 따옴표도 필요 없다. `;` 로 시작하면 주석이다.

```
python main.py --products              등록된 제품 목록
python main.py -p XVM508               XVM508 감시
python main.py -p XVM508 --tc TC009    TC 만 임시로 바꿔서 실행
python main.py -p XVM508 --list        그 제품의 TC 목록
python main.py -p XVM508,KP2S          두 제품 동시 감시
```

### 여러 제품 동시 감시

`-p` 에 쉼표로 나열하면 제품마다 별도 스레드로 각자의 폴더를 감시하고,
**리포트도 제품별로 따로** 만든다. 화면 출력에는 제품명이 붙는다.

```
[XVM508]  OK   TC002 STEP 3/4 커널 시작 확인
[KP2S]    OK   TC002 STEP 3/4 커널 시작 확인
[XVM508]  [FAIL] TC001 GSNR_Event_Upload  (3.00s)
```

```
output/
  XVM508/20260729_143012_XVM508_QA_Report.xlsx
  KP2S/20260729_143012_KP2S_QA_Report.xlsx
```

한 제품에서 오류가 나도 나머지는 계속 감시한다. `Ctrl+C` 한 번이면 전부 정리 후 저장.

### TC 파일 나누는 두 가지 방법

**방법 A - 파일로 분리 (권장)**

```
rules = tc\common.csv, tc\XVM508.csv
```

앞에서부터 순서대로 병합한다. 부팅/녹화처럼 전 제품 공통인 TC 는 `common.csv` 에,
제품 고유 TC 는 제품 파일에 둔다. **같은 TC_ID 가 뒤에 또 나오면 뒤엣것이 이긴다** —
공통 TC 의 TIMEOUT 만 특정 제품에서 늘리고 싶을 때 이걸 쓰면 된다.
덮어쓴 TC 는 실행 시작할 때 화면에 표시된다.

**방법 B - 한 파일에 PRODUCT 컬럼**

TC 파일에 `PRODUCT` 컬럼을 만들면, 해당 제품 행 + 빈칸(공통) 행만 읽는다.

| TC_ID | PRODUCT | TC_NAME | ... |
|---|---|---|---|
| TC002 | | Boot Test | 전 제품 공통 |
| TC011 | KP2S | DSM_Drowsiness | KP2S 전용 |

관리할 파일을 늘리기 싫으면 이쪽. 제품이 5개를 넘어가면 방법 A 가 낫다.

### 프로파일 없이 즉석 실행

```
python main.py --log-dir "D:\LOG\TEMP" --rules tc\XVM508.csv --tc TC002
```

CLI 인자는 항상 프로파일 값보다 우선한다.

---

## 사용법 (단일 제품)


### 1. TC 목록 확인

```
python main.py --list
```

### 2. 실시간 감시 (기본 사용법)

SecureCRT 로그 **폴더**를 지정한다. 세션을 새로 열어 새 로그 파일이 생기면
자동으로 갈아탄다. 경로를 매번 고칠 필요가 없다.

```
python main.py --log-dir "C:\Users\psj\Desktop\LOG\XVM508" --tc TC002
```

여러 TC 동시 무장:

```
python main.py --log-dir "C:\Users\psj\Desktop\LOG\XVM508" --tc TC001,TC009
```

종료는 `Ctrl+C`. 종료 시 리포트가 자동 저장된다.

### 3. 저장된 로그 재분석 (장비 불필요)

TC 를 추가하거나 TIMEOUT 값을 바꾼 뒤, 어제 로그로 바로 검증할 수 있다.

```
python main.py --replay "C:\...\[2026-07-22-10시46분32초].log" --tc TC002
```

리플레이는 **로그 타임스탬프만** 사용하므로 몇 번을 돌려도 결과가 같다.

### 4. 분석기 자체 검증

엔진이나 룰을 고친 뒤 이걸 먼저 돌린다.

```
python tools/selftest.py
```

### 주요 옵션

| 옵션 | 설명 |
|---|---|
| `-p`, `--product` | products.ini 의 제품명. 쉼표로 여러 개 동시 감시 |
| `--products` | 등록된 제품 목록 출력 |
| `--check` | 설정 진단 (경로/규칙/TC 선택 검사) |
| `--config` | 프로파일 파일 경로 (기본 `config/products.ini`) |
| `--rules` | TC 규칙 파일. 쉼표로 여러 개 병합 |
| `--log-dir` | 폴더 감시 (최근 `.log` 자동 추적) |
| `--log-file` | 특정 파일 하나만 감시 |
| `--replay` | 저장된 로그 재분석 후 종료 |
| `--from-start` | 감시 시작 시 기존 내용도 처음부터 읽기 |
| `--tc` | TC_ID 선택 (쉼표 구분) |
| `--tag` / `--name` | 태그 / 이름 부분일치로 선택 |
| `--all` | 전체 무장 (오탐 주의) |
| `--tester` `--fw` | 리포트에 기록될 테스터 / FW 버전 |
| `--verbose` | 원본 로그도 화면 출력 |
| `--quiet` | 판정 결과만 출력 |
| `--encoding` | 로그 인코딩 강제 (utf-8 / cp949) |

---

## SecureCRT 설정 (중요)

### 라인별 타임스탬프를 켤 것

Session Options → Terminal → Log File → **Custom log data**
→ "On each line" 에 시각 포맷 입력 (예: `[%h:%m:%s.%t] `)

**켜지 않으면 TIMEOUT 판정이 부정확해진다.**
SecureCRT 는 로그를 버퍼링해서 쓰기 때문에, 장비가 5초에 출력한 줄을
프로그램이 7초에 읽을 수 있다. TIMEOUT 5초 스텝이 정상인데도 실패로 찍힌다.
타임스탬프가 있으면 "장비가 출력한 시각" 기준으로 판정한다.

지원 포맷:
- `[2026-07-22 10:46:32.123]`
- `[07/22 10:46:32.123]`
- `[10:46:32.123]` / `[10:46:32]`

### 로그 파일명

`Log file name` 에 날짜가 들어가면 (`[2026-07-22-10시46분32초].log` 등)
시:분:초만 있는 타임스탬프의 날짜 기준으로 자동 사용한다.

---

## TC 규칙 파일 (`tc/tc_rules.csv`)

| 컬럼 | 필수 | 설명 |
|---|---|---|
| `TC_ID` | ○ | TC001 형식. `--tc` 로 선택할 때 쓰는 키 |
| `TC_NAME` | ○ | TC 이름 |
| `TEST_PURPOSE` | | 목적. 리포트에 그대로 들어감 |
| `STEP` | ○ | 스텝 번호. **행 순서가 아니라 이 값으로 정렬한다** |
| `TEST_METHOD` | | 사람이 읽는 스텝 설명 |
| `TYPE` | | `CHECK`(나와야 함) 또는 `ABSENT`(나오면 안 됨) |
| `VALUE` | ○ | 통과 조건 문자열 |
| `FAIL` | | 이게 나오면 즉시 FAIL |
| `TIMEOUT` | | 이전 스텝 완료 후 이 초 안에 나와야 함. `ABSENT` 는 감시 구간 길이 |
| `MATCH` | | `CONTAINS`(기본) 또는 `REGEX` |
| `PRODUCT` | | 제품명. 비우면 전 제품 공통 행 |
| `TAG` | | 쉼표 구분. `--tag` 로 묶음 실행 |
| `MODE` | | `SEQUENCE` / `EVENT` (미지정 시 자동) |
| `COOLDOWN` | | EVENT 재기록 최소 간격(초), 기본 10 |

### ABSENT - "이 문구가 나오면 실패"

`TYPE=ABSENT` 로 두면 **지정한 시간 동안 그 문구가 나오지 않아야** 통과한다.
부팅 중 재부팅, 커널 panic, watchdog reset 처럼 "없어야 정상"인 항목에 쓴다.

```
TC_ID,STEP,TYPE,VALUE,TIMEOUT
TC900,1,CHECK ,U-Boot 2019   ,
TC900,2,ABSENT,U-Boot 2019   ,30     <- 30초 안에 또 뜨면 재부팅 = FAIL
TC900,3,CHECK ,BOOT COMPLETE ,60
```

ABSENT 는 **차단이 아니라 동시 감시**다. STEP 2 가 30초를 세는 동안에도
STEP 3 의 통과 조건을 계속 확인한다. 즉 "부팅이 진행되는 내내 재부팅이 없어야 한다"가
정확히 표현된다.

- `TIMEOUT` 필수. 없으면 시작할 때 경고가 뜬다.
- STEP 1 은 ABSENT 로 둘 수 없다 (TC 를 시작시킬 트리거가 없으므로).

### 미완성 TC (VALUE 미입력)

`VALUE` 가 `TODO` 로 시작하면 **미완성**으로 표시하고 실행에서 제외한다.
옛 TC 문서를 옮겨오는 중에 로그 키워드를 아직 못 채운 항목을 관리하기 위한 것이다.
GUI 목록에서 주황색 `미완성 N` 으로 보인다.

### 정규식 사용 예

```
MATCH=REGEX,  VALUE=http status code \[(?P<code>200)\]
```

캡처 그룹은 근거(evidence)에 함께 기록된다.

### 파일 형식은 자동 판별된다

구분자(쉼표 / 탭 / 세미콜론 / 세로줄)와 인코딩(UTF-8 / CP949)을 자동으로 감지한다.
엑셀에서 "텍스트(탭으로 분리)" 로 저장했거나, 엑셀에서 복사해 메모장에 붙여넣은
파일도 그대로 읽힌다. 헤더 위에 제목 행이 있어도 건너뛴다.

TC 목록을 불러오면 화면 아래에 어떤 형식으로 읽었는지 표시된다.

```
TC 26개 로드 (구분자: 탭, 인코딩: cp949)
```

읽지 못하면 원인과 해결 방법을 알려준다. 그래도 안 되면 엑셀에서
[다른 이름으로 저장] → **CSV UTF-8(쉼표로 분리)** 로 저장하면 확실하다.

### CSV 를 정본으로 쓸 것

Excel(.xlsx)도 읽을 수 있지만, **git 에서 diff 가 되는 CSV 를 정본으로** 두는 편이 낫다.
"누가 TIMEOUT 을 30에서 60으로 왜 바꿨는지"를 추적할 수 있어야 한다.

---

## 판정 결과 종류

| 상태 | 의미 |
|---|---|
| `PASS` | 모든 스텝 통과 |
| `FAIL` | FAIL 키워드 검출 |
| `TIMEOUT` | 스텝 제한 시간 내 미검출 |
| `INCOMPLETE` | 시작은 했으나 감시 종료(또는 세션 전환) 시점까지 미완료 |
| `NOT_EXECUTED` | 무장은 했으나 시작 트리거가 한 번도 안 나옴 |
| `EVENT` | 단일 키워드 감지 항목의 발생 횟수 집계 |

`NOT_EXECUTED` 를 리포트에 반드시 넣는 이유:
TC 가 아예 안 돌았는데 결과 목록에 안 보이면 **PASS율 100% 로 착시**가 생긴다.
리포트 Summary 에 `PASS율` 과 `실행률` 을 따로 표기한다.

---

## 리포트

`output/<제품명>/` 에 두 개가 생성된다.

- `YYYYMMDD_HHMMSS_results.jsonl` — 판정마다 즉시 append. 강제 종료돼도 남는다.
- `YYYYMMDD_HHMMSS_QA_Report.xlsx` — 20건마다 / 종료 시 생성.
  임시 파일에 쓴 뒤 교체하므로 저장 중 종료돼도 깨지지 않는다.

FAIL / TIMEOUT 근거에는 **판정 지점 앞 30줄 + 뒤 10줄**이 함께 저장된다.
Redmine 에 그대로 붙여넣을 수 있다.

---

## 룰 충돌 경고

실행 시작할 때 자동으로 검사한다. 예:

```
[!] 시작 트리거 중복 ['TC004', 'TC006'] : 'dvr: (osd) Format start!!'
[!] 대기 키워드 중복 ['TC001','TC007','TC008','TC009'] : 'http status code [200]'
```

전자는 SD 포맷만 했는데 HDD TC 도 같이 시작되어 **허위 TIMEOUT** 이 나는 경우,
후자는 남의 HTTP 응답을 자기 것으로 착각해 **잘못 PASS** 하는 경우다.

**경고가 뜨면 해당 TC 들을 동시에 무장하지 말고 따로 실행하라.**
이건 프로그램이 못 고치는 규칙 자체의 문제다.

---

## 알려진 한계

1. **상관관계(correlation) 미구현.** 여러 요청이 동시에 진행되면 응답을 구분하지
   못한다. 해결하려면 요청/응답에 공통으로 붙는 ID 를 정규식으로 캡처해
   같은 ID 끼리만 스텝을 잇는 구조가 필요하다.
2. **같은 TC 의 동시 다중 인스턴스 불가.** 한 TC 는 한 번에 한 건만 추적한다.
3. **`ABSENT` 모드 없음.** "N초 안에 이 문구가 나오면 FAIL"(커널 panic, 리부팅
   루프 감시)은 아직 표현할 수 없다.
4. **타임스탬프가 없는 로그의 리플레이에서는 TIMEOUT 판정 불가.**
   (실시간 감시는 벽시계로 대체 동작)
