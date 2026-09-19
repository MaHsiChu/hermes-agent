# 源码纳入仓库验证

日期：2026-09-19。环境：Windows，当前 Hermes fork 工作区。

本次范围是将原外层 Session Hub 0.4.4 的主要源码、测试及文档纳入 `extensions/session-hub/`，并修复迁入后的构建依赖路径、显式 profile 安装、当前 Python 路径及 Node 发现。原外层在线服务未切换，真实用户数据未迁移。

已执行：

| 检查 | 结果 |
|---|---|
| `bash scripts/run_tests.sh extensions/session-hub` | 9 个文件，42 项 Python 行为测试通过 |
| `node --test extensions/session-hub/board-model.test.mjs extensions/session-hub/conversation-model.test.mjs` | 9 项前端逻辑测试通过 |
| `node extensions/session-hub/build-ui.mjs` | 插件成功构建 |
| `node extensions/session-hub/board-ui-test.mjs` | 浏览器交互夹具通过，页面错误为空 |
| 安装器真实安装 | A→B→A 两个临时 profile，配置保留、备份、构建复制、MCP Python 路径验证通过；无效配置拒绝 |

浏览器交互覆盖任务过滤/分组/字段、消息及图片输入、原会话 composer 路由、回执丢失后的稳定重试键、侧栏标签、任务引用、已读同步、窄屏和减少动画。使用合成服务响应，不代表此次又执行了 Codex / Claude 实际任务。

运行 Python 标准入口前，在本机虚拟环境补充了仓库 dev 依赖中声明的 `pytest==9.1.1`。测试用 `settings.json` 指向仓库内忽略的空测试来源目录，没有复制真实配置。Node 的模块类型探测存在提示，不影响上述通过结果。

本次没有验证：Mac 真机 App 控制、手机远程访问、独立账号服务、公网线路。历史 Windows App 验收记录见原扩展文档，其原始 JSON、截图和绑定仍只保留本地。

后续入口：[CHECKOUT.zh-CN.md](CHECKOUT.zh-CN.md)、[远程开发提示词](../../docs/remote-control/MACMINI-START-PROMPT.zh-CN.md)。
