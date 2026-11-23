"""`tirai` command line."""

import argparse
import shutil
import sys
from pathlib import Path

from tirai import __version__

TEMPLATE = Path(__file__).parent / "assets" / "scenario.template.yaml"


def cmd_doctor(_args):
    from tirai import doctor

    return doctor.run()


def cmd_validate(args):
    from tirai.scenario import ScenarioError, env_vars, load

    try:
        sc = load(args.scenario)
    except ScenarioError as e:
        print(e)
        return 1
    print(f"ok: {sc['name']} ({len(sc['steps'])} steps, tabs: {', '.join(sc['tabs'])})")
    needed = sorted(env_vars(sc))
    if needed:
        print("env vars: " + ", ".join(needed))
    return 0


def _summary(tl):
    steps = tl["steps"]
    failed = [s["id"] for s in steps if s["status"] != "passed"]
    print(f"\n{len(steps) - len(failed)}/{tl['total_steps']} steps passed" + (f"; failing: {failed}" if failed else ""))
    return 1 if failed or len(steps) < tl["total_steps"] else 0


def cmd_run(args):
    from tirai import runner
    from tirai.scenario import ScenarioError, load

    try:
        sc = load(args.scenario)
    except ScenarioError as e:
        print(e)
        return 1
    out = Path(args.out) / ("record" if args.record else "dry-run")
    tl = runner.run(sc, out, record=args.record, session=args.session, scope=args.scope, hold=args.hold)
    print(f"timeline: {out / 'timeline.json'}")
    return _summary(tl)


def cmd_compose(args):
    from tirai import compose

    final, seconds = compose.compose(args.timeline, out=args.output, lead=args.lead, title_seconds=args.title_seconds)
    print(f"final video: {final} ({seconds:.1f}s)")
    return 0


def cmd_record(args):
    """dry-run -> record -> compose; stops at the first phase that fails."""
    args.record = False
    if not args.skip_dry_run and cmd_run(args):
        print("dry-run failed; fix the scenario before recording")
        return 1
    args.record = True
    if cmd_run(args):
        return 1
    args.timeline = str(Path(args.out) / "record" / "timeline.json")
    return cmd_compose(args)


def cmd_init(args):
    dest = Path(args.path)
    if dest.exists() and not args.force:
        print(f"{dest} exists; use --force to overwrite")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE, dest)
    print(f"wrote {dest}")
    return 0


def cmd_install_skill(args):
    from tirai.install import TARGETS, install

    agents = list(TARGETS) if "all" in args.agent else args.agent
    install(agents, project=args.project, dest=args.dest, force=args.force)
    return 0


def cmd_asset(args):
    from tirai.resources import annotate_js_path

    print(annotate_js_path())
    return 0


def build_parser():
    from tirai.install import TARGETS

    p = argparse.ArgumentParser(prog="tirai", description="Scenario-driven test evidence recorder")
    p.add_argument("--version", action="version", version=f"tirai {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check ffmpeg, BrowserSkill, fonts and optional drivers").set_defaults(fn=cmd_doctor)

    s = sub.add_parser("init", help="write a scenario template")
    s.add_argument("path", nargs="?", default="scenarios/example.yaml")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("validate", help="validate a scenario file")
    s.add_argument("scenario")
    s.set_defaults(fn=cmd_validate)

    def run_opts(s):
        s.add_argument("scenario")
        s.add_argument("--out", default="evidence", help="output root (default: evidence/)")
        s.add_argument("--session", help="reuse a live bsk session instead of opening a fresh one")
        s.add_argument("--scope", default="tirai", help="bsk scope for the fresh session")
        s.add_argument("--hold", type=float, help="seconds each step stays on screen")

    def compose_opts(s):
        s.add_argument("--output", help="final video path (default: <timeline dir>/final.mp4)")
        s.add_argument("--lead", type=float, default=0.3, help="seconds kept before each step starts")
        s.add_argument("--title-seconds", type=float, default=3.0)

    s = sub.add_parser("run", help="run a scenario (--dry-run or --record)")
    run_opts(s)
    mode = s.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--record", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("compose", help="build final.mp4 + subtitles + report from a recorded timeline")
    s.add_argument("timeline")
    compose_opts(s)
    s.set_defaults(fn=cmd_compose)

    s = sub.add_parser("record", help="dry-run, record, then compose in one go")
    run_opts(s)
    compose_opts(s)
    s.add_argument("--skip-dry-run", action="store_true")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("install-skill", help="install the tirai-evidence skill for an agent")
    s.add_argument("--agent", action="append", choices=[*TARGETS, "all"], required=True)
    s.add_argument("--project", help="install into this project instead of the user profile")
    s.add_argument("--dest", help="explicit skills directory (overrides --agent paths)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_install_skill)

    sub.add_parser("annotate-js", help="print the path of the injectable annotate.js").set_defaults(fn=cmd_asset)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    sys.exit(args.fn(args))
