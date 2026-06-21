# K8s Healing Agent

> Event-driven Kubernetes remediation service that receives alerts, collects context, proposes actions, and executes approved fixes.

[![Status](https://img.shields.io/badge/status-developing-yellow)](https://github.com/290298661-pixel/k8s-healing-agent)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![K8s](https://img.shields.io/badge/K8s-v1.35-326CE5)](https://kubernetes.io/)

## 概述

K8s Healing Agent 是一个实验性的 Kubernetes 告警处理服务。它接收 AlertManager Webhook，收集相关 Pod、Deployment、Event、日志和节点状态，然后根据规则和模型输出修复建议。符合策略的低风险动作可以自动执行，其他动作进入人工审批或仅通知。

当前定位：

- 接收和去重 Kubernetes 告警。
- 汇总故障上下文，减少手动排查时间。
- 对修复动作进行置信度、权限和白名单校验。
- 记录诊断、决策、执行和验证结果。

## 处理流程

```
                              ┌──────────────────┐
                              │  Prometheus       │
                              │  AlertManager     │
                              │  (告警源)          │
                              └────────┬─────────┘
                                       │ Webhook
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                      K8s Healing Agent                            │
│                                                                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │ Alert        │   │ Diagnosis    │   │ AI Analysis          │  │
│  │ Ingestion    │──▶│ Engine       │──▶│ Engine               │  │
│  │ (FastAPI)    │   │ (K8s Client) │   │ (Claude API)         │  │
│  └──────────────┘   └──────────────┘   └──────────┬───────────┘  │
│                                                    │              │
│                                       ┌────────────▼───────────┐  │
│                                       │ Decision Engine        │  │
│                                       │ (置信度判断 + 安全校验)  │  │
│                                       └────────────┬───────────┘  │
│                                                    │              │
│ ┌────────┬─────────────────────┬─────────────────────┬─────────┐ │
│          │                     │                     │           │
│      conf ≥ 0.8          0.5 ≤ c < 0.8            c < 0.5        │
│          │                     │                     │           │
│          ▼                     ▼                     ▼           │
│ ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│ │ Healing Executor │  │ Human Approval   │  │ Escalate         │ │
│ │ (自动修复)        │  │ (钉钉确认)        │  │ (仅通知)          │ │
│ └────────┬─────────┘  └────────┬─────────┘  └──────────────────┘ │
│           │                     │                                │
│           ▼                     ▼                                │
│  ┌──────────────────────────────────────────────┐               │
│  │ Verification Engine (修复后验证)               │               │
│  └──────────────────────┬───────────────────────┘               │
│                         │                                        │
│              ┌──────────┼──────────┐                            │
│              ▼          ▼          ▼                             │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ Audit    │   │ Notification │   │ Metrics      │            │
│  │ Log      │   │ (钉钉通知)    │   │ (Prometheus) │            │
│  └──────────┘   └──────────────┘   └──────────────┘            │
└──────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 前提条件

- Python 3.12+
- Kubernetes 集群
- `kubectl` 已配置
- 模型 API Key（按 `config/config.yaml` 配置）
- 钉钉 Webhook（可选）

### 安装依赖

```bash
git clone https://github.com/290298661-pixel/k8s-healing-agent.git
cd k8s-healing-agent
pip install -r requirements.txt
```

### 配置

```bash
cp config/config.example.yaml config/config.yaml
# 编辑 config/config.yaml，填写 API Key、命名空间白名单、通知配置等
```

### 部署 RBAC

```bash
kubectl apply -f deploy/rbac.yaml
```

### 本地运行

```bash
python -m src.main
# 或
uvicorn src.main:app --reload --port 8080
```

### 配置 AlertManager Webhook

```yaml
receivers:
  - name: k8s-healing-agent
    webhook_configs:
      - url: http://healing-agent:8080/webhook/alertmanager
```

### 验证

```bash
curl http://localhost:8080/health
```

API 文档默认由 FastAPI 提供：`http://localhost:8080/docs`。

## 目录结构

```text
k8s-healing-agent/
├── src/
│   ├── main.py                        # FastAPI 入口
│   ├── config.py                      # 配置加载
│   ├── models/                        # 告警、诊断、修复数据模型
│   ├── engine/                        # 诊断、分析、决策、执行、验证
│   ├── safety/                        # 权限、白名单、循环保护、响应校验
│   ├── notification/                  # 通知适配
│   ├── audit/                         # 审计日志
│   └── utils/                         # Kubernetes 客户端和指标工具
├── config/
│   ├── config.yaml
│   └── prompt.yaml
├── deploy/
│   ├── deployment.yaml
│   ├── rbac.yaml
│   ├── configmap.yaml
│   └── prometheus-rule.yaml
├── docs/
│   └── DESIGN.md
├── tests/
└── requirements.txt
```

## 安全边界

| 层级 | 说明 |
| --- | --- |
| RBAC | ServiceAccount 只授予必要的 Kubernetes 权限 |
| Namespace 白名单 | 只处理明确允许的命名空间 |
| 动作白名单 | 只执行预定义修复动作 |
| 置信度门槛 | 低置信度结果不自动执行 |
| 人工审批 | 中高风险动作进入人工确认流程 |
| 审计日志 | 记录输入、决策、执行和验证结果 |

AI 或模型输出不直接操作 Kubernetes，所有动作都必须通过代码层校验。

## 支持的故障类型

| 故障类型 | 默认处理方式 |
| --- | --- |
| `OOMKilled` | 生成资源调整建议，符合策略时可执行 |
| `ImagePullBackOff` | 检查镜像、Secret 和事件，默认进入审批或通知 |
| `CrashLoopBackOff` | 收集启动日志和事件，生成诊断建议 |
| `Pending` | 检查调度事件、资源不足和节点状态 |
| `ReadinessProbe` 失败 | 检查探针配置、日志和服务状态 |
| `DiskPressure` / `Evicted` | 通知并关联节点状态 |
| ConfigMap/Secret 缺失 | 报告缺失资源和引用位置 |

具体动作策略应在配置中按环境调整，生产环境建议先使用审批或仅通知模式。

## 开发

```bash
pip install -r requirements.txt
pytest tests/ -v
ruff check src tests
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/DESIGN.md](docs/DESIGN.md) | 设计说明 |
| [config/prompt.yaml](config/prompt.yaml) | Prompt 和诊断规则 |
| [deploy/rbac.yaml](deploy/rbac.yaml) | Kubernetes 权限配置 |

## 相关项目

| 仓库 | 关系 |
| --- | --- |
| [fleet-observability](https://github.com/290298661-pixel/fleet-observability) | 提供 Prometheus / AlertManager 告警来源 |
| [fleet-gitops](https://github.com/290298661-pixel/fleet-gitops) | 可管理本服务的部署配置 |
| [node-health-watcher](https://github.com/290298661-pixel/node-health-watcher) | 节点巡检告警可作为输入信号 |
| [node-guardian](https://github.com/290298661-pixel/node-guardian) | 诊断命令可作为人工排查补充 |

## License

MIT
