# 04. 소프트웨어 설계

> 1단계 구현 반영 (v0.1.0). 구현이 바뀌면 함께 갱신한다.

## 1. 기술 스택

| 구분 | 사용 |
|------|------|
| 언어/런타임 | Python 3.8.10 (embedded, `Python3.8.10/`) |
| 시리얼 통신 | pyserial 3.5 |
| GUI | PyQt5 5.15 |
| 결과 저장 | CSV (표준 라이브러리), Excel (openpyxl) |
| DB (선택) | MongoDB (pymongo) |

Python 3.8 기준으로 작성한다 (예: `match` 문, `X | Y` 타입 표기 사용 불가).

## 2. 모듈 구조

```
app/
├─ __init__.py
├─ main.py            # 진입점: 인자가 없으면 GUI, --cli/--compare/--list-ports면 CLI
├─ cli.py             # 명령행 인자 → TestConfig, CLI 측정·비교
├─ winutil.py         # Windows 타이머 분해능 1 ms, 프로세스 우선순위
├─ config.py          # 측정 설정 dataclass (포트, UART 파라미터, 메시지, 반복 조건)
├─ serial_port.py     # 포트 검색(CH340/FTDI 식별), open/close, 버퍼 초기화
├─ latency_test.py    # 측정 루프 (송신 → 에코 수신 → 시간 기록 → 검증)
├─ payload.py         # 페이로드 생성 (SEQ + 패턴), 수신 데이터 검증
├─ stats.py           # 통계 계산 (min/max/mean/stdev/SE/percentile/histogram)
├─ sweep.py           # baudrate 스윕 (baudrate 목록을 순서대로 측정), [2단계] 채널 순차 측정
├─ compare.py         # 측정 구성 A/B/C 결과 비교 (평균 차이, 표준오차)
├─ storage.py         # CSV / Excel 저장
└─ gui/
   ├─ main_window.py  # 설정 입력, 실행/중지, 진행률, 결과 표시, 비교 탭
   ├─ histogram.py    # latency 히스토그램 (QPainter)
   └─ worker.py       # QThread: run_sweep 실행, 결과를 signal로 전달
```

### 구현 메모

- 수신은 `in_waiting` 폴링(바쁜 대기)이며, 데이터가 **감지된 시각**을 기록한다 (`read()` 호출 시간 제외).
- 회차 간격은 Windows 대기 함수 분해능(약 15.6 ms) 문제 때문에 마지막 20 ms 구간을 바쁜 대기로 맞춘다.
- 측정 중에는 CPU 코어 하나를 거의 100 % 사용한다 (정확도 우선).
- 포트 목록에서 어댑터를 식별해 최대 baudrate(CH340 2 Mbps)를 넘는 스윕 값은 건너뛴다.
- 수신 대기 바이트는 pyserial `in_waiting` 대신 Win32 `ClearCommError`를 직접 호출해서 읽는다. `in_waiting`은 드라이버 오류 플래그(FRAME, OVERRUN, PARITY)를 버리기 때문이다.

### 에러 분석 (`error_analysis.py`)

- 오류 메시지는 `tx_hex`/`rx_hex`를 저장하고, 오류 직후 늦게 들어온 바이트도 `rx_hex`에 붙인다.
- `difflib`으로 송수신 바이트를 정렬해서 **DROP**(누락) / **EXTRA**(추가) / **BIT**(값 바뀜)로 나눈다.
- BIT 오류는 반전된 비트 위치(bit0 = start 다음 첫 데이터 비트), 0→1/1→0 방향, 엣지 옆 여부를 기록하고 세부 유형으로 분류한다.
  - `LATE_kBIT` (k = 1~7) `rx = tx>>k | 상위 k비트 1`: 수신기가 k비트 늦게 동기됨. start bit를 놓치면 첫 0 데이터 비트를 start bit로 착각하므로 k = (b0부터 이어지는 1의 개수) + 1
  - `EARLY_1BIT` `rx = tx<<1`: 1비트 일찍 동기됨
  - `SINGLE_BIT` / `MULTI_BIT`
- 결과: `<이름>_errors.csv`, Excel `Errors`/`ErrorAnalysis` 시트, GUI "에러 분석" 탭, `run.bat --analyze <csv>`.
- 비트 위치를 겨냥한 시험용으로 `walking1`(0x01, 0x02 … 0x80), `walking0`, `fixed`(값 지정) 패턴을 제공한다.

## 3. 실행 흐름

```
MainWindow ──(설정)──▶ Worker(QThread) ──▶ LatencyTest.run()
     ▲                                          │
     └──── progress / result signal ◀───────────┘
```

- 1단계: **1개 채널(1개 COM 포트)** 만 측정한다.
- 2단계 확장: `LatencyTest`는 포트 1개만 담당하도록 만들고, 4채널은 채널 목록을 돌며 순차 실행(또는 채널별 Worker를 여러 개 실행)한다. 측정 루프 자체는 바꾸지 않는다.
- 측정 루프는 Worker 스레드에서 실행하고, GUI는 signal로 받은 결과만 표시한다.
- GUI 갱신은 일정 회차 또는 일정 시간 단위로 묶어서 전달해 측정 루프 부하를 줄인다.
- 중지 요청은 플래그로 전달하고, 진행 중인 회차가 끝난 뒤 종료한다.

## 4. 설정 항목

| 항목 | 기본값 (안) | 설명 |
|------|-------------|------|
| port | (자동: 첫 CH340/FTDI) | COM 포트 |
| channel_no | 1 | 시험 중인 장비 채널 번호 (1~8, 결과 기록용) |
| channels | - | **[2단계]** 장비 채널 번호 → COM 포트 매핑 (최대 4개) |
| setup | C | 측정 구성: A(어댑터 루프백) / B(로컬 RS-422 루프백) / C(광 링크 전체) / C0(짧은 fiber) |
| fiber_length_m | 1000 | fiber 길이 (결과 기록·이론값 계산용) |
| baudrate | 115200 | 어댑터 한계 이내 (CH340 2,000,000 / FT4232H 8,000,000까지 사용) |
| bytesize / parity / stopbits | 8 / N / 1 | |
| rtscts | False | 하드웨어 흐름 제어 |
| payload_size | 16 | 메시지 길이 (byte) |
| pattern | incrementing | fixed / incrementing / random / 0x55-0xAA |
| baud_sweep | - | 스윕할 baudrate 목록. 1단계 예: 115200, 460800, 921600, 1000000, 1500000, 2000000 / 2단계 추가: 3000000, 4000000, 6000000, 8000000 |
| use_seq | True | 페이로드 앞 4 byte에 시퀀스 번호 |
| iterations | 1000 | 측정 횟수 |
| warmup | 10 | 결과에서 제외할 사전 송수신 횟수 |
| interval_ms | 10 | 회차 간 대기 시간 |
| timeout_ms | 1000 | 회차당 수신 타임아웃 |
| read_mode | poll | poll / blocking |

baudrate 스윕에서 어댑터가 지원하지 않는 값은 건너뛰고 결과에 "미지원"으로 기록한다.

## 5. 측정 결과 데이터

### 회차별 레코드

| 필드 | 타입 | 설명 |
|------|------|------|
| channel | int | 장비 채널 번호 (1단계는 항상 같은 값, 2단계 다채널 구분용) |
| baudrate | int | 해당 회차의 baudrate (스윕 시 구분용) |
| seq | int | 회차 번호 |
| t_send_ns | int | 송신 시각 (perf_counter_ns) |
| first_byte_us | float | 첫 바이트 도착까지 시간 |
| latency_us | float | 전체 수신 완료까지 시간 |
| rx_len | int | 수신 바이트 수 |
| err_bytes | int | 송신 데이터와 다른 바이트 수 |
| status | str | OK / TIMEOUT / MISMATCH / SEQ_ERROR |

### 메타데이터 (결과 파일 헤더 또는 별도 시트)

- 측정 일시, PC 이름, 포트, USB-UART 어댑터 종류와 드라이버 버전 (FTDI면 Latency Timer 값)
- UART 설정, 페이로드 설정, 반복 조건
- 측정 구성 (A/B/C), 장비 채널 번호, fiber 길이
- 장비 정보 (펌웨어/보드 버전, SFP 모델, 샘플링 클럭)
- 이론값: UART 직렬 시간 (`T_wire`), fiber 왕복 전파 지연

### 파일 형식

- CSV: `results/latency_<setup>_ch<N>_YYYYMMDD_HHMMSS.csv`
- Excel: `results/latency_<setup>_ch<N>_YYYYMMDD_HHMMSS.xlsx`
  - `Summary`: 메타데이터, (채널별) baudrate별 통계·오류율
  - `Raw`: 회차별 레코드
  - `Compare` (비교 실행 시): 구성 간 평균 차이와 표준오차, fiber 이론 지연과의 비교
