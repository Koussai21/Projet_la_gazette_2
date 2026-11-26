from gazette import db, evaluation, registre
from gazette.themes import ConfigThemes


def test_evaluation_garde_fous():
    cfg_eval = {
        "seuils": {
            "silhouette_min": 0.12,
            "part_bruit_max": 0.45,
            "nb_themes_min": 3,
            "nb_themes_max": 25,
            "part_theme_geant_max": 0.40,
        },
        "derive": {
            "jours_consecutifs": 2,
            "variation_bruit_max": 0.20,
            "fenetre_historique_runs": 7,
        },
    }

    m_ok = {
        "nb_articles": 100,
        "part_bruit": 0.20,
        "nb_themes": 5,
        "silhouette": 0.25,
        "taille_max": 25,
    }
    assert evaluation.evaluer_run(m_ok, cfg_eval, []).verdict == "valide"

    m_bruit = {
        "nb_articles": 100,
        "part_bruit": 0.80,
        "nb_themes": 4,
        "silhouette": 0.20,
        "taille_max": 10,
    }
    res = evaluation.evaluer_run(m_bruit, cfg_eval, [])
    assert res.verdict == "recale"
    assert any("bruit" in r.lower() for r in res.raisons)

    m_geant = {
        "nb_articles": 100,
        "part_bruit": 0.10,
        "nb_themes": 4,
        "silhouette": 0.20,
        "taille_max": 60,
    }
    assert evaluation.evaluer_run(m_geant, cfg_eval, []).verdict == "recale"


def test_evaluation_derive():
    cfg_eval = {
        "seuils": {
            "silhouette_min": 0.10,
            "part_bruit_max": 0.60,
            "nb_themes_min": 2,
            "nb_themes_max": 25,
            "part_theme_geant_max": 0.50,
        },
        "derive": {
            "jours_consecutifs": 2,
            "variation_bruit_max": 0.20,
            "fenetre_historique_runs": 7,
        },
    }
    hist = [{"run_id": "r1", "metriques": {"part_bruit": 0.15}, "verdict": "valide"}]
    m_derive = {
        "nb_articles": 100,
        "part_bruit": 0.40,
        "nb_themes": 5,
        "silhouette": 0.20,
        "taille_max": 20,
    }
    assert evaluation.evaluer_run(m_derive, cfg_eval, hist).verdict == "revue"


def test_registre_promotion_et_rollback(conn):
    db.migrate(conn)
    registre.initialiser_si_vide(conn)

    ver, _ = registre.version_en_service(conn)
    assert ver == "v1.0.0"

    cfg_v2 = ConfigThemes(brut="fenetre_heures: 48\n", valeurs={"fenetre_heures": 48})
    registre.enregistrer_candidat(conn, "v1.1.0", "run-test", cfg_v2, par_qui="test")
    registre.promouvoir(conn, "v1.1.0", par_qui="ci")

    ver, cfg_active = registre.version_en_service(conn)
    assert ver == "v1.1.0"
    assert cfg_active["fenetre_heures"] == 48

    cible = registre.rollback(conn, par_qui="test")
    assert cible == "v1.0.0"
    ver_apres, _ = registre.version_en_service(conn)
    assert ver_apres == "v1.0.0"
