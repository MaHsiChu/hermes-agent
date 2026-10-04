# 远程会话实施状态

2026-10-04；基线 `a58f863f17`；实现与本文一起提交在开发分支 `codex/remote-sessions`，推送状态另行确认。原 checkout 保留，代码位于 `C:/Users/maxin/.codex/worktrees/remote-sessions/hermes-agent`。

## 当前结果

Windows Hermes 桌面、原后端和 Session Hub 已恢复运行。手机 PWA、认证中转及 PC Bridge 已实现，已用浏览器手机视口实际经过中转控制电脑上的原 Hermes session。整分支独立复审已批准，六项 Important 与两项 Minor 全部关闭。最终原生事件代次契约已加载到运行中的后端，重启后的手机发送与完整历史再次通过实际验证。

执行仍在原电脑、原 Profile、原 session；没有通过新会话或独立执行进程冒充续接。测试只使用独立 home 内的一条专用验证会话，没有把个人 Codex/Claude 历史绑定到中转。

| 范围 | 已实现 | 当前验收边界 |
| --- | --- | --- |
| 本地恢复 | Python 3.11.15、项目 npm 11.17、桌面生产构建、Hub 安装及路由 | 真模型返回 `HERMES_RESTORED`；Hub 新分页实现已启用 |
| 账号与绑定 | Authlib OIDC Code + PKCE、持久登录、CSRF/Origin、独立设备凭据、明确来源授权、撤销 | 真实 HTTP + RSA/JWKS 登录测试通过；本地 Keycloak 尚未创建管理员/realm/正式账号 |
| 会话与历史 | 来源/Profile/归档/状态筛选、稳定分页、修订/墓碑、离线中转副本、增量补读 | 1000 会话/10000 消息真实数据库链路测试通过；超大记录有明确未同步状态 |
| 原会话操作 | 发送、排队、引导、停止、原审批及澄清、持久 request_id/回执 | 真模型发送、澄清、拒绝审批、图片及停止完成；回执接受与任务完成分别显示 |
| 手机 PWA | 中文 360px 布局、Markdown/工具/代码、草稿、能力限制、设备管理、静态壳缓存 | 30 个 Vitest、typecheck/build 通过；真实 iOS/Android 尚未验收 |
| 原生图片隔离 | `prompt.submit` 请求自带图片，显式空数组保护电脑暂存；排队与 ComputeHost 保留归属 | 相关 84 测试通过，最终清理修复 58 测试通过且独立复审批准；真手机页面图片已进入原会话 |
| Codex/Claude | 复用 Hub 的原会话历史与 App 续接接口；目录包含归档与稳定快照 | Hub 实际目录总数 399、分页/插件路由健康；审批/停止/附件明确不支持，没有发送消息到个人任务 |
| 部署 | 独立依赖锁、Keycloak/PostgreSQL/Caddy 配置、迁移、备份恢复、Windows/macOS 启动说明 | 公网域名、Mac mini、PostgreSQL 恢复和实际手机尚未验收 |

## 已取得的实际执行证据

验证会话为 `20261004_135506_5066c7`，原生 home 在 `D:/5_Git_WorkSpace/hermes-agent/.local-runtime/hermes-home`。

- 两个原生 RPC 客户端附着同一运行实例，断开其中一个后另一个继续接收事件；模型返回 `REMOTE_PC_CORE_OK`。
- 手机页面经签名的本地测试 OIDC、中转、常驻 Bridge 发送消息，原模型返回 `MOBILE_RELAY_PC_OK`。原库中对应用户/助手标记各一条；相同请求重放复用回执，改内容复用同 ID 返回 409。
- 手机回答模型实际发起的“手机是否继续”澄清，原模型继续并返回 `MOBILE_CLARIFY_OK`。
- 手机拒绝原生受保护文件审批，模型返回 `MOBILE_DENY_OK`，目标测试文件没有创建。另一 RPC 客户端再次答复的 resolved 数为 0。
- 手机上传蓝色测试图片，原会话保留该图片的原生引用，模型回复“蓝色”。保持同一原生客户端连接后再次验证：手机请求只含蓝色图片，电脑暂存橙色图片仍可独立移除，运行实例与原 session 均未变化。
- 手机实时区域实际显示尚未完成的编号正文；点击“请求停止”后，独立原生 RPC 客户端确认 running=false、最后 message.complete 的 status=interrupted，原 session 未改变。验证结果保存在本地 live-stop-result.json。
- 服务重启后的手机连接已观察到补读积压后恢复“实时连接”。已修复迟到订阅 ACK 导致游标倒退、迟到回执覆盖新请求，以及新增消息挤掉已展开早期历史的问题。
- 最终原生后端与 Bridge 重启后，手机发送新消息，原模型返回 `MOBILE_FINAL_PC_OK`。独立 RPC 核对原 session 不变、30 条历史完整、该助手结果恰好一条、running=false；原生补读返回非空 `replay_generation`。结果保存于本地 final-generation-result.json。

这些是本机真实执行证据，身份服务使用专门的签名测试 OIDC。它们不代表正式 Keycloak 登录、公网手机访问或第三方引擎控制均已验收。

## 验证记录

Python 统一通过 Git Bash `scripts/run_tests.sh`。完整命令与红绿输出保存在本地 `.superpowers/sdd/task-*-report.md`；这些是开发记录，不随代码发布。

- Hub：10 文件、44 tests passed，25.8s，独立审查通过。
- 中转/Bridge 初次整组：6 文件、24 tests passed，193.5s，含真实 1000 会话/10000 消息以及落库后丢 ACK 的恢复。
- 后端修复整组：6 文件、24 tests passed，25.2s；最终大消息/脱敏/登录验证：3 文件、9 tests passed，11.1s。
- `messages_changed` 修复：`test_relay.py` 12 tests passed，6.9s，复审通过。只在实际消息修订变化时补读历史，元数据轮询不再重读所有已展开消息。
- 原生图片及原子 busy 拒绝：10 文件、84 tests passed，38.5s；后续清理归属修复 4 文件、58 tests passed。共享契约生成校验与 TypeScript 检查通过，复审通过。
- 最终审查修复组：后端 11 文件、45 tests passed（46.5s），相关复查 17 tests passed（16.5s），禁用重试且无 flaky；手机 30 tests passed、typecheck/build 通过。
- 原生 ring 代次最终修复：先复现失败，再以真实原生事件缓存淘汰覆盖序号追平/超越、实时与补读不同到达顺序、迟到旧帧；7 文件、41 tests passed（27.5s），禁用重试且无 flaky。契约生成及共享 TypeScript 检查通过；手机 EventLink/Runtime 10 tests passed。独立最终复审批准全部八项发现。
- 手机最新基础验证：30 tests passed，10 文件；TypeScript 与 Vite 构建通过。Playwright 场景源码已编写但未运行，实际浏览器检查通过 CUA 完成。
- 未修改的 Windows `test_compute_host_phase1::test_append_log_record_single_write_lines` 在基线和工作区均失败，不能把该项报告为本次通过。一次重复大规模测试的最终输出丢失，未计为成功。

## 本机运行与入口

- 桌面启停：`D:/5_Git_WorkSpace/hermes-agent/.local-runtime/Start-Hermes.ps1`；加 `-Stop` 停止脚本记录并验证的桌面进程。该脚本当前指向开发 checkout 的后端，沿用原独立 home。
- 原后端当前为 `http://127.0.0.1:9184`，端口与 token 会在重启时改变。Bridge 必须刷新该明确连接后重启；尚未提供桌面端点自动发现，不能承诺桌面重启后无人值守恢复。
- Session Hub：`http://127.0.0.1:47831`，已运行新分页实现；实际插件代理健康接口返回成功。
- 中转正式配置入口：`http://127.0.0.1:8787`。未配置 OIDC 时受保护 API 拒绝访问，不能用作已登录产品演示。
- 本机测试预览：`http://127.0.0.1:8789`，页面明确标为“本地界面验证 · 测试数据”；其中只有一条绑定的真实隔离 Hermes 验证会话，其余为界面样例。
- Keycloak 本地服务：`http://127.0.0.1:8788`，待用户在浏览器中创建管理员及正式身份配置。

中转/Bridge 使用独立 `.local-runtime/remote-venv`，不要把它们的依赖锁安装进桌面 `.venv`。桌面 cryptography 固定 50.0.0，中转锁为 50.0.2。共享环境曾因 Windows DLL 占用造成修复中断；现已按各自官方锁恢复，RSA/EC 与版本元数据已验证。

通用安装、配对、启动与备份恢复见 [部署说明](../../deploy/remote-control/README.md)。本地脚本和真实凭据均处于忽略目录，不提交。

## 尚待完成或外部验收

服务端部署及 iOS/TestFlight 后续开发已按用户要求划归 Mac mini，具体组件、接收代码方法、任务与验收见 [Mac mini 开发交接](MACMINI-HANDOFF.zh-CN.md)。当前 PWA 不包含 iOS 工程或可上传的 app build。

- 旧版原生后端没有 `replay_generation` 时，只能按进程/运行实例变化或可见的序号回退恢复，不能保证识别序号已追平的事件缓存重建；完整保证需要本次更新后的原生网关。本机已运行更新版本。
- 配置正式 Keycloak 管理员、realm、产品账号及邀请/恢复流程。浏览器新凭据步骤需要用户接手，不在聊天中传密码。
- 提供实际 Mac mini/域名后部署 HTTPS 中转；执行 PostgreSQL 权限隔离、备份恢复及真实账号验收。
- 用实际 iOS Safari、Android Chrome 验证后台恢复、键盘、安全区和网络切换；公开网络性能、容量和数据保留策略尚未验证。
- Codex/Claude 审批、停止没有原生接口支持；当前不会用新 CLI 会话或伪造成功替代。

因此当前成果是可运行、可审查的本机实现及真实 Hermes 操作链路；不是已经部署完成的公网手机服务，也未标记全量 M0–M4 验收通过。
