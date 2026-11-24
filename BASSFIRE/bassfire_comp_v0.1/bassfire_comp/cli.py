"""Command line: `bassfire_comp run` and `bassfire_comp demo`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .pipeline import run


def _print_summary(s: dict, out: Path) -> None:
    print(f"References: {s['references']}  Targets: {s['targets']}  Pairs: {s['pairs']}")
    print(f"Tiers: {s['tiers'] or 'none'}")
    print(f"Targets with match: {s['targets_with_match']}  without: {s['targets_without_match']}")
    print(f"Planned/supplementary: {s['planned_or_supplementary']}  Excluded: {s['excluded']}")
    for n in s["notes"][:10]:
        print("note:", n)
    print(f"Outputs written to: {out.resolve()}")
    if s["references"] == 0 or s["targets"] == 0:
        print("No pairs formed. See output/run_report.md and README.md (where to put data).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bassfire_comp",
                                 description="BASS/BASS-II <-> SAFFIRE comparability finder")
    ap.add_argument("--version", action="version", version=f"bassfire_comp {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="ingest data/, compare all pairs, write output/")
    r.add_argument("--data", default="data", help="data folder (default: data)")
    r.add_argument("--out", default="output", help="output folder (default: output)")
    r.add_argument("--config", default="config.toml", help="TOML overrides (default: config.toml)")
    d = sub.add_parser("demo", help="run on built-in SYNTHETIC records to check the install")
    d.add_argument("--out", default="output_demo")
    args = ap.parse_args(argv)

    if args.cmd == "run":
        data, out = Path(args.data), Path(args.out)
        if not data.exists():
            print(f"Data folder not found: {data}. Run from the repo folder or pass --data.")
            return 1
        cfg = load_config(args.config)
        _print_summary(run(data, out, cfg), out)
        return 0
    if args.cmd == "demo":
        out = Path(args.out)
        print("DEMO: using SYNTHETIC records (fake values). Not NASA data.")
        s = run(Path(__file__).parent / "demo_data", out, load_config(None), label="demo-synthetic")
        _print_summary(s, out)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
