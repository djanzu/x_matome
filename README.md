# x_matome

指定した X（旧 Twitter）ユーザーの直近 7 日間の投稿を取得し、LLM で要約して Slack に送るスクリプトです。

1. Playwright でブラウザを操作し、X の検索（`from:` / `since:` / `until:`）から投稿を集める
2. vLLM などの OpenAI 互換 API で投稿を要約する
3. 要約を Slack の Incoming Webhook に送る

## 必要なもの

- Python 3
- X のアカウント（検索結果を見るためにログインが必要）
- OpenAI 互換 API のエンドポイント（vLLM など）
- Slack の Incoming Webhook URL

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```


### 設定ファイル

`.env.example` をコピーして `.env` を作り、値を書き換えます。

```bash
cp .env.example .env
```

| 変数名 | 内容 | 既定値 |
| --- | --- | --- |
| `TARGET_USERNAME` | 取得対象の X ユーザー ID（`@` なし） | `jack` |
| `SLACK_WEBHOOK_URL` | Slack の Incoming Webhook URL | なし（必須） |
| `VLLM_BASE_URL` | OpenAI 互換 API のベース URL | `http://192.168.2.131:8888/v1` |
| `VLLM_API_KEY` | API キー（vLLM を `--api-key` なしで起動しているなら任意の値でよい） | `EMPTY` |
| `VLLM_MODEL` | 要約に使うモデル名 | `qwen3.8-flash-next` |

すでに環境変数が設定されている場合は、`.env` よりそちらが優先されます。

### X へのログイン（初回のみ）

**venvを有効化するのを忘れないでください。**


```bash
python shokai.py
```

ブラウザが起動するので、X にログインしてください。ログインが終わったらターミナルで Enter を押します。ログイン情報は `x_user_data/` に保存され、以降の実行で使われます。

## 使い方

```bash
python fetch_send.py
```

実行すると、次の順に処理が進みます。

1. 対象ユーザーの直近 7 日分（今日を含む）の投稿を取得する
2. 取得した投稿を LLM で要約する
3. 要約を Slack に送る

期間内に投稿がない場合や取得に失敗した場合は、「ツイートが取得できませんでした。」と表示して終了します（終了コード 1）。

取得する日数は [fetch_send.py](fetch_send.py) の `DAYS` で変えられます。

## ファイル構成

| ファイル | 役割 |
| --- | --- |
| `shokai.py` | 初回ログイン用。ブラウザを開いてログイン情報を保存する |
| `fetch_send.py` | 投稿の取得・要約・Slack への送信を行う |
| `.env.example` | 設定ファイルのひな形 |
| `requirements.txt` | 依存パッケージ |

## 注意

- `x_user_data/` と `.env` にはログイン情報や Webhook URL が含まれます。`.gitignore` で除外していますが、共有しないよう注意してください。
- X の画面構成が変わると、投稿を取得できなくなることがあります。
- ログインの有効期限が切れたら、もう一度 `shokai.py` を実行してください。
