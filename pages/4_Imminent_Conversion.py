"""
페이지 4 — 전환청구 임박 (디버깅 모드)
원인 파악용. dart.event() 응답을 직접 확인.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from lib import require_dart_or_stop, get_dart_client

st.set_page_config(page_title="전환청구 임박 (진단)", page_icon="⏰", layout="wide")
st.title("⏰ 전환청구 임박 (진단 모드)")
st.caption("dart.event() 동작을 직접 확인하여 원인 파악")

require_dart_or_stop()
dart, _ = get_dart_client()

st.markdown("---")
st.markdown("### 🔍 단계별 진단")

# Step 1: dart.list() 동작 확인
st.markdown("#### Step 1: 시장 전체 발행공시 조회 (최근 90일)")
end = datetime.now().strftime("%Y-%m-%d")
start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

with st.spinner("dart.list() 호출 중..."):
    try:
        df_list = dart.list(start=start, end=end, kind="B", final=True)
        st.success(f"✅ 응답 받음 — 총 {len(df_list) if df_list is not None else 0}건")
        if df_list is not None and len(df_list) > 0:
            st.write("**컬럼명**:", list(df_list.columns))
            mask = df_list["report_nm"].str.contains(
                "전환사채권\\s*발행결정|신주인수권부사채권\\s*발행결정",
                na=False, regex=True
            )
            cb_bw = df_list[mask]
            st.write(f"CB/BW 공시 수: **{len(cb_bw)}건**")
            if len(cb_bw) > 0:
                st.dataframe(cb_bw[["rcept_dt", "corp_name", "stock_code", "report_nm"]].head(5),
                              use_container_width=True, hide_index=True)
                # 첫 번째 종목 코드 저장
                test_ticker = str(cb_bw.iloc[0]["stock_code"]).zfill(6)
                test_corp = cb_bw.iloc[0]["corp_name"]
                st.session_state["test_ticker"] = test_ticker
                st.session_state["test_corp"] = test_corp
    except Exception as e:
        st.error(f"❌ 실패: {e}")
        st.stop()

st.markdown("---")

# Step 2: dart.event() 동작 확인
st.markdown("#### Step 2: 종목별 dart.event() 호출 테스트")

if "test_ticker" not in st.session_state:
    st.warning("Step 1에서 테스트 종목을 못 찾음")
    st.stop()

test_ticker = st.session_state["test_ticker"]
test_corp = st.session_state["test_corp"]
st.info(f"테스트 종목: **{test_corp}** ({test_ticker})")

ev_start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
ev_end = datetime.now().strftime("%Y-%m-%d")

with st.spinner(f"dart.event({test_ticker}, '전환사채권 발행결정') 호출 중..."):
    try:
        ev_df = dart.event(test_ticker, "전환사채권 발행결정", start=ev_start, end=ev_end)
        if ev_df is None:
            st.error("❌ None 반환")
        elif len(ev_df) == 0:
            st.warning("⚠️ 빈 DataFrame 반환 (행 0개)")
            st.write("이 경우 시장 전체 임박 검색이 작동 안 함")
        else:
            st.success(f"✅ {len(ev_df)}건 반환")
            st.write("**컬럼명 전체**:")
            st.code(", ".join(ev_df.columns.tolist()))
            st.write("**첫 번째 행 (모든 컬럼)**:")
            first_row = ev_df.iloc[0]
            for col in ev_df.columns:
                val = first_row[col]
                st.write(f"- `{col}`: `{val}`")
    except Exception as e:
        st.error(f"❌ 예외 발생: {type(e).__name__}: {e}")

st.markdown("---")

# Step 3: 다른 호출 방식 테스트 (이름 없이)
st.markdown("#### Step 3: 다른 호출 방식 시도")

with st.spinner("event() 다양한 방식 시도..."):
    methods = [
        ("기본", lambda: dart.event(test_ticker, "전환사채권 발행결정", start=ev_start, end=ev_end)),
        ("종료일 없이", lambda: dart.event(test_ticker, "전환사채권 발행결정", start=ev_start)),
        ("기간 없이", lambda: dart.event(test_ticker, "전환사채권 발행결정")),
    ]

    for name, fn in methods:
        try:
            r = fn()
            if r is None:
                st.write(f"- **{name}**: None")
            elif len(r) == 0:
                st.write(f"- **{name}**: 빈 DataFrame")
            else:
                st.write(f"- **{name}**: ✅ {len(r)}건 (컬럼: {list(r.columns)[:5]}...)")
        except Exception as e:
            st.write(f"- **{name}**: ❌ {type(e).__name__}: {str(e)[:80]}")

st.markdown("---")
st.caption("📌 이 화면은 진단용입니다. 결과 확인 후 원래 코드로 복원합니다.")
