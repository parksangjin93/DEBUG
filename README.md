# DEBUG — 디버그 로그 자동 판정기

임베디드 FW 검증에서 반복되는 로그 확인을 줄이기 위해 만든 Python 도구입니다. 터미널 프로그램이 저장한 로그 파일을 읽고, CSV/XLSX에 정의한 조건에 따라 PASS·FAIL·TIMEOUT을 판정합니다. 결과와 전후 로그는 JSONL 및 Excel 리포트로 남깁니다.

테스트 조작과 UART 수신은 외부에서 수행합니다. 이 프로그램은 **저장된 파일을 감시하거나 재분석**하며, COM 포트를 직접 열거나 FOTA·전원 제어를 실행하지 않습니다. [pytest 하네스](https://github.com/parksangjin93/crx-harness)와도 별도 프로그램입니다.

## 장비 없이 실행하기

Python 3.10 이상을 사용합니다. 아래 명령은 저장소 루트에서 실행합니다.

```bash
python -m pip install -r requirements.txt
python main.py --config examples/products.ini -p DEMO --replay examples/sample.txt --quiet
python tools/selftest.py
```

사내 TC·장비·원본 로그는 필요하지 않습니다. `examples/rules.csv`와 `examples/sample.txt`는 직접 작성한 가상 규칙과 로그입니다.

| 예제 결과 | 기대값 |
| --- | --- |
| PASS | 2건 |
| FAIL | 2건: 오류 키워드 및 ABSENT 위반 |
| TIMEOUT | 1건 |
| INCOMPLETE | 1건 |
| EVENT | 집계 행 1개, cooldown 적용 후 2회 검출 |
| NOT_EXECUTED | Excel에 미시작 TC 1건 추가 |
| TODO 규칙 | 1개, 실행 대상에서 제외 |

위 실패는 의도한 음성 사례입니다. CLI의 종료 코드 0은 실행 오류가 없다는 뜻이며 **TC가 전부 PASS라는 뜻은 아닙니다.** CI에서 실행할 경우 이 차이를 고려해야 합니다. `tools/selftest.py`는 기대 판정과 실제 판정의 전체 목록·횟수, 이벤트 집계, TODO 제외, JSONL/Excel 결과 및 별도 부팅 TIMEOUT 사례를 검사하고 불일치 시 종료 코드 1을 반환합니다.

데모 리포트는 `output/DEMO/`에 생성됩니다. JSONL에는 판정·이벤트 집계 7건, Excel `TC_Results`에는 NOT_EXECUTED를 포함해 8행이 생깁니다. 이 수치는 가상 예제 결과이며 실무 자동화 성과나 커버리지 수치가 아닙니다.

## 실제 로그 사용

먼저 판정하려는 동작의 시작·완료·오류 문구를 규칙 파일에 작성하고, 해당 TC만 선택해 확인합니다.

```bash
python main.py --rules examples/rules.csv --list
python main.py --rules path/to/rules.csv --log-dir path/to/logs --tc TC001
python main.py --rules path/to/rules.csv --replay path/to/session.log --tc TC001
```

`examples/rules.csv`는 가상 키워드만 사용하므로 실제 제품 로그를 판정하는 규칙으로 사용할 수 없습니다.

- `--log-dir`: 폴더에서 가장 최근 수정된 파일 하나를 추적합니다. 모든 파일을 동시에 분석하지 않습니다.
- `--log-file`: 지정한 파일 하나를 감시합니다.
- `--replay`: 저장된 파일을 읽은 후 종료합니다. 로그 끝 이후의 시간은 진행하지 않습니다.
- `--from-start`: 감시를 시작할 때 기존 내용도 읽습니다. 기본값은 기존 파일 끝에서 시작합니다.
- 파일 전환 시 진행 중인 시나리오는 INCOMPLETE로 마감합니다.

제품별 설정은 `--config`로 지정할 수 있습니다. 가상 프로파일 진단 예시:

```bash
python main.py --config examples/products.ini -p DEMO --check
```

기존 `config/products.ini`는 과거 운영 설정입니다. 여기에 적힌 제품 TC 파일은 공개 저장소에 포함되어 있지 않아 그대로 실행할 수 없습니다. 자신의 경로와 규칙 파일로 별도 프로파일을 준비하세요. TC 규칙·프로파일 상세는 [사용 안내](docs/usage.md)를 참고하세요.

## GUI

```bash
python qa_gui.py
```

Windows에서는 `run_gui.bat`로도 실행합니다. Python의 `tkinter`가 필요합니다. GUI와 CLI는 같은 `Runner`와 판정 엔진을 사용합니다.

제품 선택 → 로그 폴더·규칙 파일 지정 → 대상 TC 선택 → 감시 시작 순서로 사용합니다. GUI는 기본 `config/products.ini`를 편집하므로 기존 설정이 있다면 변경 전에 확인하세요. 저장된 로그 재분석도 가능합니다.

## 실행 구조

| 코드 | 역할 |
| --- | --- |
| `main.py`, `qa_gui.py` | CLI·GUI 진입점 |
| `core/profile.py`, `core/runner.py` | 제품 설정, 규칙·입력·리포트 연결 |
| `core/log_source.py` | 파일·폴더 감시 및 리플레이 |
| `core/log_event.py` | ANSI 제거, 시각 파싱, 판정용 Clock |
| `core/rule_loader.py`, `core/step.py` | 규칙 로딩·병합, 문자열·정규식 매칭 |
| `core/tc_engine.py` | 시나리오 상태 전환, 이벤트 집계 |
| `core/tc_manager.py` | TC별 라우팅, 충돌 경고, 실패 전후 문맥 |
| `report/report_generator.py` | JSONL 및 Excel 리포트 |
| `examples/`, `tools/selftest.py` | 공개 가상 예제 및 자체 검증 |

판정 흐름은 `파일 입력 → 라인 정제·시각 파싱 → TC 상태 전환 → 근거 수집 → 리포트`입니다. 제품마다 Runner를 분리하며, CLI에서는 `-p A,B`로 여러 제품의 로그를 각각 감시할 수 있습니다.

## 판정과 리포트 해석

- **PASS**: 해당 시나리오의 CHECK 조건을 통과했습니다.
- **FAIL**: 현재 스텝의 FAIL 키워드 또는 활성 ABSENT 금지 문구를 검출했습니다.
- **TIMEOUT**: 진행 중인 CHECK의 제한 시간을 넘겼습니다.
- **INCOMPLETE**: 시작했지만 감시 종료·파일 전환까지 완료하지 못했습니다.
- **NOT_EXECUTED**: 시작하지 않은 시나리오입니다. Excel 저장 시 추가되며 JSONL에는 별도 기록하지 않습니다.
- **EVENT**: 단일 스텝 키워드의 발생 집계입니다. PASS 횟수와 구분합니다.

결과는 `output/<제품명>/`에 저장됩니다. 프로파일 없이 실행하면 `output/`에 저장합니다. JSONL은 리포트에 전달된 판정마다 추가하고, Excel은 20건마다 또는 종료 시 생성합니다. FAIL·TIMEOUT 등의 근거는 앞 최대 30줄과 뒤 최대 10줄을 모은 후 전달하므로, 발생 즉시 JSONL에 기록된다고 가정하면 안 됩니다. 종료 시 남은 문맥을 반영합니다.

Excel의 PASS율은 판정 횟수 기준이고 실행률은 선택한 시나리오 TC 기준입니다. 제품 품질, 요구사항 커버리지, 자동화 비율과 동일한 수치가 아닙니다. 이벤트 FAIL이 섞인 결과는 집계 대상을 따로 검토하세요.

## 현재 제한

1. **ABSENT는 구현되어 있지만 관찰 범위에 제한이 있습니다.** 뒤의 CHECK가 일찍 완료되면 지정한 ABSENT 시간이 남아도 PASS로 끝납니다. 완료 이후 로그는 그 시나리오에서 감시하지 않습니다. 고정 시간 전체의 무발생 보장으로 해석하지 마세요.
2. CHECK/ABSENT의 로그 매칭이 tick보다 먼저 처리됩니다. 시각이 크게 건너뛰는 로그, 정확한 마감 경계, 지연 기록을 포함한 규칙은 별도로 검증해야 합니다.
3. 같은 TC의 동시 다중 실행 및 요청/응답 ID 상관관계를 지원하지 않습니다. 같은 HTTP 응답 등 공통 키워드만으로 여러 요청을 구별할 수 없습니다.
4. 리플레이의 시간 판정에는 일관된 라인별 타임스탬프가 필요합니다. 타임스탬프가 없거나 혼재하면 TIMEOUT 결과를 신뢰할 수 없습니다.
5. 리포트 파일명은 초 단위입니다. 같은 제품·출력 폴더에서 같은 초에 여러 실행을 시작하지 마세요. 저장 오류 경고가 없는지와 실제 산출물도 확인해야 합니다.

오탐이 생기면 먼저 시작 트리거·공통 키워드·시간 조건·시험 전제조건을 확인합니다. 이 도구의 FAIL만으로 FW 결함을 확정하지 않습니다.

## 구현과 운영 역할

생성형 AI를 구현 보조로 활용했습니다. 실무 로그에서 확인할 조건을 규칙으로 옮기고, 실행 결과를 보며 키워드·시간 조건과 오탐을 보완하는 용도로 사용합니다. 공개 예제는 이 판정 흐름을 재현하기 위한 것으로, 실제 제품에서의 검출 성과는 별도 증적으로 관리합니다.

이번 공개 예제는 Python 3.12의 CLI·리플레이·자체 검증으로 확인했습니다. GUI와 실제 Windows 로그 감시는 별도 운영 환경에서 확인해야 합니다.
