# stock

한국·미국 국채 금리, 국내외 종목 시세·차트·기업지표, 뉴스, 공시와 공매도 데이터를
자동 수집해 보여주는 정적 주식 대시보드입니다.

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

전체 수집을 사용할 때 아래 Repository secrets를 사용합니다.

| 이름 | 용도 | 필수 시점 |
| --- | --- | --- |
| `ECOS_API_KEY` | 한국은행 국내 국채 금리 | 금리 수집 |
| `DART_API_KEY` | OpenDART 5% 이상 보유 공시 | 장 마감/전체 수집 |
| `KRX_API_KEY` | KRX 공식 주식·ETF·지수·채권 일별 데이터 | 전체 수집 |
| `KRX_ID`, `KRX_PW` | KRX 로그인 기반 국내 투자자 수급·공매도 | 장 마감/전체 수집 |
| `FINNHUB_API_KEY` | 미국 기업 지표·애널리스트 추천·EPS 서프라이즈 | 전체 수집 |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 국내외 시장 뉴스 검색 | 전체 수집 |
| `GEMINI_API_KEY` | 수집 데이터 기반 AI 브리핑 | 전체 수집 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 자동 실행 결과 알림 | 알림 사용 시 |

네이버 금융 시세, FnGuide, FRED CSV, Yahoo Chart, FINRA 공개 데이터에는
별도 API 키가 필요하지 않습니다.

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

1. 한국은행 ECOS·FRED 국채 금리
2. 네이버 금융 KoAct·TIME ETF 현재가/등락률
3. FINRA 미국 일일 공매도 거래량
4. Nasdaq 전체 미국 종목과 Yahoo 상위 200종목 1년 차트·기술지표
5. Finnhub 상위 100종목 기업지표·추천·EPS 서프라이즈
6. KRX Open API 주식·ETF·지수·국채 일별 데이터
7. KRX 로그인 기반 코스피·코스닥 투자자 수급·공매도
8. 네이버 금융 국내 시총·재무지표와 FnGuide 과거 ROE
9. OpenDART 지분 및 최근 전체 공시
10. NAVER 검색 뉴스와 Gemini 시장 브리핑

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
- `--skip-finra`: FINRA 미국 공매도 거래량 수집 생략
- `--skip-krx`: KRX Open API와 로그인 기반 수급·공매도 수집 생략
- `--skip-us-market`: Nasdaq·Yahoo 미국시장 수집 생략
- `--skip-sec`: SEC 내부자·13D/G·8-K·IPO 공시 수집 생략
- `--skip-finnhub`: Finnhub 보강 수집 생략
- `--skip-news`: NAVER 검색 뉴스 수집 생략
- `--skip-ai-briefing`: Gemini 브리핑 생성 생략
- `--us-history-limit`: Yahoo 1년 차트를 받을 미국 상위 종목 수, 기본 200
- `--finnhub-limit`: Finnhub로 보강할 미국 상위 종목 수, 기본 100
- `--sec-limit`: SEC 공시를 확인할 미국 상위 종목 수, 기본 200
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
- `data/us_finra_short_volume.json`: FINRA 최신 미국 종목별 장외 공매도 거래량
- `data/us_finra_short_interest.json`: FINRA 최신 격주 종목별 공매도 잔고
- `data/us_market_snapshot.json`: Nasdaq 전체 미국 종목과 Yahoo 상위 종목 차트·기술지표
- `data/us_finnhub.json`: Finnhub 기업지표·추천 추이·EPS 서프라이즈
- `data/krx_openapi.json`: KRX 공식 일별 주식·ETF·지수·국채 데이터
- `data/korea_investor_flow.json`: 코스피·코스닥 개인·외국인·기관 종목별 수급과 일별 추이
- `data/korea_short_selling.json`: 코스피·코스닥 종목별 공매도 거래, 거래비중·잔고 상위 50
- `data/dart_disclosures.json`: 최근 코스피·코스닥 DART 공시와 이벤트 분류
- `data/naver_news.json`: 카테고리별 NAVER 검색 뉴스
- `data/ai_market_briefing.json`: 수집 데이터 기반 Gemini 브리핑
- `data/us_sec_filings.json`: SEC 내부자·13D/G·8-K·IPO 공시 메타데이터
- `data/data_manifest.json`: 생성된 JSON의 출처·건수·기준일·파일 크기 목록

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

# FINRA 미국 일일 공매도 거래량
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_finra_short_volume.py

# 미국 전체 종목 + 상위 200종목 1년 차트
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_us_market.py

# FINRA 격주 공매도 잔고 + SEC 주요 공시
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_finra_short_interest.py
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_sec_filings.py

# Finnhub 미국 기업·애널리스트 지표
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_finnhub_us.py

# KRX 공식 Open API
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_krx_openapi.py

# KRX 로그인 기반 국내 투자자 수급·공매도
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_krx_flow_short.py

# 네이버 금융
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_naver_market_sum.py

# FnGuide
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_fnguide_roe_history.py

# OpenDART
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_disclosures.py

# 뉴스·AI 브리핑·텔레그램 시험 알림
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_naver_news.py
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_gemini_briefing.py
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" telegram_notify.py --status success
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
- 평일 16:30 KST: 국내외 전체 시장·공시·뉴스·AI 브리핑
- 수동 실행: GitHub의 `Actions` → `Update market data` → `Run workflow`

자동 실행 전에 GitHub 저장소의 `Settings` → `Secrets and variables` →
`Actions` → `New repository secret`에서 다음 이름을 등록합니다.

- `ECOS_API_KEY`
- `DART_API_KEY`
- `KRX_API_KEY`
- `KRX_ID`
- `KRX_PW`
- `FINNHUB_API_KEY`
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

그리고 `Settings` → `Pages` → `Build and deployment`의 `Source`를
`GitHub Actions`로 한 번 설정합니다.

워크플로는 갱신된 `data/*.json`을 `github-actions[bot]` 이름으로 자동 커밋하고
현재 브랜치에 푸시한 다음, 같은 실행 안에서 갱신된 대시보드를 GitHub Pages에
직접 배포합니다. 예약 실행은 GitHub 서버 상황에 따라 몇 분 늦어질 수 있습니다.
수집 성공·실패 요약은 등록한 Telegram 채팅으로 전송됩니다.

KRX Open API 인증키만 발급받는 것과 각 API 사용 승인은 별개입니다. `krx_openapi.json`에서
특정 데이터셋이 `not_authorized`로 나오면 KRX Open API 사이트에서 해당 서비스의
`API 이용신청`을 추가로 승인받아야 합니다. 종목별 투자자 수급과 공매도는
`KRX_ID`/`KRX_PW` 로그인 세션으로 별도 수집됩니다. 공매도 잔고는 거래소 공개
시차 때문에 거래 데이터보다 기준일이 늦을 수 있으므로 `korea_short_selling.json`의
`transaction_date`와 `balance_date`를 따로 확인해야 합니다.

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
