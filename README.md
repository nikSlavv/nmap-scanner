# Nmap Scanner Automation

Uno script Python per l'automazione di scansioni Nmap massive in modo concorrente e asincrono su molteplici IP e network CIDR, con esportazione automatizzata in CSV e (opzionalmente) push verso Google Cloud Storage.

## Requisiti

- **OS Environment**: Sviluppato per ambienti Linux. Nessuna lib Python esterna extra da installare (nessun `pip install` necessario) per conservare l'OS "pulito".
- **Python 3.7+**: Lo script sfrutta unicamente standard library di Python (`asyncio`, `argparse`, `csv`, `subprocess`, ecc.) per massima retro-compatibilità.
- **Nmap**: Se non già presente nel path di sistema, lo script lo rileverà e in automatico cercherà di **auto-installarlo** in maniera trasparente tramite il package manager della macchina proxy/vergine (`apt`, `yum`, `dnf`, `pacman`, `zypper`).
- **Permessi Root**: Richiede sempre `sudo` fin dall'inizio poiché esegue scan SYN Stealth e necessita dei permessi per auto-installare Nmap.
- **Google Cloud SDK (gsutil)**: Obbligatorio se si abilita il flag `-b`. E' l'unica eccezione in cui si richiede di preconfigurare l'SDK manualmente onde evitare di aggiungere chiavi GPG e repository esterni Google non voluti.

## Utilizzo

Lo script è flessibile con i parametri di input e può prelevare target multipli sia dalla riga di comando sia caricati da un file:

```bash
sudo python3 scan.py [ips ...] [-f FILE] [-b BUCKET]
```

### Argomenti Disponibili

- **`ips`**: (Posizionale) Uno o più indirizzi IP o network (range CIDR). Non c'è un limite se non lo stack della shell, separali semplicemente con uno spazio.
- **`-f`, `--file FILE`**: (Opzionale) File di testo contenente IP e/o CIDR format da dover parsare per aggiungere target. Usalo unito agli IP passati in argomenti, i duplicati verranno filtrati ed eliminati automaticamente.
- **`-b`, `--bucket BUCKET`**: (Opzionale) Esclusivamente il **nome del bucket** GCP (es. `bucket-aziendale`). Il sistema formatterà in automatico i protocolli (`gs://`) depositando il CSV direttamente alla root del bucket, partendo dal presupposto che il bucket sia dedicato a tali report.
- **`--vuln`**: (Opzionale) Attiva lo scanning **Two-Phase (Due Fasi)** di Vulnerabilità per l'identificazione CVE. Ottimizzato per la velocità: Nmap invocherà il motore di scripting (NSE) esclusivamente sulle porte accertate come "Open", evitando sovraccarichi e riducendo il tempo di calcolo.

## Esempi Comuni

**Scansione IP diretti:**
```bash
sudo python3 scan.py 192.168.1.1 8.8.8.8 10.0.0.0/24
```

**Scansione tramite file esterno:**
```bash
sudo python3 scan.py -f ips_da_scansionare.txt
```

**Scansione con caricamento su Google Cloud Platform:**
```bash
sudo python3 scan.py 192.168.1.1 -f miei_target.txt -b gs://bucket-aziendale-reports/
```

## Formato Report

I risultati vengono scritti man mano (thread-safe append al volo) su file CSV.
Se un task dovesse morire oppure bloccato dall'utente il CSV continuerà comunque a trattenere gli hostname che hanno terminato. 
Al termine globale dell'esecuzione, avverrà in automatico l'**ordinamento degli IP per via numerica**, riordinando il report e se specificato spinto sul Cloud.

## Impostazioni modificabili (su `scan.py`)

All'interno dello script puoi variare queste variabili alla voce "CONFIGURAZIONE":
- `MAX_PORT`: (Default: `10000`) Limita i port range alle Top prime porte scansionate anziché tutte le 65535.
- `MAX_CONCURRENT_SCANS`: (Default: `30`) Modifica la concorrenza massima e quante esecuzioni processi Nmap lanciare parallelamente. Attenzione a non inondare il routing hardware o il file system.
- `LOG_FILE`: Nome del file in cui verranno stampati i log operativi. (Default `scanner.log`).
