"""Évaluation automatique des runs de clustering et détection de dérive."""

from dataclasses import dataclass
from pathlib import Path

import psycopg
import yaml


@dataclass(frozen=True)
class VerdictEvaluation:
    verdict: str  # 'valide' | 'revue' | 'recale'
    raisons: list[str]


def charger_config_eval(path: str | Path = "config/evaluation.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def runs_precedents(conn: psycopg.Connection, limite: int = 7) -> list[dict]:
    rows = conn.execute(
        "SELECT run_id, metriques, verdict FROM runs"
        " WHERE statut = 'ok' AND verdict IS NOT NULL"
        " ORDER BY debut DESC LIMIT %s",
        (limite,),
    ).fetchall()
    return [{"run_id": r[0], "metriques": r[1], "verdict": r[2]} for r in rows]


def evaluer_run(metriques_run: dict, cfg_eval: dict, historique: list[dict]) -> VerdictEvaluation:
    seuils = cfg_eval["seuils"]
    derive = cfg_eval["derive"]
    raisons: list[str] = []
    recale = False

    nb_articles = metriques_run["nb_articles"]
    part_bruit = metriques_run["part_bruit"]
    nb_themes = metriques_run["nb_themes"]
    silhouette = metriques_run["silhouette"]
    taille_max = metriques_run["taille_max"]

    articles_classes = round(nb_articles * (1.0 - part_bruit))
    part_geant = (taille_max / articles_classes) if articles_classes > 0 else 1.0

    if silhouette is None or silhouette < seuils["silhouette_min"]:
        recale = True
        raisons.append(f"Silhouette insuffisante ({silhouette} < {seuils['silhouette_min']})")
    if part_bruit > seuils["part_bruit_max"]:
        recale = True
        raisons.append(
            f"Part de bruit trop élevée ({part_bruit:.1%} > {seuils['part_bruit_max']:.1%})"
        )
    if not (seuils["nb_themes_min"] <= nb_themes <= seuils["nb_themes_max"]):
        recale = True
        raisons.append(f"Nombre de thèmes hors bornes ({nb_themes})")
    if part_geant > seuils["part_theme_geant_max"]:
        recale = True
        raisons.append(f"Thème géant ({part_geant:.1%} > {seuils['part_theme_geant_max']:.1%})")

    if recale:
        return VerdictEvaluation(verdict="recale", raisons=raisons)

    revue = False
    if historique:
        bruits_hist = [h["metriques"]["part_bruit"] for h in historique if h["metriques"]]
        if bruits_hist:
            moy_bruit = sum(bruits_hist) / len(bruits_hist)
            if (part_bruit - moy_bruit) > derive["variation_bruit_max"]:
                revue = True
                raisons.append(f"Dérive bruit : +{part_bruit - moy_bruit:.1%} vs moyenne récente")

        nb_prec = derive["jours_consecutifs"] - 1
        recents = historique[:nb_prec]
        if len(recents) == nb_prec and all(r["verdict"] == "revue" for r in recents):
            revue = True
            raisons.append(f"Dérive persistante sur {derive['jours_consecutifs']} runs consécutifs")

    return VerdictEvaluation(verdict="revue" if revue else "valide", raisons=raisons)