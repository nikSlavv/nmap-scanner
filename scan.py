import asyncio
import csv
import os
import sys
import shutil
import logging
import ipaddress
import subprocess
import argparse
from datetime import datetime

# --- CONFIGURAZIONE ---
MAX_PORT = 10000
MAX_CONCURRENT_SCANS = 30  # Numero di IP in parallelo (aumentato per ridurre i tempi)
LOG_FILE = "scanner.log"

active_processes = set()

# Parametri Nmap migliorati (rimosso sudo per avviarlo esplicitamente da root)
NMAP_BASE_OPTS = [
    "nmap", "-Pn", "-sS", "-T4", "-n", 
    "--max-rate", "300", "--reason",
    "--stats-every", "30s"  # feedback sul tempo rimanente o in corso ogni 30s
]

os.umask(0o077)

# --- SETUP LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

def check_requirements():
    """Verifica che lo script giri come root e che nmap sia installato."""
    if os.geteuid() != 0:
        logging.error("Questo script richiede privilegi di root. Riavvia con: sudo python3 scan.py")
        sys.exit(1)
        
    if not shutil.which("nmap"):
        logging.error("Eseguibile 'nmap' non trovato nel sistema. Installalo prima di procedere.")
        sys.exit(1)

def parse_targets(filename):
    """Legge il file target ed espande eventuali range CIDR in singoli IP validi."""
    if not os.path.exists(filename):
        logging.error(f"File {filename} non trovato.")
        return []

    targets = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            try:
                # Se è una singola stringa IP la aggiunge
                # Se è una stringa tipo 192.168.1.0/24 espande il network
                network = ipaddress.ip_network(line, strict=False)
                for ip in network.hosts():
                    targets.append(str(ip))
            except ValueError:
                logging.warning(f"Target ignorato (formato non valido): {line}")
                
    return list(set(targets)) # Rimuove duplicati

def get_csv_filename(targets):
    if not targets:
        return "scan_empty.csv"
    return f"scan_results_{targets[0]}_to_last.csv"

def load_completed_ips(csv_file):
    """Ottimizzazione I/O: Carica gli IP finiti in un Set (RAM) una volta sola."""
    completed = set()
    if os.path.exists(csv_file):
        with open(csv_file, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                # Gestisce sia il vecchio formato (6 colonne) che il nuovo (4 colonne)
                # Nel nuovo: la colonna 3 è lo STATUS. Nel vecchio era lo STATE ("SCAN_FINISHED")
                if len(row) >= 4:
                    if row[3] in ("SCAN_FINISHED", "TIMEOUT"):
                        completed.add(row[1])
    return completed

def _write_csv_sync(csv_file, rows):
    """Scrittura sincrona sul disco, chiamata in un thread separato."""
    with open(csv_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

def sort_csv_results(csv_file):
    """Ordina numericamente per indirizzo IP i risultati generati nel CSV alla fine della scansione."""
    if not os.path.exists(csv_file):
        return

    logging.info(f"Ordinamento dei risultati nel file {csv_file} in base all'IP...")
    
    with open(csv_file, "r") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return  # CSV vuoto
        
        rows = list(reader)

    # Ordina in base all'IP per un parsing numerico corretto e sicuro
    def sort_key(row):
        try:
            return int(ipaddress.ip_address(row[1]))
        except (ValueError, IndexError):
            return 0  # Fallback a 0 se l'IP non è corretto o per altre righe strane
            
    rows.sort(key=sort_key)

    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    logging.info("Ordinamento CSV completato.")

async def scan_ip(ip, csv_file, csv_lock, semaphore, completed_ips):
    # Controllo immediato in RAM
    if ip in completed_ips:
        logging.info(f"{ip} già completato. Salto.")
        return

    async with semaphore:
        logging.info(f"Avvio scansione su: {ip}")
        cmd = NMAP_BASE_OPTS + ["-p", f"1-{MAX_PORT}", "-oG", "-", ip]
        
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            active_processes.add(process)
            
            # Lettura asincrona dell'output riga per riga per mostrare le statistiche di tempo
            port_lines = []
            try:
                while True:
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break
                    line_str = line_bytes.decode('utf-8', errors='replace').strip()
                    
                    # Nmap printa le statistiche periodiche nei commenti, es: "# Stats: 0:00:10 elapsed... ETC..."
                    if "Stats:" in line_str or "Timing:" in line_str or "remaining" in line_str:
                        clean_stat = line_str.lstrip("# ").strip()
                        if clean_stat:
                            logging.info(f"[{ip}] {clean_stat}")
                    elif "Ports:" in line_str:
                        port_lines.append(line_str)
                        
                await process.wait()
            except asyncio.CancelledError:
                # Se lo script principale viene interrotto, uccidiamo immediatamente i processi zombie
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                raise

            if process.returncode != 0:
                stderr_bytes = await process.stderr.read()
                logging.warning(f"Errore nmap su {ip}: {stderr_bytes.decode('utf-8', errors='replace').strip()}")
                return

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = port_lines
            
            # Prepariamo i risultati
            open_ports = []
            
            for line in lines:
                if "Ports:" in line:
                    parts = line.split("Ports: ")[1].split(", ")
                    for p in parts:
                        p_info = p.strip().split("/")
                        if len(p_info) >= 5:
                            port, state, reason, service = p_info[0], p_info[1], p_info[3], p_info[4]
                            
                            if state == "open":
                                open_ports.append(f"{port} ({service})")
            
            ports_str = " | ".join(open_ports) if open_ports else "Nessuna porta aperta"
            
            # Unica riga per questo IP che accorpa tutte le porte e segna SCAN_FINISHED
            results_to_write = [[timestamp, ip, ports_str, "SCAN_FINISHED"]]
            
            # Scrittura asincrona non bloccante sul disco
            async with csv_lock:
                await asyncio.to_thread(_write_csv_sync, csv_file, results_to_write)
            
            logging.info(f"{ip} completato con successo.")
            
        except Exception as e:
            logging.error(f"Eccezione su {ip}: {e}")
        finally:
            if process:
                active_processes.discard(process)

async def main():
    parser = argparse.ArgumentParser(description="Automazione Nmap Scanner")
    parser.add_argument("ips", nargs="*", help="Indirizzi IP o network CIDR da scansionare separati da spazio")
    parser.add_argument("-f", "--file", type=str, help="File contenente la lista target da scansionare")
    parser.add_argument("-b", "--bucket", type=str, help="Bucket GCP in cui caricare il file CSV finale (es. gs://mio-bucket/reports/)")
    args = parser.parse_args()

    check_requirements()

    logging.info("Lettura target in corso...")
    
    target_list = []
    
    if args.ips:
        for ip_str in args.ips:
            try:
                if '/' in ip_str:
                    network = ipaddress.ip_network(ip_str, strict=False)
                    for ip in network.hosts():
                        target_list.append(str(ip))
                else:
                    ip = ipaddress.ip_address(ip_str)
                    target_list.append(str(ip))
            except ValueError:
                logging.warning(f"Target ignorato (formato non valido): {ip_str}")

    if args.file:
        file_targets = parse_targets(args.file)
        target_list.extend(file_targets)
        
    # Rimuove duplicati
    target_list = list(set(target_list))
    
    if not target_list:
        logging.error("Nessun target valido trovato. Usa gli IP come argomenti separati da spazio o usa il flag -f/--file. Uscita.")
        return

    csv_file = get_csv_filename(target_list)
    
    # Carica in RAM lo storico delle scansioni
    completed_ips = load_completed_ips(csv_file)
    
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            csv.writer(f).writerow(["TIMESTAMP", "IP", "OPEN_PORTS", "STATUS"])

    logging.info(f"Inizio scansione su {len(target_list)} target unici.")
    logging.info(f"Saltati (già completati): {len(completed_ips)}")
    logging.info(f"Concorrenza: {MAX_CONCURRENT_SCANS} in parallelo. Limite tempo disattivato, stampa feedback in corso.")
    
    csv_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCANS)
    
    tasks = [scan_ip(ip, csv_file, csv_lock, semaphore, completed_ips) for ip in target_list]
    await asyncio.gather(*tasks)

    logging.info("="*50)
    
    # Ordina il CSV
    sort_csv_results(csv_file)
    
    logging.info(f"Scansione globale terminata. Risultati salvati (e ordinati) in: {csv_file}")
    
    if args.bucket:
        logging.info(f"Inizio caricamento su bucket GCP: {args.bucket}")
        try:
            result = subprocess.run(
                ["gsutil", "cp", csv_file, args.bucket],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                logging.info(f"Upload su {args.bucket} completato con successo.")
            else:
                logging.error(f"Errore durante l'upload su GCP:\n{result.stderr.strip()}")
        except FileNotFoundError:
            logging.error("Comando 'gsutil' non trovato. Assicurati che google-cloud-sdk sia installato e nel PATH.")
        except Exception as e:
            logging.error(f"Eccezione durante l'upload: {e}")

    # A fine script, per sicurezza ripristina lo stato corretto del TTY per evitare glitch visivi
    os.system("stty sane")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Scansione interrotta dall'utente. Uccisione di tutti i processi Nmap in background in corso...")
        # Killa forzatamente qualsiasi processo nmap rimasto in esecuzione nel set
        for p in list(active_processes):
            try:
                p.kill()
            except Exception:
                pass
        
        # Ripristina lo stato corretto del terminale (per Terminali come Ghostty o GNOME che perdono l'echo)
        os.system("stty sane")
        sys.exit(0)