# 版本更新对比

本文说明当前维护分支相对最早可验证版本的优化点。

## 可验证来源

- 最早可验证版本：git 根提交 `75d868d5b579585f050fa38ba20ca57ac672a87e`
  (`v1.0.0`, `Initial public auto image production skill`)。
- 当前维护分支：`maintenance/attempt-manifest-validator`，当前提交
  `637b21a` (`feat: persist failed inspection outcomes`)。
- 用户提供的旧会话 ID 已尝试读取，但本地 Codex 线程索引未找到可读取记录。
  因此本文只使用 git 历史和当前仓库文件作为事实来源。

如果“朋友最早版本”另有未提交代码或私有文档，需要补充该版本文件后才能继续做逐行对比。

## 总览

最早版本已经定义了自动图片生产的核心理念：读取需求、提交模型、绑定结果、
下载候选图、校验、选择、原子提交。当前维护分支把这套理念补成了更适合公开仓库和持续自动化运行的工程化框架。

## 主要优化点

| 方向 | 最早版本 | 当前维护分支 |
| --- | --- | --- |
| 任务绑定 | 提到使用 `TASK-ID`，但契约较轻 | `result_binding` 成为必填输入，支持字符串或嵌套元数据，并校验候选图必须属于当前任务 |
| attempt 记录 | 只描述 `.attempts` 和 `attempts` 目录 | 增加成功/失败 manifest 校验，失败 attempt 可记录 `status: failed`、`error_code`、`error_detail`、`candidate_count: 0` |
| 自动恢复 | 失败场景主要靠人工理解 | 新增恢复规划器，能输出 `retry`、`backoff`、`needs_human`、`reroute_provider`、`quarantine`、`review_failure` 等结构化动作 |
| 重试控制 | 未定义重试预算 | 新增 `retry_count`、`next_retry_count`、`remaining_retries`、`max_retries`、指数退避 `retry_after_seconds`，避免无限循环 |
| 人工介入 | 没有统一字段 | 新增 `requires_operator` 和 `operator_block_key`，用于 CAPTCHA、登录、审核拦截、重试耗尽等人工队列 |
| OCR/文字残留 | 只要求 OCR 检查 | 新增 `quality_rules`，支持缺失 OCR 证据、检测到任意文字、禁止文本、OCR 状态矛盾等质量门 |
| 水印/来源标识 | 没有明确合规边界 | 明确禁止把第三方来源标识或 AI 生成水印当作后处理移除目标；应检测、拒收、隔离或切换合规 provider |
| 图像检查 | 只描述人工/项目规则 | 新增 `inspect_attempt_images.py`，检查解码、尺寸、重复文件哈希、OCR 证据、可见标记，并输出 JSON 诊断 |
| manifest 安全 | 未覆盖路径攻击细节 | 新增 `validate_attempt.py`，检查 JSON/UTF-8、目录一致性、候选路径、父目录引用、软链接、重复路径、selected_path 成员关系等 |
| 错误归类 | 只列少量 provider 错误 | 扩展为 CAPTCHA、未登录、并发限制、限流、provider busy、网络、页面加载、浏览器崩溃、控件不可用、上传/下载、生成超时、OCR/可见标记等 |
| 报告脱敏 | 未系统说明 | JSON 报告会把本机绝对路径脱敏为 `<path>`，并限制 display-safe identity 字段 |
| 公开示例 | 早期 `main` 曾含更具体的 marketplace/Doubao 语境 | 当前分支改为中性的 `ASSET-0001` 示例，适合公开仓库复用 |
| 测试覆盖 | 没有测试脚本 | 新增 `tests/`，覆盖 manifest validator、recovery planner、image inspector |

## 对 Doubao / 浏览器 provider 的改进含义

- 不再把页面上已有的历史图片当成当前结果。
- 每次提交必须有唯一 `TASK-ID`，并在下载后绑定到当前 attempt。
- CAPTCHA、未登录、浏览器窗口不可控、并发限制、网络波动、模型繁忙等都被拆成明确错误码。
- 重试会遵守退避和最大次数；重试耗尽后进入人工 review，而不是持续空转。
- 若输出带有 `AI 生成`、平台来源标识或其他文字残留，应作为质量失败处理，而不是自动擦除。

## 公开仓库层面的优化

- README 增加文档导航、安全公开规则和许可状态说明。
- 新增 `CHANGELOG.md`，方便 GitHub 读者追踪版本变化。
- 新增 `CONTRIBUTING.md`，说明测试命令、文档规范和 PR 检查项。
- 新增 `SECURITY.md`，说明不要公开提交密钥、cookie、私有图片、浏览器状态或未脱敏日志。

## 仍需确认

- 许可证尚未选择；公开可读不等于自动授予复用和再分发权利。
- 用户提供的旧会话当前不可读取，不能作为事实来源。
- 仓库当前主要提供 Codex skill、契约、验证脚本和测试；完整 Doubao 浏览器 adapter 仍应作为独立实现继续补充。
