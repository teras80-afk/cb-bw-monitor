"""
페이지 5 — 전환청구 데이터 진단 모드

특정 종목(예: 024840 케이비아이메탈) 입력 시
dart.event() 응답을 직접 화면에 표시하여 어떤 컬럼이 있는지,
실제 전환청구개시일이 어떻게 들어있는지 확인하는 디버깅 페이지.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from lib import require_dart_or_stop, get_dart_client

st.set_page_config(page_title="진단 모드", page_icon="🔧", layout="wide")
st.title("🔧 전환청구 데이터 진단")
st.caption("특정 종목의 dart.event() 응답을 그대로 보여줘 누락 원인 파악")

require_dart_or_stop()
dart, _ = get_dart_client()

ticker = st.text_input("진단할 종목코드 6자리", value="024840",
                        help="예: 024840 (케이비아이메탈)")

if not ticker.strip():
    st.stop()

ticker = ticker.strip().zfill(6)
end_date = datetime.now().strftime("%Y-%m-%d")
start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

st.markdown("---")
st.markdown(f"### 종목: `{ticker}` (조회 기간: 최근 5년)")

# ─── Step 1: dart.list() 발행 공시 조회 ───
st.markdown("#### 📋 Step 1: 발행 공시 (dart.list)")
try:
    df_list = dart.list(ticker, start=start_date, end=end_date, kind="B", final=True)
    if df_list is None or len(df_list) == 0:
        st.warning("발행 공시 0건")
    else:
        cb_bw = df_list[df_list["report_nm"].str.contains(
            "전환사채권|신주인수권부사채권", na=False, regex=True
        )]
        st.success(f"✅ 전체 {len(df_list)}건 / CB·BW 공시 {len(cb_bw)}건")
        if len(cb_bw) > 0:
            st.dataframe(cb_bw[["rcept_dt", "report_nm", "rcept_no"]],
                          use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"실패: {type(e).__name__}: {e}")

st.markdown("---")

# ─── Step 2: dart.event() 전환사채발행 ───
st.markdown("#### 🔍 Step 2: dart.event(ticker, '전환사채발행')")
try:
    ev_cb = dart.event(ticker, "전환사채발행", start=start_date, end=end_date)
    if ev_cb is None:
        st.error("❌ None 반환")
    elif len(ev_cb) == 0:
        st.warning(f"⚠️ 빈 DataFrame 반환 (행 0개) — 핵심 문제!")
        st.write("이 경우 전환청구개시일을 추출할 수 없음")
    else:
        st.success(f"✅ {len(ev_cb)}건 반환")

        # 컬럼명 보여주기
        st.markdown("**전체 컬럼명:**")
        st.code(", ".join(ev_cb.columns.tolist()))

        # 모든 행의 핵심 컬럼만
        st.markdown("**핵심 정보 추출:**")
        target_cols = []
        for c in ev_cb.columns:
            cl = str(c).lower()
            if any(k in cl for k in ["bd_tm", "bd_fta", "cv_prd_bgd", "cv_prd_edd",
                                      "cv_prc", "ex_prd_bgd", "ex_prd_edd",
                                      "rcept_dt", "rcept_no"]):
                target_cols.append(c)

        if target_cols:
            st.dataframe(ev_cb[target_cols], use_container_width=True, hide_index=True)
        else:
            st.warning("핵심 컬럼명을 못 찾음 — 컬럼 구조가 예상과 다름")

        # 전체 데이터 (디버깅용)
        with st.expander("🔬 전체 응답 데이터 보기"):
            st.dataframe(ev_cb, use_container_width=True, hide_index=True)

        # 첫 번째 행의 모든 컬럼 값을 일대일로 보여주기
        with st.expander("🔬 첫 번째 행 - 모든 컬럼 값"):
            first = ev_cb.iloc[0]
            for col in ev_cb.columns:
                val = first[col]
                st.write(f"- `{col}` = `{val}`")
except Exception as e:
    st.error(f"❌ 예외: {type(e).__name__}: {e}")

st.markdown("---")

# ─── Step 3: dart.event() 신주인수권부사채발행 ───
st.markdown("#### 🔍 Step 3: dart.event(ticker, '신주인수권부사채발행')")
try:
    ev_bw = dart.event(ticker, "신주인수권부사채발행", start=start_date, end=end_date)
    if ev_bw is None:
        st.info("None 반환 (BW 발행 이력 없음일 가능성)")
    elif len(ev_bw) == 0:
        st.info("빈 DataFrame (BW 발행 없음)")
    else:
        st.success(f"✅ {len(ev_bw)}건 반환")
        st.dataframe(ev_bw, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"❌ 예외: {type(e).__name__}: {e}")

st.markdown("---")
st.caption("💡 Step 2 결과로 다음을 알 수 있습니다:\n"
           "- '빈 DataFrame'이면 dart.event()가 이 종목 데이터를 못 가져옴 → 다른 방법 필요\n"
           "- 'N건 반환'인데 우리 화면엔 안 나오면 → 컬럼명 매칭 실패 → 코드 수정으로 해결")
