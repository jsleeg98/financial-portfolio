#!/usr/bin/env python3
"""종합거래내역 CSV → Google Sheets 업로드

탭 구조:
  - transactions : 전체 합산 (대시보드 로드용)
  - {증권사}-{계좌번호} : 계좌별 거래내역 (예: NH나무증권-202-01-292788)

사용법:
    python scripts/upload_to_sheets.py

설정:
    .env 파일에 SPREADSHEET_ID 설정 필요
    credentials/service_account.json 필요
"""

import os
import sys
import time
from pathlib import Path

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# web config 생성 스크립트 (같은 scripts/ 디렉토리)
sys.path.insert(0, str(Path(__file__).parent))
from generate_web_config import main as generate_web_config


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS_PATH = Path("credentials/service_account.json")
CSV_PATH = Path("output/종합거래내역.csv")
COMBINED_SHEET = "transactions"


def load_env():
    env_path = Path(".env")
    if not env_path.exists():
        return {}
    result = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def get_or_create_worksheet(spreadsheet, title: str, rows: int, cols: int):
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
    return ws


def upload_df(ws, df: pd.DataFrame):
    header = list(df.columns)
    rows = df.values.tolist()
    ws.update([header] + rows, value_input_option="USER_ENTERED")
    return len(df)


def main():
    # web/data/portfolio_config.json 갱신 (EXCLUDED_TICKERS 등 .env 설정 반영)
    generate_web_config()

    env = load_env()
    spreadsheet_id = env.get("SPREADSHEET_ID") or os.environ.get("SPREADSHEET_ID")
    if not spreadsheet_id:
        print("[ERROR] SPREADSHEET_ID가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    if not CREDENTIALS_PATH.exists():
        print(f"[ERROR] 서비스 계정 키를 찾을 수 없습니다: {CREDENTIALS_PATH}")
        sys.exit(1)

    if not CSV_PATH.exists():
        print(f"[ERROR] CSV 파일을 찾을 수 없습니다: {CSV_PATH}")
        sys.exit(1)

    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    print(f"CSV 로드: {len(df)}건")

    # 계좌 목록 추출 (증권사-계좌번호 조합)
    accounts = sorted(
        df.apply(lambda r: f"{r['증권사']}-{r['계좌번호']}", axis=1).unique()
    )
    print(f"계좌: {len(accounts)}개 → {', '.join(accounts)}")

    # Google Sheets 인증 및 접속
    creds = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=SCOPES)
    gc = gspread.authorize(creds)
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"[ERROR] 스프레드시트를 찾을 수 없습니다: {spreadsheet_id}")
        print("  → 서비스 계정 이메일에 스프레드시트 편집 권한을 부여했는지 확인하세요.")
        sys.exit(1)

    results = []

    # 1. 전체 합산 탭 (대시보드 로드용)
    print(f"\n[{COMBINED_SHEET}] 전체 {len(df)}건 업로드 중...")
    ws = get_or_create_worksheet(spreadsheet, COMBINED_SHEET, len(df) + 10, len(df.columns))
    upload_df(ws, df)
    results.append((COMBINED_SHEET, len(df)))
    time.sleep(1)  # API rate limit 방지

    # 2. 계좌별 탭
    for account in accounts:
        broker, acct_no = account.split("-", 1)
        acct_df = df[(df["증권사"] == broker) & (df["계좌번호"] == acct_no)].reset_index(drop=True)
        print(f"[{account}] {len(acct_df)}건 업로드 중...")
        ws = get_or_create_worksheet(spreadsheet, account, len(acct_df) + 10, len(acct_df.columns))
        upload_df(ws, acct_df)
        results.append((account, len(acct_df)))
        time.sleep(1)

    print(f"\n=== 업로드 완료 ===")
    for name, cnt in results:
        print(f"  [{name}] {cnt}건")
    print(f"\nURL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")


if __name__ == "__main__":
    main()
