"""Automatic source updates from the project's GitHub Releases (standard library)."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.request import Request, urlopen
import zipfile

BASE = Path(__file__).resolve().parent
API = 'https://api.github.com/repos/EzekLobo/codex-pulse/releases/latest'
FILES = {'app.js', 'dashboard.html', 'style.css', 'codex_pulse.py', 'overlay.py',
         'updater.py', 'VERSION', 'pricing.json', 'README.md',
         'iniciar-flutuante-windows.bat', 'iniciar-windows.bat',
         'iniciar-flutuante-macos-linux.sh', 'iniciar-macos-linux.sh'}
MAX_SIZE = 20 * 1024 * 1024


def version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value.strip())
    if not match:
        raise ValueError('Versão inválida')
    return tuple(map(int, match.groups()))


def fetch(url):
    if not url.startswith(('https://api.github.com/', 'https://github.com/EzekLobo/codex-pulse/releases/download/')):
        raise ValueError('Origem de atualização inválida')
    with urlopen(Request(url, headers={'User-Agent': 'Codex-Pulse-Updater',
                                     'Accept': 'application/vnd.github+json'}), timeout=8) as response:
        data = response.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise ValueError('Pacote excede o tamanho permitido')
    return data


def unpack(data, digest):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest or ''):
        raise ValueError('Release sem digest SHA-256 do GitHub')
    if 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Integridade da atualização inválida')
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(i.file_size for i in archive.infolist()) > MAX_SIZE:
            raise ValueError('Conteúdo descompactado excede o limite')
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if entry.is_dir():
                continue
            if len(path.parts) != 1 or path.name not in FILES or path.name in result:
                raise ValueError('Conteúdo inesperado no pacote')
            result[path.name] = archive.read(entry)
    if set(result) != FILES:
        raise ValueError('Pacote incompleto')
    for name, content in result.items():
        if name.endswith('.py'):
            compile(content, name, 'exec')
    return result


def check_and_apply():
    """Run before importing application modules; failures leave the current app usable."""
    if os.environ.get('CODEX_PULSE_AUTO_UPDATE', '1') == '0':
        return False
    # Development checkouts must retain local work.
    if (BASE / '.git').exists():
        return False
    try:
        current = version((BASE / 'VERSION').read_text())
        release = json.loads(fetch(API))
        if release.get('prerelease') or release.get('draft') or version(release['tag_name']) <= current:
            return False
        asset = next(a for a in release['assets'] if a['name'] == 'codex-pulse-update.zip')
        contents = unpack(fetch(asset['browser_download_url']), asset.get('digest'))
        if version(contents['VERSION'].decode()) != version(release['tag_name']):
            raise ValueError('Versão do pacote difere da release')
        # A lock also prevents two launchers applying an update simultaneously.
        lock = BASE / '.update-lock'
        lock.mkdir()
        try:
            with tempfile.TemporaryDirectory(prefix='codex-pulse-backup-') as backup:
                saved = Path(backup)
                existing = {name for name in FILES if (BASE / name).exists()}
                for name in existing:
                    shutil.copy2(BASE / name, saved / name)
                try:
                    for name, content in contents.items():
                        staged = lock / name
                        staged.write_bytes(content)
                        os.replace(staged, BASE / name)
                except Exception:
                    for name in existing:
                        shutil.copy2(saved / name, BASE / name)
                    for name in FILES - existing:
                        (BASE / name).unlink(missing_ok=True)
                    raise
        finally:
            shutil.rmtree(lock)
        return True
    except Exception as exc:
        print(f'Atualização adiada: {exc}')
        return False
