"""Build separately, then verify the default user and real HTTP container health."""

import json
import subprocess
import time
import urllib.request


def docker(*arguments: str) -> str:
    return subprocess.check_output(["docker", *arguments], text=True).strip()


def main() -> None:
    container = docker("run", "--detach", "--publish", "127.0.0.1::8000", "formreview:local")
    try:
        uid = docker("exec", container, "id", "-u")
        if uid != "10001":
            raise RuntimeError(f"Expected default UID 10001, got {uid}")
        address = docker("port", container, "8000/tcp")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = json.loads(docker("inspect", container))[0]["State"]
            if not state["Running"]:
                raise RuntimeError("Container exited before becoming healthy")
            if state.get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(1)
        else:
            raise RuntimeError("Container did not become healthy within 60 seconds")
        with urllib.request.urlopen(f"http://{address}/health/live", timeout=3) as response:
            if response.status != 200 or json.load(response) != {"status": "ok"}:
                raise RuntimeError("Unexpected real HTTP liveness response")
        print("PASS: default UID 10001, Docker healthy, real HTTP liveness")
    finally:
        docker("rm", "--force", container)


if __name__ == "__main__":
    main()
