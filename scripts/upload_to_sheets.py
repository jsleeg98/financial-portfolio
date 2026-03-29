#!/usr/bin/env python3
"""종합거래내역.csv → Google Sheets 업로드

사전 준비:
    1. credentials/service_account.json 에 서비스 계정 JSON 저장
    2. .env 또는 환경변수에 SPREADSHEET_ID 설정

사용법:
    python scripts/upload_to_sheets.py
    python scripts/upload_to_sheets.py --sheet-id <SPREADSHEET_ID>
    python scripts/upload_to_sheets.py --credentials credentials/service_account.json
"""

import argparse
import os
import sys
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CREDENTIALS = ROOT / "credentials" / "service_account.json"
DEFAULT_CSV = ROOT / "output" / "종합거래내역.csv"
WORKSHEET_NAME = "transactions"


def load_env() -> None:
    """프로젝트 루트의 .env 파일에서 환경변수 로드."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def upload(spreadsheet_id: str, credentials_path: Path, csv_path: Path) -> None:
    print(f"인증 중: {credentials_path}")
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(spreadsheet_id)

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
        print(f"워크시트 사용: {WORKSHEET_NAME}")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=10000, cols=20)
        print(f"워크시트 생성: {WORKSHEET_NAME}")

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    print(f"CSV 로드: {len(df)}건")

    ws.clear()
    data = [df.columns.tolist()] + df.values.tolist()
    ws.update(data, value_input_option="USER_ENTERED")

    print(f"\n업로드 완료: {len(df)}건")
    print(f"스프레드시트 URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")


def main():
    load_env()

    parser = argparse.ArgumentParser(description="종합거래내역 → Google Sheets 업로드")
    parser.add_argument(
        "--sheet-id",
        default=os.environ.get("SPREADSHEET_ID"),
        help="Google 스프레드시트 ID (또는 SPREADSHEET_ID 환경변수)",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIALS,
        help=f"서비스 계정 JSON 경로 (기본: {DEFAULT_CREDENTIALS})",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"업로드할 CSV 경로 (기본: {DEFAULT_CSV})",
    )
    args = parser.parse_args()

    if not args.sheet_id:
        print("[ERROR] 스프레드시트 ID가 필요합니다.")
        print("  방법 1: --sheet-id <ID> 옵션 사용")
        print("  방법 2: .env 파일에 SPREADSHEET_ID=<ID> 설정")
        sys.exit(1)

    if not args.credentials.exists():
        print(f"[ERROR] 서비스 계정 파일 없음: {args.credentials}")
        print("  credentials/service_account.json 에 서비스 계정 JSON 파일을 저장하세요.")
        sys.exit(1)

    if not args.csv.exists():
        print(f"[ERROR] CSV 파일 없음: {args.csv}")
        sys.exit(1)

    upload(args.sheet_id, args.credentials, args.csv)


if __name__ == "__main__":
    main()
