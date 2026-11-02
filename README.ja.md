# VCP TradingView リファレンス・トレーディング・エージェント (VCP-TV-RTA)

[English](README.md) | [**日本語**](README.ja.md)

[![VCP v1.1](https://img.shields.io/badge/VCP-v1.1-blue)](https://github.com/veritaschain/vcp-spec)
[![Non-certified PoC](https://img.shields.io/badge/Status-Non--certified_PoC-orange)](DISCLAIMER.md)
[![License CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

> **"Verify, Don't Trust."** — AIにはフライトレコーダーが必要

VCP-TV-RTA は、TradingView ベースの取引監査証跡を扱う **非認証の PoC（概念実証）** です。VCP v1.1 Silver を目標としていますが、**同梱 Evidence Pack は Silver 適合を実証していません**。アンカーはローカル記録のみで、独立検証可能な実外部アンカー証跡は含まれていません。

---

## 認証とMerkle構築の訂正 — 2026年11月2日

起動前に非公開の`VCP_WEBHOOK_SECRET`または`server.webhook_secret`を設定してください。
未設定・空の場合は、イベント・鍵・アンカーの初期化前に起動を拒否します。
`/vcp/`配下は`X-VCP-Webhook-Secret`ヘッダーによる認証が必要です。
イベント受信時のみ、JSON最上位の`webhook_secret`も受け付けます。
これは送信認証用の値で、記録・署名するイベントには含めません。
両方を送る場合は両方の一致が必要で、比較には`hmac.compare_digest`を使います。

従来の認証なしアラートは拒否されます。非公開の送信側・アラートテンプレートへ
認証値を設定するか、信頼する中継サーバーでヘッダーを追加してください。
同梱Pine戦略は秘密情報を挿入しません。公開スクリプトやURLへ認証値を入れないでください。
`/health`とAPIドキュメントは公開です。再送防止・利用者ごとの権限・本番適合性は未実装です。
詳細は[統合手順](docs/INTEGRATION.md)を参照してください。

ブラウザー向けCORSは`server.allowed_origins`で明示したHTTP(S)オリジンだけに許可します。
ワイルドカードを拒否し、資格情報付きCORSは無効です。CORS自体は認証ではありません。

Merkleツリーは過去の奇数ノード複製方式を保持します。RFC形式のハッシュ接頭辞を使いますが、
RFC 6962/9162の分割方式には準拠しません。未実装の整合性証明は検証で`False`（未検証）、
生成で`NotImplementedError`を返します。過去の証跡・ルート・包含証明の構築は変更しません。
[構築方式の制約](docs/MERKLE_LIMITATIONS.md)も確認してください。

強制・定期アンカーでは、プロバイダーが失敗を返す場合、例外が発生する場合、
処理がキャンセルされる場合に、未処理バッチを保持します。強制APIで結果を確認できない場合は
HTTP 502を返します。処理対象バッチを固定し、その間に届くイベントは別のツリーへ追加します。
再試行では固定済みバッチを優先し、そのルートに対する明示的な成功を受け取った場合だけ処理済みにします。
ローカルプロバイダーの成功はローカル記録のみを意味し、外部保証を示しません。
未処理件数は両ツリーの合計で、ステータスのルートは最も古い未処理バッチを示します。
この管理は単一プロセスのメモリー内に限られ、再起動時の復旧・複数ワーカー間の調整・
処理済み包含証明のアーカイブは未実装です。[アンカーの挙動](docs/INTEGRATION.md#force-anchor-testing-only)を参照してください。

## 概要

本エビデンスパックは、TradingView の Pine Script 環境で VCP の一部の仕組みを示す PoC です。本番品質や完全な適合性を実証するものではありません。Webhook とサイドカーアーキテクチャを使用して、取引イベントをキャプチャし、暗号学的監査証跡を生成します。

---

## クイックスタート

```bash
# クローン
git clone https://github.com/veritaschain/vcp-tradingview-rta-reference.git
cd vcp-tradingview-rta-reference

# インストール
pip install -r requirements.txt

# 鍵生成
python -m sidecar.keygen

# サーバー起動
export VCP_WEBHOOK_SECRET="$(openssl rand -hex 32)"
python -m sidecar.main
```

---

## クイック検証

```bash
python tools/verifier/vcp_verifier.py \
    evidence/01_trade_logs/vcp_tv_events.jsonl \
    -s evidence/04_anchor/security_object.json \
    -a evidence/04_anchor/anchor_reference.json
```

---

## 証跡と検証範囲

- 同梱40イベントのハッシュ・連番・PrevHash・Merkle root・件数の内部整合性を確認できます。独立した情報源に対する収録の完全性は確認できません。
- `anchor_type: "local"` は外部アンカーではなく、Silver の外部アンカー要件は未達です。OpenTimestamps・Bitcoin・TSA の実装もシミュレーションで、実外部証跡の生成・検証は未実装です。
- 署名・署名者の同一性・外部時刻・24時間以内のアンカー間隔・VCP 全体の適合性は検証しません。PoC 独自のシリアライズと Merkle 計算を再現するツールです。
- 上記コマンドの終了コード **2** は「内部整合性成功、Silver 適合は未実証」です。**1** は証跡不整合・入力エラーです。`--integrity-only` 指定時のみ限定した内部検証の成功を **0** にできます。
- イベント中の `tier: "SILVER"` はハッシュ対象の原データとして保持しており、適合判定ではありません。
- イベント時刻は2025年1月、ローカル生成物の日時は2026年1月です。実際のパック作成日時は不明なので `created_at` は `null` とし、元の2025年の値と修正理由を別途記録しています。詳細は [検証ガイド](docs/VERIFICATION_GUIDE.md) を参照してください。

## ライセンス

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)（エビデンスパック）  
MIT License（実装コード）

---

**VeritasChain Standards Organization (VSO)**  
*"Verify, Don't Trust."*

## ライセンスの適用範囲 — 2026年11月2日

文書は引き続きCC BY 4.0です。自社作成のコード・スクリプト・コード例・スキーマには、[Apache-2.0](LICENSE-CODE)による利用の選択肢を追加しています。従来の許諾と第三者の表示は維持します。詳細は[LICENSE](LICENSE)を参照してください。仕様の要件や適合状態を変更するものではありません。
