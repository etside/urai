#!/usr/bin/env python3
"""Brand map: public Urai model identities (stdlib only).

Users only ever see Urai brands. Internal teacher/backend names
(qwen3-4b, llama-local, jev-local-student) stay in traces and metadata —
never as the primary model id. Laya is the upcoming Urai-owned student
(imatrix + LoRA lineage); its slot is wired before the weights land.
"""
BRANDS = {
    "urai": {"tier": "urai", "desc": "Balanced Urai — everyday default",
             "internal": ["jev-local-student", "local-student", "llama-local",
                          "qwen3-4b", "qwen3-17b", "local"]},
    "urai-fast": {"tier": "urai-fast", "desc": "Fast Urai — short answers",
                  "internal": []},
    "urai-ultra": {"tier": "urai-ultra", "desc": "Quality Urai — verified depth",
                   "internal": []},
    "urai-cyber": {"tier": "urai-cyber", "desc": "Security Urai — hardened review",
                   "internal": []},
    "laya": {"tier": "urai-ultra", "desc": "Laya — Urai-owned student (landing soon)",
             "internal": ["laya"], "student": True},
}


def brand_id(internal: str) -> str:
    name = (internal or "").lower()
    for bid, b in BRANDS.items():
        if name == bid or name in [i.lower() for i in b.get("internal", [])]:
            return bid
    if "qwen" in name or "llama" in name or "local" in name or "student" in name:
        return "urai"
    return internal or "urai"


def tier_of_brand(model: str) -> str:
    m = (model or "").lower()
    if m in BRANDS and m != "laya":
        return BRANDS[m]["tier"]
    if m == "laya":
        return "urai-ultra"
    return "urai"


def brand_list(available: bool = True) -> list:
    return [{"id": bid, "owned_by": "Urai", "available": available,
             "tier": b["tier"], "description": b["desc"]}
            for bid, b in BRANDS.items()]
