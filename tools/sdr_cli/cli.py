"""Inline commands and entry point."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

from . import __version__
from .protocol import format_record, summarize
from .core import (ToolError, build, load_config, program, remote, repo_root,
                   run, save_config, simulate, ps_literal)
from .serial_io import Session, ports, resolve_port, serial_module


def parser():
    p = argparse.ArgumentParser(prog='sdr', description='Basys 3 SDR workbench. Run without a command to open the dashboard.')
    p.add_argument('--version', action='version', version='sdr ' + __version__)
    p.add_argument('--repo', type=Path, help='FPGA repository (default: current checkout)')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('tui', help='Open the full-screen dashboard')
    setup = sub.add_parser('setup', help='Configure this checkout; omitted values are preserved')
    for field, help_text in [('host', 'Windows hostname or Tailscale IP'), ('user', 'Windows username'),
                             ('identity', 'SSH private key PATH (never copied)'), ('remote-root', 'Windows snapshot directory'),
                             ('vivado', 'Full Windows path to vivado.bat'), ('port', 'UART device, or auto')]:
        setup.add_argument('--' + field, help=help_text)
    setup.add_argument('--baud', type=int)
    setup.add_argument('--project', choices=['sdr', 'blink'])
    setup.add_argument('--interactive', action='store_true', help='Prompt for connection settings')
    doctor = sub.add_parser('doctor', help='Check tools and board ports')
    doctor.add_argument('--remote', action='store_true', help='Also check SSH and the Vivado path')
    doctor.add_argument('--board', action='store_true', help='Also query JTAG via openFPGALoader')
    sub.add_parser('ports', help='List serial devices')
    sub.add_parser('config', help='Show effective settings (paths only, no key contents)')
    for name, help_text in [('sim', 'Run FPGA simulation testbenches'), ('build', 'Build current sources on Windows'),
                             ('program', 'Load a bitstream into temporary FPGA memory'),
                             ('flash', 'Write a bitstream to persistent board flash')]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument('--project', choices=['sdr', 'blink'])
        if name in ('program', 'flash'):
            command.add_argument('--bit', type=Path, help='Explicit bitstream (bypasses source freshness check)')
    receive = sub.add_parser('receive', aliases=['rx', 'connect'], help='Read UART until Ctrl-C or a duration expires')
    receive.add_argument('--port')
    receive.add_argument('--baud', type=int)
    receive.add_argument('--seconds', type=float, default=0, help='0 means continuous')
    receive.add_argument('--format', choices=['decoded', 'records', 'text', 'hex', 'raw', 'json'], default='decoded',
                         help='decoded: one line per link message (default); records: JSON lines; '
                              'text/hex/raw/json: undecoded UART bytes')
    receive.add_argument('--output', type=Path, help='Also record exact raw bytes to a NEW file')
    send = sub.add_parser('send', help='Write raw UART data; current FPGA diagnostic has no command receiver')
    send.add_argument('data', help='UTF-8 text, or bytes with --hex')
    send.add_argument('--hex', action='store_true', help='DATA is hexadecimal, e.g. "aa 01 ff"')
    send.add_argument('--newline', action='store_true')
    send.add_argument('--port')
    send.add_argument('--baud', type=int)
    return p


def doctor(root, config, check_remote=False, check_board=False, log=print):
    failures = 0
    log('Repository: ' + str(root))
    for executable in ['python3', 'make', 'iverilog', 'vvp', 'ssh', 'scp', 'openFPGALoader']:
        path = shutil.which(executable)
        log(('OK      ' if path else 'MISSING ') + executable + (': ' + path if path else ''))
        failures += not bool(path)
    try:
        serial = serial_module()
        log('OK      pyserial ' + serial.VERSION)
        for item in ports():
            log('PORT    {}  {}'.format(item.device, item.description))
        log('UART    ' + resolve_port(config['port']))
    except ToolError as exc:
        log('MISSING ' + str(exc))
        failures += 1
    log('FPGA    Link is TX-only and its data is SIMULATED; RF stages and receiver controls are not implemented yet.')
    if check_remote:
        try:
            remote(config, "$ErrorActionPreference='Stop'; if (!(Test-Path -LiteralPath " +
                   ps_literal(config['vivado']) + ")) { throw 'Vivado executable not found' }; "
                   "Write-Output 'OK      SSH and Vivado executable (license checked during build)'", log)
        except ToolError as exc:
            log('FAILED  ' + str(exc))
            failures += 1
    if check_board:
        try:
            run(['openFPGALoader', '--detect', '-b', 'basys3'], log=log)
        except ToolError as exc:
            log('FAILED  ' + str(exc))
            failures += 1
    return 1 if failures else 0


def configure(root, config, args):
    fields = ['host', 'user', 'identity', 'remote_root', 'vivado', 'port', 'baud', 'project']
    for field in fields:
        value = getattr(args, field, None)
        if value is not None:
            config[field] = value
    if args.interactive:
        if not sys.stdin.isatty():
            raise ToolError('Interactive setup needs a terminal. Use setup flags instead.')
        for field in fields:
            value = input('{} [{}]: '.format(field, config[field])).strip()
            if value:
                config[field] = int(value) if field == 'baud' else value
    save_config(root, config)
    print('Saved local settings to ' + str(root / '.sdr/config.json'))
    print('Check connections: sdr doctor --remote --board')


def receive(config, args):
    if args.seconds < 0:
        raise ToolError('--seconds must be nonnegative.')
    session = Session(config)
    try:
        session.connect()
        if args.output:
            session.start_capture(args.output)
        print('Connected to {} at {} baud. Ctrl-C stops.'.format(session.port, config['baud']), file=sys.stderr)
        started = time.monotonic()
        deadline = started + args.seconds if args.seconds else None
        heartbeats = 0
        while deadline is None or time.monotonic() < deadline:
            data = session.read()
            if not data:
                time.sleep(0.01)
                continue
            if args.format == 'decoded':
                for record in session.last_records:
                    print(format_record(record), flush=True)
                if session.heartbeats > heartbeats:
                    heartbeats = session.heartbeats
                    print('Legacy SDR READY heartbeat: this bitstream predates the link protocol '
                          '(rebuild, or use --format text --baud 115200).', flush=True)
            elif args.format == 'records':
                for record in session.last_records:
                    print(json.dumps(record.as_json()), flush=True)
            elif args.format == 'raw':
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            elif args.format == 'hex':
                print(data.hex(' '), flush=True)
            elif args.format == 'json':
                print(json.dumps(dict(timestamp=time.time(), hex=data.hex(), bytes=len(data))), flush=True)
            else:
                # Preserve ASCII newlines, suppress terminal escape sequences. --raw is byte exact.
                sys.stdout.write(''.join(chr(b) if b in (9, 10, 13) or 32 <= b < 127 else '.' for b in data))
                sys.stdout.flush()
    finally:
        session.close()
        print('\nReceived {} bytes.'.format(session.rx_bytes), file=sys.stderr)
        if session.started is not None:
            for line in summarize(session.decoder.stats, time.monotonic() - session.started):
                print(line, file=sys.stderr)


def main(root=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    args = parser().parse_args()
    try:
        root = (args.repo or root or repo_root()).expanduser().resolve()
        if not (root / 'scripts/build.tcl').is_file():
            raise ToolError('Not an FPGA checkout: ' + str(root))
        config = load_config(root)
        for key in ('project', 'port', 'baud'):
            if getattr(args, key, None) is not None:
                config[key] = getattr(args, key)
        from .core import validate_config
        validate_config(config)
        if args.command in (None, 'tui'):
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ToolError('Dashboard needs an interactive terminal. Try sdr --help for inline commands.')
            from .tui import launch
            launch(root, config)
        elif args.command == 'setup':
            configure(root, config, args)
        elif args.command == 'config':
            print(json.dumps(config, indent=2))
        elif args.command == 'ports':
            for port in ports():
                print('{}\t{}\t{}'.format(port.device, port.description, port.serial_number or ''))
        elif args.command == 'doctor':
            return doctor(root, config, args.remote, args.board)
        elif args.command == 'sim':
            simulate(root, config['project'])
        elif args.command == 'build':
            build(root, config)
        elif args.command in ('program', 'flash'):
            program(root, config, persist=args.command == 'flash', path=args.bit)
        elif args.command in ('receive', 'rx', 'connect'):
            receive(config, args)
        elif args.command == 'send':
            data = bytes.fromhex(args.data) if args.hex else args.data.encode('utf-8')
            if args.newline:
                data += b'\n'
            session = Session(config)
            try:
                session.connect()
                session.send(data)
                print('Sent {} bytes. No receiver command/acknowledgement protocol is implemented yet.'.format(len(data)))
            finally:
                session.close()
        return 0
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except (ToolError, OSError, ValueError, KeyError) as exc:
        print('sdr: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
