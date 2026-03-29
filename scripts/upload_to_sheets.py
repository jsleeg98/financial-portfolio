#!/usr/bin/env python3
"""종합거래내역 CSV → Google Sheets 업로드

사용법:
    python scripts/upload_to_sheets.py

설정:
    .env 파일에 SPREADSHEET_ID 설정 필요
    credentials/service_account.json 필요

업로드 대상: output/종합거래내역.csv → 시트 'transactions'
"""

import os
import sys
from pathlib import Path

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

CREDENTIALS_PATH = Path("credentials/service_account.json")
CSV_PATH = Path("output/종합거래내역.csv")
SHEET_NAME = "transactions"


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


def main():
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

    # CSV 로드
    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    print(f"CSV 로드: {len(df)}건")

    # Google Sheets 인증
    creds = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=SCOPES)
    gc = gspread.authorize(creds)

    # 스프레드시트 열기
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"[ERROR] 스프레드시트를 찾을 수 없습니다: {spreadsheet_id}")
        print("  → 서비스 계정 이메일에 스프레드시트 편집 권한을 부여했는지 확인하세요.")
        sys.exit(1)

    # 시트 선택 또는 생성
    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
        print(f"시트 '{SHEET_NAME}' 기존 내용 초기화 중...")
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        print(f"시트 '{SHEET_NAME}' 생성 중...")
        ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=len(df) + 10, cols=len(df.columns))

    # 헤더 + 데이터 업로드
    header = list(df.columns)
    rows = df.values.tolist()
    all_data = [header] + rows

    ws.update(all_data, value_input_option="USER_ENTERED")

    print(f"\n=== 업로드 완료 ===")
    print(f"시트: '{SHEET_NAME}'")
    print(f"행수: {len(df)}건 (헤더 포함 {len(all_data)}행)")
    print(f"URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")


if __name__ == "__main__":
    main()
