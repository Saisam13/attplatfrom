"""One-time batch re-score of existing runs under the v2 scoring engine
(anchor-band + direct-use dimensions — see docs/PLATFORM_REDESIGN_PLAN.md §2).

Re-runs the full pipeline against each run's original uploaded files (still on
disk under data/uploads/<run_id>/) and overwrites that run's stored scores in
place via the same _execute/_execute_battery path a live run uses, so every
existing run ends up on the same, current, comparable engine_version.

NLP chemical matching is deterministic here as long as the LLM provider is
off (the default) — no re-matching drift versus the original run, only the
scoring math changes.

Usage:  venv\\Scripts\\python -m backend.rescore
"""
import json
import os

from .db import SessionLocal, Run, DATA_DIR, init_db
from . import runner, settings

DEFAULT_BASE = os.path.join(DATA_DIR, 'default_base_portfolio.xlsx')


def rescore_all(kinds=('chemical', 'battery'), log=print):
    init_db()  # ensure additive schema migrations (engine_version etc.) are applied first
    session = SessionLocal()
    try:
        runs = (session.query(Run)
                .filter(Run.status == 'done', Run.kind.in_(kinds))
                .order_by(Run.id).all())
        run_data = [(r.id, r.kind, r.config_json) for r in runs]
    finally:
        session.close()

    results = []
    for run_id, kind, config_json in run_data:
        config = json.loads(config_json or '{}')
        rdir = runner.run_dir(run_id)
        exim_files = [os.path.join(rdir, fname) for fname in config.get('files', [])]
        missing = [f for f in exim_files if not os.path.exists(f)]
        if missing or not exim_files:
            log(f'[rescore] run {run_id} ({kind}): SKIPPED — missing source file(s) {missing or "(none listed)"}')
            results.append((run_id, 'skipped', missing))
            continue

        log(f'[rescore] run {run_id} ({kind}): re-scoring against {len(exim_files)} file(s)...')
        try:
            if kind == 'chemical':
                base_file_name = config.get('base_file', 'default')
                if base_file_name and base_file_name != 'default':
                    custom_base = os.path.join(rdir, 'base_portfolio.xlsx')
                    base_path = custom_base if os.path.exists(custom_base) else DEFAULT_BASE
                else:
                    base_path = DEFAULT_BASE
                llm_config = settings.get('llm', {})
                runner._execute(run_id, exim_files, base_path, config, llm_config)
            else:
                runner._execute_battery(run_id, exim_files, config)
            results.append((run_id, 'done', None))
            log(f'[rescore] run {run_id}: OK')
        except Exception as e:
            results.append((run_id, 'error', str(e)))
            log(f'[rescore] run {run_id}: FAILED — {type(e).__name__}: {e}')

    ok = sum(1 for _, s, _ in results if s == 'done')
    skipped = sum(1 for _, s, _ in results if s == 'skipped')
    errored = sum(1 for _, s, _ in results if s == 'error')
    log(f'[rescore] complete: {ok} re-scored, {skipped} skipped, {errored} failed')
    return results


if __name__ == '__main__':
    rescore_all()
