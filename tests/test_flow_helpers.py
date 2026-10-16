"""Shared setup: a client with a complete profile and (optionally) a stored allocation."""
from app import allocation as al
from app import compliance, store
from app.products import load_personas, load_products
from tests.helpers import persona_profile


def ready_client(pid="persona_li", passed=True):
    per = load_personas()[pid]
    facts = {k: per[k] for k in per["known"]}
    facts.update(per["demo_answers"])
    cid = f"c_{pid}"
    prof = persona_profile(pid)
    prof.id = cid
    store.save_client(cid, {"name": per["name"], "facts": facts, "profile": prof.model_dump(),
                            "extra": {"investable_amount_cny": per["investable_amount_cny"],
                                      "goal_target_cny": per["goal_target_cny"]}})
    products = load_products()
    a = al.build(prof, products, preferred_ids=[] if passed else ["P13"])
    store.save_allocation(a)
    res = compliance.check(a, prof, products)
    store.set_compliance(a.id, res)
    return cid, a.id
