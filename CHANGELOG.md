# FounderOS 变更日志

*每次需求迭代后更新此文件。记录"改了什么 + 为什么改"。*

---

## 2026-03-20 — 需求深化迭代

### 新增文档

| 文档 | 位置 | 内容 |
|------|------|------|
| PRD-context-lifecycle | 2-requirements/ | Context 生命周期（装载→校验→执行→校验→写回→上报→压缩） |
| PRD-compression-spec | 2-requirements/ | 压缩策略规格（Narrative MD 格式、规则基压缩、无 LLM） |
| PRD-cognitive-engine | 2-requirements/ | V2 认知引擎（跨工具集成层，Adapter 架构） |
| PRD-cto-agent | 2-requirements/ | CTO Agent 需求（第一个 Office 实例） |
| GLOSSARY | 根目录 | 术语表，统一所有专有概念定义 |
| USER-SCENARIOS | 2-requirements/ | 8 个用户场景，从 Founder 视角描述使用流程 |
| CHANGELOG | 根目录 | 本文件 |

### 关键设计决策

1. **Context 不是聊天记录，是工作台**
   - 定义了 context 的精确组成（自身骨架 + 向上 + 向下 + 横向 + 历史）
   - 明确了裁剪铁律：半残的全景不如完整的焦点

2. **生命周期从"读-做-写"扩展为六步循环**
   - 新增进入校验（开工前确认方向对齐）
   - 新增中途校验（执行中发现重要信息时"抬头看全局"）
   - 新增退出上报（关键发现向上冒泡，与 rollup 的 status 冒泡互补）
   - 灵感来源：人类做复杂任务时的"总分总"不是一次，而是反复抬头

3. **任务拆解 = Context 分形**
   - 拆解的判断标准：context 超预算 = 还没拆够
   - 拆解的目的不是管理，是让每个子任务的 context 自给自足

4. **V2 方向确定：不重造轮子，只做认知引擎**
   - V1 = Standalone FPMS（自己存所有数据）
   - V2 = 跨工具认知引擎（连接 GitHub/Notion/Lark，只做它们做不到的事）
   - V2 只做：跨工具因果链、Context 组装、压缩记忆、主动校验

5. **压缩策略确定：规则基，不用 LLM**
   - 节省成本、确定性可控、可审计
   - 三步压缩：时间过滤 → 结构化提取 → 模板渲染

### 审计修复

| 问题 | 修复 |
|------|------|
| 派生层隔离 vs rollup 矛盾 | 澄清：rollup 是事务内确定性计算，不是"读派生物" |
| done 是否为终态 | 澄清：done 是软终态，archived 是硬终态 |
| 焦点丢失行为未定义 | 定义：进入无焦点模式，只有 L0 + L_Alert |

### 文档重组

- 所有文档从散落状态整理为 4 层分类：vision / requirements / architecture / implementation
- 新建 README.md 作为总入口

---

## 2026-03-17 — V3 基础需求建立

### 文档

| 文档 | 内容 |
|------|------|
| PRD-functional | 14 个功能需求（FR-0 ~ FR-13），含状态机、DAG、Tool Call |
| PRD-nfr | 非功能需求（性能、安全、可靠性） |
| PRD-philosophy | 设计哲学（人类认知映射、DCP、眼球模型） |
| PRD-goals | 核心目标和成功标准 |
| ARCHITECTURE | FPMS 架构设计 |
| ARCHITECTURE-V3.1 | Memory 六层架构 + DCP 模型 |
| INTERFACES | MCP Tool 接口定义（14 个工具） |
| CLAUDE | Agent 开发规范 |
| WhitePaper | 愿景白皮书 |
| OVERVIEW | 系统全景 |
| v0-task-breakdown | V0 详细任务分解（6 Task + Agent 分配） |
| v0-acceptance | V0 验收清单（4 层 checklist） |

### 关键设计决策

1. **分形节点模型** — 统一 Schema，goal/project/task/signal 同构
2. **DCP Push 模型** — 脊髓引擎推送 context，禁止 RAG Pull
3. **14 Tool 写入路径** — LLM 通过标准化工具操作数据，不直接碰存储
4. **SQLite + WAL** — 单文件数据库，原子提交，WAL 读写不互锁
5. **眼球模型** — L0/L1/L2 三层分辨率 + L_Alert 独立告警

---

## 变更记录格式说明

每次迭代记录：
- **日期 + 标题**
- **新增/修改/删除了哪些文档**
- **关键设计决策**（决定了什么 + 为什么）
- **修复了什么问题**（如果有审计/review 反馈）
