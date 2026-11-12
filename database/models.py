
DECISION_CONFIRMED = "confirmed"
DECISION_CORRECTED = "corrected"
DECISION_REJECTED = "rejected"
DECISION_ADDITIONAL = "additional_review"
FINAL_DECISIONS = {DECISION_CONFIRMED, DECISION_CORRECTED, DECISION_REJECTED}
ALL_DECISIONS = FINAL_DECISIONS | {DECISION_ADDITIONAL}

DECISION_LABELS = {
    DECISION_CONFIRMED: "Confirmada",
    DECISION_CORRECTED: "Corrigida e confirmada",
    DECISION_REJECTED: "Rejeitada",
    DECISION_ADDITIONAL: "Análise adicional solicitada",
}

OCCURRENCE_TYPES = [
    "Acidente / colisão",
    "Veículo parado na via",
    "Veículo em chamas",
    "Capotamento",
    "Objeto na pista",
    "Dano no pavimento",
    "Outra ocorrência",
]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS analyses (
    id               TEXT PRIMARY KEY,
    image_name       TEXT NOT NULL,
    stored_name      TEXT NOT NULL,
    processed_name   TEXT,
    source           TEXT,
    created_at       TEXT NOT NULL,
    result           TEXT NOT NULL CHECK (result IN ('possible','none','inconclusive')),
    situation_type   TEXT NOT NULL,
    evidence_level   TEXT NOT NULL,
    confidence       REAL,
    detections_json  TEXT NOT NULL,
    detection_count  INTEGER NOT NULL,
    classes_json     TEXT NOT NULL,
    reasons_json     TEXT NOT NULL,
    quality_json     TEXT NOT NULL,
    image_width      INTEGER,
    image_height     INTEGER,
    inference_ms     REAL NOT NULL,
    total_ms         REAL NOT NULL,
    notify           INTEGER NOT NULL,
    requires_review  INTEGER NOT NULL,
    model_name       TEXT NOT NULL,
    model_mode       TEXT NOT NULL,
    rules_version    TEXT,
    triage_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at);
CREATE INDEX IF NOT EXISTS idx_analyses_result  ON analyses(result);

CREATE TABLE IF NOT EXISTS human_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id),
    decision        TEXT NOT NULL CHECK (decision IN ('confirmed','corrected','rejected','additional_review')),
    corrected_type  TEXT,
    operator        TEXT,
    notes           TEXT,
    decided_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_analysis ON human_decisions(analysis_id);

CREATE TABLE IF NOT EXISTS definitive_occurrences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id     TEXT NOT NULL UNIQUE REFERENCES analyses(id),
    decision_id     INTEGER NOT NULL REFERENCES human_decisions(id),
    final_type      TEXT NOT NULL,
    operator        TEXT,
    confirmed_at    TEXT NOT NULL,
    evidence_image  TEXT,
    model_name      TEXT
);
"""


CREATE_DISPATCH = """
CREATE TABLE IF NOT EXISTS dispatch_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL REFERENCES analyses(id),
    status      TEXT NOT NULL,
    operator    TEXT,
    created_at  TEXT NOT NULL
);
"""

DISPATCH_STEPS = ["acionada", "a_caminho", "no_local", "concluida"]
DISPATCH_LABELS = {
    "acionada": "Equipe acionada",
    "a_caminho": "Equipe a caminho",
    "no_local": "Equipe no local",
    "concluida": "Atendimento concluído",
}
