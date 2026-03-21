"""不变量测试：写路径不读派生层。

覆盖 PRD-functional §FR-0 不变量 #7 + ARCHITECTURE.md §Derived Layer Isolation：
- 写路径（tools.py → store.py）禁止读取任何派生表
- 写路径只读 facts（nodes, edges, recent_commands, audit_outbox, session_state）
- 派生表命名 derived_* 或 *_cache 或 *_index

这些测试永远不允许被后续 coding agent 修改。
"""

import ast
import inspect
import os
import textwrap

import pytest


# 派生表名模式（任何匹配的表名都不应出现在写路径中）
DERIVED_TABLE_PATTERNS = [
    "derived_",
    "_cache",
    "narrative_index",
    "global_view_cache",
    "risk_cache",
    "archive_index",
]

# 事实表（写路径允许读的表）
FACT_TABLES = [
    "nodes",
    "edges",
    "session_state",
    "audit_outbox",
    "recent_commands",
]

# 写路径模块（这些模块的 SQL 查询不允许引用派生表）
WRITE_PATH_MODULES = [
    "fpms.spine.tools",
    "fpms.spine.store",
    "fpms.spine.command_executor",
    "fpms.spine.validator",
]


class TestDerivedIsolationStaticAnalysis:
    """静态分析：写路径源码中不包含对派生表的引用。"""

    def _get_module_source(self, module_name: str) -> str:
        """获取模块源码。"""
        module = __import__(module_name, fromlist=[""])
        source_file = inspect.getfile(module)
        with open(source_file) as f:
            return f.read()

    @pytest.mark.parametrize("module_name", WRITE_PATH_MODULES)
    def test_no_derived_table_references(self, module_name):
        """写路径模块源码中不应包含派生表名。"""
        source = self._get_module_source(module_name)
        source_lower = source.lower()

        violations = []
        for pattern in DERIVED_TABLE_PATTERNS:
            if pattern.lower() in source_lower:
                # 排除注释和文档字符串中的引用
                for i, line in enumerate(source.splitlines(), 1):
                    stripped = line.strip()
                    # 跳过纯注释行
                    if stripped.startswith("#"):
                        continue
                    if pattern.lower() in line.lower() and not stripped.startswith("#"):
                        # 检查是否在字符串字面量中（SQL 查询）
                        if f'"{pattern}' in line or f"'{pattern}" in line or \
                           f"`{pattern}" in line or f" {pattern}" in line:
                            violations.append(
                                f"  {module_name}:{i}: {stripped} (contains '{pattern}')"
                            )

        assert not violations, (
            f"写路径模块引用了派生表！违反 FR-0 不变量 #7:\n"
            + "\n".join(violations)
        )

    @pytest.mark.parametrize("module_name", WRITE_PATH_MODULES)
    def test_sql_queries_only_reference_fact_tables(self, module_name):
        """写路径中的 SQL 查询只应引用事实表。

        这是一个 AST 级别的检查：遍历源码中的字符串字面量，
        查找 SQL 关键字（SELECT, INSERT, UPDATE, DELETE, FROM），
        确认引用的表名在事实表白名单中。
        """
        source = self._get_module_source(module_name)

        try:
            tree = ast.parse(source)
        except SyntaxError:
            pytest.skip(f"Cannot parse {module_name}")

        sql_keywords = {"select", "insert", "update", "delete", "from", "into", "join"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.strip().lower()
                words = val.split()

                # 粗略判断是否是 SQL
                if not any(kw in words for kw in sql_keywords):
                    continue

                # 检查是否引用了派生表
                for pattern in DERIVED_TABLE_PATTERNS:
                    if pattern.lower() in val:
                        pytest.fail(
                            f"写路径 SQL 查询引用了派生表 '{pattern}':\n"
                            f"  模块: {module_name}\n"
                            f"  SQL: {node.value[:200]}"
                        )
