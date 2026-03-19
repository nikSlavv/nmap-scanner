# Nmap Scanner Automation

Uno script Python per l'automazione di scansioni Nmap massive in modo concorrente e asincrono su molteplici IP e network CIDR, con esportazione automatizzata in CSV e (opzionalmente) push verso Google Cloud Storage.

## Requisiti

- **OS Environment**: Sviluppato per ambienti Linux.
- **Python 3.7+**: Lo script utilizza la libreria `asyncio` per la gestione ottimizzata dei processi in background.
- **Nmap Installato**: L'eseguibile di nmap deve risiedere nei path di sistema (es. `sudo apt install nmap`).
- **Permessi Root**: Richiede l'esecuzione tramite `sudo` siccome utilizza dei layer raw-socket packet injection performati dalla flag `-sS` (SYN Stealth scan) di Nmap.
- **Google Cloud SDK (gsutil)**: Richiesto esclusivamente qualora si decida di utilizzare la funzionalità di esportazione dei report sul proprio Cloud Bucket tramite l'argomento `-b`.

## Utilizzo

Lo script è flessibile con i parametri di input e può prelevare target multipli sia dalla riga di comando sia caricati da un file:

```bash
sudo python3 scan.py [ips ...] [-f FILE] [-b BUCKET]
```

### Argomenti Disponibili

- **`ips`**: (Posizionale) Uno o più indirizzi IP o network (range CIDR). Non c'è un limite se non lo stack della shell, separali semplicemente con uno spazio.
- **`-f`, `--file FILE`**: (Opzionale) File di testo contenente IP e/o CIDR format da dover parsare per aggiungere target. Usalo unito agli IP passati in argomenti, i duplicati verranno filtrati ed eliminati automaticamente.
- **`-b`, `--bucket BUCKET`**: (Opzionale) URI di un bucket GCP compatibile con i comandi del protocollo gsutil in cui depositare l'archivio CSV generato a root script terminata. Es (`gs://mio-sec-bucket/reports/`).

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
