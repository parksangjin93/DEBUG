# 규칙과 제품 설정

## 규칙 작성

[가상 규칙](../examples/rules.csv)은 CSV 형식입니다. XLSX도 읽을 수 있지만 변경 이력을 확인하려면 CSV로 관리하는 편이 편리합니다.

| 컬럼 | 의미 |
| --- | --- |
| `TC_ID`, `TC_NAME` | TC 식별자와 이름 |
| `STEP` | 처리 순서. 행 순서 대신 이 번호로 정렬 |
| `TEST_PURPOSE`, `TEST_METHOD` | 목적과 단계 설명 |
| `TYPE` | `CHECK` 또는 `ABSENT` |
| `VALUE` | 문자열 또는 정규식 조건 |
| `FAIL` | 현재 단계에서 즉시 실패시킬 조건 |
| `TIMEOUT` | CHECK는 단계 진입 후 제한 시간, ABSENT는 금지 문구 감시 시간 |
| `MATCH` | `CONTAINS` 또는 `REGEX`. VALUE와 FAIL에 같이 적용 |
| `PRODUCT` | 제품 필터. 빈칸은 공통 규칙 |
| `TAG` | 선택용 태그. 쉼표를 넣을 때 CSV 인용 필요 |
| `MODE`, `COOLDOWN` | 이벤트 모드 및 중복 검출 억제 간격 |

여러 단계의 첫 CHECK가 시작 트리거입니다. 단일 스텝 TC는 MODE가 SEQUENCE여도 이벤트 감시로 처리됩니다. EVENT로 지정한 경우에도 첫 스텝만 감시하므로 여러 단계 시나리오에 EVENT를 사용하지 마세요. `VALUE`가 TODO로 시작하는 TC는 Runner에서 제외합니다.

ABSENT는 첫 단계로 두지 말고, 시작 CHECK 뒤에 배치합니다. TIMEOUT을 지정해야 합니다. ABSENT를 활성화하면 즉시 다음 단계로 넘어가 함께 감시하며, 모든 CHECK가 끝나면 ABSENT 잔여 시간과 관계없이 시나리오를 종료합니다. 예제에서는 정상 부팅 완료를 ABSENT 30초 이후에 배치했습니다.

TIMEOUT의 경계와 의미는 장비 동작에 맞게 검증해야 합니다. 시간 초과를 시험할 때는 기대 문구 대신 충분히 늦은 시각의 무관한 줄을 넣고 TIMEOUT이 나오는지 확인하세요. EOF 직전까지 진행 중이고 제한 시간도 지나지 않았다면 INCOMPLETE가 됩니다.

CSV는 구분자·인코딩을 감지합니다. 자동 감지가 어긋나면 UTF-8 CSV로 저장해 다시 확인하세요. 정규식의 캡처는 내부 매칭 기록에 남지만 현재 Excel evidence_text에는 캡처 사전이 별도로 표시되지 않습니다.

## 제품 프로파일

```ini
[MY_DEVICE]
log_dir = D:\LOG\MY_DEVICE
rules = path/to/common.csv, path/to/device.csv
tc = TC001,TC002
tester = tester-name
fw = build-id
```

```bash
python main.py --config path/to/products.ini -p MY_DEVICE --check
python main.py --config path/to/products.ini -p MY_DEVICE
python main.py --config path/to/products.ini -p MY_DEVICE --tc TC003
```

규칙 파일의 상대 경로는 저장소 루트를 기준으로 해석합니다. 로그·출력 상대 경로는 실행 작업 폴더의 영향을 받으므로 저장소 루트에서 실행하거나 절대 경로를 사용하세요.

여러 규칙 파일은 앞에서부터 병합하고, 같은 TC_ID는 뒤 파일의 TC 정의 전체로 교체합니다. 단계별로 부분 병합하지 않습니다. CLI의 선택·경로 인자는 프로파일 값을 덮어씁니다. `--check`는 프로파일 기반 경로와 규칙·선택을 확인하며 리플레이 자체의 정합성을 검증하는 명령은 아닙니다.

TC를 모두 선택하기 전에 충돌 경고를 확인하세요. 시작 트리거가 같으면 의도하지 않은 TC가 함께 시작할 수 있고, 완료 문구가 같으면 다른 요청의 응답으로 통과할 수 있습니다. 경고는 자동으로 실행을 막지 않습니다.

## 로그 시각

지원하는 대표 라인 선두 형식:

- `[2026-01-01 09:00:00.123]`
- `[01/01 09:00:00.123]`
- `[09:00:00.123]` 또는 `[09:00:00]`

날짜 없는 시각은 파일명에서 추출한 날짜 또는 실행 날짜를 사용합니다. 재현 가능한 예제에는 전체 날짜와 시간을 사용했습니다. SecureCRT 등에서 라인별 시각을 저장하도록 설정한 뒤 실제 파일의 형식이 파서와 맞는지 확인하세요. 기록 시각은 장비 내부의 실제 이벤트 시각과 차이가 날 수 있습니다.

## 가상 로그 복사

```bash
python tools/make_test_log.py --output logs/sample.log
python main.py --rules examples/rules.csv --replay logs/sample.log --all
```

`--output`은 UTF-8로 저장합니다. 출력 파일은 생성물이므로 Git에서 제외합니다. 실제 운영 규칙과 로그도 공개 예제와 분리해 관리하세요.
