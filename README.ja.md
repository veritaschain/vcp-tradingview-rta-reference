# VCP TradingView リファレンス・トレーディング・エージェント (VCP-TV-RTA)

[English](README.md) | [**日本語**](README.ja.md)

[![VCP v1.1](https://img.shields.io/badge/VCP-v1.1-blue)](https://github.com/veritaschain/vcp-spec)
[![Non-certified PoC](https://img.shields.io/badge/Status-Non--certified_PoC-orange)](DISCLAIMER.md)
[![License CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

> **"Verify, Don't Trust."** — AIにはフライトレコーダーが必要

VCP-TV-RTA は、TradingView ベースの取引監査証跡を扱う **非認証の PoC（概念実証）** です。VCP v1.1 Silver を目標としていますが、**同梱 Evidence Pack は Silver 適合を実証していません**。アンカーはローカル記録のみで、独立検証可能な実外部アンカー証跡は含まれていません。

---

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
