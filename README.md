# stock

한국·미국 국채 금리, 네이버 금융 ETF·시가총액 데이터, FnGuide 과거 ROE,
OpenDART 5% 이상 보유 공시를 수집해 보여주는 정적 주식 대시보드입니다.

## 준비

### Python 확인

이 프로젝트는 Python 3.13을 사용합니다. 현재 PC에서는 아래 실행 파일을 사용합니다.

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" --version
```

### 의존성 설치

```powershell
cd C:\stock
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" -m pip install -r requirements.txt
```

### API 키 설정

현재 수집기에 필요한 키는 두 개입니다.

| 이름 | 용도 | 필수 시점 |
| --- | --- | --- |
| `ECOS_API_KEY` | 한국은행 국내 국채 금리 | 금리 수집 |
| `DART_API_KEY` | OpenDART 5% 이상 보유 공시 | 장 마감/전체 수집 |
| `KRX_ID`, `KRX_PW` | 향후 KRX 공매도·수급 확장 | 현재는 사용하지 않음 |

네이버 금융, FnGuide, FRED 미국 국채 금리에는 별도 API 키가 필요하지 않습니다.

1. [한국은행 ECOS](https://ecos.bok.or.kr/api/)에서 인증키를 발급합니다.
2. [OpenDART](https://opendart.fss.or.kr/)의 `인증키 신청/관리`에서 인증키를 발급합니다.
3. 아래 스크립트를 실행해 로컬 `.env` 파일에 입력합니다.

```powershell
cd C:\stock
.\scripts\setup_api_keys.ps1
```

`run_all.py`, 국채 크롤러, DART 크롤러는 `.env`를 자동으로 읽습니다.
`.env`는 Git에서 제외되며 키 값은 소스와 JSON에 저장하지 않습니다.

## 데이터 한 번에 수집

`run_all.py`가 다음 작업을 순서대로 실행합니다.

1. 한국은행 ECOS·FRED 국채 금리 수집
2. 네이버 금융 KoAct·TIME ETF 현재가/등락률 수집
3. 네이버 금융 시가총액 데이터 수집
4. FnGuide 과거 ROE 수집
5. OpenDART 5% 이상 보유 공시 수집

전체 실행:

```powershell
cd C:\stock
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py
```

OpenDART를 제외하고 국채 금리, 네이버, FnGuide만 실행:

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --skip-dart
```

중간 작업이 실패하면 이후 작업은 실행하지 않으며, 실패한 단계와 종료 코드를 출력합니다.

### 통합 실행 옵션

```powershell
# FnGuide에서 현재 ROE 15% 이상 종목만 수집
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --fnguide-min-roe 15

# 테스트를 위해 FnGuide와 OpenDART 대상을 각각 10개로 제한
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --fnguide-limit 10 --dart-limit 10

# OpenDART 우선 검토 후보만 수집
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --dart-scope priority
```

전체 옵션 확인:

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --help
```

주요 옵션:

- `--skip-dart`: OpenDART 수집 생략
- `--skip-rates`: ECOS·FRED 국채 금리 수집 생략
- `--skip-etf-tickers`: 네이버 금융 ETF 브랜드 수집 생략
- `--etf-brands`: ETF 티커로 수집할 브랜드 목록, 기본 `KoAct TIME`
- `--rates-lookback-days`: 금리의 최근 유효값을 찾을 조회 기간, 기본 21일
- `--fnguide-min-roe`: FnGuide 대상의 최소 현재 ROE, 음수이면 필터 해제
- `--min-roa`: FnGuide/OpenDART 대상의 최소 현재 ROA, 기본 7, 음수이면 필터 해제
- `--no-financial-roa-exempt`: 은행·증권·보험 등 금융업 이름 키워드도 ROA 필터 적용
- `--fnguide-limit`: FnGuide 대상 수 제한, `0`이면 제한 없음
- `--dart-scope`: OpenDART 대상 범위 (`roe`, `priority`, `all`)
- `--dart-limit`: OpenDART 대상 수 제한, `0`이면 제한 없음
- `--naver-delay`, `--fnguide-delay`, `--dart-delay`: 각 요청 사이의 대기 시간(초)

## 생성 파일

- `data/market_sum.json`: 네이버 전체 시가총액 데이터
- `data/market_sum_by_roe.json`: ROE 기준 정렬 데이터
- `data/fnguide_roe_history.json`: FnGuide 과거 ROE 데이터
- `data/dart_major_holders.json`: OpenDART 5% 이상 보유 공시 데이터
- `data/treasury_yields.json`: ECOS 한국 국고채 및 FRED 미국 국채 만기별 금리
- `data/naver_etf_brands.json`: 네이버 금융 ETF 브랜드별 현재가와 등락률

FnGuide 파싱 실패 시 아래 디버그 파일이 추가로 생성됩니다.

- `data/fnguide_debug/<code>.html`
- `data/fnguide_debug/<code>.txt`

## 대시보드 실행

브라우저의 `fetch()`로 JSON을 읽기 때문에 `index.html`을 직접 열지 말고 로컬 서버를 실행해야 합니다.

```powershell
cd C:\stock
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" -m http.server 8000
```

브라우저에서 다음 주소로 접속합니다.

```text
http://localhost:8000
```

## 개별 수집

문제 진단이나 특정 단계만 다시 실행할 때 사용합니다.

```powershell
# 한국·미국 국채 금리
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_treasury_yields.py

# KoAct·TIME ETF (브랜드 인수를 바꾸면 다른 브랜드도 수집)
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_naver_etf_brands.py KoAct TIME

# 네이버 금융
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_naver_market_sum.py

# FnGuide
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_fnguide_roe_history.py

# OpenDART
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py
```

FnGuide는 기본적으로 `data/market_sum.json`에서 현재 ROE가 10% 이상인 종목을 수집합니다. 공개 재무비율 페이지에 보이는 기간에 따라 최근 연간 결산과 최신 중간기 데이터가 함께 포함될 수 있습니다.

OpenDART 크롤러의 기본 범위는 현재 ROE가 10% 이상인 종목입니다. `data/dart_major_holders.json`이 없어도 대시보드는 해당 공시 항목을 비운 상태로 동작합니다.

## 현재 대시보드 동작

- `data/market_sum_by_roe.json`을 읽고 기본적으로 ROE 10% 이상 종목을 표시합니다.
- 우선 검토 후보 위에서 한국·미국 국채 금리, KoAct ETF, TIME ETF가 각각 한 줄 티커로 흐릅니다.
- 국채 금리는 같은 만기에서 한국과 미국이 연이어 보이도록 배치되며, ETF는 상승 빨강·하락 파랑으로 표시됩니다.
- 거래정지 추정 종목은 흐리게 표시하고 `거래정지` 배지를 붙입니다.
- 테이블 헤더를 클릭해 정렬할 수 있습니다.
- OpenDART 기준 5% 공시, 주요 보유자, 보유비율, 최근 보고일을 표시합니다.
- 보수적, 기준, 낙관적 시나리오 기반 적정가 범위와 켈리 범위를 보여줍니다.

## 자동 수집

[`.github/workflows/update-market-data.yml`](.github/workflows/update-market-data.yml)이
GitHub Actions에서 다음 일정으로 실행됩니다.

- 평일 08:30 KST: ECOS·FRED 한국/미국 국채 금리
- 평일 16:30 KST: 네이버 ETF·시가총액, FnGuide, OpenDART
- 수동 실행: GitHub의 `Actions` → `Update market data` → `Run workflow`

자동 실행 전에 GitHub 저장소의 `Settings` → `Secrets and variables` →
`Actions` → `New repository secret`에서 다음 두 개를 등록합니다.

- `ECOS_API_KEY`
- `DART_API_KEY`

그리고 `Settings` → `Pages` → `Build and deployment`의 `Source`를
`GitHub Actions`로 한 번 설정합니다.

워크플로는 갱신된 `data/*.json`을 `github-actions[bot]` 이름으로 자동 커밋하고
현재 브랜치에 푸시한 다음, 같은 실행 안에서 갱신된 대시보드를 GitHub Pages에
직접 배포합니다. 예약 실행은 GitHub 서버 상황에 따라 몇 분 늦어질 수 있습니다.

로컬에서 예약 실행 구성을 실제 네트워크 요청 없이 확인할 수도 있습니다.

```powershell
python scheduled_update.py rates --dry-run
python scheduled_update.py market-close --dry-run
python scheduled_update.py all --dry-run
```

## GitHub Pages 배포

GitHub Pages 자체에서는 Python이 실행되지 않지만, 위 GitHub Actions가 Python
크롤러를 실행하고 결과 JSON을 저장소에 커밋한 후 Pages까지 직접 배포합니다.
Pages 배포 소스는 `GitHub Actions`로 설정해야 합니다. `.nojekyll`이 포함되어
있어 정적 파일 그대로 배포됩니다.
