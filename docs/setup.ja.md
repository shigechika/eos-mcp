# セットアップ

## インストール

```bash
pip install eos-mcp
```

ソースから:

```bash
git clone https://github.com/shigechika/eos-mcp.git
cd eos-mcp
uv sync            # または: pip install -e ".[dev]"
```

## config.ini

`config.ini.example` を `~/.config/eos-mcp/config.ini` にコピーし、認証情報を記入する:

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

このファイルがサーバの唯一の認証情報保管手段であり、機器のユーザ名・パスワードを渡す平文の環境変数は存在しない。`health_check` の設定状態確認を除く全ツールがこのファイルを読み込み、解決済みパスに実データが無ければ失敗する。

設定ファイルの探索順:

1. `EOS_MCP_CONFIG` 環境変数
2. `./config.ini`（カレントディレクトリ）
3. `~/.config/eos-mcp/config.ini`

個々の MCP ツール呼び出しでは `config_path` パラメータでパスを上書きすることも可能——それでも指すのはローカルファイルパスであり、認証情報そのものを直接渡す手段ではない。

## 組み込む前に確認する

```bash
# config.ini が読み込めるか確認し、機器一覧を表示
eos-mcp --check

# 特定ホストへ eAPI 接続も試す
eos-mcp --check --check-host switch1.example.com
```

終了コード: `0` は成功、`1` は設定エラー（`config.ini` が無い、またはパースできない）、`2` はホスト接続エラー（config に無いホスト、または eAPI 呼び出し自体の失敗）。一度実行しておけば「ツールが何も返さない」原因を先に潰しておける。

## MCP クライアントへの登録

### Claude Code（プラグイン）

このリポジトリはプラグイン 1 個のマーケットプレイスも兼ねているので、Claude Code から
そのまま導入できる:

```
/plugin marketplace add shigechika/eos-mcp
/plugin install eos-mcp@eos-mcp
```

プラグインは `uvx eos-mcp` を起動し、上記 [config.ini](#configini) と同じ `EOS_MCP_CONFIG` を読む。未設定のままなら通常の探索順（`./config.ini` → `~/.config/eos-mcp/config.ini`）にそのままフォールスルーする。`/plugin install` はサーバプロセスの配線だけを行うもので、`config.ini` ファイルやそこに書く機器ごとの eAPI 認証情報までは作ってくれない——プラグインを動かすマシン上に、あらかじめそのファイルが存在している必要がある（無ければ `health_check` 以外のツールはすべて失敗する）。

プラグインは `uvx` を起動するため、Claude Code を実行するプロセスの `PATH` に
`uvx` が通っている必要がある。ログインシェルなら通常問題ないが、GUI から起動した
場合は通っていないことがある。プラグインが起動しない場合は
[uv](https://docs.astral.sh/uv/) をシステム全体にインストールすること。

### Claude Code（手動）

`.mcp.json`:

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

### 直接実行

```bash
export EOS_MCP_CONFIG=~/.config/eos-mcp/config.ini
eos-mcp
```

## 状態を変えるツール

3 つのツールがガード付きの経路で機器の状態を変更する:

| ツール | API 呼び出し | 何が許可を決めるか |
|---|---|---|
| `push_config` | `configure session <name>` を開き `config_lines` を投入したうえで、`show session-config diffs` + `abort`（`dry_run=True`、デフォルト）または `commit timer HH:MM:SS`（`dry_run=False`）を実行——eAPI JSON-RPC Command API | eAPI アカウント自身の EOS 権限レベル: `configure session` モードに入れる必要がある（実質的に privilege 15 / enable アクセス）。デフォルトが `dry_run=True` なので、明示的に `dry_run=False` を指定しない限り差分表示と中断だけで済む。 |
| `confirm_config_session` | `configure session <name> commit` —— `push_config` が開始した commit timer 待ちのセッションを確定 | `push_config` と同じ EOS アカウント権限が必要。 |
| `abort_config_session` | `configure session <name> abort` —— 保留中のセッションを破棄 | `push_config` と同じ EOS アカウント権限が必要。 |

対象機器の `config.ini` アカウントを show 専用の低権限にしておけば、この 3 つは EOS 側の API で失敗するだけで書き込まれず、その機器に対する読み取り専用ツールはすべて動き続ける。

**`run_command`・`run_commands`・`run_command_batch`・`run_commands_batch` は、コマンド実行系として案内されているものの `show ...` 系コマンドに制限されていない。** サーバー側はコマンド文字列を検証もホワイトリスト化もせずそのまま eAPI Command API へ渡すため、これらのツールは `configure terminal ...` や `reload` を含む任意の enable モードコマンドを、設定済みの任意の機器（単体、または `_batch` 系なら `tags` でフリート全体）に対して実行できる。ゲートしているのは `push_config` と同じ EOS アカウント権限だが、`push_config` が持つ `dry_run` / commit timer のような安全機構は無い——機器の `config.ini` アカウントにどこまでの権限を持たせるかを判断するうえで覚えておく価値がある、事実上の第二の書き込み経路。

## 次に読むもの

[リファレンス](reference.ja.md) に全ツールの索引、`health_check` の契約、CLI をまとめている。
