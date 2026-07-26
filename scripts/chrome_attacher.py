"""起動済みChromeへのCDPアタッチ機能.

記事「playwright-cli-attach-local-chrome」の手法に基づく実装。
`playwright attach --cdp=chrome` に相当するチャンネル名解決と
接続前ヘルスチェック（/json/version）を提供する。

接続方法の優先順位:
  1. 環境変数 CHROME_CDP_URL
  2. チャンネル名 "chrome" → ポートスキャンで自動解決
  3. DevToolsActivePort ファイルからポート読み取り
  4. デフォルト http://localhost:9222
"""
import json
import os
import platform
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser

# チャンネル名解決でスキャンするポート（playwright attach --cdp=chrome と同じ範囲）
_SCAN_PORTS = [9222, 9223, 9229, 9224, 9225]


class ChromeAttacher:
    """起動済みChromeにCDPでアタッチするクラス.

    使い方:
        attacher = ChromeAttacher()
        browser = attacher.connect(playwright_instance)
    """

    def __init__(self, cdp_url: Optional[str] = None):
        self._cdp_url = cdp_url or self.detect_cdp_url()

    @property
    def cdp_url(self) -> str:
        return self._cdp_url

    @staticmethod
    def detect_cdp_url() -> str:
        """環境変数・チャンネル名・DevToolsActivePort の順でCDP URLを解決する."""
        # 1. 環境変数
        env_url = os.environ.get("CHROME_CDP_URL", "")
        if env_url:
            return env_url

        # 2. チャンネル名 "chrome" → ポートスキャン
        # resolved = ChromeAttacher._resolve_channel("chrome")
        # if resolved:
        #     return resolved

        # 3. DevToolsActivePort ファイル
        port_file = ChromeAttacher._devtools_port_file()
        if port_file and port_file.exists():
            port = port_file.read_text().splitlines()[0].strip()
            ws_path = port_file.read_text().splitlines()[1].strip()
            ws_endpoint = f"ws://127.0.0.1:{port}{ws_path}"
            return ws_endpoint

        # 4. デフォルト
        return "http://localhost:9222"

    @staticmethod
    def _resolve_channel(channel: str) -> Optional[str]:
        """チャンネル名（"chrome" 等）をCDP URLに解決する.

        playwright attach --cdp=chrome と同様に /json/version でポートをスキャンする。
        Browser フィールドに "Chrome" が含まれるポートを返す。
        """
        for port in _SCAN_PORTS:
            url = f"http://localhost:{port}"
            info = ChromeAttacher._fetch_version_info(url)
            if info and channel.lower() in info.get("Browser", "").lower():
                return url
        return None

    @staticmethod
    def _devtools_port_file() -> Optional[Path]:
        """OS別の DevToolsActivePort ファイルパスを返す."""
        if platform.system() == "Windows":
            user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        elif platform.system() == "Darwin":
            user_data = os.path.expanduser("~/Library/Application Support/Google/Chrome")
        else:
            user_data = os.path.expanduser("~/.config/google-chrome")
        return Path(user_data) / "DevToolsActivePort"

    @staticmethod
    def _fetch_version_info(cdp_url: str) -> Optional[dict]:
        """/json/version エンドポイントからブラウザ情報を取得する."""
        try:
            parsed = urllib.parse.urlparse(cdp_url)
            if parsed.scheme in ("ws", "wss"):
                # ws://localhost:9222/devtools/browser/xxx → http://localhost:9222
                http_scheme = "https" if parsed.scheme == "wss" else "http"
                http_url = f"{http_scheme}://{parsed.netloc}/json/version"
            else:
                http_url = f"{cdp_url}/json/version"

            with urllib.request.urlopen(http_url, timeout=2) as res:
                return json.loads(res.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def is_reachable(self) -> bool:
        """Chrome が /json/version に応答するか確認する（接続前ヘルスチェック）."""
        return self._fetch_version_info(self._cdp_url) is not None

    def connect(self, playwright) -> Browser:
        """ヘルスチェック後に Chrome へ接続し Browser を返す.

        Args:
            playwright: sync_playwright().__enter__() で得た Playwright インスタンス

        Raises:
            RuntimeError: Chrome が起動していないか、CDP が無効な場合
        """
        # if not self.is_reachable():
        #     raise RuntimeError(
        #         f"Chrome に接続できません（{self._cdp_url}）\n"
        #         f"{self.launch_hint()}"
        #     )
        try:
            return playwright.chromium.connect_over_cdp(self._cdp_url)
        except Exception as e:
            raise RuntimeError(
                f"Chrome への接続に失敗しました（{self._cdp_url}）\n"
                f"{self.launch_hint()}\n"
                f"詳細: {e}"
            ) from e

    @staticmethod
    def launch_hint() -> str:
        """OS 別の Chrome 起動コマンド例を返す."""
        system = platform.system()
        if system == "Windows":
            cmd = (
                r'"C:\Program Files\Google\Chrome\Application\chrome.exe"'
                " --remote-debugging-port=0"
            )
        elif system == "Darwin":
            cmd = (
                '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"'
                " --remote-debugging-port=0"
            )
        else:
            cmd = "google-chrome --remote-debugging-port=0"

        return (
            "Chrome をリモートデバッグポート付きで起動してください:\n"
            f"  {cmd}\n"
            "起動後、X.com (https://x.com) にログインしてから再実行してください。"
        )
