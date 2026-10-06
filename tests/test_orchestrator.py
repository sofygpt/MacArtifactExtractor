import sys
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import extract_tahoe
from core import sha256_file
from test_core import driver


class OrchestratorTests(unittest.TestCase):
    def test_command_timeout_retains_partial_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'command.txt'
            timed_out = subprocess.TimeoutExpired(['hdiutil', 'attach'], 1,
                                                   output=b'partial stdout', stderr=b'partial error')
            with patch.object(extract_tahoe.subprocess, 'run', side_effect=timed_out):
                with self.assertRaises(subprocess.TimeoutExpired):
                    extract_tahoe.command(['hdiutil', 'attach'], log, timeout=1)
            self.assertTrue(log.exists())
            text = log.read_text()
            self.assertIn('partial stdout', text)
            self.assertIn('partial error', text)
            self.assertIn('TIMEOUT', text)

    def test_extractor_collects_numbered_bodies_from_one_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            logs = work / 'logs'
            logs.mkdir()
            firmware = work / 'IM201.fd'
            firmware.write_bytes(b'fixture')
            tool = work / 'fake-extractor'
            # Integration fixture for upstream CLI/output contract; binary execution
            # belongs to the fake extractor, never to the extracted EFI files.
            tool.write_text('#!' + sys.executable + '\n'
                'import pathlib, sys\n'
                "out = pathlib.Path(sys.argv[sys.argv.index('-o')+1]); out.mkdir()\n"
                'out.joinpath("body.bin").write_bytes(bytes.fromhex(' + repr(driver().hex()) + '))\n'
                'out.joinpath("body_1.bin").write_bytes(bytes.fromhex(' + repr(driver(marker=1).hex()) + '))\n')
            tool.chmod(0o755)
            rows = [{'path': str(firmware), 'name': 'IM201.fd'}]
            items, scan = extract_tahoe.extract_drivers(tool, rows, work, logs)
            self.assertEqual(len(items), 2)
            self.assertEqual(scan[0]['accepted_pe_sections'], 2)
            self.assertNotEqual(items[0][0], items[1][0])

    def test_collect_firmware_hashes_large_archive_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'mounted'
            root.mkdir()
            archive = root / 'update.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('AssetData/boot/EFI/EFIPayloads/IM201.fd', b'firmware-a')
                z.writestr('AssetData/boot/EFI/EFIPayloads/MBP161.fd', b'firmware-b')
            reads = []
            def measured(path):
                reads.append(Path(path))
                return sha256_file(path)
            with patch.object(extract_tahoe, 'sha256_file', side_effect=measured):
                rows = extract_tahoe.collect_firmware(root, Path(tmp) / 'out', '', [])
            self.assertEqual(len(rows), 2)
            self.assertEqual(reads.count(archive), 1)
            self.assertEqual(rows[0]['archive_sha256'], rows[1]['archive_sha256'])

    def test_selection_uses_exact_firmware_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'mounted'
            root.mkdir()
            with zipfile.ZipFile(root / 'update.zip', 'w') as z:
                z.writestr('AssetData/boot/EFI/EFIPayloads/IM201.fd', b'firmware-a')
                z.writestr('AssetData/boot/EFI/EFIPayloads/MBP161.fd', b'firmware-b')
            rows = extract_tahoe.collect_firmware(root, Path(tmp) / 'out', 'IM201.fd', [])
            self.assertEqual([r['name'] for r in rows], ['IM201.fd'])


if __name__ == '__main__':
    unittest.main()
