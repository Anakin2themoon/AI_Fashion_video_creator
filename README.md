# AI Fashion Video Director

本地优先的单图时装图片与视频工作台。人物参考图负责锁定身份，上传图负责定义衣服/造型主题；创作时可独立选择任务图片模板和视频风格，也可以只生成换装图片而不调用视频 API。视频模式先用多图编辑生成五个换装关键帧，再合成严格 18 秒的竖屏成片。全部媒体和中间产物保存在本机 `workspace/`。

## 一键启动（推荐）

要求：Docker Desktop 已启动。

```powershell
.\scripts\start.ps1
```

或：

```bash
./scripts/start.sh
```

也可以直接运行：

```bash
docker compose up --build -d
```

打开：

- WebUI: <http://127.0.0.1:3000>
- Backend: <http://127.0.0.1:8000>
- API Docs: <http://127.0.0.1:8000/docs>

## Cloudflare domain deployment

The Web UI supports local split ports and a public same-origin deployment. On `localhost`/`127.0.0.1` it calls the backend on port `8000`; on a public hostname it uses the current HTTPS origin for API and media requests.

The production hostname `aifactorycreator.org` uses a Cloudflare Tunnel and the application's own signed-cookie WebUI login. Cloudflare Access is intentionally not attached to this hostname, so visitors reach the WebUI login page directly. See [deploy/cloudflare/README.md](deploy/cloudflare/README.md) for the routing, authentication, and validation checklist.

停止服务不会删除历史产物：

```bash
docker compose down
```

## 使用

1. 在“设置”页分别配置视觉分析、换装图片、视频生成三个 API；每项独立选择服务商、模型和 API Key。
2. 点击“保存三个独立配置”；三个 Key 会按能力分别在本机加密保存，页面和 GET API 只显示各自掩码。
3. 在“创作”页选择生成类型、图片 Category、任务图片模板和独立的视频风格，再拖入 JPG、PNG 或 WebP 衣服商品图片。
4. 可填写“补充创作要求”。本地 Prompt Builder 会把该输入与图片模板、视频风格编译成提示词计划，同时保留人物、衣服和安全锁定规则。
5. 选择“仅生成图片模板”时只调用换装图片 API；选择“生成 18S 视频”时再调用视觉分析和视频 API。页面通过 SSE 与短轮询显示实时进度和结果。

Prompt Builder 是生成 handler 前的一层纯提示词编译服务，不替换或重构现有 image/video provider：

```text
Prompt Input + Image Template + Video Style
                    ↓
          GenerationPromptBuilder
                    ↓
       generation_prompt_plan.json
                    ↓
          existing generate handler
                    ↓
       existing image/video providers
```

完整计划保存在 `workspace/runs/{run_id}/prompts/generation_prompt_plan.json`。图片模板与视频风格始终写入不同字段；用户补充要求只能作为低优先级创作方向，不能覆盖人物身份、衣服忠实度、安全限制或输出类型。

遍历全部模板/风格组合、但不调用任何生成 provider 的 Prompt Builder 自测：

```powershell
python scripts/self_test_prompt_builder.py --output workspace\prompt_builder_selftest\latest
```

“人物模板”页集成了上游完整风格库：13 个 Category、22 个上游图片模板，以及 1 个本项目扩展的 4×4 动作分解模板，共 23 个可生成模板。Category、任务图片模板和视频风格是三个不同层级；13 个视频风格与图片模板相互独立。模板生成复用当前人物身份参考和已配置的换装图片 API，但不会启动视觉分析、视频生成或 18 秒成片流水线。

NoToken 只出现在视频生成服务商列表中。视觉、换装、视频三条路由互不绑定：例如可以选择快跑视觉、OpenAI 换装、NoToken Seedance 视频，并为三项输入完全不同的 Key。

快跑视频模型在 WebUI 中按系列分组显示：

- Seedance：`doubao-seedance-2.0-mini-480p`、`doubao-seedance-2.0-mini-720p`、`doubao-seedance-2.5-480p`、`doubao-seedance-2.5-720p`
- Grok Video：`grok-imagine-video`、`grok-imagine-video-1.5-preview`
- Sora：`sora-2`、`sora-2-8s`、`sora-2-12s`
- Veo：`veo_3_1`、`veo_3_1-fast`

模型出现在目录中不代表当前 API Key 分组一定有可用生成通道；实际任务创建失败时，后端会记录并返回中转站的模型分组错误。`sora-2-8s` 与 `sora-2-12s` 为固定时长别名，流水线会在下载后按分镜时长规范化。

`mock` 只用于自动化工程测试：它不会换装。为避免把商品图粘贴结果误认成真实成片，WebUI/API 默认禁止提交 Mock 生成任务。`ALLOW_MOCK_GENERATION=true` 仅应用于明确的开发自测。

## 本地产物

独立图片模板保存在：

```text
workspace/image_templates/{template_id}/{generation_id}/
├── {template_id}.png
└── generation_manifest.json
```

创作页的图片-only 任务保存在：

```text
workspace/runs/{run_id}/
├── analysis/generation_styles.json   # 图片模板与视频风格分开保存
├── task_images/{image_template_id}.png
├── task_images/generation_manifest.json
└── state.json
```

图片-only 清单会写入 `video_invoked: false`，不会创建视频结果。

每次运行完整保存在：

```text
workspace/runs/{run_id}/
├── input/
├── analysis/
├── prompts/
├── keyframes/
├── image_qa/
├── videos/
├── video_qa/
├── video_requests/       # 最终 prompt/request/input manifest/provider events（无密钥）
├── logs/events.jsonl
├── state.json
└── final/
    ├── final.mp4
    └── final_validation.json  # 完成前强制验证可播放、9:16、18 秒
```

最终导出位于 `workspace/outputs/{run_id}/`。只有 `final_validation.json` 为 `PASS` 时任务才会标记完成；人物母版或独立身份参考缺失会直接失败，不会生成占位人物冒充固定角色。SQLite 只存元数据；媒体从不写入数据库。

## 配置

三家服务商合同都在 `config/provider_relays.json` 后台预置，普通页面不能修改 base URL 或 endpoint。服务商按能力过滤：快跑与 OpenAI 可用于视觉/换装/视频，NoToken 仅用于视频。即使三项都选择快跑，也会使用三个相互独立的 Key 槽位。快跑换装模型包含 `gpt-image-1.5`、`gpt-image-2` 系列、`nana-banana-2`、`nano-banana-2` 与 `nano-banana-2-1k`：

```text
快跑 OpenAI base: https://kuaipao.pro/v1
快跑 Video:       POST /v1/videos
NoToken OpenAI:    https://notoken.pro/v1
NoToken Video:     POST /api/v3/contents/generations/tasks
OpenAI 官方:       https://api.openai.com/v1
OpenAI Video:      POST /v1/videos
```

API Key 不写 `.env`。后端首次运行生成 `workspace/.secrets/master.key`，三个能力的密文分别保存在 `workspace/app.db` 的 `runtime_secrets` 表；单独删除任一能力 Key 后真实任务立即被拒绝。旧版按服务商保存的 Key 会在升级时自动复制到该服务商支持的能力槽位。请同时备份数据库和 master key，否则旧密文不可恢复。

人物母版只用于初始化。`CharacterAssetBuilder` 确定性拆分为：

```text
identity_face.png
fullbody_front.png
fullbody_45.png
fullbody_side.png
```

生产生成不再把四宫格直接提交为唯一人物参考。图片模型只从商品图提取身体直接穿着的服装，明确排除商品原模特身份、背景、头盔、翅膀、武器和漂浮特效；视频模型负责真实动作和当代亚洲日常生活环境。Mock/静态 FFmpeg 只允许自动化测试，不能作为真实任务 fallback。

运行时配置 API 同时提供 `/api/v1` 和 `/api/v4` 前缀：`provider-config/catalog`、`provider-config`、`provider-config/test`、`runtime-config`。任何响应都不包含完整 API Key。

图片风格目录、13 个 Category 封面和 22 个模板封面来自 [awesome-gpt-image-2](https://github.com/freestylefly/awesome-gpt-image-2)，依据 MIT License 使用。同步的目录保存在 `config/awesome_style_library.json`，本项目的提示词覆盖与扩展模板保存在 `config/character_image_templates.json`。

## 测试

容器内运行完整测试：

```bash
docker compose run --rm backend sh -lc "pip install -e '.[test]' && pytest -q"
```

只调用图片 API、逐个验证全部 23 个模板（不生成视频）：

```powershell
python scripts/self_test_image_templates.py --concurrency 3 --output workspace\image_template_selftest\latest
```

脚本会从本地 API 拉取完整目录，逐模板生成并用 Pillow 解码验证，最后写入 `summary.json`；报告中的 `video_invoked` 必须为 `false`。

Mock 端到端 API 烟雾测试前，仅在测试环境设置 `ALLOW_MOCK_GENERATION=true`，然后使用：

```powershell
.\scripts\smoke_test.ps1
```

该脚本生成测试商品图、提交任务、等待完成，并用 API 与 `ffprobe` 验证最终 MP4。
