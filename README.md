# 自动录入凭证系统

这是一个本地运行的自动录入凭证原型工程，面向“上传一组业务图片 -> 生成 1 张支持多借多贷的凭证 JSON”场景。

当前仓库已包含：

- 设计文档：`docs/plans/2026-03-19-voucher-auto-entry-design.md`
- 实施计划：`docs/plans/2026-03-19-voucher-auto-entry-implementation-plan.md`
- FastAPI 工作流接口：`apps/api/main.py`
- Next.js 可视化工作台：`apps/web/`
- 规则、schema、工作流、知识层主模块：`core/`
- 架构图与处理流程图：`docs/architecture/2026-03-19-voucher-auto-entry-architecture.md`
- 当前进展说明：`docs/status/2026-03-19-progress.md`

## 环境要求

- Python `3.13`
- Node.js `22+`
- pnpm `10+`

## 本地准备

1. 复制配置文件：

```powershell
Copy-Item .env.example .env
```

2. 使用根目录虚拟环境：

```powershell
.\venv\Scripts\python.exe --version
```

3. 安装 Python 依赖：

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

4. 安装前端依赖：

```powershell
pnpm install
```

5. 预构建知识层：

```powershell
.\venv\Scripts\python.exe .\scripts\bootstrap_knowledge.py
```

## 启动

启动 API：

```powershell
pnpm run dev:api
```

启动前端：

```powershell
pnpm run dev:web
```

## 测试与验证

运行后端测试：

```powershell
.\venv\Scripts\python.exe -m pytest tests -q
```

运行交付就绪检查：

```powershell
pnpm run verify:readiness
```

运行当前样本真实回归：

```powershell
$env:PYTHONPATH='.'
.\venv\Scripts\python.exe .\scripts\run_current_sample_regression.py
```

构建前端：

```powershell
pnpm --filter voucher-auto-entry-web build
```

## 目录

- `apps/api/`：FastAPI API 与工作流入口
- `apps/web/`：可视化界面
- `core/`：配置、schema、规则、知识层、工作流
- `scripts/bootstrap_knowledge.py`：将 `ai验证` 下的源资料分发到项目目录并生成结构化知识产物
- `knowledge/`：知识库存储
- `data/`：运行产物

## 当前状态

当前项目已经不是纯骨架阶段，而是“方案 1 可跑通原型 / 准交付版”：

1. 已具备上传附件 -> 抽取 -> 组单 -> 规则阻断 -> 人工复核 -> 导出 JSON 的主链路
2. 已支持一组附件生成一张支持多借多贷的凭证草案
3. 当前样本真实回归已可稳定命中目标三行分录
4. 当前仍在继续补通用规则库、LanceDB 真写入复验和更多真实样本回归
