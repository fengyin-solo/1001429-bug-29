"""设施档案业务规则：状态流转、归属权限与字段校验都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "archive"
REQUIRED_FIELDS = ["档案编号", "关联设施", "档案类型"]
# 归档必备材料：缺了只能落待补充，补齐之后才能归档
MATERIAL_FIELDS = ["资料名称", "存放位置"]
STATUS_ORDER = ["待归档", "已归档", "待补充", "已作废"]
ACTION_RULES = {"提交归档": "已归档", "确认归档": "已归档", "作废档案": "已作废"}
DONE_LABELS = {"提交归档": "提交归档", "确认归档": "确认归档", "作废档案": "作废"}
NEGATIVE_ACTIONS = ["作废档案"]
# 提交里的控制字段与内部字段，不当作档案字段落库
CONTROL_FIELDS = {"action", "操作人", "班组"}
INTERNAL_FIELDS = {"id", "status", "pending", "abnormal", "建档人", "建档班组"}


class ArchiveService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("档案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field, value in values.items():
            if field in CONTROL_FIELDS or field in INTERNAL_FIELDS:
                continue
            entry[field] = value
        for field in REQUIRED_FIELDS:
            entry[field] = values.get(field)
        entry["建档人"] = str(values.get("操作人") or "").strip() or "未登记"
        entry["建档班组"] = str(values.get("班组") or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["档案状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str = "",
        team: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"档案记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于设施档案可执行范围"
        operator = str(operator or "").strip()
        team = str(team or "").strip()
        owner = str(entry.get("建档人") or "").strip()
        owner_team = str(entry.get("建档班组") or "").strip()
        allowed = bool(operator) and (operator == owner or bool(team) and team == owner_team)
        if not allowed:
            return None, (
                f"「{action}」仅建档人{owner or '未登记'}或{owner_team or '所属'}班组成员可提交，"
                f"当前操作人{operator or '未登记'}（{team or '未登记班组'}）不在归属范围，只能查看"
            )
        target = ACTION_RULES[action]
        lacking: list[str] = []
        if target == "已归档":
            lacking = [field for field in MATERIAL_FIELDS if not str(entry.get(field) or "").strip()]
            if lacking:
                target = "待补充"
        entry["status"] = target
        entry["档案状态"] = target
        # 重复提交以最后一次为准，经手人记当前操作人
        entry["归档人员"] = operator
        if target == "已归档":
            entry["归档日期"] = date.today().isoformat()
        entry["pending"] = target in ("待归档", "待补充")
        entry["abnormal"] = target == "待补充" or action in NEGATIVE_ACTIONS
        if lacking:
            return entry, f"资料不全（缺{'、'.join(lacking)}），档案记录落为待补充，补齐后可再次{action}"
        return entry, f"档案记录已{DONE_LABELS[action]}"
