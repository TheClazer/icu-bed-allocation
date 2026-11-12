"""Runs the whole system as plain Windows processes, no Docker and no admin rights.

  python -m app.services up       download once, initialise once, start everything
  python -m app.services down     stop everything (data is kept)
  python -m app.services status   show what is running
  python -m app.services fresh    delete all data so the next "up" starts from scratch

Everything lives in runtime/ inside the project:
  runtime/mysql-8.0.40-winx64/      portable MySQL server (official zip)
  runtime/redis/                    portable Redis 7.4 for Windows
  runtime/data/primary, replica     MySQL data directories
  runtime/logs/                     MySQL error logs, Redis and app logs
  runtime/pids/                     process ids, used by stop and by the crash demo

The app also imports this module: the crash demo kills the MySQL primary process
and starts it again, the Redis outage demo stops and starts Redis.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
RT = ROOT / "runtime"
DL = RT / "downloads"
DATA = RT / "data"
LOGS = RT / "logs"
PIDS = RT / "pids"
CNF = RT / "conf"

MYSQL_VERSION = "8.0.40"
MYSQL_URL = f"https://cdn.mysql.com/archives/mysql-8.0/mysql-{MYSQL_VERSION}-winx64.zip"
MYSQL_HOME = RT / f"mysql-{MYSQL_VERSION}-winx64"
REDIS_URL = "https://github.com/redis-windows/redis-windows/releases/download/7.4.11/Redis-7.4.11-Windows-x64-msys2.zip"
REDIS_HOME = RT / "redis"
ROOT_PASSWORD = "rootpass"

PORTS = {"primary": 3307, "replica": 3308, "redis": 6379, "app-1": 8000, "app-2": 8001}
PUBLIC = "app-1=http://localhost:8000,app-2=http://localhost:8001"
INTERNAL = "app-1=http://127.0.0.1:8000,app-2=http://127.0.0.1:8001"
FLAGS = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
         | getattr(subprocess, "CREATE_NO_WINDOW", 0))


def say(msg):
    print(f"  {msg}", flush=True)


def fwd(p):
    return str(p).replace("\\", "/")


# ---------------------------------------------------------------- download
def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return
    say(f"Downloading {url.rsplit('/', 1)[-1]} (one time only)...")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done * 10 // total > last:
                last = done * 10 // total
                say(f"  {last * 10}%")
    tmp.replace(dest)


def ensure_binaries():
    if not (MYSQL_HOME / "bin" / "mysqld.exe").exists():
        _download(MYSQL_URL, DL / "mysql.zip")
        say("Unpacking MySQL...")
        with zipfile.ZipFile(DL / "mysql.zip") as z:
            z.extractall(RT)
    if not list(REDIS_HOME.glob("**/redis-server.exe")):
        _download(REDIS_URL, DL / "redis.zip")
        say("Unpacking Redis...")
        tmp = RT / "redis_unpack"
        with zipfile.ZipFile(DL / "redis.zip") as z:
            z.extractall(tmp)
        inner = next(tmp.glob("**/redis-server.exe")).parent
        shutil.rmtree(REDIS_HOME, ignore_errors=True)
        shutil.move(str(inner), str(REDIS_HOME))
        shutil.rmtree(tmp, ignore_errors=True)


def mysql_bin(name):
    return str(MYSQL_HOME / "bin" / f"{name}.exe")


def redis_server():
    return str(next(REDIS_HOME.glob("**/redis-server.exe")))


# ---------------------------------------------------------------- configuration
def write_configs():
    for d in (DATA, LOGS, PIDS, CNF, DATA / "redis"):
        d.mkdir(parents=True, exist_ok=True)
    common = f"""basedir="{fwd(MYSQL_HOME)}"
bind-address=127.0.0.1
mysqlx=OFF
character-set-server=utf8mb4
log-bin=mysql-bin
gtid-mode=ON
enforce-gtid-consistency=ON
default-time-zone=+05:30
log-bin-trust-function-creators=1
innodb-buffer-pool-size=128M
innodb-lock-wait-timeout=15
innodb-print-all-deadlocks=ON
log-error-verbosity=3
max-connections=300
"""
    (CNF / "primary.cnf").write_text(f"""[mysqld]
{common}datadir="{fwd(DATA / 'primary')}"
port={PORTS['primary']}
server-id=1
event-scheduler=ON
log-error="{fwd(LOGS / 'primary.err')}"
""", encoding="utf-8")
    (CNF / "replica.cnf").write_text(f"""[mysqld]
{common}datadir="{fwd(DATA / 'replica')}"
port={PORTS['replica']}
server-id=2
relay-log=relay-bin
event-scheduler=OFF
log-error="{fwd(LOGS / 'replica.err')}"
""", encoding="utf-8")
    (CNF / "redis.conf").write_text(f"""port {PORTS['redis']}
bind 127.0.0.1
save ""
appendonly no
""", encoding="utf-8")


# ---------------------------------------------------------------- processes
def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def wait_port(port, timeout=90, want=True):
    end = time.time() + timeout
    while time.time() < end:
        if port_open(port) == want:
            return True
        time.sleep(0.5)
    return False


def _pidfile(name):
    return PIDS / f"{name}.pid"


def pid_of(name):
    try:
        pid = int(_pidfile(name).read_text())
        return pid if psutil.pid_exists(pid) else None
    except (OSError, ValueError):
        return None


def spawn(name, args, env=None, cwd=None):
    log = open(LOGS / f"{name}.log", "ab")
    p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         cwd=str(cwd or ROOT), env=env, creationflags=FLAGS, close_fds=True)
    _pidfile(name).write_text(str(p.pid))
    return p.pid


def kill(name):
    """Hard kill, like pulling the plug (TerminateProcess)."""
    pid = pid_of(name)
    if pid:
        try:
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                child.kill()
            proc.kill()
            proc.wait(10)
        except psutil.Error:
            pass
    _pidfile(name).unlink(missing_ok=True)


def available():
    return (MYSQL_HOME / "bin" / "mysqld.exe").exists()


def status(name):
    return "running" if port_open(PORTS[name]) else "stopped"


# ---------------------------------------------------------------- MySQL
def _mysql(port, sql=None, file=None, password=ROOT_PASSWORD, database=None):
    args = [mysql_bin("mysql"), "-uroot", "-h127.0.0.1", f"-P{port}", "--default-character-set=utf8mb4"]
    if database:
        args.append(f"--database={database}")
    if password:
        args.append(f"-p{password}")
    if sql:
        args += ["-e", sql]
    stdin = open(file, "rb") if file else subprocess.DEVNULL
    try:
        r = subprocess.run(args, stdin=stdin, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        if file:
            stdin.close()
    if r.returncode != 0:
        raise RuntimeError(f"mysql on port {port} failed: {r.stderr.decode(errors='replace')[-600:]}")


def start_mysql(name, wait=True):
    if port_open(PORTS[name]):
        return
    spawn(name, [mysql_bin("mysqld"), f"--defaults-file={CNF / f'{name}.cnf'}"])
    if wait and not wait_port(PORTS[name], 120):
        raise RuntimeError(f"MySQL {name} did not start, see runtime/logs/{name}.err")


def _initialise(name):
    datadir = DATA / name
    if (datadir / "mysql").exists():
        return False
    say(f"Initialising MySQL {name} (one time only)...")
    shutil.rmtree(datadir, ignore_errors=True)
    r = subprocess.run([mysql_bin("mysqld"), f"--defaults-file={CNF / f'{name}.cnf'}", "--initialize-insecure"],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError(f"MySQL initialise failed, see runtime/logs/{name}.err")
    return True


def _ready(name):
    return DATA / f"{name}.ready"


def _set_root_password(port):
    try:
        _mysql(port, sql="SELECT 1")
    except RuntimeError:
        _mysql(port, sql=f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{ROOT_PASSWORD}'", password=None)


def setup_primary():
    if not _ready("primary").exists():
        kill("primary")                                          # a half-finished first run starts over
        wait_port(PORTS["primary"], 20, want=False)
        shutil.rmtree(DATA / "primary", ignore_errors=True)
    _initialise("primary")
    start_mysql("primary")
    if not _ready("primary").exists():
        say("Loading schema, triggers, events and demo data...")
        _set_root_password(PORTS["primary"])
        for f in ("schema.sql", "triggers.sql", "events.sql", "seed.sql", "readonly_user.sql", "replication_user.sql"):
            _mysql(PORTS["primary"], file=ROOT / "db" / f, database=None if f == "schema.sql" else "icu_beds")
        _ready("primary").write_text("ok")


def setup_replica():
    if not _ready("replica").exists():
        kill("replica")                                          # a half-finished first run starts over
        wait_port(PORTS["replica"], 20, want=False)
        shutil.rmtree(DATA / "replica", ignore_errors=True)
    _initialise("replica")
    start_mysql("replica")
    if not _ready("replica").exists():
        say("Connecting the read replica to the primary...")
        _set_root_password(PORTS["replica"])
        _mysql(PORTS["replica"], sql=(
            f"CHANGE REPLICATION SOURCE TO SOURCE_HOST='127.0.0.1', SOURCE_PORT={PORTS['primary']}, "
            "SOURCE_USER='repl', SOURCE_PASSWORD='replpass', SOURCE_AUTO_POSITION=1, GET_SOURCE_PUBLIC_KEY=1, "
            "SOURCE_CONNECT_RETRY=2, SOURCE_RETRY_COUNT=100000, SOURCE_HEARTBEAT_PERIOD=1; "
            "START REPLICA; SET PERSIST read_only = ON; SET PERSIST super_read_only = ON;"))
        _ready("replica").write_text("ok")


def stop_mysql(name):
    if port_open(PORTS[name]):
        subprocess.run([mysql_bin("mysqladmin"), "-uroot", f"-p{ROOT_PASSWORD}", "-h127.0.0.1", f"-P{PORTS[name]}", "shutdown"],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not wait_port(PORTS[name], 30, want=False):
            kill(name)
    _pidfile(name).unlink(missing_ok=True)


def error_log(name):
    return LOGS / f"{name}.err"


def log_lines(path, offset, keywords=None):
    """Lines written to a log file after byte offset, optionally filtered by keywords."""
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read().decode("utf-8", "replace")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if keywords:
        low = [k.lower() for k in keywords]
        lines = [ln for ln in lines if any(k in ln.lower() for k in low)]
    return lines


def wait_until(check, timeout=120, every=1.0, on_tick=None):
    deadline = time.time() + timeout
    n = 0
    while time.time() < deadline:
        if check():
            return True
        n += 1
        if on_tick:
            on_tick(n)
        time.sleep(every)
    return False


# ---------------------------------------------------------------- Redis
def start_redis():
    if port_open(PORTS["redis"]):
        return
    # this Redis build (msys2) does not understand C:\ paths, so pass the config relative to its folder
    spawn("redis", [redis_server(), "redis.conf"], cwd=CNF)
    if not wait_port(PORTS["redis"], 20):
        raise RuntimeError("Redis did not start, see runtime/logs/redis.log")


def stop_redis():
    kill("redis")
    wait_port(PORTS["redis"], 10, want=False)


# ---------------------------------------------------------------- app
def ensure_frontend():
    if (ROOT / "web" / "dist" / "index.html").exists():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("The interface is not built and Node.js is not installed. Install Node.js 20 and run again.")
    say("Building the interface (one time only)...")
    for args in ([npm, "ci", "--no-audit", "--no-fund"], [npm, "run", "build"]):
        r = subprocess.run(args, cwd=ROOT / "web", capture_output=True, shell=False)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(args[1:])} failed: {r.stderr.decode(errors='replace')[-600:]}")


def start_app(name):
    if port_open(PORTS[name]):
        return
    env = dict(os.environ, INSTANCE_NAME=name, MYSQL_PORT=str(PORTS["primary"]), REPLICA_PORT=str(PORTS["replica"]),
               PUBLIC_INSTANCES=PUBLIC, INTERNAL_INSTANCES=INTERNAL, PYTHONUNBUFFERED="1")
    spawn(name, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                 "--port", str(PORTS[name]), "--no-access-log"], env=env)
    if not wait_port(PORTS[name], 60):
        raise RuntimeError(f"{name} did not start, see runtime/logs/{name}.log")


# ---------------------------------------------------------------- commands
def up():
    ensure_binaries()
    write_configs()
    for name in ("primary", "replica", "redis", "app-1", "app-2"):
        if port_open(PORTS[name]) and not pid_of(name):
            raise RuntimeError(f"Port {PORTS[name]} is already used by another program (is Docker still running the old version?).")
    say("Starting MySQL primary...")
    setup_primary()
    say("Starting Redis...")
    start_redis()
    say("Starting MySQL read replica...")
    setup_replica()
    ensure_frontend()
    say("Starting the two app instances...")
    start_app("app-1")
    start_app("app-2")


def down():
    for name in ("app-2", "app-1"):
        kill(name)
    stop_redis()
    stop_mysql("replica")
    stop_mysql("primary")


def show():
    for name, port in PORTS.items():
        print(f"  {name:8} port {port:5}  {status(name)}")


def fresh():
    down()
    shutil.rmtree(DATA, ignore_errors=True)
    say("All data deleted. The next run.bat rebuilds it from db/*.sql.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        {"up": up, "down": down, "status": show, "fresh": fresh}[cmd]()
    except Exception as exc:  # shown in the .bat window
        print(f"\n  ERROR: {exc}\n")
        sys.exit(1)
