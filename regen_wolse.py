"""월세 모델만 재학습 + undervalued_full.csv 보증금 컬럼 추가"""
import os, sys
os.chdir("/Users/kimminseok/Desktop/realestate")
sys.stdout.reconfigure(line_buffering=True)

import pandas as pd
from realestate_ml import DBLoader, FeatureEngineer, run_wolse_pipeline, fetch_macro_rates

db = "realestate.db"
loader = DBLoader(db)
fe = FeatureEngineer()

print("거시지표 로딩...")
rates_df = fetch_macro_rates()
if rates_df.empty:
    rates_df = None

print("월세 파이프라인 시작...")
wolse_df = run_wolse_pipeline(loader, fe, rates_df=rates_df)

if wolse_df is None or wolse_df.empty:
    print("월세 결과 없음. 종료.")
    sys.exit(1)

existing = pd.read_csv("undervalued_full.csv")
other = existing[existing["거래유형"] != "월세"]
combined = pd.concat([other, wolse_df], ignore_index=True)
combined.to_csv("undervalued_full.csv", index=False, encoding="utf-8-sig")
print(f"저장 완료: {len(combined):,}건 (월세 {len(wolse_df):,}건 포함)")
