"""Simplified-Chinese wording for assistant answers. Only wording lives here: every figure comes from the same ledger calculations."""
from typing import Optional

CATEGORY = {"food": "餐饮", "transport": "交通", "housing": "住房", "utilities": "水电网络", "health": "医疗健康", "education": "教育", "shopping": "购物",
            "entertainment": "娱乐", "personal care": "个人护理", "family": "家庭", "debt": "债务", "charity": "公益捐赠", "other": "其他",
            "salary": "工资", "freelance": "自由职业", "business": "经营收入", "gift": "礼金", "interest": "利息", "other income": "其他收入"}
PERIOD = {"today": "今天", "this week": "本周", "this month": "本月", "this year": "今年", "that period": "该时段", "last month": "上个月", "last week": "上周"}
STATUS = {"ok": "正常", "warning": "预警", "over": "已超支", "paid": "已付", "due": "即将到期", "planned": "计划中", "overdue": "已逾期"}
TEXT = {
    "no_accounts": "你还没有添加任何账户，所以无法显示余额。请在“账户”中添加（含期初余额），我会持续为你更新。",
    "no_budgets": "你还没有预算。可以在“计划”中创建，或告诉我类别和限额。",
    "no_goals": "你还没有目标。可以在“计划”中添加。",
    "calc_note": "以上根据你填写的期初余额和已记录的交易计算，因此只和你的记录一样完整。",
}


def cat(c: Optional[str]) -> str:
    return CATEGORY.get(c or "", c or "")


def period(label: str) -> str:
    return PERIOD.get(label, label)
