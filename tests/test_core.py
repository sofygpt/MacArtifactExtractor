import io
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from core import apple_url, pe_metadata, extract_zip_firmware, write_candidates, apple_signature_ok


def driver(machine=0x8664, magic=0x20B, subsystem=11, marker=0):
    data = bytearray(512)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\x00\x00'
    struct.pack_into('<HH', data, 0x84, machine, 1)
    struct.pack_into('<H', data, 0x94, 0xF0)
    struct.pack_into('<H', data, 0x98, magic)
    struct.pack_into('<H', data, 0x98 + 68, subsystem)
    data[-1] = marker
    return bytes(data)


class CoreTests(unittest.TestCase):
    def test_apple_http_upgraded(self):
        self.assertEqual(apple_url('http://swcdn.apple.com/a'), 'https://swcdn.apple.com/a')

    def test_rejects_lookalike_and_credentials(self):
        for value in ['https://apple.com.evil.test/a', 'https://swcdn.apple.com@evil.test/a',
                      'https://user@swcdn.apple.com/a', 'file:///etc/passwd',
                      'https://swcdn.apple.com:444/a']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                apple_url(value)

    def test_accepts_x64_efi(self):
        self.assertEqual(pe_metadata(driver())['architecture'], 'x86_64')

    def test_rejects_other_architecture_or_fake_pe(self):
        for data in [driver(machine=0xAA64), driver(machine=0x14C), driver(magic=0x10B),
                     driver(subsystem=3), b'MZ' + b'\x00' * 512, driver()[:180]]:
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                pe_metadata(data)

    def test_signature_requires_trust_and_apple_update_chain(self):
        valid = 'Status: signed by a certificate trusted by macOS\n1. Software Update\n2. Apple Software Update Certification Authority\n3. Apple Root CA'
        self.assertTrue(apple_signature_ok(valid, 0))
        self.assertFalse(apple_signature_ok(valid, 1))
        self.assertFalse(apple_signature_ok(valid.replace('Software Update', 'Unknown Vendor'), 0))
        self.assertFalse(apple_signature_ok(valid.replace('trusted by', 'untrusted by'), 0))

    def test_extracts_only_firmware_and_does_not_recreate_zip_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'asset.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('AssetData/boot/EFI/EFIPayloads/IM201.fd', b'firmware')
                z.writestr('AssetData/boot/EFI/EFIPayloads/IM201.version', b'info')
                z.writestr('AssetData/big.dmg', b'not extracted')
            rows = extract_zip_firmware(archive, Path(tmp) / 'out')
            self.assertEqual(len(rows), 1)
            self.assertEqual(Path(rows[0]['path']).read_bytes(), b'firmware')
            self.assertEqual(rows[0]['name'], 'IM201.fd')

    def test_rejects_firmware_zip_traversal_and_symlink(self):
        for symlink in [False, True]:
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / 'asset.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    info = zipfile.ZipInfo('AssetData/EFI/../evil.fd' if not symlink else 'AssetData/EFI/evil.fd')
                    if symlink:
                        info.create_system = 3
                        info.external_attr = 0o120777 << 16
                    z.writestr(info, b'bad')
                with self.assertRaises(ValueError):
                    extract_zip_firmware(archive, Path(tmp) / 'out')

    def test_dedup_creates_canonical_only_if_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = write_candidates([(driver(), {'firmware': 'a.fd'}),
                                     (driver(), {'firmware': 'b.fd'})], Path(tmp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(rows[0]['sources']), 2)
            self.assertEqual((Path(tmp) / 'HfsPlus.efi').read_bytes(), driver())

    def test_ambiguity_has_no_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = write_candidates([(driver(), {}), (driver(marker=1), {})], Path(tmp))
            self.assertEqual(len(rows), 2)
            self.assertFalse((Path(tmp) / 'HfsPlus.efi').exists())

    def test_empty_results_are_failure(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            write_candidates([], Path(tmp))


if __name__ == '__main__':
    unittest.main()
