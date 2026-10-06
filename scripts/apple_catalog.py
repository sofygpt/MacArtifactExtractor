"""Resolve Tahoe from Apple's public catalog; no third-party installer index."""
import argparse
import datetime
import gzip
import hashlib
import json
import plistlib
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from core import apple_url

CATALOG_URL = ('https://swscan.apple.com/content/catalogs/others/index-26-15-14-13-12-'
               '10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9-'
               'mountainlion-lion-snowleopard-leopard.merged-1.sucatalog')


class AppleRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Validate BEFORE following a redirect, including the host and TLS scheme.
        return super().redirect_request(req, fp, code, msg, headers, apple_url(newurl))


def apple_open(url, timeout=90):
    req = urllib.request.Request(apple_url(url), headers={'User-Agent': 'TahoeHfsPlusExtractor/1.0'})
    return urllib.request.build_opener(AppleRedirect()).open(req, timeout=timeout)


def fetch(url):
    with apple_open(url) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError('Metadata exceeds 64 MiB')
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    return data


def parse_distribution(data):
    root = ET.fromstring(data)
    values = {}
    for d in root.iter('dict'):
        children = list(d)
        for a, b in zip(children, children[1:]):
            if a.tag == 'key' and b.tag == 'string':
                values[a.text] = b.text or ''
    version = values.get('macOSProductVersion', values.get('VERSION', ''))
    build = values.get('macOSProductBuildVersion', values.get('BUILD', ''))
    if not version or not build:
        raise ValueError('Distribution has no macOS version/build metadata')
    return version, build


def select_product(rows, version='', build=''):
    if version and not re.fullmatch(r'26(?:\.\d+){1,2}', version):
        raise ValueError('Requested version must be an exact Tahoe 26.x version')
    if build and not re.fullmatch(r'25[A-Z]\d+', build):
        raise ValueError('Requested build must be a stable Tahoe 25-series build')
    eligible = [r for r in rows if re.fullmatch(r'26(?:\.\d+){1,2}', r.get('version', ''))
                and re.fullmatch(r'25[A-Z]\d+', r.get('build', ''))
                and (not version or r['version'] == version)
                and (not build or r['build'] == build)]
    if not eligible:
        raise ValueError('No matching stable Tahoe InstallAssistant.pkg in Apple catalog')
    def order(row):
        parts = tuple(int(x) for x in row['version'].split('.'))
        return (parts + (0,) * (3 - len(parts)), row.get('post_date', ''), row['build'])
    return max(eligible, key=order)


def resolve(version='', build='', catalog_url=CATALOG_URL):
    data = fetch(catalog_url)
    catalog = plistlib.loads(data)
    rows, errors = [], []
    for product_id, product in catalog.get('Products', {}).items():
        packages = [p for p in product.get('Packages', [])
                    if p.get('URL', '').split('?')[0].endswith('/InstallAssistant.pkg')]
        if len(packages) != 1:
            continue
        distributions = product.get('Distributions', {})
        dist_url = distributions.get('English') or distributions.get('en')
        if not dist_url:
            errors.append({'product_id': product_id, 'error': 'No English distribution'})
            continue
        try:
            dist = fetch(dist_url)
            v, b = parse_distribution(dist)
            p = packages[0]
            size = int(p['Size'])
            if size <= 0:
                raise ValueError('Invalid package size')
            rows.append({'product_id': product_id, 'version': v, 'build': b,
                         'package_url': apple_url(p['URL']), 'package_size_bytes': size,
                         'distribution_url': apple_url(dist_url),
                         'distribution_sha256': hashlib.sha256(dist).hexdigest(),
                         'post_date': str(product.get('PostDate', ''))})
        except Exception as exc:
            errors.append({'product_id': product_id, 'error': str(exc)})
    chosen = select_product(rows, version, build)
    return {**chosen, 'catalog_url': apple_url(catalog_url),
            'catalog_sha256': hashlib.sha256(data).hexdigest(),
            'resolved_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'catalog_metadata_errors': errors}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', default='')
    p.add_argument('--build', default='')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = resolve(args.version, args.build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"Selected Tahoe {result['version']} ({result['build']}): {result['package_url']}")


if __name__ == '__main__':
    main()
