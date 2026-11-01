# Docker 运行配置与脱敏参考

[返回构建与部署指南](BUILD_AND_DEPLOY.md) · [下载环境配置参考](../deploy/templates/docker-server.redacted.env)

把这份说明和 `docker-server.redacted.env` 交给部署 Agent，即可核对游戏协议、资源路径及大会开关。参考值来自已验证运行配置中的通用部分，并于 2026-11-01 按公开源码的配置生成器复核；地址、数据库连接串和管理凭据使用占位符，运营数值由各自实例配置。

完整运行目录由仓库工具在目标机器生成。这个参考文件用于比对，生成入口与配置源如下：

```text
runtime/docker/
├── instance.json          实例配置源，保存本机地址、凭据和功能选项
├── compose.json           生成的容器、挂载、端口和资源配置
├── server.env             生成的游戏服务环境
├── database.env           生成的数据库环境与凭据
├── data/                  Script.pvf、外部频道表、资源 manifest
└── server/
    ├── configs/           生成的服务配置
    └── logs/              运行日志
```

使用 `--runtime-dir` 时，上述路径相对所选目录。Compose 项目名、镜像名和数据库卷沿用自己实例的设置。凭据、日志和存档保留在本机，公开资料使用本页的脱敏参考。

## 游戏协议参数

以下组合用于匹配 `official-24.9` 的客户端：

| 环境变量 | 参考值 | 含义与配置来源 |
| --- | --- | --- |
| `DNFBRIDGE_CURRENT_CLIENT_VERSION` | `official-24.9` | 客户端协议映射；实例字段 `client_version` |
| `DNFBRIDGE_GAME_UPPER_HEADER` | `server16` | 服务端下行包头格式；Docker 生成器固定写入 |
| `DNFBRIDGE_GAME_UPPER_BODY_CODEC` | `plaintext` | 服务端下行包体编码；实例字段 `body_codec` |
| `DNFBRIDGE_GAME_UPPER_CLIENT_BODY_CODEC` | `plaintext` | 客户端上行包体解码；实例字段 `client_body_codec` |
| `DNFBRIDGE_DPROTO_MODE` | `legacy_patch` | 当前 dproto 兼容模式；Docker 生成器固定写入 |

这些是明确选择的 Docker 协议值；直接运行服务程序时，部分未设置项采用另一组源码默认值。核对自己的 EXE、PVF 与协议组合，并记录完整 SHA256，不能只凭客户端显示的版本号判断配套。

## 从实例源生成配置

首次部署按[构建与部署指南](BUILD_AND_DEPLOY.md#在-linux-上启动一套测试服)执行 `prepare`，显式传入真实 PVF 和完整外部频道 ETC。然后在生成的 `instance.json` 中合入下面的字段，保留原有地址、密码、数据库与其他设置：

```json
{
  "client_version": "official-24.9",
  "body_codec": "plaintext",
  "client_body_codec": "plaintext",
  "dungeon_tournament": "vendor",
  "joust_event_enabled": false,
  "packet_log": false
}
```

在仓库根目录重新生成文件：

```sh
sh deploy/docker/manage.sh prepare
```

已有实例使用原来的 `--runtime-dir`、`--project` 和 `--image` 参数。`prepare` 生成配置；`up` 会再次生成并启动或重建容器。正式服按已确认的维护窗口执行 `up`，随后核对实际游戏进程环境。

`server.env` 与 `server/configs/` 由 [Docker 生成器](../deploy/docker/manage.py)维护，后续修改继续从 `instance.json` 开始。需要调整兼容开关时，使用其中的 `runtime_compatibility` 对象；允许的键和值以生成器的 `RUNTIME_COMPATIBILITY_VALUES` 为准。

## 魂大会与赛马是不同开关

**普通大会和魂大会需要 `dungeon_tournament: "vendor"`**，对应：

```dotenv
DNFBRIDGE_DUNGEON_TOURNAMENT=vendor
```

当前[大会开关实现](../go-server/internal/services/dnfbridge/dungeon_tournament_config.go)只把去空格、忽略大小写后的 `vendor` 识别为启用；缺失、空值、`off`、`true`、`1` 都是关闭。实例生成器接受 `off` 或 `vendor`。

大会地图的对手来自 `[tournament enemies]`，通过赛程通知 386/387 下发。关闭大会模式时，这些地图可能进入零怪、立即清房的路径。遇到“魂黄龙大会不出怪、直接胜利”时，先检查实际进程是否启用了 `vendor`，再对照该次入场的地图和赛程报文。风法与女弹药使用同一套大会；按职业补一套地图不能解决开关未生效的问题。资源与入口依据见[大会入口核对](seeker/QST-015-016-tournament-entry.md)。

**赛马活动 2365 继续关闭**，对应 `joust_event_enabled: false` / `DNFBRIDGE_JOUST_EVENT_ENABLED=false`。已有数据库的活动保存值优先于环境变量，还需核对 `effectiveEnabled` 与 `pendingRestart`，完整步骤见[活动开关说明](BUILD_AND_DEPLOY.md#当前活动开关与赛马关闭方法)。

## 只读核对实际进程

下面的 Linux 命令适用于默认 Compose 项目，输出仅包含本页涉及的协议及活动参数。使用自定义项目时，替换项目名与 Compose 路径。主机需要 Python 3 和读取游戏进程环境的权限。

```sh
container_id=$(docker compose -p servers5a3-local -f runtime/docker/compose.json ps -q server)
game_pid=$(docker top "$container_id" -eo pid,comm | awk '$2 == "DNF90Server" {print $1}')
sudo python3 - "$game_pid" <<'PY'
import pathlib
import sys

pid = sys.argv[1]
if not pid.isdecimal():
    raise SystemExit("Expected one running DNF90Server process")
keys = (
    "DNFBRIDGE_CURRENT_CLIENT_VERSION",
    "DNFBRIDGE_GAME_UPPER_HEADER",
    "DNFBRIDGE_GAME_UPPER_BODY_CODEC",
    "DNFBRIDGE_GAME_UPPER_CLIENT_BODY_CODEC",
    "DNFBRIDGE_DPROTO_MODE",
    "DNFBRIDGE_DUNGEON_TOURNAMENT",
    "DNFBRIDGE_JOUST_EVENT_ENABLED",
)
raw = pathlib.Path(f"/proc/{pid}/environ").read_bytes().decode()
values = dict(row.split("=", 1) for row in raw.split("\0") if "=" in row)
for key in keys:
    print(f"{key}={values.get(key, '<UNSET>')}")
PY
```

文件中的新值、容器启动时的值和实际进程值应一致。`<UNSET>` 表示未设置，继续按相应模块的默认值判断。活动的持久化覆盖另从活动管理读取；上述进程环境核对不代替该项检查。

## 向他人分享配置

直接分享[公开参考文件](../deploy/templates/docker-server.redacted.env)即可。需要追加自己实例的信息时，保留相关变量名和普通开关值，并将以下内容整体替换为占位符：

- 数据库 DSN，包括用户名、密码、主机及数据库名。
- 管理／代理／登录令牌、签名私钥、OAuth 凭据及带鉴权参数的 URL。
- 实际公网／私网地址、域名、SSH 身份、个人绝对路径和诊断角色标识。

`DNFBRIDGE_ACCOUNT_API_LOGIN_TOKEN=true` 是启用令牌机制的布尔配置，可以保留；真实令牌内容需移除。分享文件逐项核对后单独交付，不打包原始 `runtime/docker/`、数据库卷或日志。
