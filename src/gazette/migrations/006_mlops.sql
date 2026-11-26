CREATE TABLE IF NOT EXISTS versions_modele (
    version TEXT PRIMARY KEY,
    run_id TEXT,
    parametres JSONB NOT NULL,
    hash_parametres TEXT NOT NULL,
    statut TEXT NOT NULL CHECK (statut IN ('candidat', 'production', 'archive', 'rejete')),
    cree_le TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promue_le TIMESTAMPTZ,
    par_qui TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_modele_production
    ON versions_modele (statut) WHERE statut = 'production';

ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_statut_check;
ALTER TABLE runs ADD CONSTRAINT runs_statut_check
    CHECK (statut IN ('en_cours', 'ok', 'echec', 'recale'));

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS version_modele TEXT,
    ADD COLUMN IF NOT EXISTS verdict TEXT CHECK (verdict IN ('valide', 'revue', 'recale')),
    ADD COLUMN IF NOT EXISTS raisons_verdict TEXT[] DEFAULT '{}';

CREATE TABLE IF NOT EXISTS relectures_echantillons (
    relecture_id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL,
    theme_numero INTEGER NOT NULL,
    pertinent BOOLEAN NOT NULL,
    commentaire TEXT,
    relu_par TEXT NOT NULL,
    relu_le TIMESTAMPTZ NOT NULL DEFAULT NOW()
);