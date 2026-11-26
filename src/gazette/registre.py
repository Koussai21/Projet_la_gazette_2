"""Registre des versions de configuration/modèle et gestion du cycle de vie."""

import hashlib
from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

from gazette.themes import ConfigThemes


def initialiser_si_vide(
    conn: psycopg.Connection, chemin_defaut: str | Path = "config/clustering.yaml"
) -> None:
    """Enregistre v1.0.0 en production au premier démarrage si le registre est vide."""
    row = conn.execute("SELECT 1 FROM versions_modele LIMIT 1").fetchone()
    if row is not None:
        return
    brut = Path(chemin_defaut).read_text(encoding="utf-8")
    valeurs = yaml.safe_load(brut)
    empreinte = hashlib.sha256(brut.encode()).hexdigest()[:16]
    conn.execute(
        "INSERT INTO versions_modele"
        " (version, run_id, parametres, hash_parametres, statut, promue_le, par_qui)"
        " VALUES (%s, %s, %s, %s, 'production', NOW(), 'init_systeme')",
        ("v1.0.0", "init", Jsonb(valeurs), empreinte),
    )


def version_en_service(conn: psycopg.Connection) -> tuple[str, ConfigThemes]:
    """Retourne (version, ConfigThemes) actuellement marquée 'production'."""
    row = conn.execute(
        "SELECT version, parametres FROM versions_modele WHERE statut = 'production' LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("Aucune version 'production' dans versions_modele.")
    version, parametres = row
    brut = yaml.safe_dump(parametres, allow_unicode=True, sort_keys=False)
    return version, ConfigThemes(brut=brut, valeurs=parametres)


def enregistrer_candidat(
    conn: psycopg.Connection,
    version: str,
    run_id: str,
    cfg: ConfigThemes,
    par_qui: str,
    statut: str = "candidat",
) -> None:
    conn.execute(
        "INSERT INTO versions_modele"
        " (version, run_id, parametres, hash_parametres, statut, par_qui)"
        " VALUES (%s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (version) DO UPDATE SET"
        " run_id = EXCLUDED.run_id, parametres = EXCLUDED.parametres,"
        " hash_parametres = EXCLUDED.hash_parametres, statut = EXCLUDED.statut,"
        " par_qui = EXCLUDED.par_qui",
        (version, run_id, Jsonb(cfg.valeurs), cfg.empreinte, statut, par_qui),
    )


def promouvoir(conn: psycopg.Connection, version_cible: str, par_qui: str) -> None:
    """Bascule atomiquement une version en production et archive l'ancienne."""
    with conn.transaction():
        existe = conn.execute(
            "SELECT 1 FROM versions_modele WHERE version = %s", (version_cible,)
        ).fetchone()
        if existe is None:
            raise ValueError(f"Version inconnue dans le registre : {version_cible}")

        conn.execute("UPDATE versions_modele SET statut = 'archive' WHERE statut = 'production'")
        conn.execute(
            "UPDATE versions_modele"
            " SET statut = 'production', promue_le = NOW(), par_qui = %s"
            " WHERE version = %s",
            (par_qui, version_cible),
        )


def rollback(
    conn: psycopg.Connection, version_cible: str | None = None, par_qui: str = "cli"
) -> str:
    """Revient à version_cible, ou à la dernière version archivée si non spécifiée."""
    if version_cible is None:
        row = conn.execute(
            "SELECT version FROM versions_modele"
            " WHERE statut = 'archive'"
            " ORDER BY promue_le DESC NULLS LAST, cree_le DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("Aucune version archivée disponible pour un retour arrière.")
        version_cible = row[0]

    promouvoir(conn, version_cible, par_qui=f"rollback:{par_qui}")
    return version_cible
