"""设施档案业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "archive"
REQUIRED_FIELDS = ["档案编号", "关联设施", "档案类型"]
STATUS_ORDER = ["待归档", "已归档", "待补充", "已作废"]
# 归档结论只许这样落：提交/确认归档都进已归档，待补充只留给资料不全被退回的，作废单独一路。
ACTION_RULES = {"提交归档": "已归档", "确认归档": "已归档", "退回补充": "待补充", "作废档案": "已作废"}
NEGATIVE_ACTIONS = ["作废档案"]
FINAL_STATUSES = ["已归档", "已作废"]
ARCHIVE_ACTIONS = ["提交归档", "确认归档"]


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
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["档案状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 建档归属随登记一并记下，后续提交归档、作废都按这个口径控权。
        entry["建档人"] = str(values.get("建档人") or "").strip()
        entry["班组"] = str(values.get("班组") or "").strip()
        entry["经手人"] = entry["建档人"]
        entry["经手时间"] = datetime.now().strftime("%Y-%m-%d %H:%M")
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
        # 只有建档人与本班组能改动档案，其他岗位只读；越权时讲清哪一头对不上。
        owner = str(entry.get("建档人") or "")
        owner_team = str(entry.get("班组") or "")
        is_owner = bool(operator) and operator == owner
        same_team = bool(team) and team == owner_team
        if not (is_owner or same_team):
            denied = []
            if not is_owner:
                denied.append(f"操作人「{operator or '未登记'}」不是建档人「{owner}」")
            if not same_team:
                denied.append(f"所在班组「{team or '未登记'}」与建档班组「{owner_team}」不一致")
            return None, f"{'；'.join(denied)}，只有建档人与本班组能{action}，其他岗位只读"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 重复提交以最后一次为准：状态、台账字段与经手人一起刷成最新这一笔。
        entry["status"] = target
        entry["档案状态"] = target
        entry["pending"] = target not in FINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["经手人"] = operator
        entry["经手时间"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if action in ARCHIVE_ACTIONS:
            entry["归档人员"] = operator
            entry["归档日期"] = date.today().isoformat()
        return entry, f"档案记录已{action}，经手人{operator}"
