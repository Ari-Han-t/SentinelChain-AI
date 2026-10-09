import pytest


def _headers(auth, role):
    return auth(role)


def _default_chain(client, headers):
    chains = client.get("/supply-chains", headers=headers).json()["chains"]
    return next(chain for chain in chains if chain["key"] == "sentinel-industrial-demo")


def test_permissions_matrix_matches_role(client, auth):
    expected = {
        "admin": {"chain.manage", "node.manage", "action.decide", "node.verify", "audit.read"},
        "analyst": {"evidence.submit", "forecast.manage"},
        "manager": {"action.decide", "action.escalate"},
        "auditor": {"node.verify", "audit.read"},
    }
    forbidden = {
        "analyst": {"chain.manage", "node.manage", "action.decide", "node.verify", "audit.read"},
        "manager": {"chain.manage", "node.manage", "node.verify", "audit.read"},
        "auditor": {"chain.manage", "node.manage", "evidence.submit", "action.decide"},
    }
    for role, wanted in expected.items():
        payload = client.get("/auth/permissions", headers=_headers(auth, role)).json()
        assert wanted <= set(payload["permissions"]), role
    for role, banned in forbidden.items():
        payload = client.get("/auth/permissions", headers=_headers(auth, role)).json()
        assert banned.isdisjoint(payload["permissions"]), role
    assert client.get("/auth/permissions").status_code == 401


def test_chain_crud_is_admin_only(client, auth):
    headers = auth("admin")
    for role in ("analyst", "manager", "auditor"):
        assert client.post("/supply-chains", json={"key": "nope-chain", "name": "Nope"}, headers=auth(role)).status_code == 403

    created = client.post("/supply-chains", json={"key": "east-line", "name": "East assembly line", "description": "Secondary chain"}, headers=headers)
    assert created.status_code == 201
    chain_id = created.json()["id"]

    duplicate = client.post("/supply-chains", json={"key": "east-line", "name": "Duplicate"}, headers=headers)
    assert duplicate.status_code == 409

    renamed = client.put(f"/supply-chains/{chain_id}", json={"name": "East assembly line A"}, headers=headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "East assembly line A"

    assert client.put(f"/supply-chains/{chain_id}", json={"name": "East A"}, headers=auth("analyst")).status_code == 403

    archived = client.post(f"/supply-chains/{chain_id}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.post(f"/supply-chains/{chain_id}/archive", headers=headers).status_code == 409
    # Archived chains reject node edits until restored.
    blocked = client.post(f"/supply-chains/{chain_id}/nodes", json={"key": "staging", "name": "Staging"}, headers=headers)
    assert blocked.status_code == 409
    assert client.post(f"/supply-chains/{chain_id}/restore", headers=headers).json()["status"] == "active"
    assert client.post(f"/supply-chains/{chain_id}/nodes", json={"key": "staging", "name": "Staging"}, headers=headers).status_code == 201

    chain_list = client.get("/supply-chains", headers=headers).json()["chains"]
    assert {chain["key"] for chain in chain_list} >= {"sentinel-industrial-demo", "east-line"}
    demo = next(chain for chain in chain_list if chain["key"] == "sentinel-industrial-demo")
    assert demo["node_count"] == 6
    assert demo["worst_status"] in {"at_risk", "critical", "disputed"}


def test_node_crud_validates_and_is_admin_only(client, auth):
    headers = auth("admin")
    chain_id = _default_chain(client, headers)["id"]

    for role in ("analyst", "manager", "auditor"):
        attempt = client.post(
            f"/supply-chains/{chain_id}/nodes",
            json={"key": f"rogue-{role}", "name": "Rogue node"},
            headers=auth(role),
        )
        assert attempt.status_code == 403

    created = client.post(
        f"/supply-chains/{chain_id}/nodes",
        json={"key": "quality-gate", "name": "Quality gate", "stage_type": "quality", "owner_role": "procurement_manager"},
        headers=headers,
    )
    assert created.status_code == 201
    node = created.json()
    assert node["position"]["x"] == 1560.0  # auto-positioned after the six seeded nodes

    duplicate = client.post(
        f"/supply-chains/{chain_id}/nodes",
        json={"key": "quality-gate", "name": "Duplicate"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    bad_role = client.post(
        f"/supply-chains/{chain_id}/nodes",
        json={"key": "bad-role", "name": "Bad role", "owner_role": "superuser"},
        headers=headers,
    )
    assert bad_role.status_code == 422

    bad_key = client.post(
        f"/supply-chains/{chain_id}/nodes",
        json={"key": "Bad Key!", "name": "Bad key"},
        headers=headers,
    )
    assert bad_key.status_code == 422

    updated = client.put(
        f"/nodes/{node['id']}",
        json={"name": "Quality gate 2", "position_x": 40, "position_y": 60},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Quality gate 2"
    assert updated.json()["position"] == {"x": 40.0, "y": 60.0}
    assert client.put(f"/nodes/{node['id']}", json={"name": "Nope"}, headers=auth("analyst")).status_code == 403


def test_node_keys_are_scoped_per_chain(client, auth):
    headers = auth("admin")
    second = client.post("/supply-chains", json={"key": "spare-parts", "name": "Spare parts chain"}, headers=headers).json()
    # "supplier" already exists in the demo chain; the same key is legal in another chain.
    created = client.post(
        f"/supply-chains/{second['id']}/nodes",
        json={"key": "supplier", "name": "Spare supplier", "stage_type": "supplier"},
        headers=headers,
    )
    assert created.status_code == 201

    demo_graph = client.get(f"/supply-chains/{_default_chain(client, headers)['id']}", headers=headers).json()
    spare_graph = client.get(f"/supply-chains/{second['id']}", headers=headers).json()
    assert len(demo_graph["nodes"]) == 6
    assert [node["name"] for node in spare_graph["nodes"]] == ["Spare supplier"]
    assert demo_graph["chain"]["key"] == "sentinel-industrial-demo"
    assert spare_graph["chain"]["node_count"] == 1


def test_soft_deactivate_hides_node_and_keeps_history(client, auth):
    headers = auth("admin")
    graph = client.get("/supply-chain", headers=headers).json()
    production = next(node for node in graph["nodes"] if node["key"] == "production")
    original_edge_count = len(graph["edges"])

    assert client.delete(f"/nodes/{production['id']}", headers=headers).status_code == 200
    assert client.delete(f"/nodes/{production['id']}", headers=headers).status_code == 409

    after = client.get("/supply-chain", headers=headers).json()
    assert production["id"] not in [node["id"] for node in after["nodes"]]
    # Both incident edges (procurement->production, production->logistics) are hidden.
    assert len(after["edges"]) == original_edge_count - 2
    assert client.get(f"/nodes/{production['id']}/inspector", headers=headers).status_code == 404
    assert client.post(
        f"/nodes/{production['id']}/manual-events",
        json={"event_type": "production.update", "summary": "Should be rejected"},
        headers=auth("analyst"),
    ).status_code == 404

    assert client.post(f"/nodes/{production['id']}/activate", headers=headers).status_code == 200
    restored = client.get("/supply-chain", headers=headers).json()
    assert len(restored["nodes"]) == 6
    assert len(restored["edges"]) == original_edge_count


def test_edge_crud_validates_endpoints(client, auth):
    headers = auth("admin")
    chain_id = _default_chain(client, headers)["id"]
    graph = client.get(f"/supply-chains/{chain_id}", headers=headers).json()
    demand = next(node for node in graph["nodes"] if node["key"] == "demand")
    customer = next(node for node in graph["nodes"] if node["key"] == "customer")

    assert client.post(
        f"/supply-chains/{chain_id}/edges",
        json={"source_node_id": demand["id"], "target_node_id": customer["id"], "label": "direct forecast"},
        headers=auth("analyst"),
    ).status_code == 403

    created = client.post(
        f"/supply-chains/{chain_id}/edges",
        json={"source_node_id": demand["id"], "target_node_id": customer["id"], "label": "direct forecast"},
        headers=headers,
    )
    assert created.status_code == 201
    edge_id = created.json()["id"]

    assert client.post(
        f"/supply-chains/{chain_id}/edges",
        json={"source_node_id": demand["id"], "target_node_id": customer["id"], "label": "again"},
        headers=headers,
    ).status_code == 409
    assert client.post(
        f"/supply-chains/{chain_id}/edges",
        json={"source_node_id": demand["id"], "target_node_id": demand["id"], "label": "loop"},
        headers=headers,
    ).status_code == 422

    assert client.put(f"/edges/{edge_id}", json={"label": "priority forecast"}, headers=headers).status_code == 200
    assert client.delete(f"/edges/{edge_id}", headers=headers).status_code == 200
    assert client.delete(f"/edges/{edge_id}", headers=headers).status_code == 404
    assert client.delete(f"/edges/{edge_id}", headers=auth("manager")).status_code == 403

    second = client.post("/supply-chains", json={"key": "other-chain", "name": "Other chain"}, headers=headers).json()
    outsider = client.post(
        f"/supply-chains/{second['id']}/nodes",
        json={"key": "solo", "name": "Solo node"},
        headers=headers,
    ).json()
    assert client.post(
        f"/supply-chains/{second['id']}/edges",
        json={"source_node_id": demand["id"], "target_node_id": outsider["id"], "label": "cross"},
        headers=headers,
    ).status_code == 422


def test_edge_reconnect_rewires_endpoints(client, auth):
    headers = auth("admin")
    chain_id = _default_chain(client, headers)["id"]
    graph = client.get(f"/supply-chains/{chain_id}", headers=headers).json()
    edge = graph["edges"][0]
    other = graph["edges"][1]
    assert (edge["source"], edge["target"]) != (other["source"], other["target"])

    assert client.put(f"/edges/{edge['id']}", json={}, headers=auth("manager")).status_code == 403

    # Rewire the target without touching the label.
    rewired = client.put(f"/edges/{edge['id']}", json={"target_node_id": other["target"]}, headers=headers)
    assert rewired.status_code == 200
    assert rewired.json()["source"] == edge["source"]
    assert rewired.json()["target"] == other["target"]
    assert rewired.json()["label"] == edge["label"]

    # A label-only update keeps both endpoints.
    relabelled = client.put(f"/edges/{edge['id']}", json={"label": "rerouted"}, headers=headers)
    assert relabelled.status_code == 200
    assert relabelled.json()["source"] == edge["source"]
    assert relabelled.json()["target"] == other["target"]
    assert relabelled.json()["label"] == "rerouted"

    # Self-loop, duplicate pair, and cross-chain rewires are rejected without mutating the edge.
    assert client.put(
        f"/edges/{edge['id']}", json={"source_node_id": other["target"]}, headers=headers
    ).status_code == 422
    assert client.put(
        f"/edges/{edge['id']}",
        json={"source_node_id": other["source"], "target_node_id": other["target"]},
        headers=headers,
    ).status_code == 409

    second = client.post("/supply-chains", json={"key": "reconnect-chain", "name": "Reconnect chain"}, headers=headers).json()
    outsider = client.post(
        f"/supply-chains/{second['id']}/nodes",
        json={"key": "far", "name": "Far node"},
        headers=headers,
    ).json()
    assert client.put(
        f"/edges/{edge['id']}", json={"target_node_id": outsider["id"]}, headers=headers
    ).status_code == 422

    graph = client.get(f"/supply-chains/{chain_id}", headers=headers).json()
    final_edge = next(item for item in graph["edges"] if item["id"] == edge["id"])
    assert final_edge["source"] == edge["source"]
    assert final_edge["target"] == other["target"]
    assert final_edge["label"] == "rerouted"


def test_auditor_verifies_nodes_and_evidence_voids_signoff(client, auth):
    headers = auth("admin")
    graph = client.get("/supply-chain", headers=headers).json()
    supplier = next(node for node in graph["nodes"] if node["key"] == "supplier")

    assert client.post(f"/nodes/{supplier['id']}/verify", json={"note": "checked"}, headers=auth("analyst")).status_code == 403
    assert client.post(f"/nodes/{supplier['id']}/verify", json={"note": "checked"}, headers=auth("manager")).status_code == 403

    verified = client.post(f"/nodes/{supplier['id']}/verify", json={"note": "evidence reviewed"}, headers=auth("auditor"))
    assert verified.status_code == 200
    assert verified.json()["verified_at"] is not None
    assert verified.json()["verified_by"] is not None

    inspector = client.get(f"/nodes/{supplier['id']}/inspector", headers=headers).json()
    assert inspector["node"]["verified_at"] is not None

    client.post(
        f"/nodes/{supplier['id']}/manual-events",
        json={"event_type": "supplier.update", "summary": "New supplier shipment data"},
        headers=auth("analyst"),
    )
    after = client.get(f"/nodes/{supplier['id']}/inspector", headers=headers).json()
    assert after["node"]["verified_at"] is None


def test_manager_escalates_pending_actions_only(client, auth):
    headers = auth("admin")
    graph = client.get("/supply-chain", headers=headers).json()
    supplier = next(node for node in graph["nodes"] if node["key"] == "supplier")
    client.get(f"/nodes/{supplier['id']}/inspector", headers=headers)

    pending = next(action for action in client.get("/actions", headers=headers).json() if action["status"] == "pending")
    assert client.post(f"/actions/{pending['id']}/escalate", json={"note": "supplier blocked"}, headers=auth("analyst")).status_code == 403
    assert client.post(f"/actions/{pending['id']}/escalate", json={"note": "supplier blocked"}, headers=auth("auditor")).status_code == 403

    escalated = client.post(f"/actions/{pending['id']}/escalate", json={"note": "supplier blocked"}, headers=auth("manager"))
    assert escalated.status_code == 200
    assert escalated.json()["urgency"] == "critical"

    decided = client.post(
        f"/actions/{pending['id']}/decision",
        json={"decision": "approved", "note": "ok"},
        headers=auth("manager"),
    )
    assert decided.status_code == 200
    assert client.post(f"/actions/{pending['id']}/escalate", json={"note": "too late"}, headers=auth("manager")).status_code == 409
    assert client.post("/actions/999999/escalate", json={"note": "missing"}, headers=auth("manager")).status_code == 404


def test_events_node_key_ambiguity_requires_scope(client, auth):
    headers = auth("admin")
    second = client.post("/supply-chains", json={"key": "ambig-chain", "name": "Ambiguous chain"}, headers=headers).json()
    client.post(
        f"/supply-chains/{second['id']}/nodes",
        json={"key": "logistics", "name": "Other logistics"},
        headers=headers,
    )

    ambiguous = client.post(
        "/events",
        json={"node_key": "logistics", "event_type": "shipment.status", "summary": "Ambiguous"},
        headers=auth("analyst"),
    )
    assert ambiguous.status_code == 422

    scoped = client.post(
        "/events",
        json={"node_key": "logistics", "chain_id": second["id"], "event_type": "shipment.status", "summary": "Scoped"},
        headers=auth("analyst"),
    )
    assert scoped.status_code == 200

    by_id = client.get("/supply-chain", headers=headers).json()
    demand = next(node for node in by_id["nodes"] if node["key"] == "demand")
    direct = client.post(
        "/events",
        json={"node_id": demand["id"], "event_type": "demand.signal", "summary": "Direct"},
        headers=auth("analyst"),
    )
    assert direct.status_code == 200
    assert client.post("/events", json={"event_type": "x", "summary": "no node"}, headers=auth("analyst")).status_code == 422
    assert client.post("/events", json={"node_key": "missing", "event_type": "x", "summary": "nope"}, headers=auth("analyst")).status_code == 404


def test_audit_chain_stays_valid_after_admin_mutations(client, auth):
    headers = auth("admin")
    chain = client.post("/supply-chains", json={"key": "audit-chain", "name": "Audit chain"}, headers=headers).json()
    node = client.post(
        f"/supply-chains/{chain['id']}/nodes",
        json={"key": "stage-one", "name": "Stage one"},
        headers=headers,
    ).json()
    client.put(f"/nodes/{node['id']}", json={"name": "Stage one renamed"}, headers=headers)
    client.post(f"/nodes/{node['id']}/verify", json={"note": "looks fine"}, headers=auth("auditor"))
    client.delete(f"/nodes/{node['id']}", headers=headers)
    client.post(f"/supply-chains/{chain['id']}/archive", headers=headers)

    audit = client.get("/audit", headers=headers).json()
    assert audit["valid"] is True
    types = {event["event_type"] for event in audit["events"]}
    assert {
        "supply_chain.chain_created",
        "supply_chain.node_created",
        "supply_chain.node_updated",
        "supply_chain.node_deactivated",
        "supply_chain.chain_archived",
        "node.verified",
    } <= types


def test_chain_list_and_shim_shape_for_frontend(client, auth):
    headers = auth("admin")
    listing = client.get("/supply-chains", headers=auth("auditor")).json()
    assert listing["default_chain_id"] is not None
    shim = client.get("/supply-chain", headers=auth("manager")).json()
    assert shim["chain"]["key"] == "sentinel-industrial-demo"
    assert len(shim["nodes"]) == 6
    assert all("chain_id" in node and "active" in node for node in shim["nodes"])
    assert all("source" in edge for edge in shim["edges"])
    assert shim["organization"]["configured"] is True
