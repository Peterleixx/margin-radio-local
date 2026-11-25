# 页边电台 · Margin Radio

把文章、聊天记录、文档和视频字幕做成可以分章收听的中文播客或有声书。你可以直接粘贴听稿，也可以让支持 MCP 的 Agent 翻译、编稿并制作节目。节目库运行在自己的电脑上。你可以保存多套配音配置，给同一段听稿选不同的 TTS 模型和声音。软件可免费安装，使用第三方语音服务时按该服务的规则计费。

**复制这一行给你的 Agent**

> 请从 https://github.com/Peterleixx/margin-radio-local 把页边电台安装到我的电脑，按 README 运行 bin/setup 并在后台启动节目库，验证网页可访问；如果客户端支持 stdio MCP，请注册仓库里的 bin/margin-radio-mcp，然后打开配音设置让我在本机填写自己的 API key、模型和音色。我保存后，请用两句中文做一期试听并把可播放的链接给我。

## 本机安装

支持 macOS 和 Linux。首次安装需要联网下载依赖。准备好 Git，以及 uv 或带 venv 的 Python 3。安装器会用 uv 准备 Python 3.11+ 环境和锁定依赖，并检查 FFmpeg 的 MP3 编码能力。macOS 缺少 FFmpeg 时会通过 Homebrew 安装，Debian／Ubuntu 会通过 apt 安装，其他 Linux 发行版请先用系统包管理器安装 FFmpeg。

```sh
git clone https://github.com/Peterleixx/margin-radio-local.git
cd margin-radio-local
bin/setup && bin/margin-radio-web
```

打开 [本机节目库](http://127.0.0.1:18766/)。终端按 Ctrl+C 可停止服务，之后用 `bin/margin-radio-web` 重新打开。生成的 MP3 可以离线播放。

## 配置声音，制作第一期

1. 打开「配音设置」，选择供应商。给配置起一个容易辨认的名字，例如「读书旁白」。
2. 填写自己的 API key、TTS 模型和音色或角色 ID。OpenAI 提供常用音色建议，也可直接输入该模型支持的 ID。点击「保存并使用」。
3. 展开「用自己的听稿制作一期」，粘贴一小段正文并生成 MP3。点击完成后的链接即可听、看分章稿或下载。生成时听稿会发给所选合成端点。
4. 想比较声音时，选择「新建配置」并保存另一组参数，再提交同一听稿。不同模型或音色会生成独立录音，同一配置重复提交会复用已完成的节目。

| 接口 | 模型和音色怎么填 |
| --- | --- |
| OpenAI Speech | 可从 `gpt-4o-mini-tts` 和 `coral` 开始。 [模型与音色列表](https://developers.openai.com/api/docs/guides/text-to-speech) |
| OpenRouter | 选择有语音输出能力且支持目标语言的模型，填完整模型 ID 和对应音色。 [TTS 接口说明](https://openrouter.ai/docs/guides/overview/multimodal/tts) |
| ElevenLabs | 填写 TTS 模型 ID，以及自己语音库中有权使用的 Voice ID。 [语音接口说明](https://elevenlabs.io/docs/api-reference/text-to-speech/convert) |
| 自定义 Speech API | 填写接受 OpenAI Speech 请求并返回音频的完整端点、模型及音色。支持 HTTPS 和本机环回 HTTP。免密本机服务可将 key 留空。 |

key 只需在本机设置页输入。再次编辑同一端点时留空会沿用已存的 key，输入新值即可轮换。向 Agent 提供材料和听稿即可。

## 在 Agent 中制作分章节目

在注册了本项目 MCP 的本地客户端里说「把我选中的这篇文章整理成三章中文播客，保留主要例子和来源，完成后给我收听链接」。听稿的翻译和编写由你选用的 Agent 完成，其费用与数据处理方式取决于该客户端。也可以直接在网页上提交已有听稿。

将 stdio 服务命名为 `margin-radio-local`，启动命令填入仓库内 `bin/margin-radio-mcp` 的**绝对路径**。以 Codex 或 Claude Code 为例，在仓库目录按客户端选一条运行，再重新打开会话。

```sh
codex mcp add margin-radio-local -- "$PWD/bin/margin-radio-mcp"
claude mcp add --scope user --transport stdio margin-radio-local -- "$PWD/bin/margin-radio-mcp"
```

| MCP 工具 | 用途 |
| --- | --- |
| `import_material`、`read_material` | 导入正文或用户指定的本机文件，分页读取原文。支持 TXT、Markdown、文字型 PDF、DOCX、SRT、VTT，以及带同名字幕的音视频。 |
| `save_draft`、`get_draft` | 保存或读取标题和分章听稿。每章最多 1800 字，每期最多 48 章。可附上节目类型、摘要、译文与来源。 |
| `get_narration_settings` | 查看当前配置、供应商、模型和音色。 |
| `render_episode`、`get_episode`、`list_episodes` | 按稿件 ID 制作，等到状态为 `ready` 后取得收听页和 MP3，或浏览本机节目。使用相同配置重复提交相同听稿会复用录音。 |

## 本机数据

服务只监听 `127.0.0.1:18766`。默认在仓库的 `data/` 下保存材料、听稿、SQLite 数据库与音频，成品位于 `data/audio/`。密钥以独立文件保存在 `data/credentials/`，文件权限为当前用户可读写（0600）。备份整个数据目录会包含这些密钥，分享节目时直接使用下载的 MP3。

可以设置 `MARGIN_RADIO_LOCAL_DATA` 指定其他数据目录（使用绝对路径），用 `MARGIN_RADIO_LOCAL_PORT` 修改端口。网页与 MCP 进程须使用相同的目录和端口。

## 许可证

项目源码使用 [MIT License](LICENSE)，允许使用、修改及再分发，请保留版权和许可声明。独立安装的依赖遵循各自的许可。
