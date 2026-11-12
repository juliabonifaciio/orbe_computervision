from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import current_app, g

from .models import (ALL_DECISIONS, DECISION_ADDITIONAL, DECISION_CONFIRMED, DECISION_CORRECTED,
                     DECISION_REJECTED, FINAL_DECISIONS, SCHEMA, CREATE_DISPATCH, DISPATCH_STEPS)


class DecisionError(Exception):
    def __init__(self, message: str, code: str = "invalid_decision"):
        super().__init__(message)
        self.message, self.code = message, code


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executescript(CREATE_DISPATCH)
        cols = [r[1] for r in con.execute("PRAGMA table_info(analyses)").fetchall()]
        if "triage_json" not in cols:
            con.execute("ALTER TABLE analyses ADD COLUMN triage_json TEXT")
        con.commit()
    finally:
        con.close()


def init_app(app) -> None:
    init_db(app.config["DATABASE_PATH"])
    app.teardown_appcontext(close_db)


def insert_analysis(a: dict) -> None:
    db = get_db()
    db.execute(
        """INSERT INTO analyses (id,image_name,stored_name,processed_name,source,created_at,result,
           situation_type,evidence_level,confidence,detections_json,detection_count,classes_json,
           reasons_json,quality_json,image_width,image_height,inference_ms,total_ms,notify,
           requires_review,model_name,model_mode,rules_version,triage_json)
           VALUES (:id,:image_name,:stored_name,:processed_name,:source,:created_at,:result,
           :situation_type,:evidence_level,:confidence,:detections_json,:detection_count,:classes_json,
           :reasons_json,:quality_json,:image_width,:image_height,:inference_ms,:total_ms,:notify,
           :requires_review,:model_name,:model_mode,:rules_version,:triage_json)""", a)
    db.commit()


_STATUS_SQL = """
    (SELECT decision FROM human_decisions d WHERE d.analysis_id = a.id ORDER BY d.id DESC LIMIT 1)
"""


_OP_SQL = """
    (SELECT operator FROM human_decisions d WHERE d.analysis_id = a.id ORDER BY d.id DESC LIMIT 1)
"""


_DISP_SQL = """
    (SELECT status FROM dispatch_events e WHERE e.analysis_id = a.id ORDER BY e.id DESC LIMIT 1)
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["detections"] = json.loads(d.pop("detections_json"))
    d["classes"] = json.loads(d.pop("classes_json"))
    d["reasons"] = json.loads(d.pop("reasons_json"))
    d["quality"] = json.loads(d.pop("quality_json"))
    tj = d.pop("triage_json", None)
    d["triage"] = json.loads(tj) if tj else None
    d["notify"] = bool(d["notify"])
    d["requires_review"] = bool(d["requires_review"])
    d["human_status"] = d.pop("human_status", None)
    d["operator"] = d.pop("operator", None)
    d["dispatch_status"] = d.pop("dispatch_status", None)
    d["validation_status"] = validation_status(d)
    return d


def validation_status(a: dict) -> str:
    hs = a.get("human_status")
    if hs in FINAL_DECISIONS:
        return hs
    if hs == DECISION_ADDITIONAL:
        return DECISION_ADDITIONAL
    return "pending" if a.get("requires_review") else "not_required"


def get_analysis(analysis_id: str) -> dict | None:
    row = get_db().execute(
        f"SELECT a.*, {_STATUS_SQL} AS human_status, {_OP_SQL} AS operator, {_DISP_SQL} AS dispatch_status FROM analyses a WHERE a.id = ?", (analysis_id,)).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    d["decisions"] = list_decisions(analysis_id)
    d["definitive"] = get_definitive(analysis_id)
    d["dispatch"] = list_dispatch(analysis_id)
    d["dispatch_status"] = d["dispatch"][-1]["status"] if d["dispatch"] else None
    return d


def list_analyses(*, result: str | None = None, status: str | None = None, date_from: str | None = None,
                  date_to: str | None = None, q: str | None = None, review_only: bool = False,
                  limit: int = 200, offset: int = 0) -> list[dict]:
    where, params = [], []
    if result:
        where.append("a.result = ?"); params.append(result)
    if date_from:
        where.append("a.created_at >= ?"); params.append(date_from)
    if date_to:
        where.append("a.created_at <= ?"); params.append(date_to + "T23:59:59.999Z")
    if q:
        like = f"%{q}%"
        where.append("(a.image_name LIKE ? OR a.id LIKE ? OR a.source LIKE ?)"); params += [like] * 3
    sql = f"SELECT a.*, {_STATUS_SQL} AS human_status, {_OP_SQL} AS operator, {_DISP_SQL} AS dispatch_status FROM analyses a"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.created_at DESC"
    rows = [_row_to_dict(r) for r in get_db().execute(sql, params).fetchall()]
    if review_only:
        rows = [r for r in rows if r["validation_status"] in ("pending", DECISION_ADDITIONAL)]
        rank = {"alta": 0, "media": 1, "verificar": 2, "sem_acionamento": 3}
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        rows.sort(key=lambda r: rank.get((r.get("triage") or {}).get("priority"), 3))
    if status:
        rows = [r for r in rows if r["validation_status"] == status]
    return rows[offset: offset + limit]


def list_decisions(analysis_id: str) -> list[dict]:
    rows = get_db().execute(
        "SELECT * FROM human_decisions WHERE analysis_id = ? ORDER BY id", (analysis_id,)).fetchall()
    return [dict(r) for r in rows]


def list_dispatch(analysis_id):
    rows = get_db().execute(
        "SELECT * FROM dispatch_events WHERE analysis_id = ? ORDER BY id", (analysis_id,)).fetchall()
    return [dict(r) for r in rows]


def add_dispatch_event(analysis_id, status, operator, now_iso):
    a = get_analysis(analysis_id)
    if a is None:
        raise DecisionError("Análise não encontrada.", "not_found")
    if a["definitive"] is None:
        raise DecisionError("Só é possível acompanhar o atendimento de uma ocorrência confirmada.", "not_confirmed")
    if status not in DISPATCH_STEPS:
        raise DecisionError("Status de atendimento inválido.", "bad_status")
    current = a["dispatch_status"]
    expected = DISPATCH_STEPS[DISPATCH_STEPS.index(current) + 1] if current in DISPATCH_STEPS[:-1] else None
    if status != expected:
        raise DecisionError("O próximo passo do atendimento não é esse.", "bad_step")
    operator = (operator or "").strip()[:80] or None
    db = get_db()
    db.execute("INSERT INTO dispatch_events (analysis_id,status,operator,created_at) VALUES (?,?,?,?)",
               (analysis_id, status, operator, now_iso))
    db.commit()
    return get_analysis(analysis_id)


def get_definitive(analysis_id: str) -> dict | None:
    row = get_db().execute("SELECT * FROM definitive_occurrences WHERE analysis_id = ?", (analysis_id,)).fetchone()
    return dict(row) if row else None


def record_decision(analysis_id: str, decision: str, *, operator: str | None, notes: str | None,
                    corrected_type: str | None, now_iso: str) -> dict:
    if decision not in ALL_DECISIONS:
        raise DecisionError("Decisão inválida.", "bad_decision")
    a = get_analysis(analysis_id)
    if a is None:
        raise DecisionError("Análise não encontrada.", "not_found")
    if not a["requires_review"]:
        raise DecisionError("Esta análise não exige validação humana.", "not_reviewable")
    if a["validation_status"] in FINAL_DECISIONS:
        raise DecisionError("Esta análise já possui decisão final e não pode ser alterada.", "already_final")

    operator = (operator or "").strip()[:80] or None
    notes = (notes or "").strip()[:1000] or None
    corrected_type = (corrected_type or "").strip()[:80] or None
    if decision in (DECISION_CONFIRMED, DECISION_CORRECTED) and not operator:
        raise DecisionError("Informe o responsável pela validação para confirmar a ocorrência.", "operator_required")
    if decision == DECISION_CORRECTED and not corrected_type:
        raise DecisionError("Informe o tipo corrigido da ocorrência.", "type_required")
    if decision == DECISION_CONFIRMED and corrected_type and corrected_type != a["situation_type"]:
        decision = DECISION_CORRECTED

    db = get_db()
    cur = db.execute(
        "INSERT INTO human_decisions (analysis_id,decision,corrected_type,operator,notes,decided_at) "
        "VALUES (?,?,?,?,?,?)", (analysis_id, decision, corrected_type, operator, notes, now_iso))
    decision_id = cur.lastrowid
    if decision in (DECISION_CONFIRMED, DECISION_CORRECTED):
        final_type = corrected_type if decision == DECISION_CORRECTED else a["situation_type"]
        db.execute(
            "INSERT INTO definitive_occurrences (analysis_id,decision_id,final_type,operator,confirmed_at,"
            "evidence_image,model_name) VALUES (?,?,?,?,?,?,?)",
            (analysis_id, decision_id, final_type, operator, now_iso, a["processed_name"], a["model_name"]))
        db.execute("INSERT INTO dispatch_events (analysis_id,status,operator,created_at) VALUES (?,?,?,?)",
                   (analysis_id, "acionada", operator, now_iso))
    db.commit()
    return get_analysis(analysis_id)


def dashboard_stats() -> dict:
    rows = list_analyses(limit=100000)
    total = len(rows)
    return {
        "total": total,
        "possible": sum(r["result"] == "possible" for r in rows),
        "none": sum(r["result"] == "none" for r in rows),
        "inconclusive": sum(r["result"] == "inconclusive" for r in rows),
        "awaiting": sum(r["validation_status"] in ("pending", DECISION_ADDITIONAL) for r in rows),
        "confirmed": sum(r["validation_status"] in (DECISION_CONFIRMED, DECISION_CORRECTED) for r in rows),
        "rejected": sum(r["validation_status"] == DECISION_REJECTED for r in rows),
        "high_priority": sum(r["validation_status"] in ("pending", DECISION_ADDITIONAL)
                             and (r.get("triage") or {}).get("priority") == "alta" for r in rows),
        "active_dispatch": sum(r["dispatch_status"] in ("acionada", "a_caminho", "no_local") for r in rows),
        "avg_inference_ms": round(sum(r["inference_ms"] for r in rows) / total, 1) if total else None,
    }
