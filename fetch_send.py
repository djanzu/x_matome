# fetch_and_notify.py
import os
from datetime import date, timedelta
from urllib.parse import quote
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
# suisei2 の vLLM（OpenAI 互換 API）を使用
from openai import OpenAI

# .env から設定を読み込む（既に環境変数が設定されている場合はそちらを優先）
load_dotenv()

# 設定項目
TARGET_USERNAME = os.environ.get("TARGET_USERNAME", "jack").lstrip("@")  # 取得対象のXユーザーID（@なし）
USER_DATA_DIR = "./x_user_data"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://192.168.2.131:8888/v1")
VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "EMPTY")  # vLLM を --api-key なしで起動していれば任意の値でよい
VLLM_MODEL = os.environ.get("VLLM_MODEL", "qwen3.8-flash-next")
DAYS = 7  # 今日を含めて何日分を取得するか

def get_recent_tweets(username, days=7, max_scrolls=50, max_idle_scrolls=3):
    """X の検索（from: / since: / until:）で、今日を含む直近 days 日分の投稿を取得する"""
    today = date.today()
    since = today - timedelta(days=days - 1)  # 今日を含めて days 日分
    until = today + timedelta(days=1)         # until は指定日を含まないため翌日を指定
    query = f"from:@{username} since:{since.isoformat()} until:{until.isoformat()}"
    # f=live で「最新」タブ（時系列順）を表示
    url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"

    tweets = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.new_page()
        page.goto(url)

        # ツイート要素が表示されるまで待機（期間内に投稿がなければ空で返す）
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except PlaywrightTimeoutError:
            context.close()
            return tweets

        # 新しいツイートが出てこなくなるまでスクロール
        collected = set()
        idle_scrolls = 0
        for _ in range(max_scrolls):
            new_count = 0
            for el in page.query_selector_all('article[data-testid="tweet"]'):
                text_el = el.query_selector('div[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = text_el.inner_text().strip()
                time_el = el.query_selector("time")
                posted_at = time_el.get_attribute("datetime") if time_el else ""
                # 投稿日時＋本文で重複判定（同じ文面の別投稿を潰さないため）
                key = (posted_at, text)
                if text and key not in collected:
                    collected.add(key)
                    tweets.append({"posted_at": posted_at, "text": text})
                    new_count += 1

            idle_scrolls = idle_scrolls + 1 if new_count == 0 else 0
            if idle_scrolls >= max_idle_scrolls:
                break

            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(2000)

        context.close()

    # 古い順に並べる
    tweets.sort(key=lambda t: t["posted_at"])
    return tweets

def summarize_tweets(tweets):
    client = OpenAI(base_url=VLLM_BASE_URL, api_key=VLLM_API_KEY)
    model = VLLM_MODEL
    formatted_tweets = "\n---\n".join(
        [f"{i+1}. [{t['posted_at']}] {t['text']}" for i, t in enumerate(tweets)]
    )

    prompt = f"""
以下のツイート（直近{DAYS}日間・{len(tweets)}件）を読み、主要な話題や投稿者の関心事・最新動向を簡潔に要約してください。

【ツイート一覧】
{formatted_tweets}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    return response.choices[0].message.content

def send_to_slack(summary, username):
    payload = {
        "text": f"🤖 *@{username} の直近{DAYS}日間のツイート要約*\n\n{summary}"
    }
    requests.post(SLACK_WEBHOOK_URL, json=payload)

if __name__ == "__main__":
    print("1. ツイート取得中...")
    tweets = get_recent_tweets(TARGET_USERNAME, days=DAYS)
    
    if not tweets:
        print("ツイートが取得できませんでした。")
        exit(1)
        
    print(f"2. {len(tweets)}件のツイートを要約中...")
    summary = summarize_tweets(tweets)
    
    print("3. Slackへ送信中...")
    send_to_slack(summary, TARGET_USERNAME)
    print("完了しました。")

