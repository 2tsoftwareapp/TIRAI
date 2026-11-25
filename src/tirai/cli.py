"""`tirai` command line."""

import argparse
import os
import shutil
import sys
from pathlib import Path

from tirai import __version__

TEMPLATE = Path(__file__).parent / "assets" / "scenario.template.yaml"


def cmd_doctor(_args):
    from tirai import doctor

    return doctor.run()


def cmd_setup(args):
    from tirai import bootstrap
    from tirai.install import TARGETS

    agents = (list(TARGETS) if "all" in args.agent else args.agent) if args.agent else None

    def split(items):
        return {x.strip() for item in items for x in item.split(",") if x.strip()}

    skip, only = split(args.skip), split(args.only)
    unknown = (skip | only) - set(bootstrap.STEPS)
    if unknown:
        print(f"unknown setup step(s): {', '.join(sorted(unknown))} (use {', '.join(bootstrap.STEPS)})")
        return 2
    return bootstrap.run(agents=agents, project=args.project, yes=args.yes, dry_run=args.dry_run, skip=skip, only=only)


def load_env(args):
    """Load KEY=VALUE pairs from --env-file, else from a .env next to the scenario; real env vars win."""
    from tirai.scenario import load_env_file

    path = Path(args.env_file) if getattr(args, "env_file", None) else Path(args.scenario).parent / ".env"
    if getattr(args, "env_file", None) and not path.is_file():
        raise SystemExit(f"env file not found: {path}")
    if path.is_file():
        load_env_file(path)


def env_file_unignored(scenario):
    """The .env next to the scenario when it sits in a git work tree without being ignored."""
    from tirai.system import find_bin, run_text

    env = Path(scenario).resolve().parent / ".env"
    git = find_bin("git")
    if not env.is_file() or not git:
        return None
    inside = run_text([git, "-C", str(env.parent), "rev-parse", "--is-inside-work-tree"], timeout=10)
    if inside.returncode != 0:
        return None
    ignored = run_text([git, "-C", str(env.parent), "check-ignore", "-q", str(env)], timeout=10)
    return env if ignored.returncode != 0 else None


def comma_selectors(sc):
    """Selectors written as a CSS list ('a, b'): the driver takes the first match in page order, not in list order."""
    from tirai.scenario import _selectors

    found = []
    for st in sc["steps"]:
        for item in [*(st.get("actions") or []), *(st.get("expect") or [])]:
            found += [(st["id"], x) for x in _selectors(item) if "," in x and not x.startswith("[data-tirai-id")]
    return found


def check_databases(sc):
    from tirai import db
    from tirai.scenario import ScenarioError, interpolate

    for name, cfg in (sc.get("databases") or {}).items():
        try:
            ro, detail = db.write_access(interpolate(cfg["dsn"]))
        except (ScenarioError, ImportError) as e:
            print(f"db {name}: not checked ({e})")
            continue
        except Exception as e:  # noqa: BLE001 - connection problems are reported, not fatal
            print(f"db {name}: not checked ({str(e).splitlines()[0][:120]})")
            continue
        if ro is False:
            print(f"warning: db {name} is not read-only ({detail}); use a read-only user for expect: db")
        elif ro:
            print(f"db {name}: read-only ({detail})")


def cmd_validate(args):
    from tirai.scenario import ScenarioError, env_vars, load, step_writes

    load_env(args)
    try:
        sc = load(args.scenario)
    except ScenarioError as e:
        print(e)
        return 1
    print(f"ok: {sc['name']} ({len(sc['steps'])} steps, tabs: {', '.join(sc['tabs'])})")
    needed = sorted(env_vars(sc))
    if needed:
        print("env vars: " + ", ".join(needed))
    writes = [(st["id"], step_writes(st)) for st in sc["steps"] if step_writes(st)]
    if writes:
        print("writes data: " + "; ".join(f"{i} ({w})" for i, w in writes))
        print("  a dry-run stops before the first of these unless --allow-writes; use cleanup: to undo them")
    for sid, sel in comma_selectors(sc):
        print(f"warning: {sid}: {sel!r} is a CSS list; the first match in page order wins. Prefer targets: fallbacks")
    env = env_file_unignored(args.scenario)
    if env:
        print(f"warning: {env} holds secrets but git does not ignore it; add it to .gitignore (tirai init does)")
    if not args.no_db_check:
        check_databases(sc)
    return 0


def _summary(tl):
    steps = tl["steps"]
    failed = [s["id"] for s in steps if s["status"] != "passed"]
    print(f"\n{len(steps) - len(failed)}/{tl['total_steps']} steps passed" + (f"; failing: {failed}" if failed else ""))
    for s in steps:
        if s.get("failed_requests") or s.get("console_errors"):
            n = len(s.get("failed_requests") or []) + len(s.get("console_errors") or [])
            print(f"  note: {s['id']} had {n} failed request(s)/console error(s); see timeline.json")
    stop = tl.get("stopped")
    if stop and "before" in stop:
        print(f"stopped before {stop['before']}: {stop['reason']}; the steps before it ran (--allow-writes runs all)")
    elif stop:
        print(f"stopped after {stop['after']} ({stop['reason']})")
    for c in tl.get("cleanup") or []:
        if c["status"] != "passed":
            print(f"cleanup {c['id']} {c['status']}: {c.get('error') or 'expectation failed'}")
    return 1 if failed or (len(steps) < tl["total_steps"] and not stop) else 0


def cmd_run(args):
    from tirai import runner
    from tirai.scenario import ScenarioError, load

    load_env(args)
    try:
        sc = load(args.scenario)
    except ScenarioError as e:
        print(e)
        return 1
    out = Path(args.out) / ("record" if args.record else "dry-run")
    if args.headed:
        os.environ["TIRAI_HEADED"] = "1"
    from tirai.bsk import DriverError

    if args.record and (args.from_step or args.until):
        print("--from-step/--until are for dry-runs; a recording always covers the whole scenario")
        return 2
    if args.from_step and not args.session:
        print("--from-step needs --session <name> (keep one with --keep-session) so the page state carries over")
        return 2
    try:
        tl = runner.run(
            sc,
            out,
            record=args.record,
            session=args.session,
            scope=args.scope,
            hold=args.hold,
            driver=args.driver,
            allow_writes=args.allow_writes,
            until=args.until,
            from_step=args.from_step,
            keep_session=args.keep_session,
            fresh=args.fresh,
        )
    except (DriverError, RuntimeError, ScenarioError, OSError) as e:
        print(f"error: {e}")
        return 1
    except KeyboardInterrupt:
        print("interrupted")
        return 130
    print(f"timeline: {out / 'timeline.json'}")
    return _summary(tl)


def cmd_inspect(args):
    from tirai import inspect
    from tirai.bsk import DriverError
    from tirai.scenario import ScenarioError, load

    if args.headed:
        os.environ["TIRAI_HEADED"] = "1"
    try:
        if args.scenario.startswith(("http://", "https://")):
            sc = inspect.url_scenario(args.scenario)
        else:
            load_env(args)
            sc = load(args.scenario)
        res = inspect.run(sc, Path(args.out), session=args.session, driver=args.driver)
    except (DriverError, RuntimeError, ScenarioError, OSError) as e:
        print(f"error: {e}")
        return 1
    print(f"inspect: {res['pages']} page(s), {res['targets']} suggested target(s) -> {res['dir']}")
    print(f"  per step: {res['dir']}/<step>.md   targets block: {res['dir'] / 'targets.yaml'}")
    for s in res["failed"]:
        print(f"  note: {s['id']} {s.get('status')}: {s.get('error') or 'expectation failed'}")
    return 0


def cmd_compose(args):
    from tirai import compose

    final, seconds = compose.compose(
        args.timeline,
        out=args.output,
        lead=args.lead,
        title_seconds=args.title_seconds,
        lang=args.lang,
        voice=args.voice or os.environ.get("TIRAI_TTS"),
        trim_still=args.trim_still,
    )
    print(f"final video: {final} ({seconds:.1f}s)")
    return 0


def cmd_record(args):
    """dry-run -> record -> compose; stops at the first phase that fails unless --record-failures."""
    args.record = False
    args.until = args.from_step = None
    keep, args.keep_session = args.keep_session, False
    if not args.skip_dry_run and cmd_run(args):
        if not args.record_failures:
            print("dry-run failed; fix the scenario before recording (or pass --record-failures for bug evidence)")
            return 1
        print("dry-run failed; recording anyway up to the first failing step (--record-failures)")
    args.record = True
    args.keep_session = keep
    failed = cmd_run(args)
    if failed and not args.record_failures:
        return 1
    args.timeline = str(Path(args.out) / "record" / "timeline.json")
    return cmd_compose(args) or failed


def cmd_export(args):
    import json

    from tirai import export, report

    rec = Path(args.dir)
    tl_path = rec / "timeline.final.json" if (rec / "timeline.final.json").is_file() else rec / "timeline.json"
    if not tl_path.is_file():
        print(f"no timeline in {rec}; run `tirai record` first")
        return 1
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    formats = [f for item in args.format for f in item.split(",") if f] or list(export.FORMATS)
    unknown = set(formats) - set(export.FORMATS)
    if unknown:
        print(f"unknown format(s): {', '.join(sorted(unknown))} (use {', '.join(export.FORMATS)})")
        return 2
    for path in export.write(
        rec, tl, formats, test_key=args.test_key, project_key=args.project_key, case_id=args.case_id
    ):
        print(f"wrote {path}")
    if (rec / report.MANIFEST).is_file():
        report.write_manifest(rec)
        if (rec / (report.MANIFEST + ".sig")).is_file():
            print("manifest changed: run `tirai sign` again")
    return 0


def cmd_sign(args):
    from tirai import sign

    key = args.key or os.environ.get("TIRAI_SIGN_KEY")
    if not key:
        print("pass --key (an SSH private key, e.g. ~/.ssh/id_ed25519) or set TIRAI_SIGN_KEY")
        return 2
    try:
        for path in sign.sign(args.dir, key, tsa=args.tsa or os.environ.get("TIRAI_TSA_URL")):
            print(f"wrote {path}")
    except sign.SignError as e:
        print(f"error: {e}")
        return 1
    return 0


def cmd_scan_pii(args):
    import json

    from tirai import ocr, report

    rec = Path(args.dir)
    video = rec / "final.mp4" if rec.is_dir() else rec
    rec = video.parent
    tl_file = rec / "timeline.final.json"
    priv = json.loads(tl_file.read_text(encoding="utf-8")).get("privacy", {}) if tl_file.is_file() else {}
    mask = [m for item in args.rules for m in item.split(",") if m] or priv.get("mask")
    try:
        hits = ocr.scan(video, mask, args.pattern or priv.get("patterns"), args.keep or priv.get("keep") or (),
                        every=args.every, lang=args.lang)  # fmt: skip
        for h in hits:
            print(f"{h['t']:7.1f}s  {h['text']:<28} box {h['box']}")
        print(f"{len(hits)} possible PII hit(s) in {video.name}")
        if hits and args.fix:
            n = ocr.redact(video, hits, every=args.every)
            print(f"blurred {n} region(s); rewrote {video.name}")
            if (rec / report.MANIFEST).is_file():
                report.write_manifest(rec)
                if (rec / (report.MANIFEST + ".sig")).is_file():
                    print("manifest changed: run `tirai sign` again")
            return 0
    except RuntimeError as e:
        print(f"error: {e}")
        return 2
    return 1 if hits else 0


def cmd_index(args):
    from tirai import index

    out, runs = index.write(args.dirs, args.out)
    print(f"wrote {out} ({len(runs)} runs)")
    return 0 if runs else 1


def cmd_verify(args):
    from tirai import report, sign

    args.dir = args.out or args.dir
    problems = report.verify(args.dir)
    notes = []
    try:
        for check in (
            sign.verify_signature(args.dir, args.pubkey, args.allowed_signers, args.identity),
            sign.verify_timestamp(args.dir, args.tsa_ca),
        ):
            problems += check[0]
            notes += check[1]
    except sign.SignError as e:
        problems.append(str(e))
    for p in problems:
        print(p)
    for n in notes:
        print(n)
    print("evidence intact" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_from_trace(args):
    from tirai.trace import from_trace

    scenario, env, skipped = from_trace(args.trace, args.output, do_resolve=not args.no_resolve, scope=args.scope)
    return _report_capture(args.output, env, skipped, scenario)


def cmd_from_spec(args):
    from tirai import spec

    out = args.output or str(Path(args.spec).with_suffix(".yaml"))
    try:
        sc, unmatched, unresolved = spec.write(args.spec, out, url=args.url)
    except (ValueError, OSError) as e:
        print(f"error: {e}")
        return 1
    print(f"wrote {out} ({len(sc['steps'])} steps)")
    for line in unmatched:
        print(f"not converted: {line}")
    if unresolved:
        print("fill in selectors: " + ", ".join(unresolved) + ("" if args.url else " (or pass --url to resolve them)"))
    print(f"then: tirai validate {out} && tirai run {out} --dry-run")
    return 0


def _report_capture(output, env, skipped, scenario=None):
    import yaml

    scenario = scenario or yaml.safe_load(Path(output).read_text(encoding="utf-8"))
    print(f"wrote {output} ({len(scenario['steps'])} steps)")
    for msg in skipped:
        print(f"skipped {msg}")
    if env:
        print("set in .env before running: " + ", ".join(env))
    print(f"review titles/expectations, then: tirai run {output} --dry-run")
    return 0


def cmd_capture(args):
    from tirai.system import agent_browser_bin, bsk_bin, run_text

    driver = args.driver or os.environ.get("TIRAI_DRIVER") or ("agent-browser" if agent_browser_bin() else "bsk")
    if driver == "agent-browser":
        from tirai.capture import capture

        if not agent_browser_bin():
            print("agent-browser not found; run `tirai setup`")
            return 1
        print("recording: do the flow in the browser window, then close it (or press Ctrl+C here)")
        try:
            _, env, skipped = capture(args.url, args.output, args.purpose, timeout=args.timeout)
        except (RuntimeError, OSError) as e:
            print(f"capture failed: {e}")
            return 1
        return _report_capture(args.output, env, skipped)
    if not bsk_bin():
        print("BrowserSkill CLI (bsk) not found; run `tirai setup`")
        return 1
    trace_dir = Path(args.trace_dir)
    cmd = [bsk_bin(), "record", "start", "--url", args.url, "--output", str(trace_dir)]
    if args.purpose:
        cmd += ["--purpose", args.purpose]
    print("recording: do the flow in the Agent Window, then click finish (结束) in the browser")
    p = run_text(cmd, timeout=None)
    if p.returncode != 0 or not (trace_dir / "trace.json").is_file():
        print(p.stderr.strip() or p.stdout.strip() or "bsk record produced no trace")
        return 1
    args.trace = str(trace_dir)
    return cmd_from_trace(args)


def _port_busy(port):
    import socket

    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def cmd_dbx(args):
    import subprocess
    import time
    import urllib.request

    from tirai.system import DBX_IMAGE, TIRAI_HOME, dbx_docker, dbx_package_root, dbx_running, dbx_web_bin

    url = f"http://127.0.0.1:{args.port}/"
    if dbx_running(url):
        print(f"DBX web already running: {url}")
        return 0
    binary = dbx_web_bin()
    docker = dbx_docker()
    if _port_busy(args.port) and (binary or (docker and not docker[1])):
        free = next((p for p in range(args.port + 1, args.port + 50) if not _port_busy(p)), None)
        if free is None:
            print(f"port {args.port} is used by another service (not DBX web); pass --port")
            return 1
        print(f"port {args.port} is used by another service (not DBX web); using {free}")
        print(f"  point scenarios at it: DBX_URL=http://127.0.0.1:{free}/")
        args.port, url = free, f"http://127.0.0.1:{free}/"
    if binary:
        root = dbx_package_root(binary)
        env = {**os.environ, "DBX_PORT": str(args.port), "DBX_PACKAGE_ROOT": str(root)}
        env.setdefault("DBX_DATA_DIR", str(TIRAI_HOME / "dbx-data"))
        Path(env["DBX_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
        if not args.detach:
            print(f"DBX web: {url} (Ctrl+C to stop)")
            return subprocess.call([binary], env=env, cwd=str(root))
        TIRAI_HOME.mkdir(parents=True, exist_ok=True)
        log = open(TIRAI_HOME / "dbx.log", "ab")  # noqa: SIM115 - handed to the detached process
        flags = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([binary], env=env, cwd=str(root), stdout=log, stderr=log, **flags)
    elif docker:
        exe, containers, _ = docker
        if containers:  # reuse the user's existing DBX container (it keeps its own port mapping)
            name = containers[0][0]
            print(f"starting existing DBX container {name}")
            if subprocess.call([exe, "start", name], stdout=subprocess.DEVNULL) != 0:
                return 1
            port = subprocess.run([exe, "port", name, "4224"], capture_output=True, text=True).stdout.split("\n")[0]
            if port.rsplit(":", 1)[-1].isdigit():
                url = f"http://127.0.0.1:{port.rsplit(':', 1)[-1]}/"
        else:
            pw = ["-e", "DBX_PASSWORD"] if os.environ.get("DBX_PASSWORD") else []
            cmd = [exe, "run", "-d", "--name", "tirai-dbx", "-p", f"{args.port}:4224", "-v", "tirai-dbx-data:/app/data"]
            if subprocess.call([*cmd, *pw, f"{DBX_IMAGE}:latest"]) != 0:
                return 1
    else:
        print("DBX web not installed: run `tirai setup` (or install Docker)")
        return 1
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=2)  # noqa: S310 - local URL
            print(f"DBX web running: {url}")
            return 0
        except OSError:
            time.sleep(1)
    print(f"DBX web did not answer on {url}; see {TIRAI_HOME / 'dbx.log'}")
    return 1


def cmd_dbx_connect(args):
    from tirai.dbxconn import DbxError, connect

    dsn = os.environ.get(args.dsn_env) if args.dsn_env else args.dsn
    if not dsn:
        print("give a DSN or --dsn-env NAME")
        return 1
    try:
        action, cid = connect(
            args.url, dsn, args.name, os.environ.get(args.password_env), args.db_host, test=not args.no_test
        )
    except DbxError as e:
        print(f"error: {e}")
        return 1
    print(f"{action} DBX connection {args.name!r} ({cid}) on {args.url}")
    return 0


def cmd_mcp(_args):
    from tirai.mcp import serve

    serve()
    return 0


GITIGNORE = ["# tirai: secrets and generated evidence", "**/.env", "evidence/"]


def ensure_gitignore(dest):
    """Add TIRAI's ignore lines to the .gitignore of the repo holding `dest` (or the current folder)."""
    from tirai.system import find_bin, run_text

    git, root = find_bin("git"), Path.cwd()
    if git:
        p = run_text([git, "-C", str(dest.parent), "rev-parse", "--show-toplevel"], timeout=10)
        if p.returncode == 0 and p.stdout.strip():
            root = Path(p.stdout.strip())
    gi = root / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    missing = [ln for ln in GITIGNORE[1:] if ln not in have]
    if not missing:
        return None
    text = "\n".join(have)
    text = (text + "\n\n" if text.strip() else "") + "\n".join([GITIGNORE[0], *missing]) + "\n"
    gi.write_text(text, encoding="utf-8")
    return gi, missing


def cmd_init(args):
    dest = Path(args.path)
    if dest.exists() and not args.force:
        print(f"{dest} exists; use --force to overwrite")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE, dest)
    print(f"wrote {dest}")
    added = ensure_gitignore(dest)
    if added:
        print(f"updated {added[0]}: ignores {', '.join(added[1])} (keep secrets in .env, never commit them)")
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

    s = sub.add_parser(
        "setup", help="install what is missing (ffmpeg, agent-browser, DBX, skills); reuses tools already here"
    )
    s.add_argument(
        "--agent",
        action="append",
        choices=[*TARGETS, "all"],
        help="agents to install the skill for (default: detected ones)",
    )
    s.add_argument("--project", help="install skills into this project instead of the user profile")
    s.add_argument(
        "--skip",
        action="extend",
        nargs="+",
        default=[],
        help="ffmpeg, agent-browser, dbx, browserskill, skills (comma or space separated)",
    )
    s.add_argument("--only", action="extend", nargs="+", default=[], help="run only these steps (same names)")
    s.add_argument("--yes", "-y", action="store_true", help="install without prompting")
    s.add_argument("--dry-run", action="store_true", help="print what would be installed")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("init", help="write a scenario template")
    s.add_argument("path", nargs="?", default="scenarios/example.yaml")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("validate", help="validate a scenario file")
    s.add_argument("scenario")
    s.add_argument("--env-file", help="KEY=VALUE file (default: .env next to the scenario)")
    s.add_argument("--no-db-check", action="store_true", help="don't connect to check the DSNs are read-only")
    s.set_defaults(fn=cmd_validate)

    def run_opts(s):
        s.add_argument("scenario")
        s.add_argument("--env-file", help="KEY=VALUE file (default: .env next to the scenario)")
        s.add_argument("--out", default="evidence", help="output root (default: evidence/)")
        s.add_argument("--driver", choices=["agent-browser", "bsk"], help="browser driver (default: agent-browser)")
        s.add_argument("--headed", action="store_true", help="show the agent-browser window (default: headless)")
        s.add_argument("--session", help="reuse a live driver session instead of opening a fresh one")
        s.add_argument("--scope", default="tirai", help="session name prefix for the fresh session")
        s.add_argument("--hold", type=float, help="seconds each step stays on screen")
        s.add_argument("--fresh", action="store_true", help="clear cookies and storage before tab setup (clean login)")
        s.add_argument(
            "--keep-session", action="store_true", help="leave the browser session open afterwards (for --from-step)"
        )
        s.add_argument(
            "--allow-writes", action="store_true", help="dry-run: also run steps that write data (writes:, write SQL)"
        )
        s.add_argument("--until", metavar="STEP", help="dry-run: stop after this step")
        s.add_argument("--from-step", metavar="STEP", help="dry-run: start at this step in --session's open page")

    def compose_opts(s):
        s.add_argument("--output", help="final video path (default: <timeline dir>/final.mp4)")
        s.add_argument("--lead", type=float, default=0.3, help="seconds kept before each step starts")
        s.add_argument("--title-seconds", type=float, default=3.0)
        s.add_argument("--lang", help="subtitle language to burn in (from per-step subtitle maps)")
        s.add_argument(
            "--voice",
            nargs="?",
            const="auto",
            choices=["auto", "say", "sapi", "espeak", "cmd"],
            help="read each subtitle aloud (OS speech engine) and add it as the video's audio track",
        )
        s.add_argument(
            "--trim-still",
            action="store_true",
            help="fast-forward (8x, badge shown) stretches where the screen does not change for 2 s or more",
        )

    s = sub.add_parser("run", help="run a scenario (--dry-run or --record)")
    run_opts(s)
    mode = s.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--record", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("inspect", help="list each step's page elements with locators + a suggested targets: block")
    s.add_argument("scenario", help="scenario file, or a URL to inspect a single page")
    s.add_argument("--env-file", help="KEY=VALUE file (default: .env next to the scenario)")
    s.add_argument("--out", default="evidence", help="output root; writes <out>/inspect/ (default: evidence/)")
    s.add_argument("--driver", choices=["agent-browser", "bsk"], help="browser driver (default: agent-browser)")
    s.add_argument("--headed", action="store_true", help="show the agent-browser window")
    s.add_argument("--session", help="reuse a live driver session")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("compose", help="build final.mp4 + subtitles + report from a recorded timeline")
    s.add_argument("timeline")
    compose_opts(s)
    s.set_defaults(fn=cmd_compose)

    s = sub.add_parser("record", help="dry-run, record, then compose in one go")
    run_opts(s)
    compose_opts(s)
    s.add_argument("--skip-dry-run", action="store_true")
    s.add_argument(
        "--record-failures", action="store_true", help="record and compose even when a step fails (bug evidence)"
    )
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("install-skill", help="install the tirai-evidence skill for an agent")
    s.add_argument("--agent", action="append", choices=[*TARGETS, "all"], required=True)
    s.add_argument("--project", help="install into this project instead of the user profile")
    s.add_argument("--dest", help="explicit skills directory (overrides --agent paths)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_install_skill)

    s = sub.add_parser("export", help="write junit.xml, xray.json, testrail.csv from an evidence folder (no upload)")
    s.add_argument("dir", nargs="?", default="evidence/record")
    s.add_argument("--format", "-f", action="extend", nargs="+", default=[], help="junit, xray, testrail (default all)")
    s.add_argument("--test-key", help="Xray: existing Jira test issue key (else a new Manual test is described)")
    s.add_argument("--project-key", help="Xray: Jira project key for a new test")
    s.add_argument("--case-id", help="TestRail: case id (e.g. C123) for every row")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("scan-pii", help="OCR the final video for PII the page masking missed (--fix blurs it)")
    s.add_argument("dir", nargs="?", default="evidence/record", help="evidence folder or a video file")
    s.add_argument("--rules", action="extend", nargs="+", default=[], help="email, phone, card, token (default all)")
    s.add_argument("--pattern", action="append", help="extra regex (repeatable)")
    s.add_argument("--keep", action="append", help="exact text allowed to stay visible (repeatable)")
    s.add_argument("--every", type=float, default=1.0, help="seconds between sampled frames")
    s.add_argument("--lang", help="tesseract language(s), e.g. eng+vie")
    s.add_argument("--fix", action="store_true", help="blur every hit in the video and refresh the manifest")
    s.set_defaults(fn=cmd_scan_pii)

    s = sub.add_parser("index", help="one HTML page listing every evidence folder found under DIRS")
    s.add_argument("dirs", nargs="*", default=["evidence"])
    s.add_argument("--out", "-o", default="evidence-index.html")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("sign", help="sign manifest.sha256 with an SSH key (+ optional RFC 3161 timestamp)")
    s.add_argument("dir", nargs="?", default="evidence/record")
    s.add_argument("--key", help="SSH private key (default $TIRAI_SIGN_KEY)")
    s.add_argument(
        "--tsa", nargs="?", const=True, help="add an RFC 3161 timestamp (default TSA freetsa.org, or give a URL)"
    )
    s.set_defaults(fn=cmd_sign)

    s = sub.add_parser("verify", help="check an evidence folder against its manifest.sha256 (and signature)")
    s.add_argument("dir", nargs="?", default="evidence/record")
    s.add_argument("--out", help="same as DIR (the --out folder used with run/record)")
    s.add_argument("--pubkey", help="trusted SSH public key the manifest must be signed with")
    s.add_argument("--allowed-signers", help="ssh allowed_signers file (with --identity)")
    s.add_argument("--identity", default="tirai", help="signer identity in the allowed_signers file")
    s.add_argument("--tsa-ca", help="TSA CA certificate to verify the timestamp chain")
    s.set_defaults(fn=cmd_verify)

    def trace_opts(s):
        s.add_argument("-o", "--output", default="scenario.yaml", help="scenario file to write")
        s.add_argument("--no-resolve", action="store_true", help="skip the replay that resolves CSS selectors")
        s.add_argument("--scope", default="tirai-trace", help="bsk scope for the resolving replay")

    s = sub.add_parser("from-trace", help="convert a `bsk record` trace into a scenario")
    s.add_argument("trace", help="trace.json or the folder that holds it")
    trace_opts(s)
    s.set_defaults(fn=cmd_from_trace)

    s = sub.add_parser("from-spec", help="draft a scenario from a Gherkin .feature, Markdown table or CSV test cases")
    s.add_argument("spec")
    s.add_argument("--output", "-o", help="default: <spec>.yaml")
    s.add_argument("--url", help="resolve element names to selectors on this live page (agent-browser)")
    s.set_defaults(fn=cmd_from_spec)

    s = sub.add_parser("capture", help="record a flow you click through once and turn it into a scenario")
    s.add_argument("url")
    s.add_argument("--driver", choices=["agent-browser", "bsk"], help="default: agent-browser when installed")
    s.add_argument("--timeout", type=float, default=600, help="agent-browser: stop after this many seconds")
    s.add_argument("--purpose", help="what the flow proves; becomes the scenario name")
    s.add_argument("--trace-dir", default="trace", help="bsk: where bsk writes trace.json (default: trace/)")
    trace_opts(s)
    s.set_defaults(fn=cmd_capture)

    s = sub.add_parser("dbx", help="start DBX web (installed by `tirai setup`, else Docker)")
    s.add_argument("--port", type=int, default=int(os.environ.get("DBX_PORT", 4224)))
    s.add_argument("--detach", "-d", action="store_true", help="run in the background (log: ~/.tirai/dbx.log)")
    s.set_defaults(fn=cmd_dbx)
    s = sub.add_parser("dbx-connect", help="create/update a DBX web connection from a DSN (no manual DBX setup)")
    s.add_argument(
        "dsn", nargs="?", help="postgresql://user:pw@host:port/db (prefer --dsn-env to keep it out of shell history)"
    )
    s.add_argument("--dsn-env", help="read the DSN from this environment variable, e.g. EV_DB_DSN")
    s.add_argument("--name", required=True, help="connection name shown in DBX")
    s.add_argument("--url", default=os.environ.get("DBX_URL", "http://127.0.0.1:4224/"), help="DBX web URL")
    s.add_argument("--db-host", help="database host as DBX sees it (e.g. a Docker service name)")
    s.add_argument("--password-env", default="DBX_PASSWORD", help="env var holding the DBX web password")
    s.add_argument("--no-test", action="store_true", help="save without asking DBX to test the connection")
    s.set_defaults(fn=cmd_dbx_connect)
    sub.add_parser("mcp", help="run the TIRAI MCP server on stdio (for MCP-capable agents)").set_defaults(fn=cmd_mcp)
    sub.add_parser("annotate-js", help="print the path of the injectable annotate.js").set_defaults(fn=cmd_asset)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        code = args.fn(args)
    except KeyboardInterrupt:
        code = 130
    except Exception as e:  # noqa: BLE001 - a tester gets one line; TIRAI_DEBUG=1 shows the traceback
        if os.environ.get("TIRAI_DEBUG"):
            raise
        print(f"error: {e.__class__.__name__}: {e}\n(set TIRAI_DEBUG=1 for the traceback)", file=sys.stderr)
        code = 1
    sys.exit(code)
