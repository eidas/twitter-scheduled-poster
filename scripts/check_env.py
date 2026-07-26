"""環境チェックスクリプト: 必要な依存関係と認証情報の確認."""
import importlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def check_python_packages():
    """必要なPythonパッケージの存在確認."""
    required = {
        "playwright": "playwright",
        "gspread": "gspread",
        "google.oauth2.service_account": "google-auth",
    }
    missing = []
    for module, package in required.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    return missing


def check_chrome_cdp_connection() -> tuple[bool, str]:
    """Chrome CDPへの接続確認."""
    import sys
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from chrome_attacher import ChromeAttacher

    attacher = ChromeAttacher()
    cdp_url = attacher.cdp_url
    if attacher.is_reachable():
        return True, cdp_url
    return False, f"{cdp_url} に応答なし\n  {ChromeAttacher.launch_hint()}"


def check_env_vars():
    """必要な環境変数の確認."""
    recommended = ["GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "SPREADSHEET_ID", "CHROME_CDP_URL"]
    missing_recommended = [v for v in recommended if not os.environ.get(v)]
    return missing_recommended


def check_google_credentials():
    """Googleサービスアカウント鍵ファイルの確認."""
    key_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "./credentials.json")
    if not os.path.exists(key_path):
        return False, key_path
    return True, key_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="X Batch Poster 環境チェック")
    parser.add_argument(
        "--skip-gsheet",
        action="store_true",
        help="Google Spreadsheet関連のチェックをスキップ（単発投稿モード用）",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("X Batch Poster - 環境チェック")
    print("=" * 50)
    errors = []

    # 1. Pythonパッケージ
    gsheet_packages = {"gspread", "google-auth"}
    print("\n[1/3] Pythonパッケージ...")
    missing_packages = check_python_packages()
    if args.skip_gsheet:
        missing_packages = [p for p in missing_packages if p not in gsheet_packages]
    if missing_packages:
        errors.append(f"pip install {' '.join(missing_packages)}")
        print(f"  ✗ 不足: {', '.join(missing_packages)}")
    else:
        print("  ✓ すべてインストール済み")

    # 2. Chrome CDP接続
    print("\n[2/3] Chrome CDP接続...")
    if not missing_packages or "playwright" not in " ".join(missing_packages):
        ok, detail = check_chrome_cdp_connection()
        if ok:
            print(f"  ✓ 接続成功: {detail}")
        else:
            errors.append(detail)
            print(f"  ✗ {detail}")
        # 推奨環境変数
        missing_rec = check_env_vars()
        if missing_rec:
            filtered = [v for v in missing_rec if v != "CHROME_CDP_URL"]
            if args.skip_gsheet:
                filtered = [v for v in filtered if v not in ("GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "SPREADSHEET_ID")]
            if "CHROME_CDP_URL" in missing_rec:
                print("  △ CHROME_CDP_URL 未設定（DevToolsActivePort から自動検出します）")
            if filtered:
                print(f"  △ 推奨: {', '.join(filtered)}（コマンド引数で指定も可）")
    else:
        print("  - スキップ（playwright 未インストール）")

    # 3. Google認証情報
    if args.skip_gsheet:
        print("\n[3/3] Google認証情報... スキップ（--skip-gsheet）")
    else:
        print("\n[3/3] Google認証情報...")
        exists, path = check_google_credentials()
        if exists:
            print(f"  ✓ 鍵ファイル: {path}")
        else:
            errors.append(f"Googleサービスアカウント鍵ファイルを配置: {path}")
            print(f"  ✗ 鍵ファイルが見つからない: {path}")

    # サマリー
    print("\n" + "=" * 50)
    if errors:
        print("✗ 以下を修正してください:")
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}")
        sys.exit(1)
    else:
        print("✓ すべてのチェックに合格しました")
        sys.exit(0)


if __name__ == "__main__":
    main()
