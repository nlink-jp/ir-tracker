# ir-tracker

進行中のインシデント対応会話を継続的にインジェスト・分析し、タイムラインで可視化するライブ IR トラッカー。

**ステータス: 設計フェーズ** — アーキテクチャおよび詳細設計完了、実装は後続。

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

## 仕組み

1. **Ingest** — Slack エクスポート（stail/scat 形式）を SQLite に取り込む。メッセージ ts で重複排除。重複データを何度投入しても安全。
2. **Segment** — メッセージストリームを時間窓ベース（デフォルト30分）のセグメントに分割。アクティビティの急増ではエントロピーベースの分割、静寂期間ではギャップ検出。
3. **Analyze** — 新規・変更セグメントのみ Gemini 2.5 Pro（1M コンテキスト）に送信。前セグメントの圧縮コンテキストで継続性を維持。
4. **Status** — 何が起きたか、誰が何をしているか、主要な発見、未解決の疑問をタイムラインで描画。

## 計画中の CLI

```bash
ir-tracker ingest <export.json>    # メッセージ取り込み（重複排除・ソート）
ir-tracker analyze                  # 未分析セグメントを分析
ir-tracker status                   # タイムライン出力
ir-tracker serve                    # Web UI
ir-tracker segments                 # セグメント一覧と状態
ir-tracker reset                    # 分析をクリア（メッセージは保持）
```

## 設計資料

- [アーキテクチャ](docs/design/architecture.md) — コンポーネント、データフロー、CLI、セキュリティ
- [セグメンテーション](docs/design/segmentation.md) — 時間窓 + エントロピーアルゴリズム、エッジケース
- [分析](docs/design/analysis.md) — LLM パイプライン、コンテキスト連鎖、出力スキーマ、コスト最適化

## ai-ir との関係

| 観点 | ai-ir | ir-tracker |
|---|---|---|
| タイミング | インシデント後 | インシデント中 |
| 入力 | 1回のエクスポート | 継続的な再インジェスト |
| 分析 | 会話全体を一括 | セグメント単位・差分 |
| 出力 | 最終レポート | 成長するタイムライン |
| LLM | OpenAI 互換 | Vertex AI Gemini（1M コンテキスト） |
| ストレージ | ステートレス（ファイル） | ステートフル（SQLite） |
