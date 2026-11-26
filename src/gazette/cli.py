"""Ligne de commande : python -m gazette <commande>.

migrer               applique les migrations en attente
collecter            un passage tout de suite (--source pour en viser une)
nettoyer             brut → articles_propres / rejets, puis rapport du jour
rejouer REGLE        après avoir modifié une règle : repasse ses rejets dans les règles
controler            contrôles de qualité sur les vraies données, alerte si un fait est faux
rapport              réécrit le rapport de qualité (--jour AAAA-MM-JJ)
purger               applique la rétention (docs/donnees.md)
themes               un run de regroupement tout de suite (--fin pour rejouer une fenêtre passée)
runs                 les derniers runs : données, paramètres, métriques, verdict
themes-du-jour       les thèmes du dernier run réussi
tracer ID|LIEN       d'un article, retrouver son sort, sa source et son item brut
planifier            tout ça toutes les GAZETTE_INTERVALLE_MIN minutes, via Prefect
etat                 état de chaque source : dernière réussite, échecs, sommeils, articles
reveiller SOURCE     sort une source du sommeil
modele-statut        version en production et historique du registre
modele-promouvoir    promeut une version en production
modele-rollback      revient à la version précédente
modele-evaluer-ci    évalue une configuration candidate sans toucher aux thèmes en base
relire               relecture humaine d'un échantillon de 10 articles
"""

import argparse
import random
from datetime import UTC, date, datetime, timedelta

from gazette import config, db, journal, pipeline, registre, themes
from gazette.collecteur import collect_all
from gazette.sources import load_sources
from gazette.stockage import count_items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gazette", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="commande", required=True)

    commands.add_parser("migrer", help="applique les migrations en attente")

    collecter = commands.add_parser("collecter", help="un passage tout de suite")
    collecter.add_argument("--source", action="append", help="id de sources.csv (répétable)")

    commands.add_parser("nettoyer", help="brut → articles_propres / rejets, puis rapport")

    rejouer = commands.add_parser("rejouer", help="repasse les rejets d'une règle modifiée")
    rejouer.add_argument("regle", help="ex. R07_media_seul")

    commands.add_parser("controler", help="contrôles de qualité et alerte")

    rapport = commands.add_parser("rapport", help="réécrit le rapport de qualité")
    rapport.add_argument("--jour", type=date.fromisoformat, help="AAAA-MM-JJ (UTC)")

    commands.add_parser("purger", help="applique la rétention")

    cmd_themes = commands.add_parser("themes", help="un run de regroupement tracé")
    cmd_themes.add_argument(
        "--fin",
        type=datetime.fromisoformat,
        help="fin de la fenêtre (ISO 8601) pour rejouer un run",
    )

    runs = commands.add_parser("runs", help="les derniers runs")
    runs.add_argument("-n", type=int, default=10)

    commands.add_parser("themes-du-jour", help="les thèmes du dernier run réussi")

    tracer = commands.add_parser("tracer", help="sort, source et item brut d'un article")
    tracer.add_argument("cle", metavar="ID|LIEN")

    commands.add_parser("planifier", help="collecte planifiée par Prefect")
    commands.add_parser("etat", help="état de chaque source")

    reveiller = commands.add_parser("reveiller", help="sort une source du sommeil")
    reveiller.add_argument("source")

    # --- Commandes MLOps (TD 6) ---
    commands.add_parser("modele-statut", help="version en production et historique du registre")

    promouvoir = commands.add_parser("modele-promouvoir", help="promeut une version en production")
    promouvoir.add_argument("version", help="ex. v1.1.0")
    promouvoir.add_argument("--par", default="manuel", help="auteur de la promotion")

    rb = commands.add_parser("modele-rollback", help="revient à la version précédente")
    rb.add_argument("--vers", default=None, help="version cible (défaut : dernière archivée)")
    rb.add_argument("--par", default="manuel", help="auteur du retour arrière")

    eval_ci = commands.add_parser(
        "modele-evaluer-ci", help="évalue un candidat sans toucher la prod"
    )
    eval_ci.add_argument("--version", required=True, help="identifiant de la version candidate")
    eval_ci.add_argument(
        "--config", default="config/clustering.yaml", help="fichier YAML candidat"
    )
    eval_ci.add_argument("--par", default="ci", help="auteur")

    relire = commands.add_parser("relire", help="relecture humaine d'un échantillon de 10 articles")
    relire.add_argument("--run-id", default=None, help="run à relire (défaut : dernier run)")
    relire.add_argument("--par", default="equipe", help="nom du relecteur")

    args = parser.parse_args(argv)

    journal.configure()
    cfg = config.load()

    if args.commande == "planifier":
        from gazette.flows import planifier  # Prefect n'est chargé que si on en a besoin

        planifier(cfg.intervalle_min)
        return 0

    with db.connect(cfg.database_url) as conn:
        if args.commande == "migrer":
            applied = db.migrate(conn)
            print("migrations appliquées :", ", ".join(applied) or "aucune, la base est à jour")

        elif args.commande == "collecter":
            bilans = collect_all(
                conn,
                cfg.sources_file,
                cfg.articles_dir,
                only=args.source,
                delai=timedelta(minutes=cfg.delai_min),
            )
            return 1 if bilans and all(b.statut == "echec" for b in bilans) else 0

        elif args.commande == "nettoyer":
            bilan = pipeline.nettoyer(conn, cfg)
            path, _ = pipeline.rapporter(conn, cfg, bilan)
            print(f"{bilan.gardes} gardés, {bilan.rejetes} rejetés ; rapport : {path}")

        elif args.commande == "rejouer":
            oublies = db.forget_rejections(conn, args.regle)
            bilan = pipeline.nettoyer(conn, cfg)
            path, _ = pipeline.rapporter(conn, cfg, bilan)
            print(
                f"{oublies} rejets {args.regle} repassés : {bilan.gardes} gardés, "
                f"{bilan.rejetes} rejetés à nouveau ; rapport : {path}"
            )

        elif args.commande == "controler":
            resultats = pipeline.controler(conn, cfg)
            pipeline.rapporter(conn, cfg)
            return 0 if all(r.ok for r in resultats) else 1

        elif args.commande == "rapport":
            path, contenu = pipeline.rapporter(conn, cfg, jour=args.jour)
            print(contenu)
            print(f"(écrit dans {path})")

        elif args.commande == "themes":
            fin = args.fin.astimezone(UTC) if args.fin and args.fin.tzinfo else args.fin
            if fin is not None and fin.tzinfo is None:
                fin = fin.replace(tzinfo=UTC)
            run = pipeline.regrouper(conn, cfg, declencheur="manuel", fin=fin)
            print(
                f"run {run.run_id} [verdict={run.verdict}] : {run.metriques}"
            )
            if run.raisons_verdict:
                print(f"alertes : {', '.join(run.raisons_verdict)}")
            for theme in run.themes:
                print(f"  {theme['numero']:2} [{theme['taille']:2}] {theme['nom']}")
            return 1 if run.verdict == "recale" else 0

        elif args.commande == "runs":
            print_runs(conn, args.n)

        elif args.commande == "themes-du-jour":
            print_themes_du_jour(conn)

        elif args.commande == "purger":
            print(pipeline.retenir(conn, cfg))

        elif args.commande == "tracer":
            trace = pipeline.tracer(conn, cfg, args.cle)
            if trace is None:
                print(f"aucun article {args.cle!r} dans articles_propres ni dans rejets")
                return 1
            for cle, valeur in trace.items():
                if valeur is not None:
                    print(f"{cle:10} {valeur}")

        elif args.commande == "etat":
            db.migrate(conn)
            en_service = {s.id for s in load_sources(cfg.sources_file)}
            print_report(db.report(conn), cfg.articles_dir, en_service)

        elif args.commande == "reveiller":
            if not db.wake_up(conn, args.source):
                print(f"source inconnue : {args.source}")
                return 1
            print(f"{args.source} réveillée : elle sera collectée au prochain passage")

        elif args.commande == "modele-statut":
            db.migrate(conn)
            registre.initialiser_si_vide(conn)
            print_registre(conn)

        elif args.commande == "modele-promouvoir":
            db.migrate(conn)
            registre.promouvoir(conn, args.version, par_qui=args.par)
            print(f"version {args.version} promue en production par {args.par}")

        elif args.commande == "modele-rollback":
            db.migrate(conn)
            cible = registre.rollback(conn, version_cible=args.vers, par_qui=args.par)
            print(f"retour arrière effectué : version {cible} remise en production")

        elif args.commande == "modele-evaluer-ci":
            db.migrate(conn)
            registre.initialiser_si_vide(conn)
            cfg_cand = themes.charger_config(args.config)
            run = pipeline.regrouper(
                conn,
                cfg,
                declencheur="ci",
                cfg_override=cfg_cand,
                version_override=args.version,
                mode_candidat=True,
            )
            statut_reg = "rejete" if run.verdict == "recale" else "candidat"
            registre.enregistrer_candidat(
                conn, args.version, run.run_id, cfg_cand, par_qui=args.par, statut=statut_reg
            )
            print(f"candidat {args.version} -> verdict={run.verdict} ({run.raisons_verdict})")
            return 1 if run.verdict == "recale" else 0

        elif args.commande == "relire":
            return executer_relecture(conn, run_id=args.run_id, par_qui=args.par)

    return 0


def print_report(rows: list[dict], articles_dir: str, en_service: set[str] | None = None) -> None:
    """Une ligne par source ; celles retirées de sources.csv restent, avec leur historique."""
    header = ("source", "état", "dernière réussite", "échecs", "passages", "sommeils", "articles")
    lines = [header]
    for r in rows:
        reussite = r["derniere_reussite"]
        lines.append(
            (
                r["id"],
                _etat(r, en_service),
                reussite.strftime("%Y-%m-%d %H:%M UTC") if reussite else "jamais",
                str(r["echecs_consecutifs"]),
                f"{r['passages']} ({r['echecs']} en échec)",
                str(r["sommeils"]),
                str(count_items(articles_dir, r["id"])),
            )
        )
    widths = [max(len(line[i]) for line in lines) for i in range(len(header))]
    for line in lines:
        print("  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)))
    for r in rows:
        if r["derniere_erreur"]:
            print(f"- {r['id']} : {r['derniere_erreur']}")


def _etat(row: dict, en_service: set[str] | None) -> str:
    if en_service is not None and row["id"] not in en_service:
        return "retirée"
    return "actif" if row["actif"] else "SOMMEIL"


def print_runs(conn, n: int) -> None:
    rows = conn.execute(
        "SELECT run_id, statut, verdict, version_modele, declencheur, nb_articles,"
        " hash_entree, hash_parametres, metriques, raisons_verdict"
        " FROM runs ORDER BY debut DESC LIMIT %s",
        (n,),
    ).fetchall()
    for run_id, statut, verdict, ver_mod, declencheur, nb, entree, params, m, raisons in rows:
        m = m or {}
        print(
            f"{run_id}  {statut:8} [{verdict or '-':6}] {ver_mod or '-':10}"
            f" {declencheur:8} {nb:4} articles  entrée {entree}  params {params}"
        )
        if m:
            print(
                f"    {m.get('nb_themes')} thèmes, médiane {m.get('taille_mediane')},"
                f" bruit {m.get('part_bruit')}, silhouette {m.get('silhouette')}"
            )
        if raisons:
            print(f"    alertes : {', '.join(raisons)}")


def print_themes_du_jour(conn) -> None:
    rows = conn.execute(
        "SELECT run_id, numero, nom, taille, mots_cles FROM themes_du_jour ORDER BY numero"
    ).fetchall()
    if not rows:
        print("aucun run réussi pour l'instant")
        return
    print(f"thèmes du run {rows[0][0]} :")
    for _, numero, nom, taille, mots in rows:
        print(f"  {numero:2} [{taille:2}] {nom:40} {', '.join(mots[3:])}")


def print_registre(conn) -> None:
    rows = conn.execute(
        "SELECT version, statut, run_id, hash_parametres, promue_le, par_qui, parametres"
        " FROM versions_modele ORDER BY cree_le DESC"
    ).fetchall()
    for version, statut, run_id, h_params, promue_le, par_qui, params in rows:
        date_str = promue_le.strftime("%Y-%m-%d %H:%M UTC") if promue_le else "-"
        print(
            f"{version:14} {statut:11} run={run_id or '-':22}"
            f" params={h_params}  promue={date_str}  par={par_qui}"
        )
        if statut == "production":
            print(f"    paramètres actifs : {params.get('regroupement')}")


def executer_relecture(conn, run_id: str | None = None, par_qui: str = "equipe") -> int:
    if run_id is None:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE statut = 'ok' ORDER BY debut DESC LIMIT 1"
        ).fetchone()
        if row is None:
            print("aucun run réussi à relire")
            return 1
        run_id = row[0]

    articles = conn.execute(
        "SELECT a.item_id, a.titre, t.numero, t.nom"
        " FROM articles_themes at"
        " JOIN articles_propres a ON a.item_id = at.item_id"
        " JOIN themes t ON t.theme_id = at.theme_id"
        " WHERE at.run_id = %s",
        (run_id,),
    ).fetchall()
    if not articles:
        print(f"aucun article classé pour le run {run_id}")
        return 1

    echantillon = random.sample(articles, min(10, len(articles)))
    print(f"Relecture de {len(echantillon)} articles pour le run {run_id} (o/n) :")
    valides = 0
    with conn.transaction():
        for item_id, titre, num_theme, nom_theme in echantillon:
            rep = input(f"  [{num_theme} - {nom_theme}] {titre} -> (o/n) ? ").strip().lower()
            pertinent = rep in ("o", "oui", "y", "1")
            if pertinent:
                valides += 1
            conn.execute(
                "INSERT INTO relectures_echantillons"
                " (run_id, item_id, theme_numero, pertinent, relu_par)"
                " VALUES (%s, %s, %s, %s, %s)",
                (run_id, item_id, num_theme, pertinent, par_qui),
            )
    print(f"Relecture enregistrée : {valides}/{len(echantillon)} pertinents.")
    return 0
