# Mac mini 开发启动提示词

## 使用前准备

1. 在 Mac mini 上拉取 `https://github.com/MaHsiChu/hermes-agent.git`，或使用已有、用户指定的该仓库 checkout。
2. 确认拉取后的仓库包含 `docs/remote-control/`。文档已纳入本次 Git 交接提交；若使用旧版 checkout，可更新到包含文档的版本，或单独复制文档包。
3. 在 Mac mini 的开发 Agent 中打开该仓库，粘贴下面的完整提示词。不要复制 Windows 的凭据、运行时目录、真实会话数据库、`.venv` 或 `node_modules`。
4. Session Hub 已纳入仓库 `extensions/session-hub/`。同时阅读它的 `CHECKOUT.zh-CN.md`，配置本机路径并验证平台能力；真实运行数据和 App 绑定不会随 Git 迁移。

## 可复制提示词

```text
请在当前 Mac mini 上正式开始开发我的自有 Agent 远程会话产品，直接实现、运行和验证，不要只输出方案。

先阅读项目根 AGENTS.md、相关子目录 AGENTS.md 和 docs/remote-control/REQUIREMENTS.zh-CN.md。该文档是本次研发需求与验收依据。若文档缺失，先检查我提供的文档包及当前项目路径；确实找不到时指出缺失文件，不要杜撰全文或声称已经读过。

产品目标：同一个自有产品账号在 PC 和手机登录，手机可以查看已绑定电脑授权范围内的全部 Agent session，并向原 session 继续下达指令，工作仍在原电脑、原目录和原上下文中执行。Mac mini 承担账号、设备注册、历史副本和消息中转，PC 主动向外连接。优先中文手机 PWA、中国大陆访问体验，后续覆盖目前 Session Hub 聚合的 Codex App / Claude Code 会话。

已知仓库是 https://github.com/MaHsiChu/hermes-agent.git。需求分析时 Windows 的内层仓库 HEAD 为 d177b119e9c56c9ddc0b7379ffce52341ec06584；当时的桌面改动现已归入提交 6ebd7ef。Session Hub 现已纳入 extensions/session-hub，集成研究在 docs/session-hub。先读扩展 CHECKOUT.zh-CN.md，核查源码及版本，不强制 reset、不覆盖已有修改。个人配置、会话、App 绑定未上传，按本机环境重新配置和验收；不能再将扩展源码本身当作等待提供的依赖。

第一轮先完成 M0，再连续推进 M1：核对环境与真实 Hermes 接口，选择成熟可自托管的账号实现，做真实账号登录、设备绑定、PC Bridge 出站连接、手机会话列表和历史、向原 session 发送、实时结果和双端同步。随后推进 M2 的持久化回执、断线补读、离线历史、设备撤销、双端并发、审批/停止和附件。不要做静态页面或 mock 聊天后就结束。M3 的 Codex/Claude 必须基于仓库内源码，在真实 App 环境中分别验收，缺少该阶段不得宣称全部产品目标完成。

默认使用 React/TypeScript PWA、Python Bridge、FastAPI 业务服务、PostgreSQL 和 Caddy；若源码已有更合适的基础，可以记录 ADR 后采用，不要因普通实现选型反复等待确认。产品账号与模型供应商登录分离。默认内测邀请注册、可读历史副本、PC 离线保存草稿，待上线后由用户发送。正式品牌与域名缺失不阻塞本地开发。

必须复用正在运行的 Hermes 后端和原始会话，不能启动第二个共享相同数据库的独立 Agent 来冒充接管。会话定位包含账号归属、设备、backend、Profile、引擎和原 session ID。服务端按认证身份校验归属，不能信任前端 user_id。手机历史与 Mac 副本不能直接修改原生会话数据库。只有已授权绑定的设备及范围开始同步。

为每条远程操作实现持久化业务 request_id、执行端去重和可查询回执。分别显示已接收、运行、完成、失败、待审批、投递待确认。执行后回执丢失时先核对，无法确认则标记不确定，禁止自动重发造成重复副作用。短期内存事件回放不能替代持久化恢复。手机断线不应取消健康运行的原任务，多端审批和并发发送要有确定的竞争处理规则。PC 离线不能假称仍可执行。

先在隔离 HERMES_HOME 和测试项目完成真实 E2E：桌面创建含上下文标记的原会话，手机继续该 session，执行端在隔离目录产生可验证结果，桌面看到同一轮结果；再验证重复请求、丢回执、断网、服务重启、账号隔离和撤销。遵循仓库测试入口，Python 使用 scripts/run_tests.sh。不能通过伪造操作系统或全 mock 宣称 Windows/手机/App 真机验收通过。

提供可复现的 Mac 部署配置、依赖版本、数据库迁移、启动/停止/健康检查、凭据配置说明、备份恢复和故障诊断。检查 Mac 是 Apple Silicon 还是 Intel、现有运行时和端口，不复制 Windows 依赖目录。先启动 localhost 验证；具备用户提供的域名和授权环境后按需求部署 HTTPS。不要开放未鉴权服务、上传真实凭据、修改整机网络配置或触碰无关服务。公网入口未具备时继续可独立完成的开发并明确待验项。

持续维护 docs/remote-control/IMPLEMENTATION-STATUS.zh-CN.md，记录实际提交基线、完成阶段、变更文件、测试命令与结果、运行地址、证据、已知缺口和下一步。保留用户已有工作；Git 只处理本功能文件，按用户授权提交或推送。遇到外部信息缺失，只询问真正阻塞的最少事项，继续其他工作；不要为了缺少品牌名、域名或 Session Hub 停止 Hermes 核心闭环开发。

现在开始检查仓库和 Mac 环境，简短报告事实后进入编码。最终交付必须区分自动化通过、本机真实运行、Windows 执行端验收、手机真机验收和公网线路验收，给出我可以直接复现的启动及验证步骤。
```
