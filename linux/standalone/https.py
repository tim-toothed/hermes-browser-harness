from lib import *
import ipaddress,re
ACME=Path('/opt/remote-access-acme')
def public_host(a):
    value=a.public_host or ''
    require(bool(re.fullmatch(r'[A-Za-z0-9.-]+',value)) and not value.startswith('-'),'Valid node-local --public-host required')
    return value
def install(a):
    value=public_host(a);require(a.confirm_http01 and (a.acme_email or a.acme_without_email),'Confirm HTTP01 and provide --acme-email or explicit --acme-without-email')
    run('apt-get','update');run('apt-get','install','-y','caddy')
    if not (ACME/'bin/python').exists():run(uv(),'venv','--python',runtime()[0],ACME)
    run(uv(),'pip','install','--python',ACME/'bin/python','certbot>=5.8','python-dotenv')
    Path('/usr/share/caddy').mkdir(parents=True,exist_ok=True)
    # Initial issuance requires an HTTP-only gateway: TLS files do not exist yet.
    challenge=':80 {\n handle /.well-known/acme-challenge/* {\n  root * /usr/share/caddy\n  file_server\n }\n handle {\n  respond 404\n }\n}\n'
    final=source('certbot/remote-access.Caddyfile.in').replace('@PUBLIC_HOST@',value)
    put('/etc/caddy/remote-access.Caddyfile',final if Path('/etc/letsencrypt/live/remote-access-ip/fullchain.pem').exists() else challenge)
    for name in ('remote-access-gateway.service','remote-access-renew.service','remote-access-renew.timer'):copy_source('certbot/'+name,'/etc/systemd/system/'+name)
    run('systemctl','disable','--now','caddy.service');run('systemctl','daemon-reload');run('systemctl','restart','remote-access-gateway.service')
    flags=['--cert-name','remote-access-ip','--webroot','-w','/usr/share/caddy','--non-interactive','--agree-tos']
    flags+=['--email',a.acme_email] if a.acme_email else ['--register-unsafely-without-email']
    if a.acme_server:
        require(a.acme_ca_bundle and Path(a.acme_ca_bundle).is_file(),'Custom ACME server requires an existing --acme-ca-bundle')
        flags+=['--server',a.acme_server]
    environment=os.environ.copy()
    if a.acme_ca_bundle:environment['REQUESTS_CA_BUNDLE']=a.acme_ca_bundle
    try:ipaddress.ip_address(value);flags+=['--ip-address',value,'--required-profile','shortlived']
    except ValueError:flags+=['-d',value]
    subprocess.run([str(ACME/'bin/certbot'),'certonly',*flags],check=True,env=environment)
    put('/etc/caddy/remote-access.Caddyfile',final)
    run('caddy','validate','--config','/etc/caddy/remote-access.Caddyfile','--adapter','caddyfile')
    run('systemctl','restart','remote-access-gateway.service');run('systemctl','enable','remote-access-gateway.service','remote-access-renew.timer');run('systemctl','start','remote-access-renew.timer')
def check(a):
    public_host(a);active('remote-access-gateway.service','remote-access-renew.timer')
    require(Path('/etc/letsencrypt/live/remote-access-ip/fullchain.pem').exists(),'Certificate missing')
    if a.acme_ca_bundle:
        import ssl
        from urllib.request import urlopen
        from urllib.error import HTTPError
        context=ssl.create_default_context(cafile=a.acme_ca_bundle)
        try:
            with urlopen('https://'+a.public_host+'/',timeout=15,context=context) as response:code=response.status
        except HTTPError as error:code=error.code
        require(code==404,'Unexpected HTTPS response through custom ACME CA')
    else:denial('https://'+a.public_host+'/',[404])
    run('caddy','validate','--config','/etc/caddy/remote-access.Caddyfile','--adapter','caddyfile')
if __name__=='__main__':stage_main('https',install,check)
