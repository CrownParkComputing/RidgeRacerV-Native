#!/usr/bin/env python3
"""Run Ridge V's compatibility baseline using an explicitly supplied TC3 foundation.

Solo play runs the original RRV3/A program through the shared compatibility
core. --dual-screen launches two linked cabinets through the foundation's
twin-cabinet supervisor (experimental ILSOCK link; linked gameplay is not yet
validated). Android execution is not implemented.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def foundation_path(value):
    value = value or os.environ.get('TC3_NATIVE_ROOT')
    if not value:
        raise ValueError('Pass --foundation or set TC3_NATIVE_ROOT to a built TimeCrisis3-Native checkout')
    root = Path(value).expanduser().resolve()
    binary = root / '.local/core-build/bin/tc3-native'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Build the shared playable foundation first; executable missing: ' + str(binary))
    return root, binary


def command_for(binary, data, seconds=None):
    manifest = data / 'games/NM00001.acgame'
    if not manifest.is_file() or not (data / 'PCSX2x6/inis/PCSX2.ini').is_file():
        raise ValueError('Prepare Ridge V private assets first with tools/prepare_ridge.py')
    import configparser
    config = configparser.ConfigParser(interpolation=None)
    config.read(manifest)
    if (config.get('game', 'gameid', fallback='') != 'NM00001' or
        config.get('game', 'platform', fallback='') != '246' or
        config.get('data', 'media', fallback='') != 'CD'):
        raise ValueError('The private launch manifest is not the expected Ridge V System246 CD game')
    command = [str(binary), '--data-root', str(data), '--boot-manifest', str(manifest)]
    if seconds is not None:
        command += ['--seconds', str(seconds)]
    return command


def environment():
    env = os.environ.copy()
    for key in ('TC3_CABINET_ROLE', 'TC3_CABINET_DIR'):
        env.pop(key, None)
    env.setdefault('SDL_VIDEO_DRIVER', 'x11')
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--foundation', type=Path, help='Built shared foundation, or set TC3_NATIVE_ROOT')
    parser.add_argument('--data-root', type=Path, default=ROOT / '.local/playtest')
    parser.add_argument('--seconds', type=int, help='Stop cleanly after 1..86400 seconds')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Review the launch without running it')
    parser.add_argument('--dual-screen', action='store_true',
        help='Launch two linked cabinets (experimental; linked gameplay is not yet validated)')
    args = parser.parse_args()
    if args.seconds is not None and not 1 <= args.seconds <= 86400:
        parser.error('--seconds must be between 1 and 86400')
    try:
        foundation, binary = foundation_path(args.foundation)
        data = args.data_root.expanduser().resolve()
        if args.dual_screen:
            supervisor = foundation / 'tools/run_cabinet_pair.py'
            if not supervisor.is_file():
                parser.error(f'Twin-cabinet supervisor missing in foundation: {supervisor}')
            command = ['python3', str(supervisor),
                       '--source', str(data),
                       '--manifest', 'NM00001.acgame',
                       '--state-root', str(ROOT / '.local')]
            if args.seconds is not None:
                command += ['--seconds', str(args.seconds)]
            if args.background:
                command += ['--background']
            if args.dry_run:
                print(json.dumps({'command': command}, indent=2))
                return 0
            print('Starting the linked Ridge V twin cabinet (experimental link transport).', flush=True)
            return subprocess.call(command, cwd=ROOT, env=environment())
        command = command_for(binary, data, args.seconds)
        env = environment()
        if args.dry_run:
            print(json.dumps({'command': command, 'TC3_cabinet_adapter_enabled': False}, indent=2))
            return 0
        local = ROOT / '.local'
        local.mkdir(exist_ok=True)
        pidfile = local / 'ridge-live.pid'
        if pidfile.exists():
            try:
                previous = int(pidfile.read_text())
                old = Path(f'/proc/{previous}/cmdline').read_bytes().split(b'\0')
                if os.fsencode(str(data / 'games/NM00001.acgame')) in old:
                    parser.error(f'Ridge V is already running with this data root (PID {previous})')
            except (OSError, ValueError):
                pass
        print('Starting the Ridge V compatibility baseline; full native translation remains incomplete.', flush=True)
        if args.background:
            log = local / 'ridge-live.log'
            with log.open('w') as output:
                child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            pidfile.write_text(str(child.pid) + '\n')
            print(f'Ridge V PID: {child.pid}; log: {log}', flush=True)
            return 0
        return subprocess.call(command, cwd=ROOT, env=env)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Ridge V launch failed: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
