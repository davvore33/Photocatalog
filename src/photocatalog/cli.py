import argparse
import sys
from pathlib import Path

from . import config, db, scanner


def cmd_scan(args: argparse.Namespace) -> int:
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"error: {folder} is not a directory", file=sys.stderr)
        return 1

    db_path = Path(args.db).expanduser()
    summary = scanner.ScanSummary()

    with db.open_db(db_path) as conn:
        print(f"Scanning {folder} ...")
        scanner.scan_stage_a(conn, folder, summary)
        print(
            f"  {summary.scanned} files seen: "
            f"{summary.added} added, {summary.updated} updated, "
            f"{summary.moved} moved, {summary.unchanged} unchanged, "
            f"{len(summary.skipped)} skipped"
        )
        if summary.skipped:
            for path in summary.skipped:
                print(f"    skipped: {path}")

        if not args.no_tag:
            print(f"Tagging with {args.model} ...")
            scanner.scan_stage_b(
                conn, summary, model=args.model, retry_errors=args.retry_errors
            )
            print(f"  {summary.tagged} tagged, {summary.tag_errors} errors")

        if args.prune:
            removed = scanner.prune(conn)
            print(f"Pruned {len(removed)} missing files")

    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .viewer.app import create_app

    db_path = Path(args.db).expanduser()
    app = create_app(db_path)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    with db.open_db(db_path) as conn:
        data = db.stats(conn)

    print(f"Total images: {data['total_images']}")
    print("By status:")
    for status, count in data["by_status"].items():
        print(f"  {status}: {count}")
    print("Top tags:")
    for name, count in data["top_tags"]:
        print(f"  {name}: {count}")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    with db.open_db(db_path) as conn:
        missing = [
            row["path"]
            for row in conn.execute("SELECT path FROM images")
            if not Path(row["path"]).exists()
        ]
        if not missing:
            print("Nothing to prune.")
            return 0

        print(f"{len(missing)} missing file(s):")
        for path in missing:
            print(f"  {path}")

        if not args.yes:
            answer = input("Remove these from the catalog? [y/N] ")
            if answer.strip().lower() != "y":
                print("Aborted.")
                return 0

        removed = scanner.prune(conn)
        print(f"Removed {len(removed)} entries.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photocatalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_p = subparsers.add_parser("scan", help="Scan a folder and update the catalog")
    scan_p.add_argument("folder")
    scan_p.add_argument("--db", default=str(config.DEFAULT_DB_PATH))
    scan_p.add_argument("--model", default=config.DEFAULT_VISION_MODEL)
    scan_p.add_argument(
        "--no-tag", action="store_true", help="Skip the Ollama vision tagging stage"
    )
    scan_p.add_argument(
        "--retry-errors", action="store_true", help="Also retry previously failed images"
    )
    scan_p.add_argument(
        "--prune", action="store_true", help="Remove missing files after scanning"
    )
    scan_p.set_defaults(func=cmd_scan)

    serve_p = subparsers.add_parser("serve", help="Run the local catalog viewer")
    serve_p.add_argument("--db", default=str(config.DEFAULT_DB_PATH))
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=5000)
    serve_p.add_argument("--debug", action="store_true")
    serve_p.set_defaults(func=cmd_serve)

    stats_p = subparsers.add_parser("stats", help="Show catalog statistics")
    stats_p.add_argument("--db", default=str(config.DEFAULT_DB_PATH))
    stats_p.set_defaults(func=cmd_stats)

    prune_p = subparsers.add_parser("prune", help="Remove entries for missing files")
    prune_p.add_argument("--db", default=str(config.DEFAULT_DB_PATH))
    prune_p.add_argument("--yes", action="store_true", help="Skip confirmation")
    prune_p.set_defaults(func=cmd_prune)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
