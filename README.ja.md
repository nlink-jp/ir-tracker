# ir-tracker

進行中のインシデント対応会話を継続的にインジェスト・分析し、タイムラインで可視化するライブ IR トラッカー。

[English README is here](README.md)

## コンセプト

[ai-ir](https://github.com/nlink-jp/ai-ir) がインシデント**終了後**のポストモーテムを行うのに対し、ir-tracker は進行中のインシデントの**ライブ**状況把握を提供する。

```
[インシデント対応中]                       [インシデント終了後]

stail export → ir-tracker ingest          stail export → aiir ingest
             → ir-tracker analyze                      → aiir report
             → ir-tracker status
             ↻ (15-30分ごとに繰り返し)

「今、何が起きている？」                    「何が起きて、何を学んだか？」
```

## 機能

- **差分分析** — 新規・変更されたセグメントのみ LLM に送信
- **インシデントサマリ** — インシデント全体のエグゼクティブ概要を自動生成
- **アクティビティ密度チャート** — メッセージ量の時系列ヒートマップ
- **2カラム Web UI** — タイムライン + フローティング状況パネル、ダーク/ライトテーマ
- **メッセージドリルダウン** — セグメントクリックで元の会話を表示
- **多言語対応** — 分析は英語、翻訳オーバーレイで任意の言語（日本語等）表示
- **状況エクスポート** — Current Situation を Markdown でダウンロード（Web UI + CLI）
- **コンテキスト連鎖** — 圧縮された前セグメントコンテキストで LLM の継続性を維持
- **プロンプトインジェクション防御** — ノンス付き XML タグでユーザーメッセージをラッピング
- **セキュリティヘッダー** — CSP, X-Frame-Options, X-Content-Type-Options

## クイックスタート

```bash
# インストール
git clone https://github.com/nlink-jp/ir-tracker.git
cd ir-tracker
uv sync

# 設定
export GOOGLE_CLOUD_PROJECT="your-project-id"
gcloud auth application-default login

# インジェスト → 分析 → 表示
ir-tracker ingest export.json
ir-tracker analyze --lang ja
ir-tracker serve
# http://127.0.0.1:8080 を開く
```

## CLI

```bash
ir-tracker ingest <export.json> [--channel name]  # メッセージ取り込み（重複排除・自動セグメント化）
ir-tracker analyze [-v] [--lang ja]               # 未分析セグメントを分析 + 翻訳
ir-tracker translate --lang ja [-v]               # 翻訳のみ実行
ir-tracker status [--format json|markdown] [--lang ja]  # タイムライン出力
ir-tracker situation [--lang ja] [-o file.md]     # 現在の状況を Markdown 出力
ir-tracker segments                               # セグメント一覧と状態
ir-tracker serve [--port 8080] [--host 127.0.0.1] # Web UI 起動
ir-tracker reset                                  # 分析をクリア（メッセージは保持）
```

全コマンド共通で `--db <path>` により SQLite データベースパスを指定可能（デフォルト: `tracker.db`）。

## Web UI

| ページ | URL | 説明 |
|--------|-----|------|
| タイムライン | `/` | インシデントサマリ、密度チャート、セグメントタイムライン、状況パネル |
| セグメント | `/segments` | セグメント一覧と状態 |
| API: タイムライン | `/api/timeline` | JSON タイムラインデータ |
| API: 状況 | `/api/situation.md` | Markdown 状況ダウンロード |
| API: メッセージ | `/api/segments/{id}/messages` | セグメント内メッセージ（JSON） |

全ページ `?lang=ja` で翻訳オーバーレイ表示。

## 設定

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"   # 必須
export GOOGLE_CLOUD_LOCATION="us-central1"       # 任意（デフォルト: us-central1）
export IR_TRACKER_MODEL="gemini-2.5-pro"         # 任意（デフォルト: gemini-2.5-pro）
export IR_TRACKER_TZ="Asia/Tokyo"                # 任意（システムから自動検出）
```

認証: `gcloud auth application-default login` またはサービスアカウントキー。

## セキュリティ

- 全データはローカル保存（SQLite ファイル）。Vertex AI API エンドポイントのみにデータ送信。
- Web UI は `127.0.0.1` のみにバインド。`--host 0.0.0.0` 使用時は警告を表示。
- Web UI に認証なし — 信頼されたネットワークでのみ使用。
- ノンス付き XML タグ（`<user_data_{nonce}>`）によるプロンプトインジェクション防御。
- セキュリティヘッダー: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`。
- 全 SQL クエリはパラメータ化（文字列結合なし）。
- JavaScript でのユーザーデータ表示は DOM API ベース（`innerHTML` 不使用）。
- Jinja2 自動エスケープ有効。

## アーキテクチャ

```
ir_tracker/
  cli.py           — CLI エントリポイント（argparse サブコマンド）
  ingest.py        — stail/scat エクスポート解析、ts による重複排除
  segmenter.py     — 時間窓 + ギャップ検出によるセグメンテーション
  analyzer.py      — Gemini 2.5 Pro セグメント分析 + インシデントサマリ
  translator.py    — Gemini Flash 翻訳（キャッシュ付き）
  timeline.py      — Markdown/JSON タイムライン + 状況エクスポート
  storage.py       — SQLite スキーマ（messages, segments, analyses, translations, context）
  web.py           — FastAPI アプリ（タイムライン、セグメント、API エンドポイント）
  templates/       — Jinja2 HTML（base, timeline, segments）
  static/          — CSS（ライト/ダークテーマ）
```

## 設計資料

- [アーキテクチャ](docs/design/architecture.md) — コンポーネント、データフロー、CLI、セキュリティ
- [セグメンテーション](docs/design/segmentation.md) — 時間窓 + ギャップ検出アルゴリズム
- [分析](docs/design/analysis.md) — LLM パイプライン、コンテキスト連鎖、出力スキーマ

## ai-ir との関係

| 観点 | ai-ir | ir-tracker |
|---|---|---|
| タイミング | インシデント後 | インシデント中 |
| 入力 | 1回のエクスポート | 継続的な再インジェスト |
| 分析 | 会話全体を一括 | セグメント単位・差分 |
| 出力 | 最終レポート | 成長するタイムライン |
| LLM | OpenAI 互換 | Vertex AI Gemini（1M コンテキスト） |
| ストレージ | ステートレス（ファイル） | ステートフル（SQLite） |

両ツールとも同じ stail/scat エクスポート形式を入力とする。

## cybersecurity-series の一部

ir-tracker は [cybersecurity-series](https://github.com/nlink-jp/cybersecurity-series) の一部 —
脅威インテリジェンス、インシデント対応、セキュリティ運用のための AI 活用ツール群。
