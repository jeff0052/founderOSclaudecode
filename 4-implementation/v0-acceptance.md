# FPMS v0 验收清单

v0 目标：证明写入、校验、恢复能稳定工作。

验收通过标准：**全部 checkbox 打勾，零 FAIL。**

---

## 第 1 层：铁律测试（Invariant Tests）

系统不可违背的不变量。一条不过 = v0 不通过。

- [ ] **DAG 永不成环** — parent 环、depends_on 环、跨维度环均被拒绝
- [ ] **XOR 互斥** — is_root=True 且 parent_id≠None 永不共存
- [ ] **原子提交** — facts + audit_outbox 在同一事务，崩溃后无半提交
- [ ] **状态机合法** — 所有非法迁移被拒绝，合法迁移全部通过
- [ ] **归档热区隔离** — attach/dependency 目标不可以是已归档节点
- [ ] **派生层隔离** — 写路径代码中无任何 derived_*/cache 表的读取
- [ ] **幂等** — 相同 command_id 重复调用返回相同结果，不产生重复数据

```
运行命令: pytest tests/invariants/ -v
期望结果: ALL PASSED
```

---

## 第 2 层：单元测试

每个模块的功能正确性。

### schema.py + models.py
- [ ] SQLite 建表成功，所有 CHECK 约束生效
- [ ] nodes 表 status CHECK 约束拒绝非法值
- [ ] nodes 表 XOR CHECK（is_root=1 AND parent_id IS NOT NULL → 拒绝）
- [ ] audit_outbox 表存在且结构正确
- [ ] recent_commands 表存在且结构正确
- [ ] WAL 模式已启用
- [ ] Pydantic CreateNodeInput 类型强转正确（"true" → True）
- [ ] Pydantic CreateNodeInput 非法 node_type 拒绝 + 清晰报错
- [ ] Pydantic UpdateStatusInput 非法 status 拒绝
- [ ] Pydantic deadline 非 ISO8601 格式拒绝 + 示例提示

### narrative.py
- [ ] append_narrative 追加格式 `## {timestamp} [{event_type}]\n{content}`
- [ ] append_narrative 不覆盖已有内容（append-only 验证）
- [ ] read_narrative 按条数截取（last_n_entries）
- [ ] read_narrative 按天数截取（since_days）
- [ ] read_compressed / write_compressed 正确读写
- [ ] write_repair_event 写入修复记录
- [ ] 目标文件不存在时自动创建目录和文件

### store.py
- [ ] create_node 写入 DB + audit_outbox（同一事务内）
- [ ] get_node 存在/不存在
- [ ] update_node 更新字段 + updated_at 自动刷新
- [ ] list_nodes 按 status/node_type/parent_id 过滤
- [ ] list_nodes 分页（limit + offset）
- [ ] add_edge / remove_edge 正确
- [ ] get_edges 按方向（outgoing/incoming/both）
- [ ] get_children / get_parent / get_dependencies / get_dependents / get_siblings
- [ ] get_ancestors 递归向上正确
- [ ] get_descendants 递归向下正确
- [ ] `with store.transaction():` 正常 commit
- [ ] `with store.transaction():` 异常自动 rollback，无脏数据
- [ ] write_event 写入 audit_outbox
- [ ] flush_events 从 outbox 写入 events.jsonl + 标记 flushed=1
- [ ] session_state get/set 正确
- [ ] command_id 幂等：相同 id 返回上次结果

### validator.py
- [ ] inbox→active 合法
- [ ] inbox→active 缺 summary → 拒绝 + actionable suggestion
- [ ] inbox→active 缺 parent_id 且非 root → 拒绝
- [ ] active→done 合法（无子节点）
- [ ] active→done 有活跃子节点 → 拒绝 + 列出子节点
- [ ] active→dropped 有活跃子节点 → 允许 + warning
- [ ] done→active 缺 reason → 拒绝
- [ ] dropped→inbox 缺 reason → 拒绝
- [ ] done→waiting → 拒绝（非法迁移）
- [ ] DAG parent 环路 → 拒绝
- [ ] DAG depends_on 环路 → 拒绝
- [ ] DAG 跨维度死锁（child depends_on ancestor）→ 拒绝
- [ ] XOR: is_root=True + parent_id≠None → 拒绝
- [ ] 活跃域: attach 到已归档节点 → 拒绝
- [ ] 自依赖: node depends_on 自己 → 拒绝
- [ ] 所有 ValidationError 包含 code + message + suggestion

### tools.py
- [ ] create_node: 正常创建 → 返回 Node + event_id
- [ ] create_node: Pydantic 校验失败 → 拒绝 + 详细报错
- [ ] update_status: 合法迁移 → 成功
- [ ] update_status: 非法迁移 → 拒绝 + actionable error
- [ ] update_status(is_root=true): 自动清除 parent_id
- [ ] update_field: 正常更新
- [ ] update_field: 禁止字段 → 拒绝
- [ ] attach_node: 正常挂载
- [ ] attach_node: 已有 parent → 原子替换（detach old + attach new）
- [ ] attach_node: 归档目标 → 拒绝
- [ ] attach_node: 会造成环 → 拒绝
- [ ] detach_node: 正常脱离
- [ ] add_dependency: 正常
- [ ] add_dependency: 自依赖 → 拒绝
- [ ] add_dependency: 环路 → 拒绝
- [ ] add_dependency: 归档目标 → 拒绝
- [ ] remove_dependency: 正常
- [ ] append_log: 正常追加 narrative
- [ ] unarchive: status_changed_at 刷新为 NOW()
- [ ] unarchive(new_status=): 原子解封 + 状态迁移
- [ ] set_persistent: 设置/取消
- [ ] shift_focus: 切换焦点
- [ ] expand_context: 扩展
- [ ] get_node: 存在/不存在
- [ ] search_nodes: 按 status/parent_id 过滤 + 分页
- [ ] search_nodes: summary 默认不含，include_summary=true 时含
- [ ] 幂等: 相同 command_id → 返回相同结果

```
运行命令: pytest tests/ -v --ignore=tests/invariants/
期望结果: ALL PASSED
```

---

## 第 3 层：端到端冒烟测试

模拟真实使用场景，跨模块验证。

### 场景 A：基本生命周期
- [ ] 创建 goal 节点（is_root=true）
- [ ] 创建 project 节点，attach 到 goal
- [ ] 创建 task 节点，attach 到 project
- [ ] 三层树结构正确（get_children 验证）
- [ ] task: inbox → active（补 summary 后）
- [ ] task: active → done
- [ ] project: inbox → active → done（task 已终态后）
- [ ] goal: inbox → active → done（project 已终态后）

### 场景 B：依赖与阻塞
- [ ] 创建 task-A 和 task-B
- [ ] task-B depends_on task-A
- [ ] task-B 在 task-A 未完成时无法 → done（如果有 blocked 逻辑）
- [ ] task-A → done 后 task-B 不再 blocked
- [ ] 尝试反向依赖 task-A depends_on task-B → 环路拒绝

### 场景 C：状态回退
- [ ] task → done → active（带 reason）→ 验证 reason 记录在 narrative
- [ ] task → dropped → inbox（带 reason）→ 验证 reason 记录

### 场景 D：归档边界
- [ ] unarchive 节点 → status_changed_at = NOW()
- [ ] attach 到已归档节点 → 拒绝
- [ ] add_dependency 到已归档节点 → 拒绝

### 场景 E：审计完整性
- [ ] 全部操作后 audit_outbox 有对应记录
- [ ] flush_events → events.jsonl 行数 = 操作次数
- [ ] events.jsonl 每行可 JSON parse
- [ ] 每条 event 包含 tool_name + timestamp + command_id

### 场景 F：幂等与崩溃
- [ ] 用相同 command_id 调用 create_node 两次 → 只创建一个节点
- [ ] kill 进程（模拟崩溃）→ 重启 → DB 数据完整 → 无半提交

### 场景 G：Actionable Errors
- [ ] 触发至少 3 种不同的 ValidationError
- [ ] 每个 error 都包含 suggestion 字段
- [ ] suggestion 中提到的 Tool 和参数是正确可执行的

```
运行命令: pytest tests/test_e2e.py -v
期望结果: ALL PASSED
```

---

## 第 4 层：PRD 附录 7 对照

逐条对照 PRD 第 1049-1098 行的验收清单。

### 拓扑安全
- [ ] 新增 parent 前执行全息 DAG 查环
- [ ] 新增 depends_on 前执行全息 DAG 查环
- [ ] 跨维度死锁（child depends_on ancestor）被拒绝
- [ ] 不存在的 node_id 引用被拒绝
- [ ] attach 自动处理旧 parent 的 detach
- [ ] parent 变更后 rollup 链正确（v1 验证）
- [ ] archive 条件检查包含"无活跃后代"

### 写入一致性
- [ ] 事实写入和审计日志在同一事务
- [ ] Narrative 写入失败不回滚事实
- [ ] Narrative 写入失败生成 repair event
- [ ] 无 delete_node（只有 dropped → archive）
- [ ] 所有 Tool 写入产生可重放的 event

### 状态引擎
- [ ] inbox→active 需要 summary + (parent OR root)
- [ ] →done 需要所有子节点终态
- [ ] →dropped 对活跃子节点生成告警（v1 验证）
- [ ] done→active 必须带 reason
- [ ] dropped→inbox 必须带 reason

---

## 验收流程

```
1. 运行: pytest tests/ -v
2. 确认: 零 FAIL
3. 逐条检查本文档所有 checkbox
4. 全部打勾 → v0 验收通过
5. 未通过项记录到 issues 列表，修复后重新验收
```

## 验收结果

- [ ] **v0 验收通过** — 日期: ______ — 签字: ______
