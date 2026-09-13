# gemini-web2api

<p align="center">
  <img src="logo.png" width="200" alt="gemini-web2api logo">
</p>

[English](README.md) · [完整文档](docs/README.md) · [路线图](roadmap.md)

> **当前状态：** 正在进行 Gemini Web 上游传输修复。`repair-live-gemini-web` 分支已经加入维护中的 `gemini-webapi` 传输，但在新的真实 Gemini Web 会话完成端到端验证之前，不应视为正式发布版本。

`gemini-web2api` 将 Gemini Web 转换为本地 OpenAI 兼容 API，使 Hermes、OpenCode 等 Agent 可以把 Gemini 作为推理后端，同时继续由 Agent 自己负责文件系统、终端、Git、测试和其他工具执行。

## 架构

```text
Gemini Web
   │ 推理 / 模型响应
   ▼
GeminiAgentBridge
   │ HTTP 协议 / 上下文 / 工具调用校验 / 恢复 / 可观测性
   ▼
Hermes / OpenCode
   │ 工具执行 / 工作目录状态
   ▼
文件系统 / Shell / Git / 测试
```

**核心边界：Bridge 不执行下游工具。** Bridge 可以解析、规范化、校验和有限修复工具调用，但真正执行工具的是 Hermes/OpenCode。

## 当前主要能力

- OpenAI 兼容 `/v1/chat/completions` 与 `/v1/models`。
- Responses 兼容层以及 Codex 相关协议测试。
- Function Calling 解析、Schema 校验、有限修复和恢复。
- Workspace grounding / 上下文连续性 / observation integrity。
- 结构化、自动脱敏的生命周期日志。
- 保守 enum coercion 与有界重试/稳定性逻辑。
- Hermes/OpenCode 兼容性测试与 trajectory benchmark。
- 当前修复分支默认使用 `gemini-webapi==2.1.1` 作为 Gemini Web 传输。
- 原来的 `StreamGenerate` 传输保留为显式 legacy backend，不再作为默认实时路径。

## 快速开始

```bash
git clone https://github.com/Exploiter69/GeminiAgentBridge.git
cd GeminiAgentBridge

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.json config.json
python -m gemini_web2api
```

默认地址：

```text
http://127.0.0.1:8081/v1
```

Python 3.11+ 是当前维护中的 Gemini Web 客户端所需版本。

## Gemini Web 登录态

现代传输需要可用的 Gemini Web session。仓库内置 `gemini-cookie-sync-extension/`，可以从当前浏览器登录态导出本地 `gemini-auth.json`。

使用：

```bash
python -m gemini_web2api \
  --cookie-file /path/to/gemini-auth.json
```

或者在 `config.json` 中设置：

```json
{
  "upstream_backend": "modern",
  "cookie_file": "/path/to/gemini-auth.json"
}
```

**不要**把 cookie、session、API key 粘贴到 issue、聊天、日志或 Git。认证文件应使用严格权限，例如：

```bash
chmod 600 /path/to/gemini-auth.json
```

如果上游报告：

```text
Account status: UNAUTHENTICATED
Session is not authenticated or cookies have expired
```

说明 Gemini Web session 已失效/过期；这与 Bridge HTTP 协议层是否正常是两个不同问题。

## OpenAI 客户端

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8081/v1",
    api_key="local-key",
)

response = client.chat.completions.create(
    model="gemini-3.6-flash",
    messages=[{"role": "user", "content": "你好"}],
)
print(response.choices[0].message.content)
```

Hermes/OpenCode 的详细配置见 [`docs/clients.md`](docs/clients.md)。

## curl

```bash
curl -sS \
  -H 'Authorization: Bearer YOUR_BRIDGE_KEY' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8081/v1/chat/completions \
  -d '{"model":"gemini-3.6-flash","messages":[{"role":"user","content":"Reply with exactly: OK"}],"stream":false}'
```

## 模型

当前 Bridge 暴露的是客户端模型别名。现代传输根据模型 tier 映射到 Gemini Web，而不是依赖旧版固定 deployment ID。

常见名称包括：

- `gemini-3.7-flash`
- `gemini-3.6-flash`
- `gemini-3.5-flash`
- `gemini-3.5-flash-thinking`
- `gemini-3.5-flash-thinking-lite`
- `gemini-3.1-pro`
- `gemini-3.1-pro-enhanced`
- `gemini-auto`
- `gemini-flash-lite`

这些名称是 Bridge 的客户端兼容别名，不代表 Google 永久固定的内部 deployment。

## 工具调用

```text
Gemini → 提出工具调用
Bridge → 解析 / 校验 / 规范化 / 有限修复
Hermes/OpenCode → 执行工具
Hermes/OpenCode → 返回 observation
Bridge → 保留 observation integrity
Gemini → 决定下一步
```

Bridge 不会执行 Shell、读取任意工作区文件、修改 Git 仓库，也不会伪造工具结果。

## 配置

完整配置说明见 [`docs/configuration.md`](docs/configuration.md)。主要字段：

| 字段 | 作用 |
|---|---|
| `port` | HTTP 端口，默认 8081 |
| `host` | 监听地址 |
| `upstream_backend` | 默认 `modern`；`legacy` 仅用于显式兼容 |
| `cookie_file` | Gemini Web session 文件 |
| `proxy` | HTTP 代理 |
| `api_keys` | Bridge 本地 API 密钥 |
| `temporary_chats` | Gemini Web 临时聊天开关 |
| `retry_attempts` | 有界重试次数 |
| `prompt_soft_budget_chars` | prompt 软预算 |
| `tool_schema_budget_chars` | tool schema 预算 |
| `planner_enabled` | Phase 7 实验 planner，默认关闭 |

## Docker

Docker 仍然支持，但 Gemini Web session 和网络行为取决于运行环境。认证文件应作为挂载文件提供，不应写入镜像层。

```bash
cp config.example.json config.json
docker build -t gemini-web2api .
docker run --rm \
  -p 8081:8081 \
  -v "$PWD/config.json:/app/config.json:ro" \
  gemini-web2api
```

## 常见问题

| 现象 | 优先检查 |
|---|---|
| `/v1/models` 正常，但生成提示未认证 | Gemini Web session |
| `StreamGenerate` + HTTP 405 | 旧 legacy 进程/旧传输 |
| 当前上游 HTTP 429 | Gemini 上游限流/反滥用/网络环境 |
| `gemini-webapi is not installed` | Python venv / requirements |
| `Address already in use` | 其他进程占用了端口 |
| SSE 已开始后又失败 | 当前 streaming error propagation 限制 |

完整排错见 [`docs/troubleshooting.md`](docs/troubleshooting.md)。

## 当前发布状态

Phase 1–13 已完成历史验证，其中 Phase 8 的真实客户端本地证据为 Hermes 13/13、OpenCode 13/13。

但当前分支修改了 Gemini Web 实时传输，因此这些历史结果不能直接证明新的 upstream transport 已经可用。正式发布前必须重新通过：

1. 真实认证 Gemini Web 非流式生成；
2. 真实认证 Gemini Web 流式生成；
3. Hermes 实测；
4. OpenCode 实测；
5. 完整 deterministic release gate。

详见 [`docs/release-status.md`](docs/release-status.md)。

## License

MIT。