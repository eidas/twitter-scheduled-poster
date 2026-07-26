"""Google Spreadsheet操作モジュール: 読み取り・書き込み."""
import os
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_client() -> gspread.Client:
    """認証済みgspreadクライアントを返す."""
    key_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "./credentials.json"
    )
    creds = Credentials.from_service_account_file(key_path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_worksheet(
    spreadsheet_id: str, sheet_name: str = "Sheet1"
) -> gspread.Worksheet:
    """指定のワークシートを取得."""
    client = get_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    return spreadsheet.worksheet(sheet_name)


def _normalize(record: dict) -> dict:
    """ヘッダーの末尾スペースを除去してキーを正規化する."""
    return {k.strip(): v for k, v in record.items()}


def fetch_next_pending_row(
    spreadsheet_id: str, sheet_name: str = "Sheet1"
) -> Optional[dict]:
    """statusが空またはpendingの最初の行を返す.

    Returns:
        {
            "row_number": int,       # 1-indexed (ヘッダー含む)
            "scheduled_at": str,
            "text": str,
            "media_urls": str,
            "status": str,
        }
        該当なしの場合はNone
    """
    ws = get_worksheet(spreadsheet_id, sheet_name)
    all_records = ws.get_all_records()

    for i, record in enumerate(all_records):
        record = _normalize(record)
        status = str(record.get("status", "")).strip().lower()
        if status in ("", "pending"):
            return {
                "row_number": i + 2,  # +1 for 0-index, +1 for header row
                "scheduled_at": str(record.get("scheduled_at", "")),
                "text": str(record.get("text", "")),
                "media_urls": str(record.get("media_urls", "")),
                "status": status,
            }
    return None


def write_result(
    spreadsheet_id: str,
    sheet_name: str,
    row_number: int,
    status: str,
    error_detail: str = "",
) -> None:
    """指定行のstatus, executed_at, error_detailを更新.

    列の位置: D=status(4), E=executed_at(5), F=error_detail(6)
    """
    ws = get_worksheet(spreadsheet_id, sheet_name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # バッチ更新で1回のAPI呼び出しにまとめる
    ws.update(
        f"D{row_number}:F{row_number}",
        [[status, now, error_detail]],
    )


def count_pending_rows(
    spreadsheet_id: str, sheet_name: str = "Sheet1"
) -> int:
    """未処理行の件数を返す."""
    ws = get_worksheet(spreadsheet_id, sheet_name)
    all_records = ws.get_all_records()
    return sum(
        1
        for r in all_records
        if str(_normalize(r).get("status", "")).strip().lower() in ("", "pending")
    )
