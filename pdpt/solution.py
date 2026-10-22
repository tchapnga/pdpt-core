# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Solution model: routes as sequences of typed visits, plus transfer plans."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

PICKUP, DELIVERY, DROP, PICK = "pickup", "delivery", "transfer_drop", "transfer_pick"
OPS = {PICKUP, DELIVERY, DROP, PICK}


@dataclass
class Visit:
    node: str
    op: str                       # one of OPS
    request: str
    transfer_point: str | None = None   # required for DROP / PICK


@dataclass
class Route:
    vehicle: str
    visits: list[Visit] = field(default_factory=list)


@dataclass
class Solution:
    instance: str
    routes: list[Route] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"instance": self.instance, "meta": self.meta,
                "routes": [asdict(r) for r in self.routes]}

    @classmethod
    def from_dict(cls, d: dict) -> "Solution":
        routes = [Route(vehicle=r["vehicle"], visits=[Visit(**v) for v in r["visits"]])
                  for r in d["routes"]]
        return cls(instance=d["instance"], routes=routes, meta=d.get("meta", {}))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def load(cls, path: str) -> "Solution":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
