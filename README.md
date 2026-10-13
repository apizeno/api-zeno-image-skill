# API-Zeno Media Skill

面向 Codex 的 API-Zeno 媒体 Skill，通过 API-Zeno 的兼容接口完成文生图、图片编辑、图片变体和异步视频生成，并将结果安全地保存到本地。

- API 地址：`https://api-zeno.com/v1`
- Skill 名称：`api-zeno-image`
- 运行依赖：Python 3.10 或更高版本
- Python 第三方依赖：无

> 图片和视频请求可能产生 API-Zeno 使用费用。执行前请确认模型、参数和输出位置。

## 功能

- 使用 API-Zeno 模型生成图片
- 使用 API-Zeno 视频模型提交异步视频任务并下载结果
- 支持文生视频，以及模型允许时的图生视频
- 使用一张或多张本地图片进行编辑
- 使用本地图片创建变体
- 支持本地 PNG 蒙版编辑
- 支持 `b64_json` 和 URL 两种响应格式
- 自动保存图片并避免覆盖已有文件
- 保存非敏感的最近一次工作状态
- 在 Windows、Linux 和 macOS 上安全保存 API Key
- 拒绝从本地、私有或保留网络地址下载图片结果
- 拒绝从本地、私有或保留网络地址下载视频结果
- 图片或视频提交只发送一次，不进行客户端自动重试；视频任务允许查询状态

## 安装

将仓库克隆到 Codex Skills 目录。

### Windows PowerShell

```powershell
$skillsDir = if ($env:CODEX_HOME) {
    Join-Path $env:CODEX_HOME "skills"
} else {
    Join-Path $HOME ".codex\skills"
}

New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
git clone https://github.com/apizeno/api-zeno-image-skill.git (Join-Path $skillsDir "api-zeno-image")
```

### Linux 或 macOS

```bash
git clone https://github.com/apizeno/api-zeno-image-skill.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/api-zeno-image"
```

安装后重新打开 Codex。在对话中可以显式调用：

```text
使用 $api-zeno-image 生成一张 1024x1024 的产品主图。
```

## 配置 API Key

推荐使用内置配置命令。API Key 通过隐藏的标准输入读取，不会出现在命令行参数中。

```bash
python scripts/api_zeno_image.py configure
```

检查配置状态时不会显示 API Key：

```bash
python scripts/api_zeno_image.py status
```

删除本地保存的 API Key：

```bash
python scripts/api_zeno_image.py clear-key
```

也可以使用环境变量。环境变量优先于本地配置：

| 环境变量 | 用途 | 默认值 |
| --- | --- | --- |
| `API_ZENO_KEY` | API-Zeno API Key | 无 |
| `API_ZENO_BASE_URL` | 覆盖 API 基础地址 | `https://api-zeno.com/v1` |
| `API_ZENO_CONFIG_DIR` | 覆盖凭据和状态目录 | 系统用户配置目录 |

本地配置默认保存在：

- Windows：`%APPDATA%\api-zeno-image`
- Linux/macOS：`$XDG_CONFIG_HOME/api-zeno-image` 或 `~/.config/api-zeno-image`

配置 API Key 后，建议在 API-Zeno 控制台检查模型白名单和额度。仅当当前设备具有稳定公网出口 IP 时再启用 IP 白名单。

## 支持的模型

使用以下命令读取 Skill 自带的最新模型目录：

```bash
python scripts/api_zeno_image.py models
```

| 模型 | 类型 | 文生图 | 图片编辑 | 图片变体 | 视频输入 |
| --- | --- | --- | --- | --- | --- |
| `gpt-image-2` | 图片 | 支持 | 支持 | 支持 | — |
| `gpt-image-2-4k` | 图片 | 支持 | 支持 | 支持 | — |
| `gemini-3-pro-image-preview` | 图片 | 支持 | 不支持 | 不支持 | — |
| `gemini-3.1-flash-image-preview` | 图片 | 支持 | 不支持 | 不支持 | — |
| `gemini-3.1-flash-image-1k/2k/4k` | 图片 | 支持 | 不支持 | 不支持 | — |
| `grok-imagine-video` | 视频 | — | — | — | 文字 |
| `grok-imagine-video-1.5` | 视频 | — | — | — | 文字、图片 |

完整尺寸列表和能力信息位于 [`references/models.json`](references/models.json)。Gemini 图片模型不要传入 `--quality` 或 `--output-format`。视频参数和任务状态见 [`references/video.md`](references/video.md)。

模型是否可调用仍由 API Key 的模型白名单、分组和上游渠道决定；目录保留已有 GPT 图片模型作为兼容项，默认图片模型使用当前模型广场中的 `gemini-3.1-flash-image-preview`。

## 使用方法

以下命令均在仓库根目录执行。

### 生成图片

```bash
python scripts/api_zeno_image.py generate \
  --prompt "白色背景中的极简陶瓷台灯，柔和棚拍光线，产品摄影" \
  --model gemini-3.1-flash-image-preview \
  --size 1024x1024 \
  --output ./outputs/lamp.png
```

### 编辑图片

输入文件必须是 PNG、JPEG 或 WebP，单个文件不能超过 50 MiB。

```bash
python scripts/api_zeno_image.py edit \
  --image ./inputs/product.png \
  --mask ./inputs/mask.png \
  --prompt "将背景替换为纯白摄影棚背景，保留产品本身" \
  --model gpt-image-2 \
  --size 1024x1024 \
  --output ./outputs/product-edited.png
```

多图编辑可以重复传入 `--image`：

```bash
python scripts/api_zeno_image.py edit \
  --image ./inputs/product.png \
  --image ./inputs/style-reference.jpg \
  --prompt "保留第一张图的产品，采用第二张图的布光风格" \
  --model gpt-image-2 \
  --size 1024x1024 \
  --output ./outputs/combined.png
```

### 创建图片变体

```bash
python scripts/api_zeno_image.py variation \
  --image ./inputs/source.png \
  --model gpt-image-2 \
  --size 1024x1024 \
  --output ./outputs/variation.png
```

### 生成视频

视频接口是异步任务。CLI 会提交一次任务，查询任务状态，完成后把视频下载到 `--output` 指定的路径。

```bash
python scripts/api_zeno_image.py video \
  --prompt "干净摄影棚中的产品缓慢旋转，柔和灯光，商业广告镜头" \
  --model grok-imagine-video-1.5 \
  --duration 6 \
  --aspect-ratio 16:9 \
  --output ./outputs/product.mp4
```

图生视频需要选择支持图片输入的模型：

```bash
python scripts/api_zeno_image.py video \
  --prompt "让产品轻微旋转并推进镜头" \
  --model grok-imagine-video-1.5 \
  --image ./inputs/product.png \
  --output ./outputs/product-motion.mp4
```

当前 Codex 对话界面不一定会直接预览本地视频；命令会返回绝对路径，用户可以从工作区打开或下载视频。

### 常用选项

| 参数 | 说明 |
| --- | --- |
| `--model` | API-Zeno 图片或视频模型 ID |
| `--size` | 输出尺寸，例如 `1024x1024` |
| `--resolution` | 清晰度等级：`1k`、`2k` 或 `4k` |
| `--quality` | GPT 图片模型质量：`auto`、`low`、`medium`、`high` |
| `--n` | 生成数量；当前模型绑定最大值为 `1` |
| `--response-format` | `b64_json` 或 `url` |
| `--output-format` | GPT 图片模型输出格式：`png`、`jpeg`、`webp` |
| `--output` | 本地输出路径 |
| `--timeout` | 请求超时秒数，最大 `1000` |

视频额外选项：`--image`、`--image-url`、`--duration`、`--aspect-ratio`、`--poll-interval` 和 `--poll-timeout`。完整的视频任务字段和返回结构见 [`references/video.md`](references/video.md)。

如果输出文件已经存在，Skill 会自动添加 `-1`、`-2` 等后缀，不会覆盖原文件。

## API 接口

| 操作 | 请求地址 | 请求格式 |
| --- | --- | --- |
| 生成 | `POST https://api-zeno.com/v1/images/generations` | JSON |
| 编辑 | `POST https://api-zeno.com/v1/images/edits` | multipart/form-data |
| 变体 | `POST https://api-zeno.com/v1/images/variations` | multipart/form-data |
| 视频提交 | `POST https://api-zeno.com/v1/video/generations` | JSON |
| 视频查询 | `GET https://api-zeno.com/v1/video/generations/{task_id}` | JSON |

认证方式：

```http
Authorization: Bearer <API_ZENO_KEY>
```

## 安全设计

- API Key 不支持通过命令行参数传入，避免进入 Shell 历史和进程列表。
- `status` 命令不会输出 API Key。
- 凭据和状态使用临时文件加原子替换的方式写入。
- 在支持的平台上限制凭据文件为当前用户可访问。
- URL 图片和视频下载会检查协议、主机、DNS 结果和每次重定向。
- 拒绝回环、私有、链路本地、保留、多播和未指定地址。
- 图片下载限制为 50 MiB，视频下载限制为 500 MiB，API JSON 响应限制为 70 MiB。
- API-Zeno 已处理上游重试，因此客户端不会自动重复提交计费请求。

遇到失败时，CLI 会尽量保留 HTTP 状态码、API 错误代码和请求 ID。常见认证错误包括：

- `missing_api_key`
- `key_disabled`
- `key_expired`
- `ip_not_allowed`
- `key_quota_exceeded`

## 测试

测试使用本地 Mock HTTP 服务，不调用生产 API，也不需要真实 API Key。

```bash
python -m unittest discover -s tests -v
```

## 目录结构

```text
api-zeno-image-skill/
├── SKILL.md
├── README.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── api.md
│   ├── models.json
│   └── video.md
├── scripts/
│   └── api_zeno_image.py
└── tests/
    └── test_api_zeno_image.py
```

`SKILL.md` 是 Codex 运行时使用的核心指令；README 面向安装、维护和直接使用 CLI 的用户。
