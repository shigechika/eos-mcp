# eos-mcp

[English](README.md) | 日本語

Arista EOS 機器を eAPI 経由で操作する MCP サーバ。

show コマンド実行、running-config 取得、configure session を使った設定投入（コミットタイマー付き）、tech-support 収集などを MCP 対応 AI アシスタントに提供します。

ドキュメント: <https://shigechika.github.io/eos-mcp/ja/>

## インストール

```bash
pip install eos-mcp
```

## 設定

`config.ini.example` を `~/.config/eos-mcp/config.ini` にコピーし、認証情報を記入してください。

```ini
[DEFAULT]
username = admin
password = yourpassword
transport = https
verify = false

[switch1.example.com]
tags = main,dc1

[switch2.example.com]
tags = main,dc1
```

設定ファイルの探索順:
1. `EOS_MCP_CONFIG` 環境変数
2. `./config.ini`（カレントディレクトリ）
3. `~/.config/eos-mcp/config.ini`

（個々のMCPツール呼び出しでは、`config_path`パラメータでパスを上書きすることも可能）

## 使い方

### Claude Code（プラグイン）

このリポジトリはプラグイン 1 個のマーケットプレイスも兼ねているので、Claude Code から
そのまま導入できる:

```
/plugin marketplace add shigechika/eos-mcp
/plugin install eos-mcp@eos-mcp
```

プラグインは `uvx eos-mcp` を起動し、[設定](#設定)に書いたのと同じ `EOS_MCP_CONFIG`
を読む。未設定のままなら通常の探索順（`./config.ini` → `~/.config/eos-mcp/config.ini`）
にそのままフォールスルーする。`/plugin install` はサーバプロセスの配線だけを行うもので、
`config.ini` ファイルやそこに書く機器ごとの eAPI 認証情報までは作ってくれない——プラグ
インを動かすマシン上に、あらかじめそのファイルが存在している必要がある（無ければ
`health_check` 以外のツールはすべて失敗する）。

プラグインは `uvx` を起動するため、Claude Code を実行するプロセスの `PATH` に
`uvx` が通っている必要がある。ログインシェルなら通常問題ないが、GUI から起動した
場合は通っていないことがある。プラグインが起動しない場合は
[uv](https://docs.astral.sh/uv/) をシステム全体にインストールすること。

### Claude Code（手動）

`.mcp.json` に追加:

```json
{
  "mcpServers": {
    "eos-mcp": {
      "type": "stdio",
      "command": "eos-mcp"
    }
  }
}
```

`config.ini` が上記の既定の探索先に無い場合のみ `"env": { "EOS_MCP_CONFIG": "..." }` を追加する。

### Claude Desktop

`claude_desktop_config.json` に同じ設定を追加する。

### シェルから直接

```bash
# 設定確認と機器一覧表示
eos-mcp --check

# 特定ホストへの疎通確認
eos-mcp --check --check-host switch1.example.com

# MCP サーバ起動（stdio トランスポート）
eos-mcp
```

## ツール一覧

| ツール | 説明 |
|---|---|
| `health_check` | サーバのバージョンと設定状態を報告（軽量・機器には接続しない） |
| `get_router_list` | 登録済み機器を一覧表示（タグフィルタ対応） |
| `get_device_facts` | 1 台の機器情報を取得（モデル・シリアル・EOS バージョン・稼働時間・メモリ） |
| `get_device_facts_batch` | 複数台の機器情報を並列取得 |
| `get_version` | EOS バージョン文字列を返す（疎通確認用） |
| `run_command` | 1 台の機器で enable モードコマンドを 1 つ実行 |
| `run_commands` | 1 台の機器で enable モードコマンドを複数実行 |
| `run_command_batch` | 複数台の機器で enable モードコマンドを並列実行 |
| `get_config` | running-config を取得 |
| `get_config_diff` | ロールバックチェックポイントとの設定差分を表示 |
| `list_config_sessions` | configure session の一覧と状態を表示 |
| `push_config` | configure session 経由で設定を投入（デフォルトは dry_run=True） |
| `confirm_config_session` | commit timer 待ちのセッションを確定 |
| `abort_config_session` | 保留中のセッションを中断 |
| `collect_tech_support` | show tech-support を収集 |
| `daily_brief` | 複数台のヘルスチェック（環境・errdisabled・稼働時間・メモリ・MLAG・直近 syslog アラート） |

## 要件

- Python >= 3.10
- Arista EOS（eAPI 有効化済み: `management api http-commands`）
- 対象機器のポート 443（HTTPS）への到達性

## TLS 互換性（EOS 4.28.x + Python 3.14）

EOS 4.28.x と Python 3.14 の組み合わせで `SSLV3_ALERT_HANDSHAKE_FAILURE` が発生する場合、eos-mcp は自動的にレガシー TLS を有効化するパッチを適用します。

## 設定投入の安全機構

`push_config` は以下の安全機構を備えています:

- **dry_run モード**（デフォルト）: `configure session` を作成して差分を確認するだけで、commit しません
- **コミットタイマー**: 実投入時は `commit timer` でタイムアウトを設定。`confirm_config_session` で確定するまで自動ロールバック
- **セッション管理**: `list_config_sessions` で現在のセッション状態を確認、`abort_config_session` でいつでも中断可能

これら 3 つ（`push_config`・`confirm_config_session`・`abort_config_session`）を実際に許可しているのは、`config.ini` に書いた eAPI アカウント自身の EOS 権限レベルである。`configure session` モードに入れる権限（実質的に privilege 15 / enable アクセス）が無ければ、これらは EOS 側の API で失敗するだけで書き込まれず、その機器に対する読み取り専用ツールはすべて動き続ける。対象機器のアカウントを show 専用の低権限にしておけば、それがそのまま実効的な安全境界になる。

**`run_command`・`run_commands`・`run_command_batch`・`run_commands_batch` は、コマンド実行系として案内されているものの `show ...` 系コマンドに制限されていない。** サーバー側はコマンド文字列を検証もホワイトリスト化もせずそのまま eAPI Command API へ渡すため、これらのツールは `configure terminal ...` や `reload` を含む任意の enable モードコマンドを、設定済みの任意の機器（単体、または `_batch` 系なら `tags` でフリート全体）に対して実行できる。ゲートしているのは `push_config` と同じ EOS アカウント権限だが、`push_config` が持つ dry_run / commit timer のような安全機構は無い——機器の `config.ini` アカウントにどこまでの権限を持たせるかを判断するうえで覚えておく価値がある、事実上の第二の書き込み経路である。

## 開発

### ライブスモークテスト

ユニットテストはフィクスチャに対してロジックを検証するだけで、ツールが実データを
返さなくなったことは検出できない。`scripts/smoke_test.py` は設定済みの機器に対して
**登録されている全ツール**を実行し、空・不正・エラー応答を失敗として報告する。

```bash
# サーバーと同じインベントリファイル（EOS_MCP_CONFIG）を使う
uv run python scripts/smoke_test.py
uv run python scripts/smoke_test.py --only facts --traceback
```

- **読み取り専用**。`push_config`・`confirm_config_session`・`abort_config_session` は
  名前で除外する（テストで強制）。`collect_tech_support` も除外する — 機器を変更しないが、
  ここでの検証に使わない出力のために機器 CPU を数分間占有するため。コマンド実行系ツールは
  `show version` で検証する。これらは enable モードのコマンドを一般に受け付けるので、
  スモークテストが重大なコマンドを打つ主体になってはならない。
- **レポートにペイロードを出さない**。ツール名とステータスのみ。エラー文言は必ず
  機器名を含み、ペイロードは設定そのものなので伏字にする。
- **機器固有の値を spec に書かない**。ホスト単位のツールが必要とする機器名は、設定済み
  インベントリから実行時に発見し、空ならスキップする。2本のテストで担保: 該当パラメータの
  直値を拒否し、アドレス的な形がファイル内に現れることを禁じる（公開リポジトリのため）。
- 各 probe は、これらのツールが例外の代わりに返す `Error (<host>): ...` 行を必ず拒否する。
  さもないと到達不能な機器が「成功」として通ってしまう。
- CI では安価な半分を強制する。probe spec の無いツールを登録するとビルドが失敗するので
  （`tests/test_smoke_probes.py`）、ツール追加時に「どうやって動作を確認するか」を必ず決めることになる。
- `scripts/smoke_harness.py` はエンジンであり EOS 固有の知識を持たない。このハーネスを
  共有する各サーバーで同一に保つ方針なので、エンジンのバグはこの写しを直すのではなく
  一度直して全体に同期する。

## ライセンス

Apache-2.0