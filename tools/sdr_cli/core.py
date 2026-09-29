"""Configuration and reproducible builds. No terminal UI dependencies."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile


class ToolError(Exception):
    pass


DEFAULTS = dict(project="sdr", port="auto", baud=1000000, host="", user="",
                identity="", remote_root="C:/sdr-builds",
                vivado="C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat",
                gui_admin_hash="")


def repo_root():
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents, Path(__file__).resolve().parents[2]]:
        if (candidate / 'scripts/build.tcl').is_file() and (candidate / 'projects').is_dir():
            return candidate
    raise ToolError('Run inside the fpga repository, or use --repo PATH.')


def load_config(root):
    path = root / '.sdr/config.json'
    config = DEFAULTS.copy()
    if path.exists():
        try:
            saved = json.loads(path.read_text())
            if not isinstance(saved, dict):
                raise ValueError('expected an object')
            config.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except (ValueError, OSError) as exc:
            raise ToolError('Cannot read {}: {}'.format(path, exc)) from exc
    validate_config(config)
    return config


def validate_config(config):
    if config['project'] not in ('sdr', 'blink'):
        raise ToolError('Project must be sdr or blink.')
    if type(config['baud']) is not int or not 300 <= config['baud'] <= 4000000:
        raise ToolError('Baud must be an integer between 300 and 4000000.')
    for field in DEFAULTS.keys() - {'baud'}:
        if not isinstance(config[field], str) or any(ord(c) < 32 for c in config[field]):
            raise ToolError('Invalid {} in configuration.'.format(field))
    for field in ('host', 'user'):
        if config[field] and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', config[field]):
            raise ToolError('{} must be a hostname/IP or simple Windows username.'.format(field))
    path = config['remote_root']
    if not re.fullmatch(r'[A-Za-z]:/[A-Za-z0-9_./-]+', path) or '..' in path.split('/'):
        raise ToolError('remote_root must be an absolute Windows path with forward slashes, without spaces or ..')


def save_config(root, config):
    validate_config(config)
    folder = root / '.sdr'
    folder.mkdir(exist_ok=True)
    temporary = folder / 'config.tmp'
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        if hasattr(os, 'fchmod'):
            os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(config, indent=2) + '\n')
    temporary.replace(folder / 'config.json')


def ps_command(script):
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return 'powershell.exe -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand ' + encoded


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def ssh_base(config, scp=False):
    if not config['host'] or not config['user']:
        raise ToolError('Remote build is not configured. Run sdr setup first.')
    args = ['scp' if scp else 'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']
    if config['identity']:
        key = Path(config['identity']).expanduser()
        if not key.is_file():
            raise ToolError('SSH identity file does not exist: {}'.format(key))
        args += ['-i', str(key), '-o', 'IdentitiesOnly=yes']
    return args


def remote(config, script, log=print):
    target = config['user'] + '@' + config['host']
    return run(ssh_base(config) + [target, ps_command("$ProgressPreference='SilentlyContinue'; " + script)], log=log)


def run(args, cwd=None, log=print):
    """Stream output without a shell; a nonzero exit always stops the workflow."""
    try:
        process = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace')
    except OSError as exc:
        raise ToolError('Cannot start {}: {}'.format(args[0], exc)) from exc
    try:
        for line in process.stdout:
            log(line.rstrip())
        result = process.wait()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        process.stdout.close()
    if result:
        raise ToolError('{} failed (exit {}).'.format(args[0], result))


def source_files(root, project):
    """Explicit allowlist: never upload the checkout or untracked personal files."""
    paths = [root / 'scripts/build.tcl', root / 'projects' / project / 'constraints/basys3.xdc']
    rtl = root / 'projects' / project / 'rtl'
    paths += sorted([*rtl.glob('*.v'), *rtl.glob('*.sv')])
    if len(paths) < 3:
        raise ToolError('No RTL sources found for {}.'.format(project))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ToolError('Missing source or unsupported symlink: {}'.format(path))
    return paths


def source_digest(root, project):
    digest = hashlib.sha256()
    for path in source_files(root, project):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()


def snapshot(root, project, archive):
    digest = hashlib.sha256()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in source_files(root, project):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            digest.update(name.encode() + b'\0' + data + b'\0')
            output.writestr(name, data)
    return digest.hexdigest()


def simulate(root, project, log=print):
    run(['make', 'sim', 'PROJECT=' + project], cwd=root, log=log)


def build(root, config, log=print):
    """Build uncommitted sources in an isolated remote directory, then fetch results."""
    project = config['project']
    identifier = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    remote_dir = config['remote_root'].rstrip('/') + '/' + identifier
    target = config['user'] + '@' + config['host']
    ssh_base(config)  # validate before creating anything
    output_root = root / 'build' / project
    output_root.mkdir(parents=True, exist_ok=True)
    log('Building {} snapshot {} on {}'.format(project, identifier, config['host']))
    with tempfile.TemporaryDirectory(prefix='sdr-build-') as temp:
        local = Path(temp)
        archive = local / 'sources.zip'
        digest = snapshot(root, project, archive)
        remote(config, "$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Force -Path " +
               ps_literal(remote_dir) + ' | Out-Null', log)
        run(ssh_base(config, scp=True) + [str(archive), target + ':' + remote_dir + '/sources.zip'], log=log)
        script = ("$ErrorActionPreference='Stop'; Set-Location " + ps_literal(remote_dir) + '; '
                  "Expand-Archive -LiteralPath sources.zip -DestinationPath . -Force; "
                  '& ' + ps_literal(config['vivado']) +
                  ' -mode batch -source scripts/build.tcl -tclargs ' + project +
                  '; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; '
                  'if (!(Test-Path ' + ps_literal('build/' + project + '/' + project + '.bit') +
                  ")) { throw 'Vivado did not produce a bitstream' }")
        remote(config, script, log)
        names = [project + '.bit', 'timing.rpt', 'utilization.rpt', 'drc.rpt']
        run(ssh_base(config, scp=True) + [target + ':' + remote_dir + '/build/' + project + '/' + name
                                        for name in names] + [str(local)], log=log)
        if not (local / (project + '.bit')).stat().st_size:
            raise ToolError('Downloaded bitstream is empty; previous build was preserved.')
        manifest = dict(project=project, source_sha256=digest,
                        bitstream_sha256=hashlib.sha256((local / (project + '.bit')).read_bytes()).hexdigest(),
                        built_at=time.time(), remote_dir=remote_dir, host=config['host'])
        # Keep completed builds as immutable sets. A single pointer selects the whole set.
        bundle = output_root / 'artifacts' / identifier
        bundle.mkdir(parents=True)
        for name in names:
            shutil.copy2(local / name, bundle / name)
        (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        pointer = output_root / ('latest-' + identifier + '.tmp')
        pointer.write_text(identifier + '\n')
        pointer.replace(output_root / 'latest')
        log('Build complete: {}'.format(bundle / (project + '.bit')))
        if source_digest(root, project) != digest:
            log('Sources changed during this build. Rebuild before programming the current source.')
        log('Reports saved alongside the bitstream. Remote logs retained in ' + remote_dir)
        return bundle / (project + '.bit')


def bitstream(root, project):
    out = root / 'build' / project
    pointer = out / 'latest'
    if pointer.exists():
        name = pointer.read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9-]+', name):
            raise ToolError('Invalid build/latest pointer.')
        return out / 'artifacts' / name / (project + '.bit')
    return out / (project + '.bit')


def program(root, config, persist=False, path=None, log=print):
    bit = Path(path).expanduser().resolve() if path else bitstream(root, config['project'])
    if not bit.is_file() or bit.stat().st_size == 0:
        raise ToolError('No bitstream found. Run sdr build first, or specify --bit PATH.')
    manifest_path = bit.parent / 'manifest.json'
    if path is None and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['source_sha256'] != source_digest(root, config['project']):
            raise ToolError('Sources have changed since this build. Run sdr build, or deliberately select --bit PATH.')
        if manifest['bitstream_sha256'] != hashlib.sha256(bit.read_bytes()).hexdigest():
            raise ToolError('Bitstream checksum does not match the build manifest.')
    elif path is None:
        log('Using existing bitstream without a source manifest: ' + str(bit))
    log(('Writing persistent flash: ' if persist else 'Programming volatile FPGA memory: ') + str(bit))
    run(['openFPGALoader', '-b', 'basys3'] + (['-f'] if persist else []) + [str(bit)], cwd=root, log=log)
    log('Programming complete.')
