#!/usr/bin/env python3
"""Experimental two-cabinet Ridge link test; linked racing is not yet validated.

Requires a shared foundation containing the guarded RRV3 ILSOCK profile. Cabinet
LINK AS identities must be set using each original service menu, never ROM patches.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import time

from prepare_ridge import copy_new, require_hash, safe_private, PINS, BIOS_HASH
from run_ridge import command_for, environment, foundation_path

ROOT = Path(__file__).resolve().parents[1]
MUTABLE = ('games/sram.bin', 'PCSX2x6/memcards/NM00001.ps2',
           'PCSX2x6/bios/246C.nvm', 'PCSX2x6/bios/246C.mec',
           'PCSX2x6/inis/PCSX2.ini')
IMMUTABLE = {'games/proverb.elf': PINS['proverb.elf'],
             'games/NM00001.chd': PINS['NM00001 RRV1-A (CD-ROM).chd'],
             'PCSX2x6/bios/246C.bin': BIOS_HASH}


def prepare_cabinets(source, cabinet_root):
    source, cabinet_root = safe_private(source), safe_private(cabinet_root)
    if source == cabinet_root or source.is_relative_to(cabinet_root) or cabinet_root.is_relative_to(source):
        raise ValueError('Single-cabinet and paired storage must be separate')
    command_for(Path('/validation-only'), source)
    for name, digest in IMMUTABLE.items():
        require_hash(source / name, digest)
    for name in MUTABLE:
        if not (source / name).is_file():
            raise ValueError('Missing original private prerequisite: ' + name)
    roots = {role: cabinet_root / role for role in ('left', 'right')}
    files = (*IMMUTABLE, *MUTABLE, 'games/NM00001.acgame')
    for root in roots.values():
        safe_private(root)
        for name in files:
            copy_new(source / name, root / name)
        for name, digest in IMMUTABLE.items():
            require_hash(root / name, digest)
        command_for(Path('/validation-only'), root)
        for name in ('logs', 'cache', 'snaps', 'sstates'):
            (root / 'PCSX2x6' / name).mkdir(parents=True, exist_ok=True)
    for name in MUTABLE:
        paths = (source / name, *(root / name for root in roots.values()))
        if len({(p.stat().st_dev, p.stat().st_ino) for p in paths}) != len(paths):
            raise ValueError('Cabinets share a mutable inode: ' + name)
    return roots


def worker_environment(role, session):
    if role not in ('left', 'right'):
        raise ValueError('Unknown cabinet role')
    env = environment()
    # The names describe the shared foundation API. Ridge module guards and
    # original Ridge settings determine protocol/cabinet identity.
    env.update(TC3_CABINET_ROLE=role, TC3_CABINET_DIR=str(session))
    return env


def layout_workers(workers, laid_out):
    try:
        monitors = json.loads(subprocess.check_output(['hyprctl', 'monitors', '-j'], text=True))
        monitor = next((m for m in monitors if m.get('focused')), monitors[0])
        scale = monitor.get('scale', 1)
        width, height = monitor['width'] / scale, monitor['height'] / scale
        game_height = int(min(900, height - 100, (width - 40) * 3 / 8))
        game_width = game_height * 4 // 3
        start_x = monitor['x'] + int((width - game_width * 2 - 12) / 2)
        start_y = monitor['y'] + int((height - game_height) / 2)
        clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'], text=True))
        for index, child in enumerate(workers):
            client = next((c for c in clients if c['pid'] == child.pid), None)
            if client and child.pid not in laid_out:
                address = 'address:' + client['address']
                for operation, value in (
                    ('setfloating', address),
                    ('resizewindowpixel', f'exact {game_width} {game_height},{address}'),
                    ('movewindowpixel', f'exact {start_x + index * (game_width + 12)} {start_y},{address}')):
                    subprocess.run(['hyprctl', 'dispatch', operation, value],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                laid_out.add(child.pid)
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError):
        pass


def run_pair(binary, roots, seconds):
    local = ROOT / '.local'
    session = Path(tempfile.mkdtemp(prefix='ridge-link-'))
    (session / 'control.bin').write_bytes(struct.pack('<5I', 0x54433301, 0, 0, 0, 0))
    report = {'session': str(session), 'experimental': True,
              'linked_gameplay_validated': False, 'workers': {}}
    report_path = local / 'ridge-pair-run.json'
    workers, outputs = [], []
    try:
        for role, root in roots.items():
            log = local / f'ridge-{role}.log'
            output = log.open('w'); outputs.append(output)
            child = subprocess.Popen(command_for(binary, root, seconds), cwd=ROOT,
                env=worker_environment(role, session), stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT)
            workers.append(child)
            report['workers'][role] = {'pid': child.pid, 'log': str(log), 'data_root': str(root)}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        until = time.monotonic() + seconds + 30
        laid_out = set()
        while time.monotonic() < until and all(child.poll() is None for child in workers):
            if len(laid_out) < 2:
                layout_workers(workers, laid_out)
            time.sleep(.2)
    finally:
        for child in workers:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
        for child in workers:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)
        for output in outputs:
            output.close()
        for role, child in zip(roots, workers):
            report['workers'][role]['exit_code'] = child.returncode
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        (session / 'control.bin').unlink(missing_ok=True)
        try:
            session.rmdir()
        except OSError:
            pass
    return 0 if len(workers) == 2 and all(child.returncode == 0 for child in workers) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--foundation', type=Path)
    parser.add_argument('--source-data', type=Path, default=ROOT / '.local/playtest')
    parser.add_argument('--cabinet-root', type=Path, default=ROOT / '.local/cabinets')
    parser.add_argument('--seconds', type=int, default=240)
    parser.add_argument('--experimental-link-test', action='store_true',
                        help='Explicitly run the unvalidated RRV3 cabinet-link experiment')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 86400:
        parser.error('--seconds must be between 1 and 86400')
    if not args.prepare_only and not args.experimental_link_test:
        parser.error('Linked racing is unvalidated; use --experimental-link-test for this diagnostic')
    try:
        _, binary = foundation_path(args.foundation)
        roots = prepare_cabinets(args.source_data, args.cabinet_root)
        if args.prepare_only:
            print(json.dumps({role: str(root) for role, root in roots.items()}, indent=2))
            return 0
        # Lock the supervisor across preparation/boot without guessing PIDs.
        import fcntl
        with (ROOT / '.local/ridge-pair.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('A Ridge link-test supervisor is already running')
            return run_pair(binary, roots, args.seconds)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Ridge link test failed: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
