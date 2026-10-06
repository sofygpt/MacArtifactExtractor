#!/usr/bin/env python3
"""macOS orchestrator: Apple package -> Intel firmware -> HfsPlus PE32 body."""
import argparse
import datetime
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

from apple_catalog import resolve, apple_open
from core import (HFS_GUID, MAX_FIRMWARE, apple_signature_ok, extract_zip_firmware,
                  firmware_member, pe_metadata, sha256_file, write_candidates)

TOOL_URL = ('https://github.com/LongSoft/UEFITool/releases/download/A75/'
            'UEFIExtract_NE_A75_universal_mac.zip')
TOOL_SHA256 = '8cbdd6d42193d6fb8a0c37dc860b4695c618f923b8ecfff9c0042fbdd80aaa80'


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def command(args, log, timeout=1800, check=True):
    print('Running:', ' '.join(map(str, args)), flush=True)
    with Path(log).open('ab') as f:
        f.write(('COMMAND: ' + ' '.join(map(str, args)) + '\n').encode())
    try:
        result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout,
                                env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'})
    except subprocess.TimeoutExpired as exc:
        with Path(log).open('ab') as f:
            f.write((exc.stdout or b'') + b'\n' + (exc.stderr or b'') + b'\n')
            f.write(f'TIMEOUT: {timeout} seconds\n'.encode())
        raise
    with Path(log).open('ab') as f:
        f.write(result.stdout + b'\n' + result.stderr + b'\n')
        f.write(f'EXIT: {result.returncode}\n'.encode())
    if check and result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}); see {Path(log).name}')
    return result


def download_package(source, target):
    expected = source['package_size_bytes']
    for attempt in range(3):
        try:
            size, next_message = 0, 1024 ** 3
            with apple_open(source['package_url'], timeout=180) as src, target.open('wb') as dst:
                while True:
                    data = src.read(8 * 1024 * 1024)
                    if not data:
                        break
                    size += len(data)
                    if size > expected:
                        raise ValueError('Downloaded package exceeds catalog size')
                    dst.write(data)
                    if size >= next_message:
                        print(f'Apple download: {size / 1024**3:.1f} / {expected / 1024**3:.1f} GiB', flush=True)
                        next_message += 1024 ** 3
            if size != expected:
                raise ValueError(f'Package size mismatch: {size} != {expected}')
            return
        except Exception:
            target.unlink(missing_ok=True)
            if attempt == 2:
                raise
            print('Retrying Apple package download from the start...', flush=True)
            time.sleep(3)


def prepare_tool(work, logs):
    archive = work / 'UEFIExtract-A75.zip'
    command(['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
             '--retry', '3', '--max-time', '600', '--output', archive, TOOL_URL],
            logs / 'tool-download.txt', timeout=700)
    if sha256_file(archive) != TOOL_SHA256:
        raise ValueError('UEFIExtract release checksum mismatch')
    with zipfile.ZipFile(archive) as z:
        entries = [i for i in z.infolist() if Path(i.filename).name.lower() == 'uefiextract'
                   and not i.is_dir() and '__MACOSX' not in i.filename]
        if len(entries) != 1 or entries[0].file_size > 32 * 1024 * 1024:
            raise ValueError('Unexpected UEFIExtract release layout')
        binary = work / 'UEFIExtract'
        binary.write_bytes(z.read(entries[0]))
    binary.chmod(0o755)
    result = command([binary, '--version'], logs / 'tool-version.txt', timeout=60)
    return binary, {'release': 'A75', 'url': TOOL_URL, 'archive_sha256': TOOL_SHA256,
                    'executable_sha256': sha256_file(binary),
                    'reported_version': result.stdout.decode(errors='replace').strip()}


@contextmanager
def mount_readonly(dmg, mountpoint, log):
    mountpoint.mkdir()
    attached = False
    try:
        result = command(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen',
                          '-mountpoint', mountpoint, '-plist', dmg], log, timeout=600)
        attached = True
        state = plistlib.loads(result.stdout)
        matches = [e for e in state.get('system-entities', [])
                   if e.get('mount-point') == str(mountpoint)]
        if len(matches) != 1:
            raise ValueError('Disk image did not mount at the expected private directory')
        yield mountpoint
    finally:
        if attached or os.path.ismount(mountpoint):
            # Detach only the image mounted by this invocation; fail if it remains mounted.
            command(['hdiutil', 'detach', mountpoint], log, timeout=180)


def collect_firmware(root, destination, selected_name, inventory):
    rows = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as z:
                members = [i.filename for i in z.infolist() if firmware_member(i.filename)]
                inventory.append({'archive': relative, 'firmware_members': members})
            if not members:
                continue
            zip_dest = destination / f'zip-{len(inventory):04d}'
            extracted = extract_zip_firmware(path, zip_dest, selected_name)
            archive_digest = sha256_file(path) if extracted else None
            for item in extracted:
                item['archive'] = relative
                item['archive_sha256'] = archive_digest
            rows.extend(extracted)
        elif path.suffix.lower() in ('.fd', '.scap'):
            inventory.append({'direct_firmware': relative})
            if selected_name and path.name != selected_name:
                continue
            if path.stat().st_size > MAX_FIRMWARE:
                raise ValueError('Firmware exceeds size limit: ' + relative)
            direct = destination / 'direct'
            direct.mkdir(parents=True, exist_ok=True)
            out = direct / (f'{len(rows):04d}-' + path.name)
            shutil.copyfile(path, out)
            rows.append({'name': path.name, 'path': str(out), 'member': relative,
                         'archive': None, 'sha256': sha256_file(out),
                         'size_bytes': out.stat().st_size})
    return rows


def extract_drivers(tool, firmwares, work, logs):
    items, scan = [], []
    for index, row in enumerate(firmwares):
        dump = work / f'hfs-dump-{index:04d}'
        log = logs / f'firmware-{index:04d}.txt'
        result = command([tool, row['path'], HFS_GUID, '-o', dump, '-m', 'body', '-t', '10'],
                         log, timeout=180, check=False)
        record = {k: v for k, v in row.items() if k != 'path'}
        record.update({'extractor_returncode': result.returncode, 'log': 'logs/' + log.name,
                       'accepted_pe_sections': 0, 'rejected_sections': []})
        if result.returncode == 0 and dump.is_dir():
            for path in sorted(p for p in dump.rglob('body*.bin')
                               if re.fullmatch(r'body(?:_\d+)?\.bin', p.name)):
                try:
                    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
                        raise ValueError('Unsafe or oversized section')
                    data = path.read_bytes()
                    pe_metadata(data)
                    origin = {k: v for k, v in row.items() if k != 'path'}
                    origin.update({'hfs_guid': HFS_GUID, 'section_type': '0x10',
                                   'section': str(path.relative_to(dump))})
                    items.append((data, origin))
                    record['accepted_pe_sections'] += 1
                except ValueError as exc:
                    record['rejected_sections'].append(str(exc))
        scan.append(record)
        shutil.rmtree(dump, ignore_errors=True)
    return items, scan


def compare_reference(commit, rows, output):
    if not commit:
        return {'status': 'not_requested'}
    url = f'https://raw.githubusercontent.com/acidanthera/OcBinaryData/{commit}/Drivers/HfsPlus.efi'
    with tempfile.TemporaryDirectory(prefix='hfs-reference-') as tmp:
        ref = Path(tmp) / 'reference.efi'
        command(['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                 '--max-time', '120', '--output', ref, url], output / 'logs/reference.txt', timeout=150)
        digest = sha256_file(ref)
    return {'commit': commit, 'url': url, 'sha256': digest,
            'matching_extracted_files': [r['file'] for r in rows if r['sha256'] == digest],
            'status': 'match' if any(r['sha256'] == digest for r in rows) else 'different'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='', help='Exact Tahoe 26.x; empty selects newest stable in catalog')
    parser.add_argument('--build', default='', help='Optional exact stable build, e.g. 25A354')
    parser.add_argument('--firmware-name', default='', help='Optional exact .fd/.scap filename')
    parser.add_argument('--ocbinary-commit', default='', help='Optional full 40-character commit for comparison')
    parser.add_argument('--output', type=Path, default=Path('output'))
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        parser.error('Extraction requires macOS pkgutil and hdiutil. Run the supplied GitHub workflow.')
    if args.ocbinary_commit and not re.fullmatch(r'[0-9a-fA-F]{40}', args.ocbinary_commit):
        parser.error('--ocbinary-commit must be a full 40-character commit SHA')
    if args.firmware_name and not re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:fd|scap)', args.firmware_name):
        parser.error('--firmware-name must be a filename without directories')
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('Output directory must be empty; use a new --output directory')
    output.mkdir(parents=True, exist_ok=True)
    logs = output / 'logs'
    logs.mkdir()
    manifest = {'schema_version': 1, 'status': 'running', 'hfs_guid': HFS_GUID,
                'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'runner': {'os': platform.platform(), 'architecture': platform.machine(),
                           'image_version': os.getenv('ImageVersion', ''),
                           'repository': os.getenv('GITHUB_REPOSITORY', ''),
                           'workflow_commit': os.getenv('GITHUB_SHA', ''),
                           'run_id': os.getenv('GITHUB_RUN_ID', '')}}
    try:
        with tempfile.TemporaryDirectory(prefix='tahoe-hfs-', dir=os.getenv('RUNNER_TEMP')) as tmp:
            work = Path(tmp)
            source = resolve(args.version, args.build)
            manifest['apple_source'] = source
            write_json(output / 'source.json', source)
            print(f"Selected Tahoe {source['version']} ({source['build']})", flush=True)
            # Package and expanded app coexist; leave 8 GiB for archives and private firmware copies.
            needed = 2 * source['package_size_bytes'] + 8 * 1024 ** 3
            available = shutil.disk_usage(work).free
            if available < needed:
                raise RuntimeError(f'Insufficient disk: need {needed / 1024**3:.1f} GiB, free {available / 1024**3:.1f} GiB')
            tool, manifest['extractor'] = prepare_tool(work, logs)
            pkg = work / 'InstallAssistant.pkg'
            download_package(source, pkg)
            manifest['package_sha256'] = sha256_file(pkg)
            result = command(['pkgutil', '--check-signature', pkg], logs / 'apple-signature.txt', timeout=300)
            signature = (result.stdout + result.stderr).decode(errors='replace')
            if not apple_signature_ok(signature, result.returncode):
                raise ValueError('Package is not trusted under the expected Apple Software Update chain')
            manifest['package_signature_verified'] = True
            expanded = work / 'expanded'
            command(['pkgutil', '--expand-full', pkg, expanded], logs / 'package-expand.txt', timeout=2400)
            pkg.unlink()
            images = sorted(expanded.rglob('SharedSupport.dmg'))
            if len(images) != 1:
                raise ValueError(f'Expected one SharedSupport.dmg, found {len(images)}; package layout may have changed')
            image = images[0]
            manifest['shared_support_sha256'] = sha256_file(image)
            manifest['shared_support_package_path'] = str(image.relative_to(expanded))
            inventory = []
            destination = work / 'firmwares'
            destination.mkdir()
            with mount_readonly(image, work / 'shared-support', logs / 'mount.txt') as mount:
                firmwares = collect_firmware(mount, destination, args.firmware_name, inventory)
            write_json(output / 'firmware-inventory.json', inventory)
            if not firmwares:
                raise ValueError('No matching Intel .fd/.scap firmware found in Tahoe SharedSupport; see inventory')
            items, scan = extract_drivers(tool, firmwares, work, logs)
            write_json(output / 'firmware-scan.json', scan)
            rows = write_candidates(items, output)
            manifest['drivers'] = rows
            manifest['canonical_file'] = 'HfsPlus.efi' if len(rows) == 1 else None
            manifest['comparison'] = compare_reference(args.ocbinary_commit, rows, output)
            manifest['status'] = 'extracted' if len(rows) == 1 else 'extracted_multiple_variants'
            summary = (f"Extracted {len(rows)} unique x86_64 HfsPlus driver(s) from Tahoe "
                       f"{source['version']} ({source['build']}).\n")
            if len(rows) > 1:
                summary += 'Multiple variants: use firmware-scan.json to choose, then rerun with firmware_name.\n'
            (output / 'RESULT.txt').write_text(summary)
            print(summary, flush=True)
    except Exception as exc:
        manifest['status'] = 'failed'
        manifest['error'] = str(exc)
        print('ERROR:', exc, file=sys.stderr, flush=True)
        returncode = 1
    else:
        returncode = 0
    finally:
        manifest['finished_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write_json(output / 'manifest.json', manifest)
        paths = sorted(p for p in output.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
        (output / 'SHA256SUMS').write_text(''.join(
            f'{sha256_file(p)}  {p.relative_to(output)}\n' for p in paths))
        if os.getenv('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
                f.write(f"### Tahoe HfsPlus extraction\n\nStatus: `{manifest['status']}`\n\n")
                if manifest.get('error'):
                    f.write('See manifest.json and logs for failure details.\n')
                for row in manifest.get('drivers', []):
                    f.write(f"- `{row['file']}` — SHA-256 `{row['sha256']}`\n")
    return returncode


if __name__ == '__main__':
    sys.exit(main())
