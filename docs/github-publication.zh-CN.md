# GitHub 公开仓库发布规范

本文沉淀本项目公开到 GitHub 时应遵守的文档和安全规则。目标是让普通开发者、
维护者和 AI Agent 都能快速理解项目用途、运行方式、输入要求和安全边界。

## README 应覆盖什么

- 中文优先说明项目是什么，英文可以作为补充。
- 说明项目解决的问题，以及它如何让图片生产流程更省心、更可恢复。
- 说明核心技术架构：Codex skill、prompt/output contract、attempt manifest、
  validation scripts、recovery planner 和 tests。
- 提供可复制的安装命令和最小调用示例。
- 明确用户需要提供的信息：`item_id`、`source_assets`、`prompt`、`provider`、
  `candidate_count`、`result_binding`、`validation_rules`、`selection_criteria`
  和 `commit_target`。
- 说明环境变量、登录态和 provider credential 应放在哪里，以及哪些内容绝不能提交。
- 给 AI Agent 一段快速指令，帮助小模型或自动化工具直接进入正确流程。
- 链接 `CHANGELOG.md`、`CONTRIBUTING.md`、`SECURITY.md`、许可证和关键 docs。

## License 规则

公开仓库默认应带明确许可证。本项目使用 MIT License。私有个人备份仓库可以不放
license；如果未来改成公开发布，应先确认可公开范围、第三方依赖许可和脱敏状态，
再补许可证。

## 脱敏与公开安全

- 不提交真实客户素材、未授权图片、下载产物、批次运行状态或账号数据。
- 不提交 cookie、token、API key、浏览器 profile、`.env.local`、本机绝对路径或未脱敏日志。
- 示例统一使用 `ASSET-0001` 这类中性 id 和通用 provider 名称。
- 文档可以说明需要哪些环境变量，但只能写占位符和存放位置，不写真实值。
- 自动化流程不得解决 CAPTCHA，不得绕过 provider 安全限制。
- 第三方平台来源标识或 AI 生成水印只能检测、拒收、隔离或路由到合规无水印导出/provider，
  不能作为自动后处理移除目标。

## 维护文档清单

- `README.md`：项目首页，中文优先，覆盖用途、架构、快速开始、输入和安全边界。
- `CHANGELOG.md`：记录面向用户和维护者可见的版本变化。
- `CONTRIBUTING.md`：说明开发流程、测试命令、文档规范和 PR checklist。
- `SECURITY.md`：说明如何报告安全问题，以及公开仓库不能包含哪些资料。
- `docs/version-comparison.zh-CN.md`：说明相对最早版本的优化点。
- `LICENSE`：公开仓库的复用和分发许可。

## AI Agent 快速检查清单

- 已读取 `SKILL.md` 和 `references/prompt-and-output-contract.md`。
- 已确认用户输入能组成完整任务，没有缺少必填字段。
- 每次 provider 提交都有唯一 `TASK-ID` 或 provider task id。
- 候选图进入 staging attempt 后先校验 manifest 和图片质量。
- OCR/文字残留、水印/来源标识、尺寸错误、重复图和错绑任务都会被拒收或路由。
- 网络、限流、并发、provider busy、登录过期和 CAPTCHA 被记录成结构化失败。
- 重试遵守 `retry_count`、`max_retries` 和退避时间；人工问题不进入无限循环。
- 公开文档和示例没有真实密钥、账号、客户素材、本机路径或旧会话内部信息。
