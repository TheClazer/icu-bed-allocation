"""Docker control for the failure demos (kill MySQL, stop Redis).

The app container mounts /var/run/docker.sock, so it can ask the Docker engine
to SIGKILL the MySQL container exactly like `docker kill icu_mysql` would.
"""
import time

_client = None


class DockerUnavailable(Exception):
    pass


def client():
    global _client
    if _client is None:
        try:
            import docker
            _client = docker.from_env(timeout=20)
            _client.ping()
        except Exception as exc:
            _client = None
            raise DockerUnavailable(
                "Docker engine not reachable from the app. Run with docker compose so /var/run/docker.sock is mounted.") from exc
    return _client


def available():
    try:
        client()
        return True
    except DockerUnavailable:
        return False


def get(name):
    return client().containers.get(name)


def kill(name):
    get(name).kill()          # SIGKILL: no shutdown, no flush, like pulling the plug


def stop(name):
    get(name).stop(timeout=3)


def start(name):
    c = get(name)
    c.reload()
    if c.status != "running":
        c.start()


def status(name):
    try:
        c = get(name)
        c.reload()
        return c.status
    except Exception:
        return "unknown"


def logs_since(name, since_epoch, keywords=None):
    raw = get(name).logs(since=int(since_epoch), stdout=True, stderr=True).decode("utf-8", "replace")
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
