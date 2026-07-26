"""バッチオーケストレーター: Spreadsheet読み取り→X.com予約→結果書き戻しのループ."""
import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from gsheet_ops import fetch_next_pending_row, write_result, count_pending_rows
from x_scheduler import XScheduler


MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
RATE_LIMIT_WAIT = 30  # seconds


def parse_scheduled_at(value: str) -> datetime:
    """予約日時文字列をdatetimeに変換.

    対応フォーマット: YYYY-MM-DD HH:MM, YYYY/MM/DD HH:MM
    """
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"日時フォーマットが不正です: '{value}' (期待: YYYY-MM-DD HH:MM)")


def validate_row(row: dict) -> tuple[bool, str]:
    """行データのバリデーション.

    Returns: (is_valid, skip_reason)
    """
    text = row.get("text", "").strip()
    if not text:
        return False, "テキストが空です"
    if len(text) > 280:
        return False, f"テキストが280文字を超えています ({len(text)}文字)"

    scheduled_at_str = row.get("scheduled_at", "").strip()
    if not scheduled_at_str:
        return False, "予約日時が空です"

    try:
        dt = parse_scheduled_at(scheduled_at_str)
    except ValueError as e:
        return False, str(e)

    if dt <= datetime.now():
        return False, f"予約日時が過去です: {scheduled_at_str}"

    return True, ""


def process_single_row(
    scheduler: XScheduler,
    row: dict,
    spreadsheet_id: str,
    sheet_name: str,
) -> str:
    """1行を処理: バリデーション→投稿予約→結果書き込み.

    Returns: "scheduled" | "failed" | "skipped"
    """
    row_number = row["row_number"]
    print(f"\n--- 行 {row_number} を処理中 ---")
    print(f"  テキスト: {row['text'][:50]}{'...' if len(row['text']) > 50 else ''}")
    print(f"  予約日時: {row['scheduled_at']}")

    # バリデーション
    is_valid, skip_reason = validate_row(row)
    if not is_valid:
        print(f"  スキップ: {skip_reason}")
        write_result(spreadsheet_id, sheet_name, row_number, "skipped", skip_reason)
        return "skipped"

    # 予約投稿を実行（リトライ付き）
    dt = parse_scheduled_at(row["scheduled_at"])
    media_paths = None
    media_urls = row.get("media_urls", "").strip()
    if media_urls:
        # NOTE: URLからのメディアダウンロードは未実装
        # ローカルファイルパスが指定された場合のみ対応
        media_paths = [p.strip() for p in media_urls.split(",") if p.strip()]

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            scheduler.schedule_post(
                text=row["text"],
                scheduled_at=dt,
                media_paths=media_paths,
            )
            print(f"  ✓ 予約設定完了")
            write_result(spreadsheet_id, sheet_name, row_number, "scheduled")
            return "scheduled"
        except RuntimeError as e:
            last_error = str(e)
            if "ログインを確認していません" in last_error or "ログインされていません" in last_error:
                raise
            if "レートリミット" in last_error or "rate" in last_error.lower():
                print(f"  レートリミット検知、{RATE_LIMIT_WAIT}秒待機...")
                time.sleep(RATE_LIMIT_WAIT)
            else:
                print(f"  リトライ {attempt}/{MAX_RETRIES}: {last_error}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

    # 全リトライ失敗
    print(f"  ✗ 失敗: {last_error}")
    write_result(spreadsheet_id, sheet_name, row_number, "failed", last_error)
    return "failed"


def test():
    """簡単なテスト関数."""
    print("テスト関数が呼び出されました。X.comへの接続確認＋1件の予約投稿をテストします。")
    scheduler = XScheduler()
    try:
        scheduler.start()
        print("\nX.com ログイン確認中...")
        scheduler.ensure_logged_in()
        print("✓ ログイン確認成功\n")

        scheduler.schedule_post(
            text="test",
            scheduled_at=datetime.now() + timedelta(days=1),
            media_paths=None,
        )
        print(f"  ✓ 予約設定完了")

    except Exception as e:
        print(f"テスト中にエラーが発生: {e}")
    finally:
        scheduler.stop()


def run_single(text: str, scheduled_at_str: str, media: Optional[str] = None):
    """スプレッドシートを使わず単発で予約投稿を実行する."""
    row = {
        "text": text,
        "scheduled_at": scheduled_at_str,
        "media_urls": media or "",
        "row_number": None,
    }
    is_valid, skip_reason = validate_row(row)
    if not is_valid:
        print(f"エラー: {skip_reason}")
        sys.exit(1)

    dt = parse_scheduled_at(scheduled_at_str)
    media_paths = None
    if media:
        media_paths = [p.strip() for p in media.split(",") if p.strip()]

    scheduler = XScheduler()
    try:
        scheduler.start()
        print("\nX.com ログイン確認中...")
        scheduler.ensure_logged_in()
        print("✓ ログイン確認成功\n")

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                scheduler.schedule_post(text=text, scheduled_at=dt, media_paths=media_paths)
                print("✓ 予約設定完了")
                return
            except RuntimeError as e:
                last_error = str(e)
                if "ログインを確認していません" in last_error or "ログインされていません" in last_error:
                    raise
                if "レートリミット" in last_error or "rate" in last_error.lower():
                    print(f"  レートリミット検知、{RATE_LIMIT_WAIT}秒待機...")
                    time.sleep(RATE_LIMIT_WAIT)
                else:
                    print(f"  リトライ {attempt}/{MAX_RETRIES}: {last_error}")
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY)

        print(f"✗ 失敗: {last_error}")
        sys.exit(1)
    except Exception as e:
        print(f"\n予期しないエラー: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        scheduler.stop()


def main():
    parser = argparse.ArgumentParser(description="X.com予約投稿バッチ / 単発投稿")
    parser.add_argument(
        "--max-rows", type=int, default=10, help="最大処理行数 (default: 10)"
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("SPREADSHEET_ID", ""),
        help="Google SpreadsheetのID",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.environ.get("SHEET_NAME", "Sheet1"),
        help="シート名 (default: Sheet1)",
    )
    parser.add_argument(
        "--test", action="store_true", help="テストモード: ログイン確認と1件の予約投稿テストを実行"
    )
    # 単発投稿オプション
    parser.add_argument("--text", help="投稿テキスト（単発投稿モード）")
    parser.add_argument(
        "--scheduled-at",
        dest="scheduled_at",
        help="予約日時 YYYY-MM-DD HH:MM (JST)（単発投稿モード）",
    )
    parser.add_argument(
        "--media",
        help="メディアファイルパス（カンマ区切り、最大4件）（単発投稿モード）",
    )
    args = parser.parse_args()

    if args.test:
        test()
        return

    # 単発投稿モード: --text と --scheduled-at が指定されたらスプレッドシート不要
    if args.text or args.scheduled_at:
        if not args.text:
            print("エラー: --text を指定してください")
            sys.exit(1)
        if not args.scheduled_at:
            print("エラー: --scheduled-at を指定してください")
            sys.exit(1)
        run_single(args.text, args.scheduled_at, args.media)
        return

    if not args.spreadsheet_id:
        print("エラー: --spreadsheet-id または SPREADSHEET_ID 環境変数を指定してください")
        sys.exit(1)

    # 未処理行数を確認
    pending = count_pending_rows(args.spreadsheet_id, args.sheet_name)
    actual_max = min(args.max_rows, pending)
    print(f"未処理行数: {pending}, 今回の処理上限: {args.max_rows}, 実行予定: {actual_max}")

    if actual_max == 0:
        print("処理対象の行がありません。")
        sys.exit(0)

    # Chrome に接続してログイン確認
    scheduler = XScheduler()
    results = {"scheduled": 0, "failed": 0, "skipped": 0}

    try:
        scheduler.start()
        print("\nX.com ログイン確認中...")
        scheduler.ensure_logged_in()
        print("✓ ログイン確認成功\n")

        # メインループ
        processed = 0
        while processed < args.max_rows:
            row = fetch_next_pending_row(args.spreadsheet_id, args.sheet_name)
            if row is None:
                print("\n未処理の行がなくなりました。")
                break

            try:
                result = process_single_row(
                    scheduler, row, args.spreadsheet_id, args.sheet_name
                )
                results[result] += 1
            except RuntimeError as e:
                if "ログインを確認していません" in str(e) or "ログインされていません" in str(e):
                    print(f"\n致命的エラー: {e}")
                    print("バッチを中断します。")
                    break
                results["failed"] += 1

            processed += 1

            # 行間に少し待機（レートリミット対策）
            if processed < args.max_rows:
                time.sleep(3)

    except Exception as e:
        print(f"\n予期しないエラー: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        scheduler.stop()

    # 結果サマリー
    print("\n" + "=" * 50)
    print("実行結果サマリー")
    print("=" * 50)
    print(f"  予約成功 (scheduled): {results['scheduled']}")
    print(f"  失敗     (failed):    {results['failed']}")
    print(f"  スキップ (skipped):   {results['skipped']}")
    print(f"  合計:                 {sum(results.values())}")
    print("=" * 50)

    if results["failed"] > 0:
        sys.exit(2)  # 部分的な失敗


if __name__ == "__main__":
    main()
