# UART Echo Latency TestProgram

RS-422 광 전송 장비(MAX3490 + TLK1501 SerDes + SFP, 8ch, 최대 8 Mbps, fiber 1 km)의 지연시간과 데이터 무결성을 확인하기 위한 PC 테스트 프로그램.

CH340 USB-UART로 메시지를 송신(send)하고, 광 링크 원격측에서 되돌아오는 에코(echo)를 수신하기까지의 **왕복 지연시간(round-trip latency)** 과 데이터 오류를 측정한다.

```
PC ─ CH340 ─ MAX3490 ─ TLK1501 ─ SFP ═══ fiber ═══ SFP ─ TLK1501 ─ MAX3490 ─ Echo
```

| 단계 | USB-UART | 채널 | baudrate |
|------|----------|------|----------|
| 1단계 (현재) | CH340 | 1 | ~ 2 Mbps |
| 2단계 (예정) | FT4232H 테스트보드 | 4 | ~ 8 Mbps |

## 문서 목록

| 문서 | 내용 |
|------|------|
| [01-overview.md](01-overview.md) | 배경, 개발 단계, 시스템 구성, 측정 구성(A/B/C/C0), 요구사항, 측정의 한계 |
| [02-measurement.md](02-measurement.md) | latency 정의, 지연 구성요소(fiber·SerDes·USB), 링크 지연 분리, 샘플링 지터, 통계 |
| [03-ch340.md](03-ch340.md) | USB-UART 어댑터: CH340(1단계) 특성·한계, FT4232H(2단계) 설정 주의사항 |
| [04-software-design.md](04-software-design.md) | 프로그램 구조, 모듈, 설정값, 결과 저장 형식 |

## 폴더 구조

```
TestProgram/
├─ app/            # 프로그램 소스
├─ doc/            # 문서 (이 폴더)
└─ Python3.8.10/   # 동봉된 Python 3.8.10 embedded 런타임
```

## 실행 환경 요약

- OS: Windows
- 런타임: `Python3.8.10/python.exe` (embedded 배포판, 별도 설치 불필요)
- 포함 패키지: pyserial 3.5, PyQt5 5.15.10, openpyxl 3.1.5, pymongo 4.9.2
- `python38._pth`에 `..`(프로젝트 루트)가 등록되어 있으므로 `app` 패키지를 모듈로 실행한다.

## 실행

```
run.bat                                   # GUI
run.bat --list-ports                      # COM 포트 목록
run.bat --cli --port COM4 --baud 115200 -n 1000 --setup B
run.bat --cli --sweep 115200,921600,2000000 -n 5000 --setup C --fiber 1000
run.bat --compare results\latency_B_...csv results\latency_C_...csv
run.bat --analyze results\latency_C_...csv        # 저장된 결과의 에러 분석
```

`run.bat`은 `Python3.8.10\python.exe -m app.main`을 실행한다. 전체 옵션은 `run.bat --help`.

결과는 `results/` 폴더에 `latency_<구성>_ch<채널>_<일시>.csv / .xlsx`로 저장된다.
