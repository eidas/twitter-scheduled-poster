"""X.com Web UI予約投稿モジュール: Playwrightによる操作.

ユーザーが開いているChromeにCDP（Chrome DevTools Protocol）で接続して操作する。
Chrome は --remote-debugging-port フラグ付きで起動し、X.comにログイン済みであること。

操作フロー:
  1. ログイン確認（未ログイン時はエラー）
  2. 投稿作成画面を開く
  3. テキストを入力
  4. メディアがあれば添付
  5. 予約日時を設定
  6. 予約確定
"""
import time
from datetime import datetime
from typing import Optional

from chrome_attacher import ChromeAttacher
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
    TimeoutError as PlaywrightTimeout,
)

# セレクタ定義（UI変更時はここを更新）
# 最新のセレクタは references/x-selectors.md も参照
SELECTORS = {
    # 投稿
    "tweet_textbox": 'div[data-testid="tweetTextarea_0"]',
    "schedule_button": 'button[data-testid="scheduleOption"]',

    # 予約ダイアログ
    "schedule_date_input": 'input[data-testid="scheduledDatePickerInput"]',  # 存在しない場合あり
    "schedule_month_select": 'select[data-testid="ScheduledTweetDatePickerMonthInput"]',  # 存在しない場合あり
    "schedule_day_select": 'select[data-testid="ScheduledTweetDatePickerDayInput"]',      # 存在しない場合あり
    "schedule_year_select": 'select[data-testid="ScheduledTweetDatePickerYearInput"]',    # 存在しない場合あり
    "schedule_hour_select": 'select[data-testid="ScheduledTweetDatePickerHourInput"]',    # 存在しない場合あり
    "schedule_minute_select": 'select[data-testid="ScheduledTweetDatePickerMinuteInput"]',# 存在しない場合あり
    "schedule_ampm_select": 'select[data-testid="ScheduledTweetDatePickerAMPMInput"]',    # 存在しない場合あり（24h表記の場合不要）
    "schedule_confirm_button": 'button[data-testid="scheduledConfirmationPrimaryAction"]',

    # 投稿確定
    "tweet_submit_button": 'button[data-testid="tweetButton"]',

    # メディア
    "media_input": 'input[data-testid="fileInput"]',

    # 確認用
    "home_indicator": 'a[data-testid="AppTabBar_Home_Link"]',
    "toast_success": 'div[data-testid="toast"]',
}


class XScheduler:
    """X.comの投稿予約をPlaywrightで操作するクラス.

    ユーザーが起動済みのChromeにCDPで接続して操作する。
    Chrome は --remote-debugging-port フラグ付きで起動されていること。
    """

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._logged_in = False

    def start(self):
        """ユーザーのChromeにCDPで接続する."""
        self._playwright = sync_playwright().start()
        attacher = ChromeAttacher()
        self._browser = attacher.connect(self._playwright)

        if not self._browser.contexts:
            raise RuntimeError("Chrome のコンテキストが見つかりません")
        self._context = self._browser.contexts[0]
        self._page = self._context.new_page()

    def stop(self):
        """操作用ページを閉じる（ブラウザは閉じない）."""
        if self._page:
            self._page.close()
        if self._playwright:
            self._playwright.stop()

    def ensure_logged_in(self) -> bool:
        """X.comにログイン済みか確認する（ログインは行わない）.

        Returns: ログイン済みなら True
        Raises: RuntimeError if not logged in
        """
        page = self._page
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)

        if page.query_selector(SELECTORS["home_indicator"]):
            self._logged_in = True
            return True

        raise RuntimeError(
            "X.com にログインされていません。\n"
            "Chrome で https://x.com にアクセスしてログインしてから再実行してください。"
        )

    def schedule_post(
        self,
        text: str,
        scheduled_at: datetime,
        media_paths: Optional[list[str]] = None,
    ) -> bool:
        """投稿を予約設定する.

        Args:
            text: 投稿テキスト
            scheduled_at: 予約日時 (JST)
            media_paths: ローカルの画像/動画ファイルパスのリスト

        Returns: 成功なら True
        Raises: RuntimeError on failure
        """
        if not self._logged_in:
            raise RuntimeError("ログインを確認していません。先に ensure_logged_in() を呼んでください。")

        page = self._page

        # 投稿作成画面を開く
        page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded")
        time.sleep(2)

        # テキスト入力
        textbox = page.wait_for_selector(SELECTORS["tweet_textbox"], timeout=10000)
        if not textbox:
            raise RuntimeError("投稿テキストボックスが見つかりません")
        textbox.click()
        page.keyboard.type(text, delay=30)
        time.sleep(1)

        # メディア添付
        if media_paths:
            file_input = page.query_selector(SELECTORS["media_input"])
            if file_input:
                file_input.set_input_files(media_paths)
                time.sleep(3)

        # 予約ボタンをクリック
        schedule_btn = page.wait_for_selector(SELECTORS["schedule_button"], timeout=10000)
        if not schedule_btn:
            raise RuntimeError("予約ボタンが見つかりません")
        schedule_btn.click()
        time.sleep(1)

        # 日時を設定
        self._set_schedule_datetime(page, scheduled_at)
        time.sleep(1)

        # 予約確定
        confirm_btn = page.wait_for_selector(
            SELECTORS["schedule_confirm_button"], timeout=10000
        )
        if not confirm_btn:
            raise RuntimeError("予約確定ボタンが見つかりません")
        confirm_btn.click()
        time.sleep(2)

        # 投稿（予約）ボタンをクリック
        submit_btn = page.wait_for_selector(
            SELECTORS["tweet_submit_button"], timeout=10000
        )
        if submit_btn:
            submit_btn.click()
            time.sleep(3)

        return True

    def _set_schedule_datetime(self, page: Page, dt: datetime):
        """予約ダイアログの日時フィールドを設定.

        X.comの予約UIはselect要素で月・日・年・時・分を個別に設定する。
        UIの変更頻度が高いため、セレクタが見つからない場合は
        代替手段（直接入力など）を試みる。
        """
        # テキストからセレクタを探す
        selects_from_text = {
            "month": ("月", str(dt.month)),
            "day": ("日", str(dt.day)),
            "year": ("年", str(dt.year)),
            "hour": ("時", str(dt.hour)),
            "minute": ("分", str(dt.minute)),
        }
        for field_name, (text, value) in selects_from_text.items():
            try:
                el = page.locator('label', has=page.locator('span', has_text=text)).locator('xpath=following-sibling::select[1]')
                if el:
                    el.select_option(value=value)
                    time.sleep(0.3)
            except PlaywrightTimeout:
                print(
                    f"  警告: {field_name}のセレクタが見つかりません。"
                    f"references/x-selectors.md を確認してください。"
                )
                self._try_fallback_datetime_input(page, field_name, value)
        return

        # フォールバック
        selects = {
            "month": (SELECTORS["schedule_month_select"], str(dt.month)),
            "day": (SELECTORS["schedule_day_select"], str(dt.day)),
            "year": (SELECTORS["schedule_year_select"], str(dt.year)),
            "hour": (SELECTORS["schedule_hour_select"], str(dt.hour)),
            "minute": (SELECTORS["schedule_minute_select"], str(dt.minute)),
        }
        for field_name, (selector, value) in selects.items():
            try:
                el = page.wait_for_selector(selector, timeout=5000)
                if el:
                    el.select_option(value=value)
                    time.sleep(0.3)
            except PlaywrightTimeout:
                print(
                    f"  警告: {field_name}のセレクタが見つかりません。"
                    f"references/x-selectors.md を確認してください。"
                )
                self._try_fallback_datetime_input(page, field_name, value)

    def _try_fallback_datetime_input(
        self, page: Page, field_name: str, value: str
    ):
        """select要素が見つからない場合のフォールバック.

        X.comがカスタムUIに変更した場合に備える。
        具体的なフォールバック戦略はUI変更時に実装する。
        """
        print(f"  フォールバック: {field_name}={value} の設定を試行中...")
        pass
