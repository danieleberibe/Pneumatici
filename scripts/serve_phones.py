"""Serve one shared StereoLab session over HTTP (setup/desktop) and HTTPS (phone cameras)."""

import argparse
import asyncio
import ipaddress
from pathlib import Path

import uvicorn
from cryptography import x509
from fastapi.responses import FileResponse, HTMLResponse

from stereolab.app import app

ROOT = Path(__file__).resolve().parents[1]


def setup_phone_routes(application, address, https_port, certificate, http_port=8765):
    origin = f"https://{ipaddress.IPv4Address(address)}:{int(https_port)}"
    application.state.phone_origin = origin
    application.state.setup_url = f"http://{address}:{int(http_port)}/connect"

    @application.get("/connect/certificate", include_in_schema=False)
    def public_certificate():
        # Serve only the public root, never the certs directory or private keys.
        return FileResponse(certificate, media_type="application/x-x509-ca-cert", filename="StereoLab-CA.crt")

    @application.get("/connect", response_class=HTMLResponse, include_in_schema=False)
    def connect():
        links = {
            side: f"{origin}/phone?side={side}#token={token}"
            for side, token in application.state.tokens.items()
        }
        return f'''<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>StereoLab · Collega i telefoni</title>
<link rel="stylesheet" href="/static/styles.css"></head><body class="phone-body">
<div class="eyebrow">STEREOLAB / COLLEGAMENTO TELEFONI</div><h1>Il computer è raggiungibile.</h1>
<p>Questa pagina conferma che telefono e computer comunicano sulla rete locale.</p>
<h2>1. Installa il certificato locale</h2><p>Serve per autorizzare la fotocamera sulla connessione HTTPS.
Installa questa CA solo sui tuoi dispositivi per questa prova; puoi rimuoverla al termine.</p>
<a class="button primary" href="/connect/certificate">Scarica certificato StereoLab</a>
<p><strong>iPhone:</strong> apri questa pagina in Safari. Dopo il download, vai in Impostazioni →
Generali → VPN e gestione dispositivo, installa il profilo StereoLab. Poi vai in Generali → Info →
Impostazioni attendibilità certificati e abilita la fiducia per StereoLab Local Development CA.</p>
<p><strong>Android:</strong> scarica il file, poi cerca “Installa un certificato” nelle Impostazioni.
Scegli “Certificato CA” e seleziona StereoLab-CA.crt. Il percorso cambia secondo il produttore.</p>
<h2>2. Scegli il lato di questo telefono</h2><p>Usa un telefono per L e l'altro per R.
Apri il pulsante dopo aver installato il certificato, consenti la camera e premi “Avvia fotocamera”.</p>
<div class="pair-links phone-pair-links"><a class="pair-link" href="{links["left"]}">
<strong>Camera sinistra · L</strong><img class="pair-qr" src="/api/pairing/qr/left.png" alt="QR camera sinistra">
<span>Inquadra o tocca per aprire ↗</span></a>
<a class="pair-link" href="{links["right"]}"><strong>Camera destra · R</strong>
<img class="pair-qr" src="/api/pairing/qr/right.png" alt="QR camera destra">
<span>Inquadra o tocca per aprire ↗</span></a></div>
<p>Scegli la stessa risoluzione su entrambi. Parti da 1280 × 720; se non supportata, usa 640 × 480.</p>
<p class="help">Se applichi nuove sorgenti dal computer, ricarica questa pagina per ottenere link validi.
Le anteprime compaiono sul pannello del computer. Fuoco e calibrazione vanno verificati prima delle misure 3D.</p>
<a class="inline-link" href="/">Apri il pannello StereoLab ↗</a></body></html>'''


async def serve(args):
    certificate_dir = ROOT / "certs"
    certificate = x509.load_pem_x509_certificate((certificate_dir / "server.pem").read_bytes())
    addresses = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if ipaddress.ip_address(args.ip) not in addresses.get_values_for_type(x509.IPAddress):
        raise ValueError(
            "Il certificato non include l'IP scelto: generare un certificato per questo indirizzo."
        )
    setup_phone_routes(app, args.ip, args.https_port, certificate_dir / "rootCA.crt", args.http_port)
    # Only the HTTPS listener runs lifespan: both listeners share the SAME engine and pairing tokens.
    http = uvicorn.Server(uvicorn.Config(app, host=args.ip, port=args.http_port, lifespan="off"))
    desktop = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.http_port, lifespan="off"))
    https = uvicorn.Server(
        uvicorn.Config(
            app,
            host=args.ip,
            port=args.https_port,
            lifespan="on",
            ssl_certfile=str(certificate_dir / "server.pem"),
            ssl_keyfile=str(certificate_dir / "server-key.pem"),
        )
    )
    print(f"Telefono: http://{args.ip}:{args.http_port}/connect", flush=True)
    print(f"Computer: http://127.0.0.1:{args.http_port}", flush=True)
    await asyncio.gather(http.serve(), desktop.serve(), https.serve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, type=str)
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--https-port", type=int, default=8767)
    arguments = parser.parse_args()
    ipaddress.IPv4Address(arguments.ip)
    asyncio.run(serve(arguments))
