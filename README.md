# CB/BW Monitor

한국 상장사 전환사채(CB) · 신주인수권부사채(BW) 통합 조회 사이트.
DART 전자공시 기반, Streamlit으로 구현.

## 페이지 구성

- **🎯 종목별 조회** — 발행 이력, 미상환 잔액, 잠재 출회주식수, 희석률, D-Day
- **📈 시장 동향** — 최근 N일 시장 전체 CB/BW 신규 발행 공시
- **📋 관심종목 모니터** — 관심종목 일괄 스캔
- **⏰ 전환청구 임박** — 시장 전체 D-30 도래 종목 검색

## 배포 방법

### 1. GitHub 레포 생성
- Repository name: `cb-bw-monitor`
- Public/Private 선택 (Streamlit Cloud Free 플랜은 Public 권장)
- 이 폴더의 모든 파일을 업로드

### 2. Streamlit Cloud 배포
1. https://share.streamlit.io 접속
2. "New app" 클릭
3. Repository: `your-id/cb-bw-monitor` 선택
4. Branch: `main`, Main file path: `Home.py`
5. Deploy

### 3. Secrets 설정
Streamlit Cloud → 앱 Settings → Secrets에 추가:

```toml
DART_API_KEY = "발급받은_40자리_DART_키"

# 관심종목 GitHub 저장 기능 사용 시 (선택)
GITHUB_TOKEN = "github_pat_..."
GITHUB_REPO = "your-id/cb-bw-monitor"
GITHUB_BRANCH = "main"
CB_WATCHLIST_PATH = "cb_watchlist.txt"
```

DART API 키 발급: https://opendart.fss.or.kr

## 데이터 출처

- **DART 전자공시** (opendart.fss.or.kr) — CB/BW 발행공시, 정기보고서
- **FinanceDataReader** — KRX 종목명·상장주식수 매핑

## 면책 조항

본 사이트의 계산 결과는 공개 데이터 기반 자체 계산이며, 실제 투자 판단의
근거가 되어서는 안 됩니다. 모든 정보는 DART 원문 공시와 회사 IR 자료로
교차 확인하시고, 본 사이트로 인한 손실에 대해 책임지지 않습니다.
