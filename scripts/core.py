"""Pure validators and archive/binary handling; never executes an EFI driver."""
import hashlib
import shutil
import stat
import struct
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

APPLE_HOSTS = frozenset({'swscan.apple.com', 'swcdn.apple.com', 'swdist.apple.com',
                         'updates.cdn-apple.com', 'updates-http.cdn-apple.com'})
HFS_GUID = 'AE4C11C8-1D6C-F24E-A183-E1CA36D1A8A9'
MAX_FIRMWARE = 128 * 1024 * 1024


def apple_url(value):
    u = urlsplit(value)
    if (u.scheme not in ('http', 'https') or u.hostname not in APPLE_HOSTS
            or u.username or u.password or u.port not in (None, 80, 443) or u.fragment):
        raise ValueError('Expected an Apple software-update URL: ' + value)
    return urlunsplit(('https', u.hostname, u.path, u.query, ''))


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pe_metadata(data):
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('Missing DOS header')
    offset = struct.unpack_from('<I', data, 0x3C)[0]
    if offset < 64 or offset + 24 > len(data) or data[offset:offset + 4] != b'PE\0\0':
        raise ValueError('Missing PE header')
    machine, sections = struct.unpack_from('<HH', data, offset + 4)
    optional_size = struct.unpack_from('<H', data, offset + 20)[0]
    optional = offset + 24
    if optional_size < 70 or optional + optional_size + sections * 40 > len(data):
        raise ValueError('Truncated PE headers')
    magic = struct.unpack_from('<H', data, optional)[0]
    subsystem = struct.unpack_from('<H', data, optional + 68)[0]
    if machine != 0x8664 or magic != 0x20B or subsystem not in (11, 12) or not sections:
        raise ValueError('Expected x86_64 PE32+ EFI driver')
    return {'architecture': 'x86_64', 'machine': '0x8664', 'pe_magic': '0x020b',
            'subsystem': subsystem, 'size_bytes': len(data)}


def apple_signature_ok(text, returncode):
    return (returncode == 0 and 'Status: signed by a certificate trusted by' in text
            and 'Apple Software Update Certification Authority' in text
            and 'Apple Root CA' in text)


def firmware_member(name):
    p = PurePosixPath(name)
    return (p.suffix.lower() in ('.fd', '.scap')
            and any(part.lower() in ('efi', 'efipayloads', 'firmware') for part in p.parts))


def extract_zip_firmware(archive, destination, selected_name=''):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            if not firmware_member(entry.filename):
                continue
            p = PurePosixPath(entry.filename)
            if ('..' in p.parts or p.is_absolute() or '\\' in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError('Unsafe ZIP firmware entry: ' + entry.filename)
            if selected_name and p.name != selected_name:
                continue
            if entry.file_size > MAX_FIRMWARE:
                raise ValueError('Oversized firmware entry: ' + entry.filename)
            # Use a generated flat name, never recreate any archive-controlled path.
            out = destination / (f'{len(rows):04d}-' + p.name)
            with z.open(entry) as src, out.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            rows.append({'name': p.name, 'path': str(out.resolve()),
                         'archive': str(Path(archive)), 'member': entry.filename,
                         'size_bytes': out.stat().st_size, 'sha256': sha256_file(out)})
    return rows


def write_candidates(items, destination):
    if not items:
        raise ValueError('No valid HfsPlus x86_64 driver extracted; no fallback used')
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'HfsPlus.efi').exists():
        raise ValueError('Output already contains HfsPlus.efi; use a fresh directory')
    folder = out / 'candidates'
    folder.mkdir(exist_ok=True)
    grouped = {}
    for data, source in items:
        meta = pe_metadata(data)
        digest = hashlib.sha256(data).hexdigest()
        if digest not in grouped:
            name = f'candidates/HfsPlus-{digest}.efi'
            (out / name).write_bytes(data)
            grouped[digest] = {**meta, 'sha256': digest, 'file': name, 'sources': []}
        grouped[digest]['sources'].append(source)
    rows = [grouped[d] for d in sorted(grouped)]
    if len(rows) == 1:
        shutil.copyfile(out / rows[0]['file'], out / 'HfsPlus.efi')
    return rows
