# RS-422 ↔ Fiber Optical Converter 개발 계획서

| 항목 | 내용 |
|------|------|
| 서식 번호 | DEV001 |
| 문서 번호 | DEV001-422-01 |
| 버전 | **REV 3.9** |
| 등급 | Class C (대외비) |
| 작성일 | 2026-08-10 |
| 작성자 | 김한성 |
| 보존년한 | 2년 |
| 참조 문서 | `RS422_-_광_컨버터_개발_제안_20260803101607.pdf` (FPGA 방식, 별도 보관) |
| 칩셋 데이터시트 | `manual/tlk1501.pdf`, `manual/tlk2711-sp.pdf`, `manual/MAX3483.PDF`, `manual/SiT8920B-datasheet.pdf` |
| 대상 채널 | **16채널** Full Duplex RS-422 |
| SerDes (1차) | **TLK1501** + SFP |
| SerDes (대안) | TLK2711-SP (§3 · 부록 B) |

## TLK1501 + SFP — Transparent 16-bit Parallel Tunnel (FPGA 미사용)
---

## 1. 문서 목적

16채널 RS-422를 **단일 광 링크**로 연장하는 Converter.  
**Parallel → Serialize → Fiber → Deserialize → Parallel** — 이것이 전부이며, UART·Frame·중간 프로토콜·별도 Sampler **불필요**.

| 구분 | 기존 FPGA 제안 | **본 계획** |
|------|----------------|-------------|
| SerDes | FPGA SerDes IP | **TLK1501** (온칩 8b/10b) |
| 광학 | TOSA / ROSA | **SFP** |
| 중간 프로토콜 | Frame · UART Engine | **없음** (투명 bit tunnel) |
| 프로그래머블 | FPGA | **없음** |

---

## 2. 핵심 개념 — Transparent 16-bit Parallel Tunnel

### 2.1 동작 원리

TLK1501은 **16-bit Parallel @ GTX_CLK** ↔ **직렬 @ 20×GTX_CLK** 변환기(SerDes)이다.  
광 링크 위에는 **애플리케이션 프로토콜이 없다.** (8b/10b는 line coding만)

```
[A PSE]  12V IN ──► Buck ──► Board Power
         RS-422 ×16 ──► RS-422 XCVR ×16 ──► TXD[15:0] ──► TLK1501 ──► SFP ──► Fiber
         RS-422 ×16 ◄── RS-422 XCVR ×16 ◄── RXD[15:0] ◄── TLK1501 ◄── SFP ◄── Fiber
              │ Fiber×2 + 12V/GND ═══════════════════════════════════════► [B PD]
              └── Hybrid Cable (A가 B에 전원 공급)
```

**GTX_CLK rising edge마다** TLK1501이 `TXD[15:0]` 16-line을 **한 번에 래치** → 직렬화 → 광.  
반대편 TLK1501이 역직렬화 → `RXD[15:0]` 출력.  
**별도 Sampler / UART / Frame HW 없음** — **래치 동작 자체가 샘플링**이다.

```
채널 n:  MAX3491 RO[n] ────────► TXD[n]     (GTX_CLK마다 1 bit 래치)
채널 n:  MAX3491 DI[n] ◄──────── RXD[n]     (RX_CLK마다 1 bit 출력)
```

> RS-422 위에 UART가 올라가 있든 raw bit stream이든, 컨verter는 **16개 serial line을 광으로 1:1 연장**하는 **Digital Line Extender**이다.

### 2.2 UART / Frame / Sampler가 불필요한 이유

| 요소 | 필요? | 이유 |
|------|-------|------|
| UART FSM | ❌ | 상위에서 RS-422 serial 처리 · 컨verter는 bit 단위 투명 전달 |
| SOF / CRC Frame | ❌ | TLK1501 8b/10b + CDR이 line layer 담당 |
| Sampler IC | ❌ | **TLK1501 TXD 래치 = 샘플러** |
| CPLD / FPGA | ❌ | SerDes 외 로직 없음 |
| **MAX3491 ×16** | ✅ | RS-422 differential ↔ TTL (3.3 V) |
| **TLK1501 + SFP** | ✅ | Serialize / Deserialize |
| **GTX_CLK** | ✅ | 샘플링(래치) 주기 |
| **Level Shifter** | ❌ | MAX3491 VIH=2.0 V · TLK1501 입출력과 직결 |

---

## 3. SerDes 선정 — TLK1501 vs TLK2711-SP

### 3.1 결론

**16ch × 8 Mbps bit-transparent tunnel 목적에서 TLK1501·TLK2711-SP 모두 단독으로 충분.**

| | **TLK1501 (1차)** | **TLK2711-SP (대안)** |
|---|-------------------|------------------------|
| GTX_CLK | **30 ~ 75 MHz** | **80 ~ 125 MHz** |
| Line Rate | 0.6 ~ 1.5 Gbps | 1.6 ~ 2.5 Gbps |
| 16ch × 8 Mbps | ✅ 30 MHz로 충분 | ✅ 80 MHz로 충분 |
| Parallel I/F | 16-bit TTL | 16-bit TTL |
| 패키지 / 온도 | VQFP, −40~85 °C | CFP, **−55~125 °C** |
| Crystal | **25 MHz + PLL** | 25 MHz + PLL → 80 MHz |

**TLK2711만 써도 본 사양 충분.** 다만 클럭·EMI·Crystal 내구·PCB 측면에서 **TLK1501이 유리** → 1차 채택.

### 3.2 샘플링 주파수 (대역폭) 산정

채널당 serial bit를 **GTX_CLK마다 1회 샘플** (1 sample/bit):

```
최소 GTX_CLK ≥ 채널 최대 Baud (bit/s)

16ch × 8 Mbps/ch:
  필요 GTX_CLK ≥ 8 MHz
  TLK1501 @ 30 MHz  →  ~3.75 sample/bit  ✅
  TLK1501 @ 62.5 MHz → ~7.8 sample/bit  ✅
  TLK2711 @ 80 MHz  →  ~10 sample/bit  ✅
```

| GTX_CLK | Line Rate | Max Baud/ch (1 sample/bit) | 8 Mbps/ch |
|---------|-----------|----------------------------|-----------|
| 30 MHz | 600 Mbps | 30 Mbps | ✅ |
| **62.5 MHz** | **1.25 Gbps** | **62.5 Mbps** | ✅ |
| 80 MHz | 1.6 Gbps | 80 Mbps | ✅ |

→ **100 MHz·125 MHz로 올릴 필요 없음.** 칩 minimum(30/80 MHz)으로 충분.

### 3.3 TLK2711을 쓸 경우

−55 ~ +125 °C military grade 필수, 또는 2 Gbps+ 링크 여유 필요 시. §부록 B.

---

## 4. 개발 사양

| # | 항목 | 사양 |
|---|------|------|
| 01 | RS-422 | 1 ~ 8 Mbps / Channel (bit stream, **UART 가정 안 함**) |
| 02 | 채널 | **16** Full Duplex |
| 03 | 광 | SFP × 2 (TX + RX) · SM 1310 nm |
| 04 | SerDes | **TLK1501** (대안 TLK2711-SP) |
| 05 | GTX_CLK | **62.5 MHz** (1.25G SFP) 또는 30 MHz |
| 06 | 동작 | **Transparent bit tunnel** — 프로토콜 변환 없음 |
| 07 | **전원** | **12 V** · PSE(A) 공급 → **광전 복합케이블** → PD(B) 수전 |
| 08 | **케이블** | **Hybrid Cable** — SM Fiber ×2 + Copper(12V/GND) ×2 |
| 09 | 온도 | −40 ~ +85 °C |

---

## 5. 시스템 아키텍처

### 5.1 블록 다이어그램 (최소 구성)

```
┌──────────────────────────────────────────────────────────────────────┐
│                   Converter Board (PSE or PD)                        │
│                                                                      │
│  ┌─────────┐   ┌─────────────┐   ┌────────────┐   ┌─────────────┐  │
│  │ D-sub   │   │ MAX3491×16  │   │  직결      │   │  TLK1501    │  │
│  │ RS-422  │──►│ 3.3V Full   │──►│ RO→TXD     │──►│ TXD[15:0]   │  │
│  │  ×16    │◄──│ Duplex      │◄──│ RXD→DI     │◄──│ RXD[15:0]   │  │
│  └─────────┘   └─────────────┘   └────────────┘   │ DOUTTXP/N   │──┼──► SFP-TX
│                                                    │ DINRXP/N    │◄─┼── SFP-RX
│  ┌─────────┐                                       │ TX_EN=H     │  │
│  │ SiT8920B │──────────────────────────────────────►│ GTX_CLK     │  │
│  │ 3225    │                                       │ TX_ER=L     │  │
│  │ 62.5M   │                                       └─────────────┘  │
│  └─────────┘                                                        │
│  ┌─────────┐   ┌─────────────┐                                        │
│  │ 12V IN  │──►│ Buck 3.3V   │──► SFP Cage                               │
│  │ (PSE:   │   │ Buck 2.5V   │──► TLK1501                                │
│  │  ext /  │   └─────────────┘                                        │
│  │  PD:cbl)│   ┌─────────────┐                                        │
│  └────┬────┘   │ Hybrid Conn │◄── Fiber×2 + 12V/GND                  │
│       └────────►│ (to cable)  │                                        │
└──────────────────────────────────────────────────────────────────────┘
```

**BOM 핵심:** MAX3491 · TLK1501 · SFP · **12V Buck** · Hybrid Connector (+ Clock)

> **PSE / PD** 회로는 **동일**. PSE만 외부 12 V 입력 + Cable로 12 V **송전**, PD는 Cable에서 12 V **수전**.

### 5.2 신호 연결 (채널 n)

```
RS-422 A/B ──► MAX3491[n] RO ──► TXD[n]     n = 0..15
               MAX3491[n] DI ◄── RXD[n]
```

- **제어 핀 (채널당):** `DE=H` (Driver Enable), `RE=L` (Receiver Enable) — **상시 Full Duplex**

- **TX 경로 (로컬 RS-422 입력 → 광):** RO → TXD
- **RX 경로 (광 → 로컬 RS-422 출력):** RXD → DI

### 5.3 TLK1501 제어 핀 (고정 · Input)

보드(PCB)에서 TLK1501 **으로** 인가하는 **입력** 핀. MCU/FPGA 없이 **H/L tie** 또는 pull-up/down.

| 핀 | **I/O** | Pull | 설정 | 의미 |
|----|---------|------|------|------|
| TX_EN | **I** | ↓ | **H** | 데이터 전송 활성 (상시 assert) |
| TX_ER | **I** | ↓ | **L** | Error 없음 (정상 data) |
| ENABLE | **I** | ↑ | **H** | Device 동작 (L = power-down) |
| LCKREFN | **I** | ↑ | **H** | RX data tracking (L = TX-only) |
| LOOPEN | **I** | ↓ | **L** | 정상 (H = internal loopback) |
| PRBSEN | **I** | ↓ | **L** | 정상 (H = BIST mode) |
| TESTEN | **I** | ↓ | **L** / NC | Test off |

링크 최초 establish 시 TLK1501 **Idle(K28.5) 자동 삽입** — 전원/리셋 시퀀스만 준수.

### 5.4 TLK1501 · SFP 상태 Indicator (Output)

정상 동작 여부는 TLK1501 **출력** 핀과 SFP 모듈 상태 핀으로 확인.

#### TLK1501 Status Output

| 핀 | **I/O** | 정상 (Link OK) | 이상 / 의미 |
|----|---------|----------------|-------------|
| **RX_CLK** | **O** | **GTX_CLK와 동주파수 toggle** | Low 고정 → POR · CDR unlock · 광 링크 없음 |
| **RX_DV/LOS** | **O** | **H** (valid data 수신 중) | H + **RX_ER=H** → **LOS** 또는 decode error |
| **RX_ER** | **O** | **L** | **H** → carrier extend / error propagation / invalid code |

데이터시트 Table 2 (수신 상태):

| 수신 데이터 | RX_DV/LOS | RX_ER |
|-------------|-----------|-------|
| Normal data | **1** | **0** ← **정상 data stream** |
| IDLE (K28.5) | 0 | 0 ← 링크 up · idle (fault 아님) |
| Carrier extend | 0 | 1 |
| Error / LOS | 1 | 1 |

> **Transparent tunnel** (TX_EN=H 상시): valid bit stream 수신 시 **RX_DV=1, RX_ER=0**.  
> **RX_CLK toggle**이 가장 단순한 **Link Up** hardware indicator.

#### 양단 광 연결 확인 (Peer Link Detect)

별도 광 PHY IC가 없으므로 **"상대편과 연결됨"** 전용 핀은 없다.  
**각 보드가 자기 RX 경로**를 모니터하여 **간접적으로** 양단 연결을 판단한다.

**광 배선 (Hybrid Cable 내 Fiber ×2)**

```
[A PSE]                              [B PD]
 SFP-TX ────────── Fiber-1 ─────────► SFP-RX    B: A로부터 수신
 SFP-RX ◄────────── Fiber-2 ────────── SFP-TX    A: B로부터 수신
```

TX_EN=H 상시 → **양단 모두 항상 직렬 stream 송출** (data 또는 Idle K28.5).  
상대 SFP-TX → fiber → 자기 SFP-RX 경로만 정상이면 **RX_CLK toggle** → **상대와 연결됨**으로 해석.

**보드 1장 기준 Link Up 조건 (AND)**

| # | 조건 | 신호 | 의미 |
|---|------|------|------|
| 1 | SFP-RX **LOS = L** | SFP Cage (RX 모듈) | 광 power / signal 수신 |
| 2 | **RX_CLK toggle** | TLK1501 | CDR lock · 8b/10b stream decode 가능 |
| 3 | **RX_ER = L** (권장) | TLK1501 | decode error 없음 |

```
LINK_OK = (SFP_RX_LOS == L) AND (RX_CLK_active) [AND (RX_ER == L)]
```

**양단 연결 확인**

| A단 LINK | B단 LINK | 해석 |
|----------|----------|------|
| ✅ | ✅ | **Fiber ×2 양방향 정상** — peer connected |
| ✅ | ❌ | A→B RX OK · B→A 또는 B 전원/광 이상 |
| ❌ | ✅ | B→A RX OK · A→B 또는 A 광 TX 이상 |
| ❌ | ❌ | fiber 미연결 · SFP 미삽입 · 상대 전원 off |

> PD 전원이 Hybrid Cable 12 V에 의존 → **B단 전원 없음 = B LINK 불가** → A단에서도 B-side TX stream 없음 → **A LINK off**.

**LINK vs ACT vs ERR**

| LED | 판단 | 비고 |
|-----|------|------|
| **LINK** | SFP-RX LOS=L **且** RX_CLK active | **상대편 광 연결** (최소 필수) |
| **ERR** | RX_ER=H | 8b/10b / sync error |
| **ACT** | RX_DV toggle 또는 RXD[0] toggle | traffic 있음 (optional) |
| **PWR** (PD) | 12 V cable present | Hybrid 전원 (PD only) |

**구현 (MCU 없음)**

```
SFP-RX LOS ──► inverter ──┐
                           ├──► AND ──► LINK LED (Green)
RX_CLK ──► retrigger mono ─┘          (active when toggling)

RX_ER ──────────────────────────────► ERR LED (Red)
```

- RX_CLK @ 62.5 MHz → **÷N counter** 또는 **retrigger monostable** (~100 ms) 로 `RX_CLK_active` 생성
- Phase 1: TP + scope로 RX_CLK · SFP LOS 확인 후 LED 회로 확정

#### 권장 보드 Indicator (Front Panel)

| LED | 구동 신호 | Green (OK) | Red / Off (Fault) |
|-----|-----------|------------|-------------------|
| **LINK** | **SFP-RX LOS=L AND RX_CLK active** | **상대편 광 연결** | fiber / peer / SFP 이상 |
| **ERR** | RX_ER | L | **H** |
| **ACT** | RX_DV or RXD toggle (optional) | traffic | — |
| **SFP TX_FAULT** | SFP-TX module | L | **H** (local laser fault) |
| **PWR** (PD only) | 12 V from cable | on | cable 미연결 |

- Phase 1: TP + scope로 SFP-RX LOS · RX_CLK · RX_ER 확인 후 LED 회로 확정

#### BIST (선택)

| 핀 | 설정 | Pass 조건 |
|----|------|-----------|
| LOOPEN | **H** | internal serial loopback |
| PRBSEN | **H** | **RX_ER/PRBS_PASS = H** → PRBS OK |

### 5.5 양단 클럭

| | PSE | PD |
|---|-----|-----|
| TX (→ Fiber) | **Local GTX_CLK** (62.5 MHz) | **Local GTX_CLK** |
| RX (← Fiber) | **Recovered RX_CLK** | **Recovered RX_CLK** |

양단 **GTX_CLK 동일 주파수·±100 ppm** 이내 (각자 **독립 62.5 MHz MEMS XO** 또는 25M+PLL).

### 5.6 전원 · 광전 복합케이블 (PSE / PD)

#### 구성 개념

| 구분 | **A단 — PSE (Power Sourcing)** | **B단 — PD (Powered Device)** |
|------|-------------------------------|-------------------------------|
| 역할 | **12 V 전원 생성·공급** | 케이블 경유 **12 V 수전** |
| RS-422 | D-sub ×16 | D-sub ×16 |
| 광 | SFP ×2 | SFP ×2 |
| 전원 입력 | **외부 12 V** (DC jack / system) | **Hybrid Cable Copper** |

```
[A단 PSE]                              [B단 PD]
  12V IN (외부)                           (로컬 12V 없음)
     │                                        ▲
     ▼                                        │
  DC-DC ──┬──► 3.3V (SFP)                      DC-DC ──┬──► 3.3V (SFP)
          └──► 2.5V (TLK1501)                            └──► 2.5V (TLK1501)
  TLK1501 · SFP · RS-422                  TLK1501 · SFP · RS-422
     │                                        ▲
  Hybrid Connector ◄════ Hybrid Cable ════► Hybrid Connector
       │    Fiber TX ──────────────────────►│
       │    Fiber RX ◄──────────────────────│
       └──► Copper 12V+ ────────────────────►│
            Copper GND ─────────────────────►│
```

#### Hybrid Cable 사양 (초안)

| # | 구성 | 사양 |
|---|------|------|
| 1 | Fiber TX | SM G.657.B3 (또는 A1) · SFP-A TX → SFP-B RX |
| 2 | Fiber RX | SM · SFP-A RX ← SFP-B TX |
| 3 | Copper + | **12 V** (PSE → PD) |
| 4 | Copper − | **GND** |
| 5 | Connector | Hybrid (광 2 + 전원 2) · 양단 동형 **[TBD]** |
| 6 | 길이 | **≤ 10 m** (압강 · IR drop 검증) |

> 기존 FPGA 제안(`20260803101607.pdf`)의 **2 Fiber + 2 Copper Hybrid Cable** 개념과 동일.

#### 전원 레일 — 2.5 V (칩셋) · 3.3 V (SFP)

TLK1501 데이터시트: **2.5 V supply**, I/O **3 V tolerant**.  
SFP MSA: 모듈 전원 **3.3 V** — TLK1501과 **레일 분리** 필수.

```
12 V IN ──┬──► [ Buck #1: 12→3.3 V ] ──► SFP Cage ×2        (~600 mA typ.)
          │                          └──► RS-422 ×16, Clock PLL (~200 mA)
          │
          └──► [ Buck #2: 12→2.5 V ] ──► TLK1501 VDD / VDDA  (~100 mA)
                                       (선택: VDDA에 LC filter / local LDO)
```

| Rail | 전압 | 용도 | 발생 |
|------|------|------|------|
| Input | **12 V** | PSE 외부 · PD cable | — |
| **SFP** | **3.3 V** | **SFP 모듈 ×2** (MSA) | **12 V Buck #1** |
| **I/O** | **3.3 V** | RS-422 · Clock PLL | Buck #1 (SFP와 동 rail) |
| **Core** | **2.5 V** | **TLK1501 칩셋** | **12 V Buck #2** (SFP와 **분리**) |

> **3.3 V ≠ 칩셋 전원.** 3.3 V는 SFP·주변 I/O용, **TLK1501 코어는 2.5 V 전용**.

**I/O 연결 (MAX3491 + TLK1501 직결)**

| 방향 | 신호 | 레벨 | Level Shifter |
|------|------|------|---------------|
| RS-422 → TLK | RO → TXD | ~3.3 V (VOH ≥ VCC−0.4 V) | **불필요** (TLK1501 VIH ≤ 3.6 V) |
| TLK → RS-422 | RXD → DI | ~2.3 V (VOH typ) | **불필요** (MAX3491 **VIH = 2.0 V**) |

> MAX3483/85/91 데이터시트: **VIH = 2.0 V**, **VIL = 0.8 V** · TLK1501 VOH min **2.10 V** → DI 직결 여유 **≥100 mV**.

**설계 포인트**

- SFP hot-plug inrush가 TLK1501 analog에 coupling되지 않도록 **2.5 V Buck 독립**
- Buck #2 출력에 **π-filter / ferrite** → TLK1501 VDDA decoupling 강화

#### PSE(A) 전원부

```
[외부 12V] ──► Fuse / TVS ──► Buck 3.3V (SFP) ──► SFP Cage
                          └──► Buck 2.5V ──► TLK1501
                    │
                    └──► Hybrid Connector (12V+ / GND to cable)
```

- 역방향 보호: PD측 12V가 PSE로 역류하지 않도록 **ideal diode / OR-ing** 검토
- Inrush: SFP hot-plug · Buck soft-start

#### PD(B) 전원부

```
[Hybrid Cable 12V] ──► Fuse / TVS ──► Buck 3.3V (SFP) / Buck 2.5V (TLK1501)
                         (PD 로컬 12V 입력 없음)
```

- Cable IR drop: 10 m · 1 A · AWG20 ≈ 0.35 V drop → **12 V → 11.65 V @ PD** (Buck min input margin 확인)
- Cable conductor: **AWG20 이상** 권장 (Phase 1에서 실측)

#### 소비 전력 개략 (1 board, 16ch active)

| Block | 전력 (typ.) |
|-------|-------------|
| TLK1501 | ~250 mW @ **2.5 V** |
| SFP ×2 | ~1 W @ **3.3 V** |
| MAX3491 ×16 | ~0.5 W @ 3.3 V |
| Clock · 기타 | ~0.2 W |
| **Board 합계** | **~2 W** |
| **12 V 입력 (η=85%)** | **~0.2 A / board** |

PSE Buck **12 V side ~0.2 A** + PD feed **동일** → Hybrid Cable **≥0.5 A 여유** 설계.

---

## 6. 핵심 부품

### 6.1 TLK1501

| 항목 | 값 |
|------|-----|
| GTX_CLK | **62.5 MHz** (권장) / 30 MHz (최소) |
| Parallel | TXD[15:0], RXD[15:0] — RS-422 XCVR 직접 연결 |
| Serial | DOUTTXP/N, DINRXP/N → SFP |
| 전원 (core) | **2.5 V** (VDD / VDDA) |
| I/O | **3 V tolerant** — RS-422 3.3 V TTL 직접 연결 |

### 6.2 RS-422 — MAX3491 ×16 (1차)

| 항목 | MAX3491 | MAX3485 (참고) |
|------|---------|----------------|
| 전원 | **3.3 V** (3.0 ~ 3.6 V) | **3.3 V** |
| 속도 | **10 Mbps** | **10 Mbps** |
| Duplex | **Full Duplex** ✅ | **Half Duplex** ❌ |
| 패키지 | 14-pin SO/DIP | 8-pin (75176 pinout) |
| Shutdown | ✅ (2 nA) | ✅ |

**16ch Full Duplex** 사양 → **MAX3491 채택** (MAX491 3.3 V 대응품).

- MAX3485: 속도·전압은 적합하나 **Half Duplex** — 본 설계(16ch 동시 TX/RX)에 **부적합**
- MAX3490: Full Duplex · 10 Mbps · Shutdown 없음 — **대안**

**TLK1501 연결:** RO → TXD, RXD → DI **직결** · Level Shifter **불필요**

### 6.3 Level Shifter

MAX3491(VIH=2.0 V) + TLK1501(VOH≥2.10 V, 입력 3 V compatible) → **생략**.

### 6.4 SFP + Clock

- SFP 1.25G SM 1310 nm × 2 · **3.3 V** (MSA)
- GTX_CLK **62.5 MHz** → §7 **Clock Tree** 참조

### 6.6 Clock — GTX_CLK 62.5 MHz

#### TLK1501 요구 vs 부품 적합성

| Parameter | TLK1501 GTX_CLK | SG-8002CA | SiT8208 / SiT8920B | **SJK 3N / TXC 7X** |
|-----------|-----------------|-----------|---------------------|---------------------|
| Frequency | 62.5 MHz | ✅ | ✅ | ✅ |
| Tolerance | ±100 ppm | ±50~100 ppm △ | ±20~25 ppm ✅ | **±25 ppm** ✅ |
| **Jitter (pp)** | **≤ 40 ps** | **≤ 200 ps** ❌ | **~12~20 ps** ✅ | **~1 ps** (catalog) △ |
| Package 3225 | 원함 | ❌ **7050** | ✅ | ✅ |
| Temp | −40 ~ +85 °C | −20 ~ +70 °C ❌ | −40 ~ +85 °C ✅ | **−40 ~ +85 °C** ✅ |
| Resonator | MEMS 권장 | Quartz+PLL △ | **MEMS** ✅ | Quartz OSC △ |
| 조달 | — | ❌ | JLC/Mouser | **晶科鑫 domestic** |

> **Epson SG-8002CA 62.5 MHz (预编程振荡器) → 본 설계 부적합.**  
> 범용 programmable XO · **SerDes ref clock jitter spec 미달**.  
> 3225 필요 시 **SG-8002CE**도 jitter 동급 → **동일하게 비권장**.

#### 1차 BOM — SiT8208 (3225 · 구매 용이)

SiT8920B와 동급 MEMS · **JLC/LCSC·Mouser 재고 품번 다수** · 3225.

**Production (3.3 V · 권장 — Buck 3.3 V rail)**

```
SiT8208AI-32-33E-262.500000T
```

| Field | Value |
|-------|-------|
| Series | SiT8208 · **MEMS** |
| Package | **3225** (3.2 × 2.5 mm) |
| Frequency | **62.500000 MHz** |
| VDD | **3.3 V** |
| Stability | ±25 ppm (code 2) |
| Temp | **−40 ~ +85 °C** (AI) |
| Pin1 | **E** = OE · pull-up → always on |
| Packing | **T** = 12 mm T&R |

**Prototype / 2.5 V rail 사용 시 (TLK1501 2.5 V Buck 직결 가능)**

```
SiT8208AI-22-25E-62.500000T
```

- JLCPCB: **C1211235** (재고 확인용 reference)
- 2.5 V CMOS → TLK1501 GTX_CLK **직접 연결 OK**

**Pin1 Standby (S) variant — 상시 동작:**

```
SiT8208AI-22-25S-62.500000Y
```

Pin1=S · pull-up → normal output (datasheet Standby mode)

#### 2차 — SiT8920B (SiT8208 품절 시)

```
SiT8208AI-32-33E-262.500000T   ← 1차 (구하기 쉬움)
SiT8920BM-11-33N-262.500000D   ← 2차 (SiTime direct / sample)
```

#### 3차 — 25 MHz XTAL + PLL (항상 조달 가능)

```
ABM8-25.000MHZ (3225 crystal) + LMK61E2-15625 (or CDCE913) → 62.5 MHz
```

#### 4차 — 晶科鑫 (SJK) 국내·중국 조달 — 3225 CMOS XO

공급: [晶科鑫 q-crystal.com.cn — 有源晶振](https://www.q-crystal.com.cn/product/category/34)  
SiT8208 재고 없을 때 **동일 3225 CMOS XO** 대체.

| Series | Link | F range | Output | 62.5M | 비고 |
|--------|------|---------|--------|-------|------|
| **SJK 3N** | [detail/508](https://www.q-crystal.com.cn/product/detail/508) | 1~220 MHz | **CMOS** | ✅ | **1차 domestic** |
| **TXC 7X** | [detail/604](https://www.q-crystal.com.cn/product/detail/604) | 1~125 MHz | **CMOS** | ✅ | 2차 domestic |
| SiT9121 | detail/546 | 1~220 MHz | LVPECL/LVDS | ✅ | ❌ differential |
| TXC DA/DE | detail/607/608 | 25~200 MHz | LVPECL/LVDS | ✅ | ❌ differential |
| 7U | detail/20 | 8~125 MHz | — | — | ❌ **无源 crystal** |
| A3N | detail/642 | 1~**50** MHz | CMOS | ❌ | 62.5M **超范围** |

**SJK 3N — 발주 Spec (晶科鑫 문의용)**

```
3225 有源晶振 (CMOS)
Frequency:    62.500000 MHz
Supply:       3.3 V ±10%
Output:       CMOS, 15 pF load
Stability:    ±25 ppm
Temperature:  -40 ~ +85 °C
Pin1:         OE (上拉启用 / 常高有效)
Application:  1.25G SerDes reference clock (low jitter)
Package:      3.2 × 2.5 × 1.0 mm
Reel:         3000 pcs (3N series standard)
```

中文询价示例:

> 3N系列 3225 CMOS有源晶振，62.500000MHz，3.3V，±25ppm，-40~+85°C，OE功能，用于千兆SerDes参考时钟

| 3N catalog spec | Value | TLK1501 |
|-----------------|-------|---------|
| Phase jitter (12 kHz~20 MHz) | **1 ps max** (catalog) | ≤ 40 ps pp ✅ (verify) |
| Duty cycle | 45 ~ 55 % | 40 ~ 60 % ✅ |
| Rise/fall | 3 ns max | — |
| VDD | 1.8 ~ 3.3 V | **3.3 V rail** |

> **주의:** catalog jitter는 **Phase 1 C2 시험**으로 GTX_CLK pin에서 확인.  
> Quartz OSC → SiT8208(MEMS)보다 **충격·초음파 세척** margin은 작을 수 있음.  
> **정확한 SJK 품번**은 晶科鑫 영업 확정 (0755-88352810).

**TXC 7X** — 3N과 동급 CMOS 3225 · 1~125 MHz · ±25 ppm · jitter 1 ps (catalog).  
62.5 MHz 동일 spec으로 발주.

#### Clock BOM 우선순위 (summary)

| Priority | Part | 조달 |
|----------|------|------|
| **1** | SiT8208AI-32-33E-262.500000T | JLC / LCSC / Mouser |
| **2** | SiT8920BM-11-33N-262.500000D | SiTime sample |
| **3** | 25 MHz XTAL + LMK61E2 | universal |
| **4** | **SJK 3N / TXC 7X** 62.5M 3225 CMOS | **q-crystal.com.cn** |

#### ~~비권장~~

| Part | 이유 |
|------|------|
| **SG-8002CA** 62.5M | **7050** · jitter 200 ps · −20~70 °C |
| **SG-8002CE** 62.5M | 3225이나 jitter 200 ps 동일 |
| q-crystal **7U** | 无源 crystal — OSC 아님 |
| q-crystal **A3N** | max 50 MHz — 62.5M 불가 |
| q-crystal **SiT9121/DA/DE** | differential — TLK1501 직결 불가 |
| 62.5 / 80 MHz bare quartz | 충격·초음파 세척 취약 |

#### PCB (공통)

```
VDD ── 0.1µF ── GND
OUT ── [22~33Ω] ── GTX_CLK ──► TLK1501 pin 8
```

### 6.5 전원 IC

| IC | 기능 | 비고 |
|----|------|------|
| Buck #1 | **12 V → 3.3 V** @ ≥1 A | **SFP 전용** + RS-422/Clock |
| Buck #2 | **12 V → 2.5 V** @ ≥0.5 A | **TLK1501 칩셋** · SFP rail과 분리 |
| Fuse / TVS | 12 V 입력 보호 | PSE · PD 공통 |

---

## 7. 클럭 · EMI · 충격

### 7.1 TLK1501 GTX_CLK 요구사항

TLK1501 **GTX_CLK** = parallel word clock · CDR reference. **직접 62.5 MHz TTL** 입력.

| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Frequency | 30 | **62.5** | 75 | MHz |
| Tolerance | — | — | **±100** | ppm |
| Duty cycle | 40 | 50 | 60 | % |
| Jitter (peak-to-peak) | — | — | **40** | ps |

> 양단(PSE/PD) **각자 독립 clock** · ±100 ppm 이내면 OK (광 CDR이 상대 drift 흡수).  
> **동기 master/slave 불필요** — RX recovered clock(RX_CLK)는 remote TX에서 추출.

### 7.2 62.5 MHz 생성 — Quartz 없이 (1차 권장)

**목표:** PCB에 **62.5 MHz fundamental quartz를 올리지 않고** GTX_CLK 공급.  
(25 MHz ref quartz + PLL, 또는 **MEMS oscillator** 방식)

#### 옵션 비교

| # | Architecture | Quartz? | 충격 | Jitter | BOM | 채택 |
|---|--------------|---------|------|--------|-----|------|
| **A** | **SiT8920B 62.5M MEMS XO** | **없음** | **◎** | ◎ (~12 ps pp) | 1 | **1차** |
| B | 25 MHz quartz → **Clock Synth** ×2.5 | 25M only | ○ | ○~◎ (IC급) | 2 | 2차 |
| C | 125 MHz XO (MEMS) → **÷2** | 없음 | ◎ | ◎ | 2 | 2차 |
| D | 12.5 MHz quartz → PLL ×5 | 12.5M | ◎ | ○ | 2 | 대안 |
| ~~E~~ | **62.5 MHz bare quartz** | 62.5M | **✗** | ◎ | 1 | **금지** |
| ~~F~~ | 80 MHz bare quartz → PLL | 80M | **✗** | — | — | **금지** |

#### 옵션 A — SiT8920B 62.5 MHz (1차 · BOM 확정)

```
[SiT8920BM-11-33N-262.500000D] ── 62.5 MHz CMOS ──► [22Ω] ──► TLK1501 GTX_CLK
         3225 · 3.3 V · NC pin
```

| 항목 | 내용 |
|------|------|
| Part | **SiT8920BM-11-33N-262.500000D** (§6.6) |
| 주파수 | **62.500000 MHz** · 61.674 ~ 69.240 MHz 지원 범위 ✅ |
| Stability | ±20 ppm |
| Jitter | ~12 ps pp typ (@75M ref) → TLK1501 **40 ps pp** 여유 |
| 장점 | **외부 quartz 0** · MEMS · MIL-STD-883 shock/vibe |

#### 옵션 B — 25 MHz Quartz + Clock Synthesizer (PLL)

```
[25 MHz AT-cut quartz] ──► [Clock Generator IC] ──► 62.5 MHz ──► GTX_CLK
         │                        │
    2 × Ci, load cap          fractional PLL
                              25 × 2.5 = 62.5 MHz
```

| Part (예) | Maker | 특징 |
|-----------|-------|------|
| **CDCE913** / CDCE925 | TI | fractional · 1~3 output · 3.3 V |
| **LMK61E2** | TI | I2C program · low jitter · small |
| **Si5341** | Skyworks | **초저 jitter** · 과잉 spec · cost ↑ |
| **8T49N241** | Renesas | 2-output clock generator |

- **25 MHz fundamental quartz**: 산업 표준 · **충격 내성 62.5/80 MHz quartz보다 우수**
- ×2.5 = **fractional PLL** → IC **phase jitter spec** 확인 필수 (≤ **40 ps pp** budget)
- **고성능 PLL**이 필요한 경우: Si5341 / LMK04828 class — 본 설계(단일 GTX_CLK)에는 **LMK61E2·CDCE913급으로 충분**할 가능성 큼 (Phase 1 BER로 검증)

#### 옵션 C — 125 MHz Oscillator ÷ 2

```
[125 MHz MEMS XO] ──► [74LVC74 / CDC sync divider ÷2] ──► 62.5 MHz (50% duty) ──► GTX_CLK
```

- **125 / 2 = 62.5** · **integer** → PLL fractional noise **없음**
- 125 MHz source는 MEMS canned oscillator 사용 → **bare 125 MHz quartz 회피**
- divider 추가 · duty 50% 보장 · jitter budget 여유

#### 옵션 D — 12.5 MHz Quartz × 5 (integer PLL)

```
[12.5 MHz quartz] ──► [PLL ×5 integer] ──► 62.5 MHz
```

- **integer multiply** → fractional PLL보다 jitter 유리
- 12.5 MHz crystal: 저주파 · **충격 최우수** · 부품 수 availability 확인 필요

### 7.3 크리스탈 주파수 후보 (참고)

| Crystal | → 62.5 MHz | Bare quartz on PCB | 비고 |
|---------|------------|--------------------|------|
| **— (MEMS 62.5M XO)** | direct | **No** | **1차** |
| **25 MHz** | × 2.5 PLL | Yes (저주파) | **2차 표준 ref** |
| **12.5 MHz** | × 5 PLL | Yes | integer PLL |
| **125 MHz** | ÷ 2 | Avoid (use XO module) | ÷2 깔끔 |
| **31.25 MHz** | × 2 | Rare part | 비권장 |
| **62.5 MHz** | × 1 | **Avoid** | 충격 취약 |
| **80 MHz** | → 80M (TLK2711) | **Avoid** | 충격 취약 |

### 7.4 권장 Block Diagram (REV 3.6)

```
                    ┌─────────────────────────────────┐
  Option A (1차)    │  SiT8920BM-11-33N-262.500000D      │
                    │  3225 · 3.3V · 62.5 MHz CMOS       │
                    └────────────┬────────────────────┘
                                 │ 62.5 MHz
                    ┌────────────▼────────────────────┐
                    │  74LVC1G17 (optional buffer)    │
                    └────────────┬────────────────────┘
                                 ▼
                           TLK1501 GTX_CLK (pin 8)

  Option B (2차)     25MHz XTAL ──► CDCE913/LMK61E2 ──► 62.5 MHz ──► GTX_CLK
```

- **Clock power**: 3.3 V Buck #1 (SFP rail) · local **100 nF + 10 µF** decoupling
- **Optional**: ferrite bead on VDD of clock IC
- PSE · PD **동일 clock BOM** · 각 board **독립 oscillator**

### 7.5 Phase 1 Clock 검증

| # | 시험 | Pass |
|---|------|------|
| C1 | GTX_CLK frequency | 62.5 MHz ±100 ppm |
| C2 | GTX_CLK jitter @ TLK1501 pin | < **40 ps pp** |
| C3 | Duty cycle | 40 ~ 60 % |
| C4 | PSE↔PD optical 24 h BER | < 10⁻¹² (clock margin 확인) |
| C5 | Shock / ultrasonic clean 후 C1~C4 | spec 유지 |

### 7.6 저속 클럭 · EMI (TLK1501 vs TLK2711)

| | TLK1501 @ 62.5M | TLK2711 @ 80M |
|---|-----------------|---------------|
| Parallel toggle | 62.5 MHz | 80 MHz |
| Serial rate | 1.25 Gbps | 1.6 Gbps |
| EMI / SI | **유리** | 양호 |
| Crystal | **25 MHz** | 25 MHz + PLL → 80M |

---

## 8. 대역폭 · Latency

### 8.1 대역폭

16ch × 8 Mbps = 128 Mbps aggregate ≪ TLK1501 payload 62.5M×16 = **1.0 Gbps**.

### 8.2 Latency

Frame·UART 버퍼 없음 → **TLK1501 SerDes latency 위주 (~μs 이하)** + fiber propagation.  
FPGA Frame 방식(~30 μs) 대비 **훨씬 낮음**.

---

## 9. 개발 로드맵

| Phase | 내용 | 기간 |
|-------|------|------|
| **1** | TLK1501 + SFP loopback · GTX_CLK 62.5/30 MHz BER | 4주 |
| **2** | **4ch** MAX3491 ↔ TXD[3:0] **직결** 시제 · 8 Mbps | 4주 |
| **3** | **16ch** PSE+PD · Hybrid Cable · Full Duplex stress | 6주 |
| **4** | 온도 · 충격 · 초음파 세척 · EMC | 8주 |

---

## 10. 리스크

| # | 리스크 | 대응 |
|---|--------|------|
| R1 | GTX_CLK 양단 drift | ±100 ppm · **동일 part class** (MEMS or PLL IC) |
| R2 | GTX_CLK jitter / ppm | **MEMS XO 1차** · Phase 1 C1~C5 |
| R3 | **Hybrid Cable IR drop** (10 m) | AWG20+ · Buck wide VIN · 실측 |
| R4 | Link init (Idle) | POR 시퀀스 · TX_EN idle |
| R5 | Bit jitter | GTX_CLK ≥ 3× Baud |
| R6 | **PSE 단독 동작** (케이블 미연결) | PSE만 12V로 standalone · PD는 cable 필수 |

---

## 11. 검증

| # | 시험 | Pass |
|---|------|------|
| T1 | TLK1501 LOOPEN + PRBS | Pass |
| T2 | PSE↔PD optical 24h | BER < 10⁻¹² |
| T3 | 16ch × 8 Mbps bit pattern | Bit error = 0 |
| T4 | Loopback RS-422 ↔ RS-422 | 원격 loopback 정상 |
| T5 | 충격 후 link recovery | BER 복귀 |
| T6 | **Hybrid Cable 전원** | PD 3.3 V · 2.5 V ±5% @ full load · 10 m |
| T7 | **PSE→PD 전원 단독** | PD board 동작 · SFP·TLK1501 정상 |

---

## 12. BOM (16ch, 1 board)

| # | Part | Qty |
|---|------|-----|
| 1 | **TLK1501IRCP** | 1 |
| 1a | *(대안)* TLK2711-SP | 1 |
| 2 | **MAX3491E** (Full Duplex RS-422, 3.3 V, 10M) | 16 |
| 3 | SFP Cage + 1.25G SM SFP | 2+2 |
| 4 | **SiT8208AI-32-33E-262.500000T** (3225 · 62.5M · 3.3V) | 1 |
| 4b | *(alt)* **SJK 3N** / TXC 7X 3225 62.5M CMOS (§6.6) | 1 |
| 4a | 74LVC1G17 clock buffer (optional) | 0~1 |
| 5 | **Buck 12→3.3 V** (SFP) | 1 |
| 6 | **Buck 12→2.5 V** (TLK1501) | 1 |
| 7 | Fuse / TVS (12 V) | 1 set |
| 8 | **Hybrid Connector** (광2+전원2) | 1 |
| 9 | D-sub | 1~2 |

**Hybrid Cable (별도 Item):** SM Fiber ×2 + **12 V/GND Copper ×2** · ≤10 m

**없는 것:** FPGA · CPLD · UART IC · Frame Engine · Level Shifter · TOSA/ROSA

---

## 13. 요약

1. **Parallel → SerDes → Fiber → SerDes → Parallel** — TLK1501 + SFP가 전부.
2. **MAX3491 RO → TXD[n], RXD[n] → MAX3491 DI 직결** — Sampler/UART/Frame **불필요**.
3. **GTX_CLK 래치 = 샘플링** — 62.5 MHz면 8 Mbps/ch × 16에 ~8 sample/bit.
4. **TLK2711 @ 80 MHz도 동일하게 충분** — military 온도 시 대안 (부록 B).
5. **25 MHz crystal + PLL** — 80 MHz quartz 불필요 · **1차: 62.5 MHz MEMS XO (quartz 0)**.
6. **전원 12 V** · **3.3 V = SFP**, **2.5 V = TLK1501** · Hybrid Cable로 PD 공급.
7. **Hybrid Cable** = Fiber ×2 + **12 V/GND Copper ×2** · PD는 로컬 12 V 불필요.

---

## 부록 A. 변경 이력

| REV | 내용 |
|-----|------|
| 1.x | TLK2711 · FPGA Frame · UART |
| 2.0 | TLK1501 · Link Layer Engine |
| **3.0** | Transparent bit tunnel · MAX491↔TXD/RXD 직결 |
| **3.1** | 12 V · PSE/PD · Hybrid Cable (광2+전원2) |
| **3.2** | 전원 레일 분리: 3.3 V(SFP) · 2.5 V(TLK1501) · dual Buck |
| **3.3** | RS-422: MAX3491 확정 · Level Shifter 불필요 |
| **3.4** | TLK1501 제어핀 I/O · RX_CLK/RX_DV/RX_ER status · SFP LOS |
| **3.5** | 양단 광 Peer Link Detect · LINK=(LOS+RX_CLK) |
| **3.6** | Clock tree · MEMS 62.5M · 25M+PLL 2차 |
| **3.7** | SiT8920B BOM (SiTime sample용) |
| **3.8** | SiT8208 1차 · SG-8002CA 비권장 |
| **3.9** | **晶科鑫 SJK 3N / TXC 7X** domestic clock source · q-crystal.com.cn |

---

## 부록 B. TLK2711-SP 대안

TLK2711도 **16ch × 8 Mbps transparent tunnel**에 **80 MHz GTX_CLK만으로 충분.**

| | TLK1501 | TLK2711-SP |
|---|---------|------------|
| GTX_CLK | 62.5 MHz | **80 MHz** (min) |
| Parallel 연결 | TXD/RXD ← MAX3491 | **동일** |
| 중간 HW | **없음** | **없음** |
| 제어 | TX_EN/TX_ER | TKLSB/TKMSB |
| 온도 | −40~85 °C | **−55~125 °C** |

BOM #1만 TLK2711-SP로 교체, Clock → 80 MHz, 나머지 **동일 직결 구조.**

---

## 부록 C. 기존 FPGA Frame 방식과의 차이

| | FPGA 제안 (20260803101607) | **본 설계 REV 3.0** |
|---|---------------------------|---------------------|
| 광 위 프로토콜 | SOF · VALID MAP · CRC Frame | **없음 (raw 16-bit word)** |
| RS-422 처리 | UART parse → byte → frame | **bit transparent** |
| 중간 IC | FPGA | **없음** |
| 장점 | 에러 검출 · deterministic frame | **극단적 단순 · low latency · low BOM** |
| 단점 | FPGA 필요 | bit jitter · link에 CRC 없음 |

에러 검출·프레임 동기화가 **필요해지면** 그때 상위 장비 또는 optional layer 추가 — **1차 시제품은 transparent tunnel.**

---

*© 2026 · X-BEAM TECH · CONFIDENTIAL*
