"""Small target-local installer helpers. Never connects to another machine."""
from pathlib import Path
import argparse, json, os, platform, shlex, shutil, socket, stat, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parent
HOME=Path(os.environ.get('HERMES_HOME','/root/.hermes'))

def run(*args, capture=False):
    p=subprocess.run([str(x) for x in args],check=True,text=True,stdout=subprocess.PIPE if capture else None)
    return p.stdout.strip() if capture else None

def hermes(*args,capture=False):
    executable=shutil.which('hermes') or str(HOME/'hermes-agent/.hermes/bin/hermes')
    return run(executable,*args,capture=capture)

def runtime():
    data=json.loads(hermes('--print-runtime-command',capture=True))
    if not isinstance(data,list) or '-c' not in data or 'import hermes_bootstrap' not in data[-1]:
        raise RuntimeError('Unsupported Hermes runtime contract; inspect --print-runtime-command')
    return data

def uv():
    found=shutil.which('uv')
    if found:return found
    lock=HOME/'hermes-agent/pm/lock.json'
    if lock.is_file():
        version=json.loads(lock.read_text())['packages']['uv']['version']
        pinned=HOME/'tools'/('uv-'+version+'-linux-x64')/'uv'
        if pinned.is_file():return str(pinned)
    candidates=list((HOME/'tools').glob('uv-*/uv'))
    if len(candidates)==1:return str(candidates[0])
    raise RuntimeError('Stock Hermes uv not resolved; do not install a second uv')

def bootstrap_wrapper(directory,skip_adblock_setup=False):
    argv=runtime(); code=argv[-1].split('runpy.run_module',1)[0]
    code+='sys.argv=sys.argv[1:]; '
    if skip_adblock_setup:
        # HERMES_PYTHON is the upstream-supported interpreter hook. Suppress only
        # its pinned adblock dependency helper, not generic extension control.
        code+='sys.exit(0) if sys.argv==["/usr/local/libexec/procvetaev-browser-harness/install-browser-extensions","--configure-hermes"] else None; '
    code+='exec(sys.argv[1]) if sys.argv[0]=="-c" else runpy.run_path(sys.argv[0],run_name="__main__")'
    path=Path(directory)/'hermes-python'
    path.parent.mkdir(parents=True,exist_ok=True)
    put(path,'#!/bin/sh\nexec '+shlex.join([*argv[:-1],code])+' "$@"\n',0o700)
    run(path,'-c','import hermes_cli.config')
    return path

def put(path,text,mode=0o644):
    path=Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise RuntimeError('Symlink destination refused')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.installer-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write(text);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),mode)
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

def source(name):return (ROOT/name).read_text(encoding='utf-8')
def copy_source(name,destination,mode=0o644):put(destination,source(name),mode)
def require(condition,message):
    if not condition:raise RuntimeError(message)
def active(*units):run('systemctl','is-active',*units)
def denial(url,expected):
    from urllib.request import urlopen
    from urllib.error import HTTPError, URLError
    import time
    deadline=time.monotonic()+15
    while True:
        try:
            with urlopen(url,timeout=5) as r:code=r.status
            break
        except HTTPError as e:code=e.code;break
        except URLError:
            if time.monotonic()>=deadline:raise
            time.sleep(0.1)
    require(code in expected,'Unexpected denial response')

def config_set(key,value):hermes('config','set','--force',key,value)
def config_equal(key,value):require(hermes('config','get',key,capture=True).strip()==value,'Config mismatch: '+key)

def host(args,write=False):
    require(platform.system()=='Linux','Target command requires Linux; Windows controller must use offline only')
    require(os.geteuid()==0,'Target commands require root')
    require(HOME==Path('/root/.hermes'),'Accepted systemd layout requires /root/.hermes')
    require(bool(args.target_hostname) and socket.gethostname()==args.target_hostname,'Exact --target-hostname required')
    if write:
        require(args.confirm_install,'Install needs --confirm-install after operator backup/reinstall')
        if socket.gethostname()=='vps-test':require(args.after_reinstall,'Protected comparator: --after-reinstall required ONLY after actual backup/reinstall')

def stage_main(name,install,check):
    p=argparse.ArgumentParser(description=name+' independent target-local stage')
    p.add_argument('action',choices=['install','check','offline'])
    p.add_argument('--target-hostname');p.add_argument('--confirm-install',action='store_true')
    p.add_argument('--after-reinstall',action='store_true')
    p.add_argument('--public-host');p.add_argument('--acme-email');p.add_argument('--confirm-http01',action='store_true')
    p.add_argument('--acme-without-email',action='store_true',help='Explicitly register ACME without contact email')
    args=p.parse_args()
    try:
        if args.action=='offline':
            compile(Path(__file__).read_text(),__file__,'exec')
            print(name+': offline entrypoint OK; target acceptance NOT run');return
        host(args,write=args.action=='install')
        if args.action=='install':install(args)
        check(args)
        print(name+': check PASS (component readiness, not end-to-end acceptance)')
    except (RuntimeError,OSError,ValueError,subprocess.CalledProcessError) as e:
        # No command argv/source payload printed: credentials never belong in them.
        print(name+': FAIL '+(str(e) if not isinstance(e,subprocess.CalledProcessError) else 'child command failed, exit '+str(e.returncode)),file=sys.stderr)
        raise SystemExit(1)
