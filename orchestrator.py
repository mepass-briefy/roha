"""
하네스 오케스트레이터 스켈레톤 (A 경로, 파일 기반 SSOT)

검증 목표:
  1) 오케스트레이터가 status를 읽고 다음 노드를 고른다
  2) 사람 게이트(in_review -> confirmed)가 흐름을 진행시킨다
  3) 재실행 + No Impact: 상위 재확정 시 하위 stale, 동일 산출이면 validation 전진으로 닫힌다

설계 대응(DDL v2):
  records(head) / record_versions(immutable) / record_validations / runs / events
  provenance(derived_from, 불변)와 validation(가변)을 분리한다.
  No Impact는 새 버전을 만들지 않고 validation만 전진시키고 rerun_no_impact 이벤트를 남긴다.
"""

import json
import hashlib
import time
import os
from pathlib import Path


def canonical_hash(body: dict) -> str:
    """canonical serialization 기반 body 해시. 키 정렬 + 공백 제거."""
    s = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


class Store:
    """파일 기반 SSOT. DB 테이블을 파일/JSONL로 흉내 낸다."""

    def __init__(self, root: str, project_pk: int):
        self.root = Path(root)
        self.project_pk = project_pk
        self.pdir = self.root / "projects" / str(project_pk)
        (self.pdir / "records").mkdir(parents=True, exist_ok=True)
        (self.pdir / "versions").mkdir(parents=True, exist_ok=True)
        (self.pdir / "runs").mkdir(parents=True, exist_ok=True)
        self.events_path = self.pdir / "events.jsonl"
        self.validations_path = self.pdir / "validations.json"
        self.seq_path = self.pdir / "_seq.json"
        if not self.validations_path.exists():
            self._write_json(self.validations_path, [])
        if not self.seq_path.exists():
            self._write_json(self.seq_path, {"seq": 1000})
        if not self.events_path.exists():
            self.events_path.write_text("")

    # ---- 저수준 ----
    def _write_json(self, path: Path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))

    def _read_json(self, path: Path):
        return json.loads(path.read_text())

    def next_pk(self) -> int:
        s = self._read_json(self.seq_path)
        s["seq"] += 1
        self._write_json(self.seq_path, s)
        return s["seq"]

    # ---- head (records) ----
    def head(self, rtype: str):
        p = self.pdir / "records" / f"{rtype}.json"
        return self._read_json(p) if p.exists() else None

    def save_head(self, head: dict):
        self._write_json(self.pdir / "records" / f"{head['type']}.json", head)

    # ---- versions (immutable) ----
    def version(self, rtype: str, v: int):
        p = self.pdir / "versions" / f"{rtype}.v{v}.json"
        return self._read_json(p) if p.exists() else None

    def append_version(self, ver: dict):
        p = self.pdir / "versions" / f"{ver['type']}.v{ver['version']}.json"
        if p.exists():
            raise RuntimeError("immutable violation: version already exists")
        self._write_json(p, ver)

    # ---- validations ----
    def validations(self):
        return self._read_json(self.validations_path)

    def save_validations(self, rows):
        self._write_json(self.validations_path, rows)

    # ---- runs ----
    def save_run(self, run: dict):
        self._write_json(self.pdir / "runs" / f"{run['pk']}.json", run)

    # ---- events (append-only) ----
    def emit(self, event_type, subject_type, subject_pk, payload, actor="system",
             record_pk=None, record_version=None, run_pk=None):
        ev = {
            "pk": self.next_pk(),
            "project_pk": self.project_pk,
            "event_type": event_type,
            "subject_type": subject_type,
            "subject_pk": subject_pk,
            "record_pk": record_pk,
            "record_version": record_version,
            "run_pk": run_pk,
            "payload": payload,
            "actor": actor,
            "ts": round(time.time(), 3),
        }
        with self.events_path.open("a") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def events(self):
        if not self.events_path.read_text().strip():
            return []
        return [json.loads(l) for l in self.events_path.read_text().splitlines() if l.strip()]


class Orchestrator:
    def __init__(self, store: Store, workflow: dict, producers: dict):
        self.s = store
        self.wf = workflow
        self.producers = producers
        self.nodes = {n["produces"]: n for n in workflow["nodes"]}

    # ---- 헬퍼 ----
    def _parents(self, rtype):
        node = self.nodes[rtype]
        dep_node_ids = node["depends_on"]
        return [n["produces"] for n in self.wf["nodes"] if n["node_id"] in dep_node_ids]

    def _deps_confirmed(self, rtype):
        for ptype in self._parents(rtype):
            h = self.s.head(ptype)
            if not h or h["status"] != "confirmed":
                return False
        return True

    def _input_signature(self, rtype):
        sig = []
        for ptype in self._parents(rtype):
            h = self.s.head(ptype)
            sig.append({"type": ptype, "pk": h["pk"], "version": h["current_version"],
                        "version_pk": h["current_version_pk"]})
        return sorted(sig, key=lambda x: x["type"])

    def node_state(self, rtype):
        node = self.nodes[rtype]
        head = self.s.head(rtype)
        if not self._deps_confirmed(rtype):
            return "BLOCKED"
        if head and head["status"] == "in_review":
            return "NEEDS_REVIEW"
        if head and head["status"] == "stale":
            return "STALE"
        if head and head["status"] == "rejected":
            return "REJECTED"
        if head and head["status"] == "confirmed":
            # DONE 강화: 입력이 모두 confirmed이고 stale 없음 + 시그니처 일치 검증
            if self._is_validated(rtype):
                return "DONE"
            return "STALE"
        return "READY"

    def _is_validated(self, rtype):
        """현재 버전이 모든 부모의 현재 confirmed 버전까지 검증됐는가."""
        head = self.s.head(rtype)
        if not head or head["current_version_pk"] is None:
            return False
        vrows = [r for r in self.s.validations() if r["record_version_pk"] == head["current_version_pk"]]
        for ptype in self._parents(rtype):
            ph = self.s.head(ptype)
            row = next((r for r in vrows if r["parent_record_pk"] == ph["pk"]), None)
            if row is None or row["parent_version_validated"] < ph["current_version"]:
                return False
        return True

    # ---- Run 실행 ----
    def run_node(self, rtype, actor="system"):
        node = self.nodes[rtype]
        sig = self._input_signature(rtype)
        run_pk = self.s.next_pk()
        run = {"pk": run_pk, "project_pk": self.s.project_pk, "node_id": node["node_id"],
               "produces_type": rtype, "workflow_ver": self.wf["version"],
               "input_refs": sig, "run_status": "running", "attempt": 1,
               "model_id": "mock-deterministic-1", "agent_version": "0.1",
               "prompt_version": "1", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        self.s.save_run(run)
        self.s.emit("run_state_changed", "run", run_pk, {"from": "queued", "to": "running"}, run_pk=run_pk)

        # 입력 body 수집 후 producer 실행
        inputs = {}
        for ptype in self._parents(rtype):
            ph = self.s.head(ptype)
            inputs[ptype] = self.s.version(ptype, ph["current_version"])["body"]
        new_body = self.producers[rtype](inputs)

        run["run_status"] = "succeeded"
        self.s.save_run(run)
        self.s.emit("run_state_changed", "run", run_pk, {"from": "running", "to": "succeeded"}, run_pk=run_pk)

        return self._save_output(rtype, new_body, sig, run_pk, node)

    def _save_output(self, rtype, new_body, sig, run_pk, node):
        """정책 3.6: canonical 비교로 버전 증감 판정. 동일이면 No Impact."""
        head = self.s.head(rtype)
        new_hash = canonical_hash(new_body)
        derived = [{"parent_record_pk": x["pk"], "parent_version": x["version"],
                    "parent_version_pk": x["version_pk"]} for x in sig]

        # 기존 버전과 동일한가?
        if head and head["current_version_pk"] is not None:
            cur = self.s.version(rtype, head["current_version"])
            if cur["body_hash"] == new_hash:
                # No Impact: 새 버전 미생성, validation 전진, stale 해제
                self._advance_validations(head, sig)
                prev_status = head["status"]
                head["status"] = "confirmed"
                self.s.save_head(head)
                self.s.emit("rerun_no_impact", "record", head["pk"],
                            {"body_hash": new_hash, "advanced_to": sig, "from_status": prev_status},
                            record_pk=head["pk"], record_version=head["current_version"], run_pk=run_pk)
                self.s.emit("record_state_changed", "record", head["pk"],
                            {"from": prev_status, "to": "confirmed", "trigger": "no_impact_rerun"},
                            record_pk=head["pk"])
                return {"changed": False, "version": head["current_version"]}

        # 내용 변경: 새 불변 버전 생성
        if not head:
            head = {"pk": self.s.next_pk(), "type": rtype, "project_pk": self.s.project_pk,
                    "current_version": 0, "current_version_pk": None, "status": "draft"}
        new_v = head["current_version"] + 1
        ver_pk = self.s.next_pk()
        ver = {"pk": ver_pk, "type": rtype, "record_pk": head["pk"], "version": new_v,
               "body": new_body, "body_hash": new_hash, "derived_from": derived,
               "produced_by_run": run_pk}
        self.s.append_version(ver)
        head["current_version"] = new_v
        head["current_version_pk"] = ver_pk
        head["status"] = "confirmed" if node["gate"] == "auto" else "in_review"
        self.s.save_head(head)
        self._set_validations(ver_pk, head["pk"], sig)
        self.s.emit("record_version_created", "record", head["pk"],
                    {"version": new_v, "body_hash": new_hash, "derived_from": derived},
                    record_pk=head["pk"], record_version=new_v, run_pk=run_pk)
        self.s.emit("record_state_changed", "record", head["pk"],
                    {"from": "draft", "to": head["status"], "trigger": "run_success"},
                    record_pk=head["pk"])
        return {"changed": True, "version": new_v}

    def _set_validations(self, version_pk, record_pk, sig):
        rows = [r for r in self.s.validations() if r["record_version_pk"] != version_pk]
        for x in sig:
            rows.append({"record_version_pk": version_pk, "parent_record_pk": x["pk"],
                         "parent_version_pinned": x["version"], "parent_version_validated": x["version"]})
        self.s.save_validations(rows)

    def _advance_validations(self, head, sig):
        rows = self.s.validations()
        for r in rows:
            if r["record_version_pk"] == head["current_version_pk"]:
                match = next((x for x in sig if x["pk"] == r["parent_record_pk"]), None)
                if match:
                    r["parent_version_validated"] = match["version"]
        self.s.save_validations(rows)

    # ---- 사람 게이트 ----
    def human_confirm(self, rtype):
        head = self.s.head(rtype)
        assert head["status"] == "in_review", f"{rtype} not in_review"
        head["status"] = "confirmed"
        self.s.save_head(head)
        self.s.emit("record_state_changed", "record", head["pk"],
                    {"from": "in_review", "to": "confirmed", "trigger": "human_gate"},
                    actor="human", record_pk=head["pk"])
        self._propagate(rtype)

    # ---- 영향도 전파 (정책 4.2: confirmed + version 증가) ----
    def _propagate(self, parent_type):
        ph = self.s.head(parent_type)
        new_ver = ph["current_version"]
        # 직접 하위 탐색: validations에서 parent이고 validated < new_ver
        affected = set()
        for r in self.s.validations():
            if r["parent_record_pk"] == ph["pk"] and r["parent_version_validated"] < new_ver:
                # 그 하위의 head를 찾는다 (현재 버전인지 확인)
                for ctype, node in self.nodes.items():
                    ch = self.s.head(ctype)
                    if ch and ch["current_version_pk"] == r["record_version_pk"] and ch["status"] == "confirmed":
                        affected.add(ctype)
        for ctype in affected:
            ch = self.s.head(ctype)
            ch["status"] = "stale"
            self.s.save_head(ch)
            self.s.emit("stale_propagated", "record", ch["pk"],
                        {"parent_record_pk": ph["pk"], "parent_version": new_ver},
                        record_pk=ch["pk"])
            # on_upstream_change 처리
            policy = self.nodes[ctype]["on_upstream_change"]
            if policy == "auto_rerun":
                self.run_node(ctype)
            # manual_rerun / hold: stale 유지

    # ---- 결정 루프 ----
    def tick(self):
        """READY 노드를 찾아 실행. 한 번에 한 노드. 진행 여부 반환."""
        for n in self.wf["nodes"]:
            rtype = n["produces"]
            if self.node_state(rtype) == "READY":
                self.run_node(rtype)
                return rtype
        return None

    def status_snapshot(self):
        out = {}
        for n in self.wf["nodes"]:
            rtype = n["produces"]
            h = self.s.head(rtype)
            out[rtype] = {"state": self.node_state(rtype),
                          "status": h["status"] if h else None,
                          "version": h["current_version"] if h else None}
        return out
