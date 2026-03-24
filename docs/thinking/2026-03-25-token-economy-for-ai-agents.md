# Token Economy for AI Agents — 思考笔记

> 2026-03-25 | Jeff × Claude 讨论
> 起因：FocalPoint 和所有 skill 目前都免费，代码生成能力在贬值，未来的经济模型是什么？

---

## 核心观察：代码在贬值，什么在升值？

AI 能写代码了。这意味着代码本身不再是稀缺资源。GitHub Copilot、Claude Code、Cursor——每个开发者都有一个免费的程序员助手。

**正在贬值的：**
- 写代码的能力（AI 能做）
- 基础 skill/plugin（容易复制）
- 模板和脚手架（AI 秒生成）

**正在升值的：**
- 验证过的知识（"这个方案在生产环境跑了 6 个月"）
- 决策质量（做什么 > 怎么做）
- 跨时间记忆（历史决策、教训、上下文）
- 注意力分配（有限 token 里装什么信息）
- 信任和声誉（这个 agent/skill 的输出质量有历史记录）

---

## 当前 Skill 生态：全免费，不可持续

| 产品 | 模式 | 为什么免费 |
|------|------|-----------|
| gstack（YC CEO） | MIT 开源 | 个人品牌建设，不需要赚钱 |
| superpowers | 开源 | 早期获客，生态占位 |
| openclaw-pm | 开源 | 平台获客策略 |
| FocalPoint | BSL | 还没用户，谈不上收费 |

这像 2008 年的 App Store——早期全免费或 $0.99，等生态成熟后才出现真正的商业模式。

---

## 假设：AI Agent 之间的服务经济

### 类比

| 互联网时代 | AI Agent 时代 |
|-----------|--------------|
| HTTP 协议 | MCP 协议 |
| API 调用 | Tool Call |
| SaaS 订阅 | Agent-to-Agent 微支付 |
| Stripe（支付基础设施） | Token 支付层 |
| AWS（计算基础设施） | Context/Memory 基础设施 |

### 模型描述

```
User 给 Agent A 一个任务："帮我做一个支付系统"

Agent A 调用 FocalPoint
  → 获取项目历史上下文（消耗 memory tokens）
  → 获取上次支付系统的教训（消耗 knowledge tokens）

Agent A 调用 "Stripe Expert" Skill
  → 获取 Stripe 集成最佳实践（消耗 skill tokens）
  → 这个 skill 之所以值钱，是因为它的输出经过了 100 个项目验证

Agent A 调用 "Security Reviewer" Agent
  → 审查支付代码的安全性（消耗 review tokens）
  → 这个 agent 有 OWASP Top 10 的专业知识 + 历史审查记录

每一步都有 token 流转：
  User → Agent A（任务费）
  Agent A → FocalPoint（记忆费）
  Agent A → Stripe Expert（专业知识费）
  Agent A → Security Reviewer（审查费）
```

### 什么东西值得付费？

| 层级 | 资源 | 定价逻辑 |
|------|------|---------|
| **基础设施** | 记忆存储、context assembly、搜索 | 按调用量计费（类似 AWS） |
| **知识** | 验证过的方案、行业最佳实践 | 按查询计费（类似 API） |
| **决策** | 需求审查、架构评审、风险检测 | 按审查次数计费（类似顾问） |
| **执行** | 代码生成、测试、部署 | 趋近于零（AI 能力在贬值） |
| **信任** | 输出质量历史记录、声誉评分 | 高信誉 agent 收费更高（类似评级） |

关键洞察：**越接近执行层越便宜，越接近决策层越贵。**

---

## FocalPoint 在这个经济体中的位置

### 定位：认知基础设施

每个 agent 都需要：
1. **记住**上下文（跨 session）
2. **知道**该关注什么（注意力管理）
3. **找到**相关历史（搜索）
4. **准备**工作上下文（workbench）
5. **审查**决策质量（三省）

这些都是 FocalPoint 提供的。如果它成为标准，就像 Stripe 之于支付——每个 agent 交互都经过 FocalPoint，每次都可以收一点。

### 可能的收费点

```
免费层（开源，本地运行）：
  - 基础 CRUD（24 tools）
  - 本地 SQLite 存储
  - CLI analytics

付费层（云服务）：
  - 跨设备/跨 agent 记忆同步
  - Analytics Dashboard Pro（历史趋势、团队视图）
  - 高可用 context assembly（低延迟、高并发）
  - 知识市场接入（连接其他 agent 的 knowledge）

Token 层（未来）：
  - 每次 context assembly 消耗 X tokens
  - 每次 knowledge 查询消耗 Y tokens
  - 每次三省审查消耗 Z tokens
  - 其他 agent 调用 FocalPoint API 时自动结算
```

---

## 实现路径

### 短期（现在 → 6 个月）

**做什么：** 不碰 token economy。专注产品。
- 让 FocalPoint 成为开发者/超级个体的默认认知层
- 积累用户、积累口碑
- 收集使用数据，优化 token 效率

**为什么：** 没有用户基础谈经济模型是空中楼阁。

### 中期（6 个月 → 2 年）

**做什么：** 云托管版 + 跨 agent 记忆共享。
- FocalPoint Cloud — 用户不用自己跑 SQLite
- Multi-agent 支持 — 多个 agent 读写同一个 FocalPoint
- 开始按使用量计费

**为什么：** 当多个 agent 需要共享记忆时，就有了真实的基础设施需求。

### 长期（2 年+）

**做什么：** 接入 agent 经济体的支付层。
- 如果 Anthropic/OpenAI 推出 agent marketplace + 支付系统，FocalPoint 作为认知层接入
- 每次 agent 调用 FocalPoint 的 context assembly，自动通过 token 结算
- 知识市场：agent 可以"购买"其他项目验证过的 knowledge

**为什么：** 这需要整个生态成熟，不是一家能推动的。

---

## 关键风险

1. **平台方自己做** — Anthropic/OpenAI 直接内置记忆层，FocalPoint 被替代
   - 缓解：做得比平台方更专业（垂直 > 通用）

2. **标准之争** — 多个记忆协议竞争，FocalPoint 不是赢家
   - 缓解：尽早占位，积累用户

3. **Token economy 不来** — AI agent 生态保持中心化（Anthropic/OpenAI 控制一切）
   - 缓解：不依赖 token economy，先做好 SaaS 模式

4. **开源替代** — 有人 fork FocalPoint 做免费版
   - 缓解：BSL 许可 4 年保护期 + 云服务护城河

---

## 和白皮书的关系

白皮书描述的 FounderOS 七模块（State/Signal/Interpretation/Missions/Stability/Constitution/Kill Switch）本质上都是**认知基础设施**。如果 AI agent 经济体真的出现，每个模块都是可计费的服务：

| 模块 | 服务 | 计费 |
|------|------|------|
| State | 状态管理 + 记忆 | 按存储量 |
| Signal | 外部信号感知 | 按信号源数量 |
| Interpretation | 信号解释 + 决策建议 | 按决策质量 |
| Missions | 任务执行 + 编排 | 按任务复杂度 |
| Stability | 风险检测 + 心跳 | 按扫描频率 |
| Constitution | 规则引擎 | 按规则复杂度 |

FocalPoint 现在覆盖了 State + Missions + Stability 的核心。这已经是最基础的三个。

---

## 结论

1. **代码在贬值，认知在升值** — FocalPoint 做的是认知层，方向正确
2. **Token economy 会来，但不是现在** — 先做好产品，等生态
3. **FocalPoint 的定位 = AI agent 的认知基础设施** — 类似 Stripe 之于支付
4. **短期靠产品，中期靠云服务，长期靠协议** — 三步走
5. **最大风险是平台方自己做** — 所以要做得比平台方更专业、更垂直

---

*这篇思考的触发点是一个简单的问题："这么多 skill 都免费，以后怎么赚钱？" 答案不在 skill 本身，在于 skill 背后的认知基础设施。代码免费了，但记忆、注意力、决策质量不会免费。*
