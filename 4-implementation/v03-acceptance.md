# FocalPoint v0.3 验收清单

> 工作台 + 角色化上下文装载。所有测试通过 = v0.3 完成。

---

## 1. Narrative Category 验收

### 1.1 append_log 支持 category
```python
engine.execute_tool("append_log", {
    "node_id": node_id,
    "content": "选了 Stripe",
    "event_type": "log",
    "category": "decision",
})
# 验证：narrative MD 文件里包含 [decision] 标记
```

### 1.2 category 默认值
```python
engine.execute_tool("append_log", {
    "node_id": node_id,
    "content": "日常更新",
})
# 验证：category 默认为 "general"
```

### 1.3 无效 category 拒绝
```python
result = engine.execute_tool("append_log", {
    "node_id": node_id,
    "content": "test",
    "category": "invalid_category",
})
# 验证：result.success == False
```

---

## 2. 角色化上下文装载验收

### 2.1 准备测试数据
```python
# 创建项目
project = engine.execute_tool("create_node", {
    "title": "支付系统", "is_root": True, "node_type": "project",
    "why": "用户需要在线支付", "summary": "接入 Stripe 支付",
})
project_id = project.data["id"]

# 创建子任务
task = engine.execute_tool("create_node", {
    "title": "实现支付 API", "parent_id": project_id, "node_type": "task",
})
task_id = task.data["id"]
engine.execute_tool("update_status", {"node_id": task_id, "new_status": "active"})

# 写入不同 category 的 log
engine.execute_tool("append_log", {
    "node_id": project_id, "content": "用户调研：80% 用户希望支持信用卡",
    "category": "feedback",
})
engine.execute_tool("append_log", {
    "node_id": project_id, "content": "决策：选 Stripe，API 好，费率低",
    "category": "decision",
})
engine.execute_tool("append_log", {
    "node_id": project_id, "content": "注意 PCI 合规要求",
    "category": "risk",
})
engine.execute_tool("append_log", {
    "node_id": task_id, "content": "用了 stripe.PaymentIntent.create()",
    "category": "technical",
})
engine.execute_tool("append_log", {
    "node_id": task_id, "content": "API endpoint 完成，待测试",
    "category": "progress",
})
```

### 2.2 Strategy 角色 — 只看决策和反馈
```python
bundle = engine.get_context_bundle(user_focus=project_id, role="strategy")

# 验证包含：
assert "用户调研" in bundle  # feedback ✅
assert "选 Stripe" in bundle  # decision ✅
assert "用户需要在线支付" in bundle  # why ✅

# 验证不包含：
assert "stripe.PaymentIntent" not in bundle  # technical ❌
assert "API endpoint 完成" not in bundle  # progress ❌ (执行层细节)
```

### 2.3 Review 角色 — 只看风险和方案
```python
bundle = engine.get_context_bundle(user_focus=project_id, role="review")

# 验证包含：
assert "PCI 合规" in bundle  # risk ✅
assert "接入 Stripe 支付" in bundle  # summary ✅

# 验证不包含：
assert "用户调研" not in bundle  # feedback ❌ (中书省的事)
assert "stripe.PaymentIntent" not in bundle  # technical ❌ (尚书省的事)
```

### 2.4 Execution 角色 — 只看技术和进度
```python
bundle = engine.get_context_bundle(user_focus=task_id, role="execution")

# 验证包含：
assert "stripe.PaymentIntent" in bundle  # technical ✅
assert "API endpoint 完成" in bundle  # progress ✅
assert "实现支付 API" in bundle  # task title ✅

# 验证不包含：
assert "用户调研" not in bundle  # feedback ❌
assert "选 Stripe" not in bundle  # decision ❌ (中书省的事)
assert "PCI 合规" not in bundle  # risk ❌ (门下省的事)
```

### 2.5 All 角色 — 向后兼容
```python
bundle = engine.get_context_bundle(user_focus=project_id, role="all")

# 验证：所有 category 的 log 都包含
assert "用户调研" in bundle
assert "选 Stripe" in bundle
assert "PCI 合规" in bundle
assert "stripe.PaymentIntent" in bundle
assert "API endpoint 完成" in bundle
```

### 2.6 不传 role — 默认 "all"
```python
bundle_default = engine.get_context_bundle(user_focus=project_id)
bundle_all = engine.get_context_bundle(user_focus=project_id, role="all")

# 验证：行为完全一致
assert bundle_default == bundle_all
```

---

## 3. Token Budget 动态分配验收

### 3.1 Execution 角色不加载 L0
```python
bundle = engine.get_context_bundle(user_focus=task_id, role="execution")

# 验证：L0 全局看板为空或极简
assert bundle.l0_dashboard == "" or len(bundle.l0_dashboard) < 50
```

### 3.2 Strategy 角色 L0 比例更大
```python
bundle_strategy = engine.get_context_bundle(user_focus=project_id, role="strategy")
bundle_execution = engine.get_context_bundle(user_focus=project_id, role="execution")

# 验证：strategy 的 L0 内容比 execution 多
assert len(bundle_strategy.l0_dashboard) > len(bundle_execution.l0_dashboard)
```

### 3.3 总 token 不超限
```python
bundle = engine.get_context_bundle(user_focus=project_id, role="strategy")

# 验证：总 token 在预算内（8000 tokens）
assert bundle.total_tokens <= 8000
```

---

## 4. 工作台 (activate_workbench) 验收

### 4.1 基本调用
```python
workbench = engine.activate_workbench(node_id=project_id, role="execution")

# 验证返回结构
assert "goal" in workbench
assert "context" in workbench
assert "subtasks" in workbench
assert "suggested_next" in workbench
assert "token_budget" in workbench
```

### 4.2 子任务排序
```python
# 创建有依赖关系的子任务
task_a = create_node("设计 API schema", parent_id=project_id)
task_b = create_node("实现 API", parent_id=project_id)
task_c = create_node("写测试", parent_id=project_id)
add_dependency(source=task_b, target=task_a)  # B 依赖 A
add_dependency(source=task_c, target=task_b)  # C 依赖 B

workbench = engine.activate_workbench(node_id=project_id, role="execution")

# 验证：按依赖排序 A → B → C
assert workbench["subtasks"][0]["title"] == "设计 API schema"
assert workbench["subtasks"][1]["title"] == "实现 API"
assert workbench["subtasks"][2]["title"] == "写测试"
```

### 4.3 suggested_next 返回第一个未完成的
```python
update_status(task_a, "done")

workbench = engine.activate_workbench(node_id=project_id, role="execution")

# 验证：跳过已完成的，建议下一个
assert workbench["suggested_next"]["title"] == "实现 API"
```

### 4.4 Strategy 角色返回决策历史
```python
workbench = engine.activate_workbench(node_id=project_id, role="strategy")

# 验证：包含 decisions
assert len(workbench["decisions"]) > 0
assert "选 Stripe" in workbench["decisions"][0]["content"]
```

### 4.5 Review 角色返回风险项
```python
workbench = engine.activate_workbench(node_id=project_id, role="review")

# 验证：包含 risks
assert len(workbench["risks"]) > 0
assert "PCI 合规" in workbench["risks"][0]["content"]
```

---

## 5. MCP Tool 验收

### 5.1 append_log MCP tool 支持 category
```python
from fpms.mcp_server import append_log
result = json.loads(append_log(node_id=node_id, content="test", category="decision"))
assert result["success"] is True
```

### 5.2 get_context_bundle MCP tool 支持 role
```python
from fpms.mcp_server import get_context_bundle
result = json.loads(get_context_bundle(focus_node_id=node_id, role="execution"))
assert "l0_dashboard" in result
```

### 5.3 activate_workbench MCP tool
```python
from fpms.mcp_server import activate_workbench
result = json.loads(activate_workbench(node_id=node_id, role="execution"))
assert result["goal"] is not None
assert "subtasks" in result
```

---

## 6. 回归验收

### 6.1 全量测试通过
```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v
# 预期：584 existing tests + 新 tests 全绿
```

### 6.2 现有 MCP tools 不受影响
```python
# 不传 role/category 的调用行为完全不变
result = engine.execute_tool("append_log", {"node_id": id, "content": "test"})
assert result.success is True

bundle = engine.get_context_bundle(user_focus=id)
# 和 v0.2 行为完全一致
```

---

## 通过标准

- [ ] 1.1 ~ 1.3 全通过（narrative category）
- [ ] 2.1 ~ 2.6 全通过（角色化上下文）
- [ ] 3.1 ~ 3.3 全通过（token budget）
- [ ] 4.1 ~ 4.5 全通过（工作台）
- [ ] 5.1 ~ 5.3 全通过（MCP tools）
- [ ] 6.1 ~ 6.2 全通过（回归）
- [ ] 发布 v0.3.0 到 PyPI
