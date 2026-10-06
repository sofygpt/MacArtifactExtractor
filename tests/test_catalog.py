import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from apple_catalog import CATALOG_URL, parse_distribution, select_product


class CatalogTests(unittest.TestCase):
    def test_public_catalog_uses_apples_big_sur_10_16_alias(self):
        self.assertIn('index-26-15-14-13-12-10.16-', CATALOG_URL)
        self.assertNotIn('-11-', CATALOG_URL)

    def test_embedded_auxinfo_metadata(self):
        xml = b'<installer-gui-script><auxinfo><dict><key>macOSProductVersion</key><string>26.2</string><key>macOSProductBuildVersion</key><string>25C56</string></dict></auxinfo></installer-gui-script>'
        self.assertEqual(parse_distribution(xml), ('26.2', '25C56'))

    def test_newest_stable_tahoe_not_27_or_beta(self):
        rows = [{'version': v, 'build': b, 'product_id': b} for v, b in
                [('26.1', '25B1'), ('26.2', '25C56'), ('27.0', '26A1'), ('26.3', '25D5000a')]]
        self.assertEqual(select_product(rows)['version'], '26.2')

    def test_exact_version_build(self):
        rows = [{'version': '26.2', 'build': '25C56'}, {'version': '26.2', 'build': '25C57'}]
        self.assertEqual(select_product(rows, '26.2', '25C56')['build'], '25C56')
        with self.assertRaises(ValueError):
            select_product(rows, '15.7')
        with self.assertRaises(ValueError):
            select_product(rows, '26.0')

    def test_missing_version_cannot_be_assumed_tahoe(self):
        with self.assertRaises(ValueError):
            parse_distribution(b'<installer-gui-script/>')


if __name__ == '__main__':
    unittest.main()
