# 从 GitHub 拉取 Session Hub

本扩展现在随 `MaHsiChu/hermes-agent` 仓库的 `extensions/session-hub/` 一起分发，是统一任务看板、Codex / Claude 原会话视图、消息投递、完成收件箱和聊天任务引用的实际实现。桌面宿主对工作区侧栏及任务引用的支持在提交 `6ebd7ef` 中。

## 目录与配置

- `plugin/desktop/`：任务看板、会话详情、输入框、附件、任务引用和状态展示。
- `plugin/dashboard/`：本地后端插件路由。
- `service.py`、`live.py`、`board.py`：本地服务、投递状态及任务投影。
- `readers.py`、`transcript.py`：原会话只读索引与完整历史分页。
- `codex_app.py`、`claude_live.py`：两种 App 控制适配。
- `mcp_server.py`：Agent 可调用的会话与任务工具。
- `test_*.py`、`*.test.mjs`：隔离行为测试；`*-test.mjs` 是额外浏览器验收脚本。

`settings.json`、`data/`、绑定、token、原始日志、会话数据库、截图和构建产物不随源码发布。本机历史验收文件名在旧文档中保留用于追溯，这些文件不在 Git 中，不能作为新机器验收证据。

## 安装

先按仓库说明安装 Python 虚拟环境及根 Node 工作区依赖。必须使用安装好 Hermes 依赖的 Python；不要迁移 Windows `.venv` 到 Mac。Node 依赖从根工作区解析，浏览器检查使用根工作区中的 `@playwright/test`。

从仓库根目录执行：

```bash
cp extensions/session-hub/settings.example.json extensions/session-hub/settings.json
```

编辑 `settings.json`：所有 home/workspace 值使用本机真实绝对路径，不填写 `~`；两个 binary 可使用 PATH 中的命令或真实绝对路径。Claude Desktop Code 数据目录需实际检查。尚未安装的引擎应指向独立空目录用于开发，不伪造已有会话。多个 Hub 实例使用不同空闲端口，不共享 `data/`。

先装到隔离 Hermes profile（下方目录仅为示例，替换成明确的测试目录）：

```bash
python extensions/session-hub/install.py --hermes-home /absolute/path/to/test-hermes-home
```

Windows 示例（PowerShell）：

```powershell
& .\.venv\Scripts\python.exe extensions/session-hub/install.py --hermes-home C:/Temp/hermes-session-hub-test
```

安装器会先编译插件，保留已有配置字段，首次修改时备份 `config.yaml`，并把当前 Python 可执行文件写入该 profile 的 MCP 配置。通过 `HERMES_HOME` 选择同一 profile 启动 Hermes。后续切换真实 profile 时显式传入它的路径；不要在原外层 Hub 仍运行时启动同端口的新实例。

本地健康检查会启动 Hub 服务并创建忽略的 `data/`：

```bash
python extensions/session-hub/client.py health
```

Codex App 接入需在具有真实 App Tools 上下文的授权任务中运行 `python extensions/session-hub/codex_app.py bind`。不要复制另一台机器的绑定文件。历史读取和 App 实时控制是不同能力；安装成功不等于 App 控制已通过。

## 验证

先配置独立测试来源目录，不连接或操作正式会话。从仓库根目录运行：

```bash
bash scripts/run_tests.sh extensions/session-hub
node --test extensions/session-hub/board-model.test.mjs extensions/session-hub/conversation-model.test.mjs
node extensions/session-hub/build-ui.mjs
```

Python 测试复用原有隔离数据用例，未配置的首次 checkout 需要先建立本地 `settings.json`。UI 验收脚本及 `verify_*.py` 中有真实服务/模型调用，执行前阅读脚本；它们不是默认单元测试。`verify_gateway.py` 要求显式设置 `HERMES_HOME` 到已安装插件的测试 profile。

## 平台与交接边界

这是现有 Windows Session Hub 的源码交接，同时修正了仓库迁入后的构建目录和显式安装路径。Mac 的 Claude 进程发现、App URI 激活、CLI 参数以及 Codex App Tools 版本仍需真机适配验证；不宣称本次发布已完成 Mac 端 App 控制。

Windows 当前仍运行原外层 `HermesAgent/extensions/session-hub` 副本。本次只纳入源码，不自动重新绑定现有会话或切换在线服务。后续维护以仓库内版本为准；切换前停止旧实例，并保留其数据和配置供明确迁移，不能同时运行两个写同一数据目录的实例。

远程产品开发请继续阅读 [远程需求](../../docs/remote-control/REQUIREMENTS.zh-CN.md)。Session Hub 源码已经具备，不再是“等待提供扩展”状态；尚未具备的是新的远程账号、连接层和各平台验收。
