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
import threading
import time
import uuid
import zipfile


class ToolError(Exception):
    pass


DEFAULTS = dict(project="sdr", port="auto", baud=1000000, host="", user="",
                identity="", remote_root="C:/sdr-builds",
                vivado="C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat",
                gui_admin_hash="", host_cores=0)

FALLBACK_HOST_CORES = 12
MAX_VIVADO_THREADS = 8  # general.maxThreads limit


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
    if type(config['host_cores']) is not int or not 0 <= config['host_cores'] <= 1024:
        raise ToolError('host_cores must be an integer from 0 (detect on the remote) to 1024.')
    for field in DEFAULTS.keys() - {'baud', 'host_cores'}:
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


_processes = {}  # thread id -> running subprocesses started by run()
_cancelled = set()  # thread ids whose workflow was cancelled
_processes_lock = threading.Lock()


def cancel_threads(idents):
    """Stop the subprocesses of these threads and refuse to start new ones."""
    with _processes_lock:
        _cancelled.update(idents)
        running = [p for i in idents for p in _processes.get(i, ())]
    for process in running:
        try:
            process.terminate()
        except OSError:
            pass


def run(args, cwd=None, log=print):
    """Stream output without a shell; a nonzero exit always stops the workflow."""
    ident = threading.get_ident()
    with _processes_lock:
        if ident in _cancelled:
            raise ToolError('Cancelled.')
        try:
            process = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, errors='replace')
        except OSError as exc:
            raise ToolError('Cannot start {}: {}'.format(args[0], exc)) from exc
        _processes.setdefault(ident, set()).add(process)
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
        with _processes_lock:
            _processes[ident].discard(process)
    if result:
        raise ToolError('{} failed (exit {}).'.format(args[0], result))


def source_files(root, project):
    """Explicit allowlist: never upload the checkout or untracked personal files.

    Matches scripts/build.tcl: direct rtl/*.v and *.sv, rom/*.mem memory images
    ($readmemh), and the one project XDC.
    """
    paths = [root / 'scripts/build.tcl', root / 'projects' / project / 'constraints/basys3.xdc']
    rtl = root / 'projects' / project / 'rtl'
    sources = sorted([*rtl.glob('*.v'), *rtl.glob('*.sv')])
    if not sources:
        raise ToolError('No RTL sources found for {}.'.format(project))
    paths += sources + sorted((root / 'projects' / project / 'rom').glob('*.mem'))
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


def thread_count(cores, concurrent):
    """Vivado threads per build: an even share of the host, within 1..8."""
    return max(1, min(MAX_VIVADO_THREADS, cores // max(1, concurrent)))


def host_cores(config, log=print):
    """Core count of the build host: config override, else the remote, else 12."""
    if config.get('host_cores'):
        return config['host_cores']
    lines = []
    try:
        remote(config, 'Write-Output ("CORES=" + $env:NUMBER_OF_PROCESSORS)', lines.append)
        for line in lines:
            match = re.fullmatch(r'CORES=(\d+)', line.strip())
            if match and int(match.group(1)) > 0:
                return int(match.group(1))
    except ToolError:
        pass
    log('Could not read the build host core count; assuming {}.'.format(FALLBACK_HOST_CORES))
    return FALLBACK_HOST_CORES


def pointer_name(variant):
    """Bundle pointer per variant, so concurrent variants never fight over one."""
    return 'latest' if variant == 'default' else 'latest-' + variant


def build(root, config, log=print, demo=False, threads=None):
    """Build uncommitted sources in an isolated remote directory, then fetch results.

    demo=True selects the opt-in APEX flight replay variant of the sdr project
    (sdr_top DEMO_FLIGHT=1). The default build is unchanged. threads is the
    Vivado general.maxThreads for this build; None sizes it for a lone build.
    The completed bundle is selected by build/PROJECT/latest (default variant)
    or build/PROJECT/latest-demo.
    """
    project = config['project']
    variant = 'demo' if demo else 'default'
    if demo and project != 'sdr':
        raise ToolError('The flight replay demo exists only for the sdr project.')
    identifier = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    remote_dir = config['remote_root'].rstrip('/') + '/' + identifier
    target = config['user'] + '@' + config['host']
    ssh_base(config)  # validate before creating anything
    if threads is None:
        threads = thread_count(host_cores(config, log), 1)
    if type(threads) is not int or not 1 <= threads <= MAX_VIVADO_THREADS:
        raise ToolError('Vivado threads must be an integer from 1 to {}.'.format(MAX_VIVADO_THREADS))
    output_root = root / 'build' / project
    output_root.mkdir(parents=True, exist_ok=True)
    log('Building {}{} snapshot {} on {} with {} Vivado threads'.format(
        project, ' (flight replay demo)' if demo else '', identifier, config['host'], threads))
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
                  ' -mode batch -source scripts/build.tcl -tclargs ' + project + ' ' + variant + ' ' + str(threads) +
                  '; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; '
                  'if (!(Test-Path ' + ps_literal('build/' + project + '/' + project + '.bit') +
                  ")) { throw 'Vivado did not produce a bitstream' }")
        remote(config, script, log)
        names = [project + '.bit', 'timing.rpt', 'utilization.rpt', 'drc.rpt']
        run(ssh_base(config, scp=True) + [target + ':' + remote_dir + '/build/' + project + '/' + name
                                        for name in names] + [str(local)], log=log)
        if not (local / (project + '.bit')).stat().st_size:
            raise ToolError('Downloaded bitstream is empty; previous build was preserved.')
        manifest = dict(project=project, variant=variant, source_sha256=digest, threads=threads,
                        bitstream_sha256=hashlib.sha256((local / (project + '.bit')).read_bytes()).hexdigest(),
                        built_at=time.time(), remote_dir=remote_dir, host=config['host'])
        # Keep completed builds as immutable sets. A per-variant pointer selects the whole set.
        bundle = output_root / 'artifacts' / identifier
        bundle.mkdir(parents=True)
        for name in names:
            shutil.copy2(local / name, bundle / name)
        (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        pointer = output_root / (pointer_name(variant) + '-' + identifier + '.tmp')
        pointer.write_text(identifier + '\n')
        pointer.replace(output_root / pointer_name(variant))
        log('Build complete ({} variant): {}'.format(variant, bundle / (project + '.bit')))
        if source_digest(root, project) != digest:
            log('Sources changed during this build. Rebuild before programming the current source.')
        log('Reports saved alongside the bitstream. Remote logs retained in ' + remote_dir)
        return bundle / (project + '.bit')


def build_variants(root, config, variants=('default', 'demo'), log=print):
    """Build several variants at the same time; returns {variant: bitstream path}.

    The host core count is read once and split evenly. Every build has its own
    remote directory, local temp directory and bundle. Log lines are prefixed
    with the variant. All builds run to completion; any failure is then raised.
    """
    variants = list(dict.fromkeys(variants))
    if len(variants) == 1:
        return {variants[0]: build(root, config, log, demo=variants[0] == 'demo')}
    if 'demo' in variants and config['project'] != 'sdr':
        raise ToolError('The flight replay demo exists only for the sdr project.')
    ssh_base(config)
    cores = host_cores(config, log)
    threads = thread_count(cores, len(variants))
    log('Building {} concurrently: {} host cores, {} Vivado threads each.'.format(
        ' + '.join(variants), cores, threads))
    lock = threading.Lock()
    results, errors = {}, {}

    def work(variant):
        def prefixed(line):
            with lock:
                log('[{}] {}'.format(variant, line))
        try:
            results[variant] = build(root, config, prefixed, demo=variant == 'demo', threads=threads)
        except BaseException as exc:  # reported after the other builds finish
            errors[variant] = exc
            prefixed('FAILED: {}'.format(exc))
        finally:
            with _processes_lock:
                _cancelled.discard(threading.get_ident())

    workers = [threading.Thread(target=work, args=(v,), name='sdr-build-' + v, daemon=True) for v in variants]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join()
    except BaseException:
        # Stop the local ssh/scp children, wait for the workers to unwind, then re-raise.
        cancel_threads([w.ident for w in workers])
        for worker in workers:
            worker.join(timeout=10)
        with _processes_lock:
            _cancelled.difference_update(w.ident for w in workers)  # thread ids get reused
        unfinished = [v for v in variants if v not in results]
        log('Cancelled: {} not completed. Remote Vivado processes may keep running on {}; '
            'their directories are under {}.'.format(', '.join(unfinished) or 'none', config['host'],
                                                     config['remote_root']))
        raise
    if errors:
        raise ToolError('Build failed for: ' + '; '.join('{} ({})'.format(v, e) for v, e in errors.items()))
    return {v: results[v] for v in variants}


def bitstream(root, project, demo=False):
    out = root / 'build' / project
    pointer = out / pointer_name('demo' if demo else 'default')
    if pointer.exists():
        name = pointer.read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9-]+', name):
            raise ToolError('Invalid build/{} pointer.'.format(pointer.name))
        return out / 'artifacts' / name / (project + '.bit')
    if demo:
        raise ToolError('No demo build found. Run sdr build --demo (or --all) first.')
    return out / (project + '.bit')


def program(root, config, persist=False, path=None, log=print, demo=False):
    """Program the default bundle (build/PROJECT/latest), or with demo=True the
    flight replay bundle (latest-demo). Concurrent builds never share a pointer."""
    bit = Path(path).expanduser().resolve() if path else bitstream(root, config['project'], demo)
    if not bit.is_file() or bit.stat().st_size == 0:
        raise ToolError('No bitstream found. Run sdr build first, or specify --bit PATH.')
    manifest_path = bit.parent / 'manifest.json'
    if path is None and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['source_sha256'] != source_digest(root, config['project']):
            raise ToolError('Sources have changed since this build. Run sdr build, or deliberately select --bit PATH.')
        if manifest['bitstream_sha256'] != hashlib.sha256(bit.read_bytes()).hexdigest():
            raise ToolError('Bitstream checksum does not match the build manifest.')
        if manifest.get('variant', 'default') != 'default' and not demo:
            log('Selected build is the {} variant (APEX flight replay). Use sdr program (no --demo) for '
                'the default bundle.'.format(manifest['variant']))
    elif path is None:
        log('Using existing bitstream without a source manifest: ' + str(bit))
    log(('Writing persistent flash: ' if persist else 'Programming volatile FPGA memory: ') + str(bit))
    run(['openFPGALoader', '-b', 'basys3'] + (['-f'] if persist else []) + [str(bit)], cwd=root, log=log)
    log('Programming complete.')
