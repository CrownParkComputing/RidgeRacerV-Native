#!/usr/bin/env python3
"""Prepare private Ridge Racer V Arcade Battle RRV3/A assets; game data is never distributed.

Requires the user's own SquashFS package, dongle archive and 246C BIOS files.
Existing mutable SRAM, memory-card data and settings are preserved on rerun.
"""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CARD_ENTRY = '246_memcards/rrvac-rrv3vera.bin'
PINS = {
    'proverb.elf': '0739518b76c297d26fcf0eb1b0fd0163cafbc3661b0c40bda7a20974a7c0c28c',
    'sram.bin': '0d550d7fcc2a8c14e3003a948bf4cd0fe3e933791ba3311d2a19e5ea6856dc3b',
    'NM00001 RRV1-A (CD-ROM).chd': '3cd0369703cb45702cd0322d5cd2e17c3c34f4ee8abf8a73533a8c2d3718f265',
    'Ridge Racer V Arcade Battle.acgame': '8e65d9b0de255feb3fa858697af364e0b02ac9fc864cd957805883521e5c3801',
}
CARD_HASH = '5bb6e602bbdf34ba21fe37eda0a38c2d3d0c8a1213bd1dff723aeb701fc46f05'
BIOS_HASH = '8eb8f4d963dde4659de4fbb6eca870077f9af59a9100e8eecd59ec836ff79fae'


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require_hash(path, expected):
    if path.is_symlink() or not path.is_file() or sha(path) != expected:
        raise ValueError('Unexpected private asset or SHA-256 mismatch: ' + str(path))


def safe_private(path, inspect_children=True):
    if '..' in path.parts:
        raise ValueError('Private destination must not contain parent traversal')
    path = path.absolute()
    if not path.is_relative_to((ROOT / '.local').absolute()):
        raise ValueError('Private destination must be inside this project .local directory')
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError('Private destination contains a symlink: ' + str(parent))
    if inspect_children and path.exists():
        for child in path.rglob('*'):
            if child.is_symlink():
                raise ValueError('Unexpected symlink in mutable private storage: ' + str(child))
    return path


def copy_new(source, destination):
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or os.path.samefile(source, destination):
            raise ValueError('Mutable target is not an independent private file: ' + str(destination))
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.ridge-prepare-', dir=destination.parent)
    os.close(descriptor)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        try:
            # Atomic exclusive publication: a concurrent preparation must never
            # replace mutable data created by the first preparer or the game.
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file() or os.path.samefile(source, destination):
                raise ValueError('Concurrent private target is not an independent file: ' + str(destination))
            return False
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def settings():
    values = {
        'UI': {'SettingsVersion': '1', 'SetupWizardIncomplete': 'false', 'PauseOnFocusLoss': 'false'},
        'Filenames': {'BIOS': '246C.bin'},
        'EmuCore': {'EnableFastBoot': 'true', 'EnablePatches': 'false', 'EnableCheats': 'false',
                    'EnableWideScreenPatches': 'false', 'EnableNoInterlacingPatches': 'false',
                    'SaveStateOnShutdown': 'false'},
        'EmuCore/CPU/Recompiler': {'EnableEE': 'true', 'EnableIOP': 'true', 'EnableVU0': 'true',
                                 'EnableVU1': 'true', 'EnableFastmem': 'true'},
        'EmuCore/Speedhacks': {'EECycleRate': '0', 'EECycleSkip': '0', 'vuThread': 'true'},
        'EmuCore/GS': {'Renderer': '14', 'upscale_multiplier': '1', 'AspectRatio': '4:3',
                       'OsdMessagesPos': '0', 'OsdPerformancePos': '0', 'fxaa': 'false',
                       'CASMode': '0', 'CASSharpness': '50', 'VsyncEnable': 'false', 'VsyncQueueSize': '2'},
        'InputSources': {'SDL': 'false', 'Evdev': 'false'},
        'MemoryCards': {'Slot1_Filename': 'NM00001.ps2', 'Slot2_Filename': ''},
        'USB1': {'Type': 'None'},
        'USB2': {'Type': 'None'},
        'JVS': {'ToggleTestMode': 'Keyboard/F9', 'Coin1': 'Keyboard/5',
                'P1_Start': 'Keyboard/Return', 'P1_Button1': 'Keyboard/Return',
                'P1_Service': 'Keyboard/9', 'P1_Up': 'Keyboard/Up', 'P1_Down': 'Keyboard/Down',
                'P1_Left': 'Keyboard/Left', 'P1_Right': 'Keyboard/Right',
                'SteerLeft': 'Keyboard/A', 'SteerRight': 'Keyboard/D',
                'Gas': 'Keyboard/W', 'Brake': 'Keyboard/S',
                'Racing_ShiftUp_P1': 'Keyboard/E', 'Racing_ShiftDown_P1': 'Keyboard/Q',
                'Racing_View_P1': 'Keyboard/V', 'AnalogDeadzone': '0',
                'AnalogSensitivity': '1', 'TriggerDeadzone': '0', 'InvertSteering': 'false'},
    }
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read_dict(values)
    return config


def prepare(package, cards, bios, destination):
    local = safe_private(ROOT / '.local', inspect_children=False)
    destination = safe_private(destination)
    # The CHD lives in owned private storage, never in the Git source tree.
    if not destination.is_relative_to(local):
        raise ValueError('Private playtest must remain inside .local')
    bios = bios.resolve()
    require_hash(bios / '246C.bin', BIOS_HASH)
    for name in ('246C.nvm', '246C.mec'):
        if not (bios / name).is_file():
            raise ValueError('Supply the existing BIOS companion file: ' + str(bios / name))
    local.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cards) as archive:
        info = archive.getinfo(CARD_ENTRY)
        if info.file_size != 8650752:
            raise ValueError('Unexpected raw PS2 dongle size')
        card = archive.read(info)
    if hashlib.sha256(card).hexdigest() != CARD_HASH or not card.startswith(b'Sony PS2 Memory Card Format '):
        raise ValueError('Ridge V raw memory-card identity mismatch')
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='ridge-extract-', dir=local) as temporary:
        unpacked = Path(temporary) / 'package'
        subprocess.run(['unsquashfs', '-no-progress', '-processors', '2', '-d', str(unpacked),
                        str(package.resolve()), *PINS], check=True, stdout=subprocess.DEVNULL)
        for name, expected in PINS.items():
            require_hash(unpacked / name, expected)
            hashes[name] = expected
        asset = local / 'assets'
        safe_private(asset)
        asset.mkdir(parents=True, exist_ok=True)
        original_card = Path(temporary) / 'NM00001.ps2'
        original_card.write_bytes(card)
        for source, target, expected in [
            (original_card, asset / 'NM00001-original.ps2', CARD_HASH),
            (unpacked / 'NM00001 RRV1-A (CD-ROM).chd', asset / 'NM00001.chd', PINS['NM00001 RRV1-A (CD-ROM).chd']),
        ]:
            if target.exists():
                require_hash(target, expected)
            else:
                copy_new(source, target)
        games = destination / 'games'
        games.mkdir(parents=True, exist_ok=True)
        # Immutable CD image is independent of the source package and original media.
        media = games / 'NM00001.chd'
        if media.exists():
            require_hash(media, PINS['NM00001 RRV1-A (CD-ROM).chd'])
        else:
            copy_new(asset / 'NM00001.chd', media)
        for source, target in [
            (unpacked / 'proverb.elf', games / 'proverb.elf'),
            (unpacked / 'sram.bin', games / 'sram.bin'),
            (asset / 'NM00001-original.ps2', destination / 'PCSX2x6/memcards/NM00001.ps2'),
            *[(bios / name, destination / 'PCSX2x6/bios' / name) for name in ('246C.bin', '246C.nvm', '246C.mec')],
        ]:
            copy_new(source, target)
        require_hash(games / 'proverb.elf', PINS['proverb.elf'])
        require_hash(destination / 'PCSX2x6/bios/246C.bin', BIOS_HASH)
    ini = destination / 'PCSX2x6/inis/PCSX2.ini'
    ini.parent.mkdir(parents=True, exist_ok=True)
    if not ini.exists():
        with ini.open('x') as output:
            settings().write(output)
    manifest = games / 'NM00001.acgame'
    if not manifest.exists():
        config = configparser.ConfigParser(interpolation=None)
        config.read_dict({'game': {'name': 'Ridge Racer V Arcade Battle [RRV3 Ver. A]',
                                  'gameid': 'NM00001', 'platform': '246'},
                          'data': {'subdir': '', 'elf': 'proverb.elf', 'dongle': 'NM00001.ps2',
                                   'mediasrc': 'NM00001.chd', 'media': 'CD', 'sram': 'sram.bin',
                                   'jvsmode': 'racing'}})
        with manifest.open('x') as output:
            config.write(output)
    for directory in ('logs', 'cache', 'snaps', 'sstates'):
        (destination / 'PCSX2x6' / directory).mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 1, 'game': 'NM00001', 'variant': 'RRV3 Ver. A',
              'data_root': str(destination), 'manifest': str(manifest),
              'private_asset_sha256': {**hashes, 'dongle': CARD_HASH, 'bios': BIOS_HASH},
              'mutable_files': 'Independent private copies; existing files preserved',
              'dual_screen': 'Not implemented or validated for Ridge V; TC3 link adapter must stay disabled until Ridge firmware-specific validation'}
    (destination / 'preparation.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path, help='User-owned Ridge Racer V Arcade Battle.squashfs')
    parser.add_argument('--cards', required=True, type=Path, help='User-owned 246_memcards.zip')
    parser.add_argument('--bios-dir', required=True, type=Path, help='Directory with 246C.bin/.nvm/.mec')
    parser.add_argument('--data-root', type=Path, default=ROOT / '.local/playtest')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.package, args.cards, args.bios_dir, args.data_root), indent=2))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Ridge V preparation failed: {error}\n')


if __name__ == '__main__':
    main()
