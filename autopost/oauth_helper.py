"""ブラウザでログインして「認可コード」を受け取るための小さな仕組み（TikTok用）。"""
from __future__ import annotations

import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

SUCCESS_HTML = (
    "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif'>"
    "<h2>ログインできました。</h2><p>このページを閉じて、黒い画面（コマンドプロンプト）に戻ってください。</p>"
    "</body></html>"
)


def extract_code(url_or_code: str) -> tuple[str, str]:
    """リダイレクト先のURL（またはコードそのもの）から code と state を取り出す。"""
    text = url_or_code.strip()
    if "code=" not in text:
        return text, ""
    qs = parse_qs(urlparse(text).query)
    return qs.get("code", [""])[0], qs.get("state", [""])[0]


def get_authorization_code(auth_url: str, redirect_uri: str, timeout: int = 300) -> tuple[str, str]:
    """ブラウザを開いてログインしてもらい、認可コードを受け取る。

    redirect_uri が http://localhost:ポート/... の場合は自動で受け取る。
    それ以外の場合（または自動で受け取れなかった場合）は、ブラウザのアドレス欄のURLを貼り付けてもらう。
    """
    parsed = urlparse(redirect_uri)
    result: dict[str, str] = {}

    server = None
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1") and parsed.port:

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                qs = parse_qs(urlparse(self.path).query)
                if "code" in qs:
                    result["code"] = qs["code"][0]
                    result["state"] = qs.get("state", [""])[0]
                elif "error" in qs:
                    result["error"] = qs.get("error_description", qs["error"])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(SUCCESS_HTML.encode("utf-8"))

            def log_message(self, *args):  # 余計な表示を出さない
                pass

        try:
            server = HTTPServer((parsed.hostname, parsed.port), Handler)
            server.timeout = 1
        except OSError:
            server = None

    print("ブラウザが開きます。投稿したいアカウントでログインし、「許可」を押してください。")
    print("（ブラウザが開かないときは、次のURLをコピーしてブラウザに貼り付けてください）")
    print(auth_url)
    webbrowser.open(auth_url)

    if server is not None:
        stop = threading.Event()

        def serve():
            import time

            end = time.time() + timeout
            while not stop.is_set() and time.time() < end and not result:
                server.handle_request()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        t.join(timeout + 2)
        stop.set()
        server.server_close()
        if "error" in result:
            raise RuntimeError(f"ログインが拒否されました: {result['error']}")
        if "code" in result:
            return result["code"], result.get("state", "")
        print("自動で受け取れませんでした。")

    print()
    print("「許可」を押したあとに表示されたページのアドレス欄のURLを、まるごとコピーして")
    pasted = input("ここに貼り付けて Enter を押してください: ")
    code, state = extract_code(pasted)
    if not code:
        raise RuntimeError("URLに認可コード（code=…）が見つかりませんでした。もう一度やり直してください。")
    return code, state
