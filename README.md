# 自动图片生产 Skill / Auto Image Production

> 让 Codex 按明确的素材、提示词、验收和落盘规则生成图片，并保留每次候选、校验与选择的可审计记录。

- **仓库状态**：上游 fork，用于跟踪和试用
- **最后核对**：2026-07-18
- **上游项目**：[lightbulingling/auto-image-production-skill](https://github.com/lightbulingling/auto-image-production-skill)

## 中文说明

这个仓库不是通用“画图软件”，而是一套给 Codex 使用的图片生产流程。它要求每个任务都有唯一编号，把模型返回的候选图先放进暂存区，完成尺寸、解码、文字、重复内容和业务规则检查后，才把选中的图片发布到最终目录。

### 适合谁使用

- 需要批量生成商品图、内容配图或模板化素材，并希望每张图都能追溯来源与验收结果的人。
- 同时使用浏览器图片工具和 API 模型，但不希望误拿历史图片或错误任务结果的 Agent 工作流。
- 需要“生成多个候选 → 自动检查 → 明确选优 → 原子发布”固定流程的项目。

不适合没有明确输入素材、输出尺寸、禁用内容和选择标准的临时随意生成。Skill 也不会替用户取得第三方模型权限、绕过平台限制或判断素材版权。

### 工作链路

```text
任务规则与源素材
  → 唯一 TASK-ID
  → 第三方模型生成候选
  → 暂存与任务绑定
  → 尺寸/OCR/重复/业务校验
  → 选择最佳候选
  → 原子发布并保留记录
```

### Fork 说明

本仓库保留上游项目结构和作者成果，当前只用于 Douglax 账号下的同步、中文入口与兼容性观察。核心工作流来自上游；除非提交记录和文档明确列出，不应把上游功能描述为本 fork 的原创改动。

`auto-image-production` is a Codex skill for automated image-production workflows. It helps an agent turn user-provided output rules, prompts, source assets, third-party image models, validation rules, selection standards, and target paths into auditable final images.

The skill is provider-agnostic. Browser-based image tools and API image models can all be used if they can return candidates that are bound to the current task.

## What It Does

The skill guides an agent through this flow:

1. Read the local project spec and handoff files.
2. Confirm the item is safe and eligible for generation.
3. Submit source assets and prompt to a third-party model with a unique task id.
4. Bind returned images to the current task instead of scraping old page images.
5. Download candidates into a staging directory.
6. Validate dimensions, decoding, OCR/text safety, duplicates, and project rules.
7. Select the best candidate using explicit criteria.
8. Commit the successful attempt atomically.
9. Export or copy the final selected image to the requested target path.

## Install

Clone this repository into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/DouglaxYuan/auto-image-production-skill.git ~/.codex/skills/auto-image-production
```

Then start a new Codex session and invoke:

```text
Use $auto-image-production ...
```

如果希望始终使用原作者最新版本，请改为克隆上游仓库。安装成功的标志是新 Codex 会话能够识别 `$auto-image-production`，并在缺少必需输入时先要求补齐，而不是直接生成或写入最终目录。

## Required Inputs

Provide these fields as clearly as possible:

- `item_id`: stable unit of work, such as asset id, content id, row id, or campaign image id
- `source_assets`: input image(s), template, border, mask, style reference, or source table rows
- `prompt`: exact prompt or prompt template
- `generation_rules`: visual and workflow rules the output must follow
- `provider`: third-party image model or browser/API provider
- `candidate_count`: expected number of candidates
- `validation_rules`: size, OCR/text, duplicate, safety, and quality checks
- `selection_criteria`: how to pick the final image
- `commit_target`: final directory, filename pattern, manifest, or registry destination

## Example Request

```text
Use $auto-image-production to generate final images.

item_id: ASSET-0001
source_assets:
- input image: ./input/ASSET-0001.png
- template image: ./templates/final-frame.png
provider: browser image tool
candidate_count: 3
prompt: Create a clean final image. Preserve the main subject shape and color. Use the provided template. Do not include prohibited text, marks, or unrelated text. Output square 2048x2048 images. Echo TASK-ID.
validation_rules:
- image decodes successfully
- selected image is 2048x2048
- OCR finds no prohibited text
- no duplicate hash against previous committed items
selection_criteria:
- complete subject visible
- cleanest background
- least distortion
- best template alignment
commit_target: ./generated/selected/ASSET-0001__selected.png
```

## Atomic Commit

Atomic commit means the workflow does not write half-finished model output directly into the final image path.

Use a layout like:

```text
ITEM/
  .attempts/
    ATTEMPT_ID/        # staging, can be discarded if failed
  attempts/
    ATTEMPT_ID/        # immutable successful result
  current -> attempts/ATTEMPT_ID
```

Only after candidates pass validation and a final image is selected should the attempt be published and `current` moved to the successful attempt. This prevents failed, partial, duplicate, or mismatched images from polluting the final output.

## 注意事项

- 不要把第三方模型页面里的历史图片当成本次结果。
- 每次提交都要有唯一 `TASK-ID` 或 provider task id。
- 不要生成来源素材中已经命中禁用规则的任务。
- 不要跳过尺寸、OCR、重复哈希和业务质量检查。
- 不要把失败 attempt 的 staging 文件复制到最终目录。
- 不要用部分导出的 registry 覆盖生产 registry。
- 不要在公开仓库提交真实客户数据、账号信息、cookie、token、本机绝对路径或未脱敏的业务批次状态。

## Files

- `SKILL.md`: skill trigger metadata and core workflow
- `references/prompt-and-output-contract.md`: provider-agnostic prompt/output contract
- `references/asset-example.md`: neutral example
- `agents/openai.yaml`: UI metadata for Codex
