from app import profiling
from app.products import load_personas, load_products


def persona_profile(pid: str):
    per = load_personas()[pid]
    ans = {k: per[k] for k in per["known"]}
    ans.update(per["demo_answers"])
    return profiling.build_profile(pid, ans, per["name"], per)


def make_profile(**over):
    base = dict(id="c1", name="T", age=40, horizon_years=10, goal="growth", monthly_income_cny=20000,
                liquidity_need_pct=10, experience="advanced", risk_tolerance_score=50, risk_capacity_score=50,
                bucket="Balanced", investable_amount_cny=200000, goal_target_cny=400000)
    base.update(over)
    from app.schemas import ClientProfile
    return ClientProfile(**base)


PRODUCTS = load_products()
