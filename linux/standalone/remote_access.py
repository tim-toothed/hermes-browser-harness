from lib import *
import secrets
from importlib import import_module
def install(a):
    public_host=import_module('https').public_host(a)
    copy_source('skills/browser-human-access/SKILL.md',HOME/'skills/browser-human-access/SKILL.md')
    require(Path('/etc/systemd/system/procvetaev-chrome.service').exists(),'Browser stage required')
    run('apt-get','install','-y','x11vnc','novnc','websockify')
    # Pin upstream with automatic clipboard support; v1.7.0 does not include it.
    run('curl','-fL','--retry','2','https://github.com/novnc/noVNC/archive/e8b5024d4603587b29ffede4fbd28b1fa2939829.tar.gz','-o','/var/lib/novnc-redd.tar.gz')
    run('tar','-xzf','/var/lib/novnc-redd.tar.gz','-C','/usr/share/novnc','--strip-components=1')
    Path('/var/lib/novnc-redd.tar.gz').unlink()
    locale=Path('/usr/share/novnc/app/localization.js')
    text=locale.read_text()
    require('        this._setupLanguage(supportedLanguages);' in text,'Unknown noVNC localization entrypoint')
    locale.write_text(text.replace('        this._setupLanguage(supportedLanguages);','        this.language = "ru"; // REDD: fixed interface language',1))
    for name in ('broker.py','core.py','store.py','otp.html'):copy_source('remote-access/'+name,'/usr/local/libexec/procvetaev-browser-harness/temporary-share/'+name)
    for name in ('procvetaev-share-broker.service','procvetaev-browser-share.service','procvetaev-x11vnc.service','procvetaev-novnc.service'):copy_source('remote-access/'+name,'/etc/systemd/system/'+name)
    Path('/var/lib/procvetaev-browser-share').mkdir(parents=True,exist_ok=True)
    if not Path('/etc/procvetaev-browser/share.pepper').exists():put('/etc/procvetaev-browser/share.pepper',secrets.token_hex(32)+'\n',0o600)
    put('/etc/systemd/system/procvetaev-share-broker.service.d/standalone.conf','[Service]\nEnvironment=REMOTE_ACCESS_PUBLIC_BASE=https://'+public_host+'\nEnvironment=BROWSER_SHARE_PORT=6080\n')
    run('systemctl','daemon-reload');run('systemctl','enable','--now','procvetaev-share-broker.service');run('systemctl','restart','procvetaev-share-broker.service')
def check(a):
    active('procvetaev-share-broker.service')
    denial('http://127.0.0.1:8790/access/remote/invalid',[404,410])
    require('/usr/local/libexec/procvetaev-browser-harness/temporary-share/broker.py' in run('systemctl','show','procvetaev-share-broker.service','-p','ExecStart',capture=True),'Wrong broker owner')
if __name__=='__main__':stage_main('remote_access',install,check)
