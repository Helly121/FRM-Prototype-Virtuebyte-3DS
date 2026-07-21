import subprocess
from pathlib import Path
import time
import sys

pgdata = Path(r"D:\FRM Anamoly MVP\.pgdata")
pg_ctl = Path(r"C:\Users\Ethan Santosh Gade\AppData\Local\Programs\Python\Python311\Lib\site-packages\pgserver\pginstall\bin\pg_ctl.exe")

def main():
    print("Cleaning up old locks...")
    pid_file = pgdata / "postmaster.pid"
    if pid_file.exists():
        try:
            pid_file.unlink()
        except OSError:
            pass
            
    # Also clean up the log file that causes sharing violations
    log_file = pgdata / "log"
    if log_file.exists():
        try:
            log_file.unlink()
        except OSError:
            pass

    print("\nStarting PostgreSQL (this might take up to 60 seconds if doing crash recovery)...")
    try:
        # Start DB with a 60 second timeout to bypass pgserver's hardcoded 10s limit
        subprocess.run(
            [str(pg_ctl), "start", "-D", str(pgdata), "-w", "-t", "60"],
            check=True
        )
        print("\n==========================================================")
        print("Database started successfully on port 5432!")
        print("==========================================================")
        print("\nKeep this window open to keep the database running.")
        print("\nTo connect your Uvicorn server, open a DIFFERENT terminal and run:")
        print('  $env:PG_DSN="postgresql://postgres:@127.0.0.1:5432/postgres"')
        print('  python -m uvicorn scoring-engine.app.main:app --host 127.0.0.1 --port 8000')
        print("\nPress CTRL+C here to safely shut down the database.")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down database safely...")
        subprocess.run([str(pg_ctl), "stop", "-D", str(pgdata), "-m", "fast"])
        print("Database stopped.")
    except subprocess.CalledProcessError as e:
        print(f"\nFailed to start database. Error: {e}")

if __name__ == "__main__":
    main()
