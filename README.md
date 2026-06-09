# 🤖 K8s Healing Agent — AI 驱动的 Kubernetes 自愈系统

> **事件驱动的自治系统** — Prometheus 告警 → AI 诊断 → 自动修复 → 验证闭环
>
> 独立项目，继承自 [K8s 全栈运维平台](https://github.com/290298661-pixel)

[![Status](https://img.shields.io/badge/status-developing-yellow)](https://github.com/290298661-pixel/k8s-healing-agent)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![Claude](https://img.shields.io/badge/AI-Claude%20API-D97757)](https://docs.anthropic.com/en/api)
[![K8s](https://img.shields.io/badge/K8s-v1.35-326CE5)](https://kubernetes.io/)

---

## 🎯 一句话描述

**"当 K8s Pod 出故障时，AI Agent 自动诊断根因、按置信度分流——高置信自动修复、低置信人工审批——全程 15 秒内完成，修复前后全量审计。"**

---

## 🏗️ 架构总览

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
│                    ┌───────────────────────────────┼───────┐      │
│                    │                               │       │      │
│             conf ≥ 0.8                  0.5 ≤ c < 0.8  c < 0.5  │
│                    │                               │       │      │
│                    ▼                               ▼       ▼      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ Healing Executor │  │ Human Approval   │  │ Escalate     │  │
│  │ (自动修复)        │  │ (钉钉确认)        │  │ (仅通知)      │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────────┘  │
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

---

## 🔗 在平台中的位置

```
K8s 自愈 AI Agent ←── 你在这里 ★
    │
    │ 事件驱动，自治运行
    │ 与 fleet-gitops 互补：GitOps 管部署，Agent 管运行时的故障自愈
    │
    ├── 消费：Prometheus AlertManager 告警
    ├── 依赖：Claude API（AI 诊断）
    └── 操作：K8s Deployment/StatefulSet（修复执行）
```

---

## 🚀 快速开始

### 前提

- Python 3.12+
- Kubernetes 集群 (Kind/Minikube/K3s)
- Claude API Key ([获取](https://console.anthropic.com/))
- 钉钉机器人 Webhook（可选）

### 1. 克隆并安装依赖

```bash
git clone https://github.com/290298661-pixel/k8s-healing-agent.git
cd k8s-healing-agent
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config/config.example.yaml config/config.yaml
# 编辑 config.yaml，填入 Claude API Key 和钉钉 Webhook
```

### 3. 部署 RBAC（最小权限）

```bash
kubectl apply -f deploy/rbac.yaml
```

### 4. 本地运行

```bash
python -m src.main
# 或
uvicorn src.main:app --reload --port 8080
```

### 5. 配置 Prometheus AlertManager Webhook

```yaml
receivers:
  - name: 'k8s-healing-agent'
    webhook_configs:
      - url: 'http://healing-agent:8080/webhook/alertmanager'
```

### 6. 验证

```bash
# 健康检查
curl http://localhost:8080/health

# 查看 API 文档
open http://localhost:8080/docs
```

---

## 🧠 四大设计原则

| # | 原则 | 说明 |
|---|------|------|
| 1 | **AI 做判断，代码做执行** | AI 不直接操作 K8s，代码层作为安全护栏 |
| 2 | **安全优先** | 任何修复动作都有置信度门槛和回滚机制 |
| 3 | **人类兜底** | AI 不确定时自动升级人工，不做猜测性修复 |
| 4 | **全程可审计** | 每次诊断、决策、修复都记录到审计日志 |

---

## 📂 仓库结构

```
k8s-healing-agent/
├── README.md                          ← 你在这里
├── docs/
│   └── DESIGN.md                      ← 深度设计文档
│
├── src/
│   ├── __init__.py
│   ├── main.py                        ← FastAPI 入口
│   ├── config.py                      ← 配置管理
│   ├── models/
│   │   ├── __init__.py
│   │   ├── alert.py                   ← 告警数据模型
│   │   ├── diagnosis.py               ← 诊断数据模型
│   │   └── fix.py                     ← 修复方案模型
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── diagnosis.py               ← 诊断引擎（K8s 数据收集）
│   │   ├── analyzer.py                ← AI 分析引擎（Claude API）
│   │   ├── decision.py                ← 决策引擎（置信度分流）
│   │   ├── healer.py                  ← 修复执行器
│   │   └── verifier.py                ← 验证引擎（修复后检查）
│   ├── safety/
│   │   ├── __init__.py
│   │   ├── guard.py                   ← 安全护栏（五层防护）
│   │   ├── loop_guard.py              ← 修复循环保护
│   │   └── validator.py               ← AI 响应校验（反幻觉）
│   ├── notification/
│   │   ├── __init__.py
│   │   └── dingtalk.py                ← 钉钉通知
│   ├── audit/
│   │   ├── __init__.py
│   │   └── logger.py                  ← 审计日志
│   └── utils/
│       ├── __init__.py
│       ├── k8s_client.py              ← K8s 客户端封装
│       └── metrics.py                 ← Prometheus 指标暴露
│
├── tests/
│   ├── test_diagnosis.py
│   ├── test_analyzer.py
│   ├── test_integration.py
│   └── test_fault_injection.py        ← 故障注入测试
│
├── deploy/
│   ├── deployment.yaml                ← K8s 部署清单
│   ├── rbac.yaml                      ← RBAC 最小权限
│   ├── configmap.yaml                 ← 应用配置
│   └── prometheus-rule.yaml           ← 告警规则
│
├── config/
│   ├── config.yaml                    ← 主配置
│   └── prompt.yaml                    ← AI Prompt 模板
│
├── Dockerfile
├── requirements.txt
├── .gitignore
└── LICENSE
```

---

## 🎯 核心设计决策

| 决策 | 选择 | 为什么不选替代方案 |
|------|------|-------------------|
| **AI 引擎** | Claude API (Sonnet) | JSON Schema 结构化输出、低幻觉率、原生 Tool Use 支持 |
| **Web 框架** | FastAPI | 天然异步、自带 OpenAPI 文档、WebSocket 支持 |
| **K8s 交互** | kubernetes Python Client | 官方维护、覆盖所有 API、InCluster 配置零配置部署 |
| **决策模型** | 三层置信度分流 | 简单故障自动修、复杂故障人工批、不确定只通知——不做赌博 |
| **安全模型** | 五层纵深防护 | RBAC → Namespace 白名单 → 动作白名单 → 置信度门槛 → 人工兜底 |
| **审计存储** | SQLite（单实例）/ PostgreSQL（多副本） | 轻量起步、SQLite 零运维、随时可迁移到 PG |
| **通知通道** | 钉钉 Webhook | 国内团队通用、Markdown 格式丰富、支持交互式卡片 |

---

## 🚦 故障处理流水线

```
T+0s    AlertManager Webhook 到达 FastAPI
T+0.1s  告警去重检查（fingerprint 缓存，5min 窗口）
T+0.2s  启动 Diagnosis Engine
T+0.3s  ─┬─ 并发请求 K8s API ──────────────
         │  · get Pod Status         (~0.3s)
         │  · list Namespace Events  (~0.5s)
         │  · get Pod Logs           (~2.0s)  ← 最慢
         │  · get Node Conditions    (~0.3s)
         └──────────────────────────────────
T+3.0s  诊断数据聚合 → 构建 DiagnosisReport
T+3.0s  发送 Claude API 请求
T+8.0s  Claude API 返回（~5s 推理）
T+8.1s  Decision Engine 判断：
        ├─ AUTO_EXEC (confidence ≥ 0.8) → 执行修复 → 验证 → 通知
        ├─ APPROVAL  (0.5 ≤ c < 0.8)   → 钉钉审批 → 等人工确认
        └─ NOTIFY    (c < 0.5)          → 仅通知，不做操作
T+12s   完成（AUTO_EXEC 路径，不含验证等待）
```

> 典型故障从告警到修复，全程 **10-15 秒**（不含验证等待）。

---

## 🔒 安全五层防护

```
┌──────────────────────────────────────────────────┐
│              安全防护五层模型                        │
├──────────────────────────────────────────────────┤
│ Layer 1: RBAC — K8s ServiceAccount 最小权限        │
│ Layer 2: Namespace 白名单 — 只处理授权的 namespace  │
│ Layer 3: 动作白名单 — 只能执行预先定义的操作         │
│ Layer 4: 置信度门槛 — 不确定就不动                   │
│ Layer 5: 人工兜底 — 高风险操作必须人类确认           │
└──────────────────────────────────────────────────┘
```

---

## 📋 故障覆盖矩阵

| # | 故障类型 | AI 置信度 | 修复策略 | 自动化程度 |
|---|---------|----------|---------|-----------|
| 1 | **OOMKilled** | 0.90-0.95 | 增加 memory limit（翻倍，上限 4Gi） | ✅ 自动 |
| 2 | **ImagePullBackOff** | 0.70-0.90 | 检查 imagePullSecrets / 验证镜像 | ⚠️ 需审批 |
| 3 | **CrashLoopBackOff** | 0.60-0.85 | 检查启动命令 / 依赖可达性 | ⚠️ 需审批 |
| 4 | **Pending (资源不足)** | 0.85-0.95 | 降低 request 或报告需扩容 | ✅ 自动 |
| 5 | **ReadinessProbe 失败** | 0.65-0.80 | 增加 initialDelaySeconds/failureThreshold | ⚠️ 需审批 |
| 6 | **DiskPressure (Evicted)** | 0.80-0.90 | Evicted Pod 自动调度到其他节点 | 🔔 仅通知 |
| 7 | **ConfigMap/Secret 缺失** | 0.90-0.95 | 报告缺失资源名称 | ⚠️ 需审批 |

---

## 📚 文档导航

| 文档 | 适合 |
|------|------|
| [DESIGN.md](docs/DESIGN.md) | 深入理解系统设计、Prompt 工程、安全模型 |
| [config/prompt.yaml](config/prompt.yaml) | AI Prompt 模板和诊断规则 |
| [deploy/rbac.yaml](deploy/rbac.yaml) | K8s RBAC 权限设计参考 |

---

## 🔗 相关仓库

| 仓库 | 关系 |
|------|------|
| [fleet-gitops](https://github.com/290298661-pixel/fleet-gitops) | GitOps 交付平台——管部署，Agent 管运行时自愈 |
| [fleet-observability](https://github.com/290298661-pixel/fleet-observability) | 可观测性——Prometheus 告警规则来源 |

---

> **核心理念：不是"我又调了一个 AI API"，而是"我设计了一个 AI 驱动的自治系统——AI 做判断，代码做执行，安全五层兜底，全程可审计"。**
