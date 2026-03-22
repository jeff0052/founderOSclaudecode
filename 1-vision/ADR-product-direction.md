# ADR: FocalPoint 产品方向决策

> Architecture Decision Record — 2026-03-22

## 决策

**FocalPoint = 记忆 + 工作流 + 角色化上下文 = AI 认知操作系统**

不做两个独立产品，做一个完整的认知操作系统。

## 为什么

三省六部（工作流编排）离开 FocalPoint 的记忆层没有意义 — 角色化上下文装载是核心价值，没有智能记忆层的工作流编排和普通 prompt chain 没区别。

## 产品定位

```
FocalPoint ≠ 记忆工具（那是 Mem0）
FocalPoint ≠ 项目管理（那是 Notion/Linear）
FocalPoint ≠ prompt chain（那是 LangChain）

FocalPoint = AI 的认知操作系统
           = 记忆 + 注意力管理 + 工作流编排
           = 让 AI agent 像一个有经验的团队一样工作
```

## 三层架构

```
第一层：记忆引擎（已完成）
  节点管理、状态机、Heartbeat、Context Bundle
  GitHub/Notion 双向同步
  → 让 AI 记住事情

第二层：认知层（Work Mode — 下一步）
  角色化上下文装载（中书/门下/尚书看不同信息）
  智能焦点分配（token 预算动态调整）
  事件驱动心跳
  → 让 AI 关注对的事情

第三层：协作层（未来）
  多 Agent 任务分配和协调
  三省流转状态机（决策→审核→执行）
  跨 Agent 共享记忆
  → 让多个 AI 像团队一样协作
```

## 这就是 FounderOS

```
最初愿景 = AI 助手的操作系统
绕了一圈 = 从 FPMS 记忆引擎做起
现在     = 手里有跑通的代码 + 验证过的架构
下一步   = 在记忆引擎上加认知层和协作层
最终     = FounderOS
```

## 竞品对比

| | Mem0 | Zep | Letta | LangChain | **FocalPoint** |
|--|------|-----|-------|-----------|---------------|
| 记忆存储 | ✅ | ✅ | ✅ | ❌ | ✅ |
| 注意力管理 | ❌ | ❌ | 部分 | ❌ | ✅ |
| 角色化上下文 | ❌ | ❌ | ❌ | ❌ | ✅ (计划中) |
| 工作流编排 | ❌ | ❌ | ❌ | ✅ | ✅ (计划中) |
| 多 Agent 协作 | ❌ | ❌ | ❌ | 部分 | ✅ (计划中) |
| 外部工具同步 | ❌ | ❌ | ❌ | 部分 | ✅ |
| 主动风险告警 | ❌ | ❌ | ❌ | ❌ | ✅ |

没有任何现有产品覆盖这个完整定位。

## 决策人

Jeff, Onta Network Founder
