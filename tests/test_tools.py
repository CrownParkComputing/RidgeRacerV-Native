import configparser
import importlib.util
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

PREP = module('prepare_ridge')
RUN = module('run_ridge')
with patch.object(sys, 'path', [str(ROOT / 'tools'), *sys.path]):
    PAIR = module('run_ridge_link_test')

class PreparationTests(unittest.TestCase):
    def test_mutable_copy_is_independent_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'private/card'
            source.write_bytes(b'original card')
            self.assertTrue(PREP.copy_new(source, target))
            target.write_bytes(b'game-modified card')
            self.assertFalse(PREP.copy_new(source, target))
            self.assertEqual(target.read_bytes(), b'game-modified card')
            self.assertEqual(source.read_bytes(), b'original card')
            self.assertNotEqual(source.stat().st_ino, target.stat().st_ino)

    def test_private_destination_rejects_symlink_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / '.local'; local.mkdir()
            actual = local / 'actual'; actual.mkdir()
            (local / 'alias').symlink_to(actual, target_is_directory=True)
            with patch.object(PREP, 'ROOT', root):
                with self.assertRaises(ValueError):
                    PREP.safe_private(local / 'alias/playtest')
                with self.assertRaises(ValueError):
                    PREP.safe_private(root / 'outside')
                with self.assertRaises(ValueError):
                    PREP.safe_private(local / '../outside')

    def test_settings_select_ridge_dongle_and_disable_patches(self):
        config = PREP.settings()
        self.assertEqual(config.get('MemoryCards', 'Slot1_Filename'), 'NM00001.ps2')
        self.assertFalse(config.getboolean('EmuCore', 'EnablePatches'))
        self.assertFalse(config.getboolean('EmuCore', 'EnableCheats'))
        self.assertEqual(config.get('EmuCore/GS', 'Renderer'), '14')
        self.assertFalse(config.getboolean('InputSources', 'SDL'))
        self.assertEqual(config.get('JVS', 'SteerLeft'), 'Keyboard/A')
        self.assertEqual(config.get('JVS', 'SteerRight'), 'Keyboard/D')
        self.assertEqual(config.get('JVS', 'Gas'), 'Keyboard/W')
        self.assertEqual(config.get('JVS', 'Brake'), 'Keyboard/S')
        self.assertEqual(config.get('JVS', 'Racing_ShiftUp_P1'), 'Keyboard/E')
        self.assertEqual(config.get('JVS', 'Racing_ShiftDown_P1'), 'Keyboard/Q')
        self.assertEqual(config.get('JVS', 'Racing_View_P1'), 'Keyboard/V')

class LaunchTests(unittest.TestCase):
    def test_tc3_cabinet_adapter_is_removed(self):
        with patch.dict(os.environ, {'TC3_CABINET_ROLE': 'right', 'TC3_CABINET_DIR': '/private/session'}):
            env = RUN.environment()
            self.assertNotIn('TC3_CABINET_ROLE', env)
            self.assertNotIn('TC3_CABINET_DIR', env)

    def test_wrong_game_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'games').mkdir(); (data / 'PCSX2x6/inis').mkdir(parents=True)
            (data / 'PCSX2x6/inis/PCSX2.ini').write_text('[Filenames]\nBIOS=246C.bin\n')
            manifest = data / 'games/NM00001.acgame'
            manifest.write_text('[game]\ngameid=NM00012\nplatform=246\n[data]\nmedia=DVD\n')
            with self.assertRaises(ValueError):
                RUN.command_for(Path('/foundation/tc3-native'), data)
            manifest.write_text('[game]\ngameid=NM00001\nplatform=246\n[data]\nmedia=CD\n')
            command = RUN.command_for(Path('/foundation/tc3-native'), data, 90)
            self.assertEqual(command[-2:], ['--seconds', '90'])
            self.assertIn(str(manifest), command)

    def test_foundation_path_is_explicit_and_configurable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                RUN.foundation_path(None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / '.local/core-build/bin/tc3-native'
            binary.parent.mkdir(parents=True); binary.write_text('#!/bin/sh\n'); binary.chmod(0o700)
            self.assertEqual(RUN.foundation_path(root), (root, binary))
            with patch.dict(os.environ, {'TC3_NATIVE_ROOT': str(root)}):
                self.assertEqual(RUN.foundation_path(None), (root, binary))

class PairStorageTests(unittest.TestCase):
    def test_cabinets_preserve_independent_mutable_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / '.local/playtest'
            source.mkdir(parents=True)
            for name in (*PAIR.MUTABLE, 'games/NM00001.acgame'):
                path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'original')
            with patch.object(PAIR, 'safe_private', lambda p: p), \
                 patch.object(PAIR, 'IMMUTABLE', {}), \
                 patch.object(PAIR, 'command_for', lambda *args: []):
                roots = PAIR.prepare_cabinets(source, root / '.local/cabinets')
                left = roots['left'] / 'games/sram.bin'
                right = roots['right'] / 'games/sram.bin'
                left.write_bytes(b'original menu changed cabinet identity')
                PAIR.prepare_cabinets(source, root / '.local/cabinets')
                self.assertEqual(left.read_bytes(), b'original menu changed cabinet identity')
                self.assertEqual(right.read_bytes(), b'original')
                self.assertEqual((source / 'games/sram.bin').read_bytes(), b'original')
                # Accidental cross-cabinet hard links must be rejected too.
                right.unlink(); os.link(left, right)
                with self.assertRaisesRegex(ValueError, 'share a mutable inode'):
                    PAIR.prepare_cabinets(source, root / '.local/cabinets')

    def test_roles_are_explicit_without_inheriting_another_session(self):
        with patch.dict(os.environ, {'TC3_CABINET_ROLE': 'right', 'TC3_CABINET_DIR': '/old'}):
            env = PAIR.worker_environment('left', Path('/new'))
            self.assertEqual(env['TC3_CABINET_ROLE'], 'left')
            self.assertEqual(env['TC3_CABINET_DIR'], '/new')
        with self.assertRaises(ValueError):
            PAIR.worker_environment('third', Path('/new'))

if __name__ == '__main__':
    unittest.main()
