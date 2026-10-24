# StereoLab

POC locale per localizzare palline nello spazio con due camere: **backend Python/FastAPI + OpenCV**, dashboard web e pagina di acquisizione per **Android e iPhone**. Include ingressi USB e MJPEG/RTSP per passare a camere dedicate.

La demo sintetica attraversa lo stesso rilevatore e la stessa triangolazione delle camere reali. È esplicitamente separata dalle misure reali. All'avvio non vengono inventate coordinate o simulati collegamenti.

## Avvio rapido

Richiede Python 3.11–3.13 a 64 bit. Non servono Node, servizi cloud o compilazione del frontend.

```powershell
cd C:\Users\danie\src\Pneumatici
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,https]"
.\scripts\start.ps1
```

Aprire **http://127.0.0.1:8765** e premere **Avvia demo**. API documentate in **/docs**. Per arrestare il server avviato dallo script: `Ctrl+C`. Usare un solo processo Uvicorn: lo stato delle camere è in memoria, non condiviso tra worker.

Se PowerShell non consente l'esecuzione dello script, avviare direttamente senza modificare le policy: `.\.venv\Scripts\python.exe -m uvicorn stereolab.app:app --host 127.0.0.1 --port 8765`.

L'ambiente `.venv` di questa consegna è già installato. `requirements-lock.txt` fotografa le dipendenze effettivamente collaudate su Windows/Python 3.12; per riprodurle installare prima quel file, poi `pip install -e . --no-deps`. Il progetto è installabile anche su Linux/macOS con i corrispondenti comandi Python e Uvicorn. USB su questi sistemi richiede la verifica dei driver locali.

## Due telefoni: procedura concreta

### Collegamento guidato (Windows, stessa sessione sul PC e sui telefoni)

Dopo aver generato i certificati con il proprio IP come descritto sotto, arrestare l'eventuale server sulla porta 8765 e avviare:

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_phones --ip 192.168.1.37
```

Sostituire l'IP con quello effettivo del computer. Sul PC usare `http://127.0.0.1:8765`; sui telefoni aprire `http://IP-DEL-PC:8765/connect`. La pagina guida all'installazione della CA e offre i due link HTTPS per L/R, sulla porta 8767. I listener condividono la stessa pipeline e gli stessi token. La pagina HTTP distribuisce soltanto il certificato **pubblico**, mai le chiavi private; per la fotocamera passa a HTTPS. Consentire nel firewall le porte TCP 8765 e 8767 solo dalla sottorete locale. Se il Wi-Fi è classificato pubblico, una regola limitata al solo profilo privato non basta.

Questa modalità evita di dover installare la CA anche sul PC per usare il pannello HTTP locale. Ricaricare `/connect` dopo aver applicato nuove sorgenti. Il server singolo descritto di seguito rimane un'alternativa.

Nel pannello **Sorgenti → Inquadra e collega le camere** trovi due QR distinti per L/R e un QR per la configurazione iniziale del certificato. L'indirizzo HTTPS viene compilato automaticamente dal server telefoni. I QR sono generati localmente da OpenCV, senza servizi esterni, e includono il token corrente: dopo un riavvio o una modifica delle sorgenti, ricaricare il pannello e inquadrare i nuovi codici. Anche `/connect` mostra i due QR camera.

### 1. Rete e HTTPS

Entrambi i telefoni e il computer devono essere sulla stessa rete Wi-Fi, senza isolamento client. Il browser mobile richiede un'origine HTTPS attendibile per accedere alla fotocamera: HTTP sull'IP del PC non basta.

Individuare l'IPv4 del computer con `ipconfig`, poi:

```powershell
# Sostituire con l'IPv4 reale del computer.
.\.venv\Scripts\python.exe scripts\make_certificate.py 192.168.1.10
.\scripts\start.ps1 -Https -Bind 0.0.0.0 -Port 8443
```

Lo script genera in `certs/` una CA locale dedicata e un certificato server con l'IP indicato. Non modifica l'archivio di fiducia del computer o dei telefoni. Il certificato server dura 60 giorni; cambiando IP occorre un nuovo certificato. Non sovrascrive file esistenti.

Trasferire ai propri dispositivi **solo `certs/rootCA.crt`** e installarlo come CA attendibile. Su iPhone installare il profilo e abilitare esplicitamente la fiducia in **Impostazioni → Generali → Info → Impostazioni attendibilità certificati**. Su Android la voce per installare un certificato CA varia per produttore e versione. Rendere attendibile la CA anche sul computer se si usa il pannello HTTPS da lì. Conservare le due chiavi private sul computer, non trasferirle ai telefoni. Al termine della POC rimuovere la CA dai dispositivi se non serve più.

Aprire `https://IP-DEL-PC:8443` sul computer, consentire la porta nel firewall **solo per la rete privata**, quindi aprire **Sorgenti**. Inserire quell'indirizzo HTTPS, scegliere **Telefono · browser** per entrambi, verificare le opzioni e premere **Applica e connetti**. Aprire il link L su un telefono e R sull'altro. Ogni applicazione delle sorgenti rinnova i link: quelli precedenti smettono di funzionare. I token nel frammento URL non finiscono nei normali access log HTTP.

Il pannello è pensato per una **LAN fidata**: non include account o autorizzazioni per operatore. I token proteggono l'abbinamento dei frame, non limitano l'accesso al pannello/API per chi può raggiungere il server. Non pubblicarlo su Internet. Le immagini sono elaborate localmente e non sono registrate su disco.

### 2. Ottica e fuoco

- Fissare rigidamente i telefoni affiancati orizzontalmente, con scene sovrapposte; punto di partenza: baseline 10–20 cm, palline a 1–2 m.
- Usare la stessa risoluzione effettiva. Provare 1280×720; se non disponibile su entrambi, usare 640×480. Niente ridimensionamento silenzioso dei frame.
- Sono accettati anche i corrispondenti frame verticali, per esempio 720×1280 e 1080×1920: il limite è applicato al lato corto (240–1080 px) e a quello lungo (320–1920 px). Safari può fornire il formato verticale anche quando viene richiesta una risoluzione orizzontale. I pixel sono conservati senza rotazioni o ritagli; per calibrare, usare lo stesso orientamento e le stesse dimensioni effettive sulle due camere. L'orientamento esposto dal browser entra nella firma ottica e una sua modifica invalida il profilo.
- Bloccare orientamento, lente, zoom e fuoco **prima** di calibrare. Lasciare assestare il fuoco, poi usare **Blocca fuoco** nella pagina del telefono quando disponibile. Mantenere la pagina in primo piano.
- Preferire la lente principale 1×. Disattivare stabilizzazione digitale, cambio automatico della lente/macro e ritaglio dinamico se esposti dall'app: modificano la geometria anche senza cambiare il fuoco. Lenti fisheye/ultrawide molto distorte richiedono una validazione specifica; questo modello usa gli intrinseci pinhole di OpenCV.
- La pagina controlla capability e impostazioni effettive: se il browser non espone `focusMode=manual`, non dichiara un blocco riuscito. Safari/iPhone può non esporre queste funzioni. In quel caso usare un'app camera con **fuoco manuale e stream MJPEG/RTSP**, configurando l'URL come sorgente IP.
- La spunta “Ho verificato il blocco di fuoco e zoom” è un'attestazione dell'operatore per dispositivi che non espongono lo stato. Non può scavalcare un autofocus che il dispositivo dichiara attivo. Non spuntarla per sbloccare una camera che continua a rifocheggiare.
- Driver USB e stream possono non esporre il fuoco. L'app tenta di disattivare l'autofocus USB, ma non interpreta un valore non supportato come prova del blocco.

La firma del profilo comprende sorgente, risoluzione, ottica e sessione del telefono. Una modifica rilevata blocca il 3D. Anche dopo riapertura della pagina del telefono occorre ricalibrare. **Uno spostamento fisico delle camere non è rilevabile in modo affidabile dal software**: ricalibrare sempre dopo urti o variazioni di montaggio.

### 3. Calibrazione

1. In **Calibrazione**, aprire la tavola ChArUco: default 7×5 quadrati da 25 mm, marker 18 mm, `DICT_4X4_50`. Il foglio SVG misura 195×155 mm e include una scala da 50 mm. Stampare al 100%, senza adattamento; verificare con un righello. Fissare su un supporto rigido e piano.
2. Confermare la scena statica in Sorgenti. Muovere **solo la tavola**. Fermarla in una posa ben visibile da entrambe le camere e acquisire una coppia.
3. Acquisire 25–35 pose, minimo 15. Coprire almeno tre regioni dell'immagine, diverse distanze e inclinazioni. Le pose duplicate, sfocate, troppo piccole o con meno di 12 angoli comuni vengono rifiutate. Per cambiare tavola o azzerare i campioni usare **Applica / nuova sessione**.
4. Calcolare. Il sistema stima gli intrinseci di ciascuna camera, poi gli estrinseci stereo a intrinseci fissi. Ogni quinta posa è esclusa da **entrambi** i fit e usata per la verifica.
5. Controllare il report: RMS sinistro/destra/stereo ≤1 px; RMS epipolare sui campioni esclusi ≤1 px; riproiezione sui campioni esclusi ≤1,2 px; baseline 20–2000 mm; almeno tre regioni e 15° di escursione delle normali della tavola. Vengono controllati anche intrinseci plausibili e rig orizzontale. Questi limiti sono filtri iniziali, non certificazioni di accuratezza.
6. Il profilo è salvato atomicamente in `data/calibration.json` ed esportabile. Un profilo rifiutato non abilita il 3D. Le immagini/coppie di calibrazione rimangono solo in memoria fino al riavvio o reset; il profilo persistente contiene parametri, metriche e configurazione della tavola.

### 4. Rilevamento e misura

Rimuovere la tavola e mettere palline **ferme** nella zona comune. In **Rilevamento** scegliere i colori effettivamente presenti; arancione, rosso, verde, blu, bianco e nero sono supportati. Tarare luminosità del bianco/nero, raggi e circolarità. Uno sfondo grigio medio opaco aiuta a separare sia il bianco sia il nero; ombre, riflessi e sfondi dello stesso colore possono impedire la misura.

Il rilevatore combina maschere HSV, morfologia, convessità, circolarità e residuo del contorno ellittico. Scarta contorni tagliati e anelli. Il matching usa classe, riga epipolare, dimensione apparente, segno della disparità, reciprocità e margine rispetto alle alternative. In caso di palline indistinguibili sulla stessa riga, **rinuncia alla misura**: separarle verticalmente o usare colori diversi.

I punti sono triangolati con `cv2.triangulatePoints`, verificati per profondità positiva in entrambe le viste, riproiezione e distanza. Si restituiscono coordinate **in metri nel riferimento ottico originale della camera sinistra**: X a destra, Y verso il basso, Z in avanti. La rotazione della rettifica viene annullata. Gli ID P01… valgono solo per il singolo frame, non sono tracking persistente. Esportazione CSV disponibile solo per misure correnti, con timestamp, flag simulazione, unità, riferimento e tipo di sincronizzazione.

## Precisione: cosa misuriamo davvero

- Due telefoni, webcam non sincronizzate e URL IP non forniscono un trigger hardware comune. Il sistema abbina **tempi di arrivo al server**, scarta coppie vecchie oltre 0,8 s e scarti oltre 150 ms. Lo scarto mostrato **non è l'errore temporale di esposizione**. Buffer e rolling shutter restano incognite.
- La modalità reale richiede conferma di scena ferma e almeno 0,8 s senza spostamenti rilevati dei centri. È un controllo euristico, non certifica che due esposizioni siano simultanee. Oggetti in caduta o in movimento non rientrano nella validazione di questa POC.
- La σZ mostrata è la propagazione del rumore dei centri in pixel: `σZ ≈ Z² / (f · B) · √2 · σpixel`. È riferita alla profondità rettificata e non comprende errori di scala, ottica, asincronia o bias del modello. Con f=800 px, B=160 mm, σpixel=0,5 px, a 2 m vale circa **22 mm**. Non promettiamo precisione millimetrica con telefoni non ancora misurati.
- Il centro dell'ellisse della sagoma non coincide esattamente con la proiezione del centro di una sfera fuori asse. Le coordinate sono una **stima del centro dalla sagoma**, non una misura certificata del centro fisico. Un cerchio stampato può passare il rilevatore: non è riconoscimento semantico di sfere.
- Un basso RMS da solo non garantisce accuratezza. Una tavola stampata al 95% e dichiarata al 100% introduce un errore sistematico di scala. Anche una superficie non piana altera la calibrazione.

Per una verifica fisica, raccogliere almeno 10 posizioni note e 30 letture per posizione. Le coordinate di riferimento devono essere riportate nello **stesso riferimento ottico sinistro**; il bordo del telefono non è il centro ottico. Valutare prima distanze tra posizioni note se non si conosce l'origine fisica. Le soglie di accettazione vanno concordate sulla tolleranza della futura presa robotica.

Per confrontare coordinate già riferite correttamente, preparare un CSV con intestazione:

```text
point_id,x_true_m,y_true_m,z_true_m,x_m,y_m,z_m
```

Poi eseguire:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_measurements.py misure.csv
```

Restituisce errore medio, RMSE 3D, percentile 95, massimo, bias per asse e ripetibilità per posizione. Esclude dati con `simulated=True`. Acquisire frame indipendenti: non duplicare la stessa esportazione per simulare ripetibilità.

## Struttura e test

```text
stereolab/
  app.py              API, upload telefoni, esportazioni e frontend
  acquisition.py      ingressi phone/USB/IP, buffer e pairing per arrivo
  calibration.py      ChArUco, calibrazione, holdout e persistenza
  detection.py        sagome candidate, colori e filtri geometrici
  geometry.py         matching conservativo, triangolazione e σZ
  engine.py           pipeline, ciclo di elaborazione e stato
  demo.py             scena sintetica con geometria nota
  models.py           configurazioni validate
  static/             dashboard e acquisizione mobile, nessuna CDN
tests/                geometria, calibrazione, rilevamento e API
scripts/              avvio, certificati e valutazione metrica
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check stereolab tests scripts
```

Le verifiche automatiche coprono la geometria sintetica, recupero di baseline e scala, holdout corrotto, riconoscimento effettivo ChArUco, palline acromatiche, falsi contorni, ambiguità, frame scaduti, autofocus, isolamento della demo, token scaduti e ingressi non validi. **Il collaudo su Android/iPhone reali e le misure fisiche richiedono i dispositivi dell'operatore.**

## Passaggio alle camere stereo e ai pneumatici

Gli ingressi USB/IP sono già disponibili, ma le camere acquistate potrebbero fornire un'immagine stereo affiancata, uno SDK proprietario o timestamp hardware: occorre implementare l'adattatore corrispondente e verificare il vero timestamp di esposizione, senza confonderlo con l'arrivo al PC. La POC non dichiara una compatibilità non ancora verificata con quel modello.

Per pneumatici e robot occorreranno segmentazione/pose dedicate, stima della geometria di presa e delle occlusioni, trasformazione camera–robot/hand–eye, verifica del piano di appoggio e validazione con tolleranze della pinza. Questo progetto non emette comandi di movimento.

## Riferimenti tecnici

- [OpenCV: calibrazione e ricostruzione 3D](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)
- [OpenCV: ChArUco](https://docs.opencv.org/4.x/df/d4a/tutorial_charuco_detection.html)
- [MDN: getUserMedia e contesti sicuri](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [MDN: capability e vincoli delle camere](https://developer.mozilla.org/en-US/docs/Web/API/Media_Capture_and_Streams_API/Constraints)
- [Apple: fiducia nei certificati installati manualmente](https://support.apple.com/en-us/102390)
- [Cryptography: generazione di certificati X.509](https://cryptography.io/en/latest/x509/tutorial/)
