"""
CB/BW Monitor — 홈
한국 상장사의 전환사채(CB) / 신주인수권부사채(BW) 정보 통합 조회 사이트
"""
import streamlit as st
from lib import get_dart_client, _HAS_DART, _HAS_FDR

st.set_page_config(
    page_title="CB/BW Monitor",
    page_icon="🏦",
    layout="wide",
)

st.title("🏦 CB/BW Monitor")
st.caption("한국 상장사 전환사채(CB) · 신주인수권부사채(BW) 통합 조회 — DART 전자공시 기반")

st.markdown("---")

# 시스템 상태
col1, col2 = st.columns(2)
with col1:
    st.markdown("#### 🔌 시스템 상태")
    if _HAS_DART:
        dart, err = get_dart_client()
        if dart is not None:
            st.success("✅ DART API 연결 정상")
        else:
            st.error("❌ DART API 키 미설정")
            with st.expander("상세"):
                st.code(err)
    else:
        st.error("❌ OpenDartReader 라이브러리 없음")

    if _HAS_FDR:
        st.success("✅ FinanceDataReader 로딩됨 (종목명 자동 변환 가능)")
    else:
        st.info("ℹ️ FinanceDataReader 미사용 (Python 3.14 호환 이슈로 제외) — **6자리 종목코드 직접 입력** 방식")

with col2:
    st.markdown("#### 📚 사용 메뉴")
    st.markdown(
        """
        왼쪽 사이드바에서 페이지를 선택하세요:

        - **1️⃣ 종목별 조회** — 특정 종목의 CB/BW 발행 이력, 미상환 잔액, 잠재 희석률
        - **2️⃣ 시장 동향** — 최근 시장 전체의 CB/BW 신규 발행 공시
        - **3️⃣ 관심종목 모니터** — 저장한 관심종목들 일괄 스캔
        - **4️⃣ 전환청구 임박** — 향후 D-30 이내 전환청구 개시 예정 종목
        """
    )

st.markdown("---")

st.markdown("""
### 📖 용어 가이드

- **CB (Convertible Bond, 전환사채)**: 발행 시 일반 채권이지만, 일정 기간 후 발행회사 주식으로 전환할 수 있는 권리가 붙은 채권
- **BW (Bond with Warrant, 신주인수권부사채)**: 채권 + 신주인수권. 행사 시 신주 발행
- **미상환 잔액**: 발행 후 아직 상환·전환되지 않고 남아있는 원금
- **전환청구개시일**: 보유자가 주식 전환을 청구할 수 있게 되는 시점 (보통 발행 후 1년)
- **잠재 출회주식수**: 미상환 잔액 ÷ 전환가액 = 전환되면 시장에 풀릴 주식 수
- **희석률**: 잠재 출회주식수 ÷ 현재 상장주식수
""")

st.markdown("---")

st.caption(
    "📌 본 사이트는 공개 데이터(DART 전자공시) 기반 자체 계산 결과를 제공합니다. "
    "실제 투자 판단은 반드시 DART 원문 공시와 회사 IR 자료를 교차 확인하세요. "
    "본 사이트의 계산 결과를 근거로 한 투자 손실에 대해 책임지지 않습니다."
)
