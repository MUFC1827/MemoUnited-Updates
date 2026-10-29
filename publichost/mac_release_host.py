"""Public GitHub runner host: private source, private logs, encrypted artifacts.

Only controlled stage names/status reach the public console. The original
private-source commands, application and native assertions are unchanged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


VERSION = "7.2.0"
SOURCE_REPOSITORY = "MUFC1827/MemoUnited-macOS-20261009"
HOST_REPOSITORY = "MUFC1827/MemoUnited-Updates"
SOURCE_COMMIT = "380580c5713a69452252fbbcfe418eeb44a9d7fd"
SOURCE_WORKFLOW_SHA256 = "f55df7f9f7a0ce447a195e5f2ff886ff69da167e938935cb3ab495785af7d833"
MAGIC = b"MEMOUNITED-CLOUD-720\x00"
ARTIFACT = "MemoUnited_macOS_7.2.0_arm64.mucloud"
ROOTS = ("MemoUnited-macOS-arm64", "MemoUnited-macOS-QA-arm64")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status(name: str, state: str) -> None:
    # Names are controlled by the fixed accepted workflow; never print commands.
    print(name + ": " + state, flush=True)


def host_identity() -> dict:
    if (sys.platform != "darwin" or platform.machine() != "arm64"
            or sys.version_info[:3] != (3, 13, 12)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != HOST_REPOSITORY
            or os.environ.get("RUNNER_OS") != "macOS"):
        raise RuntimeError("Unexpected build host")
    run_id, attempt = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "")
    commit = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Missing host identity")
    return {"schema": 1, "provider": "github-actions", "version": VERSION,
            "executionRepository": HOST_REPOSITORY, "executionRepositoryVisibility": "public",
            "sourceRepository": SOURCE_REPOSITORY, "repositoryVisibility": "private",
            "sourceCommit": SOURCE_COMMIT, "workflowCommit": commit,
            "runId": run_id, "runAttempt": attempt, "architecture": "arm64", "system": "Darwin"}


def bootstrap(log_path: Path) -> bool:
    status("Bootstrap private build tools", "running")
    with log_path.open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                                     "--only-binary=:all:", "cryptography==46.0.5", "PyYAML==6.0.3"],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            ok = result.returncode == 0
        except Exception:
            ok = False
    status("Bootstrap private build tools", "passed" if ok else "failed")
    return ok


def copy_accepted_source(source: Path, destination: Path, receipt: dict, log_path: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("Unexpected source checkout")
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, timeout=30)
        if result.returncode != 0 or result.stdout.decode("ascii").strip() != SOURCE_COMMIT:
            raise RuntimeError("Source commit differs")
    workflow = source / ".github/workflows/macos.yml"
    if workflow.is_symlink() or digest(workflow) != SOURCE_WORKFLOW_SHA256:
        raise RuntimeError("Source workflow differs")
    manifest_path = source / "BUILD_KIT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("personal_data_included") is not False:
        raise RuntimeError("Unexpected source manifest")
    files = {row["path"]: row for row in manifest["files"]}
    for name, row in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise RuntimeError("Unexpected source path")
        original = source / name
        if (original.is_symlink() or not original.resolve().is_relative_to(source.resolve())
                or original.stat().st_size != row["bytes"] or digest(original) != row["sha256"]):
            raise RuntimeError("Source manifest mismatch")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    for relative in ("BUILD_KIT_MANIFEST.json", ".github/workflows/macos.yml"):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    receipt["sourceWorkflowSha256"] = digest(workflow)
    receipt["buildKitManifestSha256"] = digest(manifest_path)


def original_pipeline(source: Path) -> list[dict]:
    import yaml
    document = yaml.safe_load((source / ".github/workflows/macos.yml").read_text(encoding="utf-8"))
    steps = []
    for original in document["jobs"]["mac-app"]["steps"]:
        if "run" not in original or original["name"] == "Compare native Metal window startup without packaging":
            continue
        steps.append({"name": original["name"], "run": original["run"].replace("${{ matrix.arch }}", "arm64"),
                      "env": original.get("env", {}), "timeout": int(original.get("timeout-minutes", 35)) * 60,
                      "always": "!cancelled()" in original.get("if", "")})
    if len(steps) != 20 or sum(step["always"] for step in steps) != 2:
        raise RuntimeError("Unexpected accepted pipeline")
    # Existing original source-window diagnostic, with ordinary GitHub Python.
    steps.insert(1, {"name": "Verify exposed production Cocoa and Metal source window first", "timeout": 90,
                    "run": 'python -B release/qa/mac_window_test.py "release/macos/qa/arm64/mac-window-source-preflight.json"\n',
                    "env": {"QT_QPA_PLATFORM": "cocoa", "QT_QUICK_BACKEND": "rhi", "QSG_RHI_BACKEND": "metal"},
                    "always": False, "exposure_preflight": True})
    return steps


def execute(step: dict, source: Path, private: Path, ordinal: int, deadline: float) -> dict:
    name = step["name"]
    status(name, "running")
    command = private / "commands" / f"{ordinal:02d}.sh"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.write_text(step["run"], encoding="utf-8", newline="\n")
    log_path = private / "logs" / f"{ordinal:02d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"GITHUB_WORKSPACE": str(source), "PYTHONDONTWRITEBYTECODE": "1"})
    env.update(step["env"])
    result = {"name": name, "status": "failed", "startedAt": now(), "exitCode": 125,
              "commandSha256": digest(command), "log": f"host/logs/{ordinal:02d}.log"}
    with log_path.open("w", encoding="utf-8") as log:
        try:
            remaining = max(1, int(deadline - time.monotonic()))
            process = subprocess.Popen(["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(command)],
                                       cwd=source, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, process_group=0)
            try:
                code = process.wait(timeout=min(step["timeout"], remaining))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                code = 124
            result.update(exitCode=code, status="passed" if code == 0 else "failed")
        except Exception as error:
            log.write("Private host execution failure: " + type(error).__name__ + "\n")
    result["finishedAt"] = now()
    status(name, result["status"])
    return result


def collect_payload(source: Path, private: Path, receipt: dict) -> Path:
    payload = private / "payload"
    payload.mkdir()
    apps, qa = (payload / root for root in ROOTS)
    apps.mkdir()
    source_qa = source / "release/macos/qa/arm64"
    if source_qa.exists():
        shutil.copytree(source_qa, qa, symlinks=True)
    else:
        qa.mkdir()
    shutil.copytree(private / "logs", qa / "host/logs")
    commands = private / "commands"
    if commands.exists():
        shutil.copytree(commands, qa / "host/commands")
    if receipt["pipelineOk"]:
        dist = source / "release/macos/dist"
        expected = ("MemoUnited_macOS_arm64.app.zip", "MemoUnited_macOS_arm64.dmg", "release-info-arm64.json")
        if not all((dist / name).is_file() and not (dist / name).is_symlink() for name in expected):
            receipt["pipelineOk"] = False
            receipt["artifactCollectionFailed"] = True
        else:
            for item in sorted(dist.iterdir()):
                if item.is_file() and not item.is_symlink():
                    shutil.copyfile(item, apps / item.name)
    save_json(payload / "PUBLIC_HOST_PROVENANCE.json", receipt)
    inventory = []
    for item in sorted(payload.rglob("*")):
        if item.is_symlink():
            raise RuntimeError("Outer payload contains a link")
        if item.is_file():
            inventory.append({"path": item.relative_to(payload).as_posix(), "bytes": item.stat().st_size,
                              "sha256": digest(item)})
    save_json(payload / "FILES.json", {"schema": 1, "provider": "github-actions", "files": inventory})
    archive = private / "private-payload.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for root in ROOTS:
            bundle.writestr(root + "/", b"")
        for item in sorted(payload.rglob("*")):
            if item.is_file():
                bundle.write(item, item.relative_to(payload).as_posix())
    return archive


def encrypt_artifact(archive: Path, target: Path, public_key: Path, receipt: dict) -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = serialization.load_pem_public_key(public_key.read_bytes())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 3072:
        raise RuntimeError("Expected the accepted RSA3072 public key")
    aes_key, nonce = os.urandom(32), os.urandom(12)
    wrapped = key.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                               algorithm=hashes.SHA256(), label=None))
    header = {"schema": 1, "algorithm": "AES-256-GCM+RSA-OAEP-SHA256",
              "nonce": base64.b64encode(nonce).decode("ascii"),
              "wrappedKey": base64.b64encode(wrapped).decode("ascii"),
              "sourceCommit": SOURCE_COMMIT, "runId": receipt["runId"],
              "workflowCommit": receipt["workflowCommit"], "version": VERSION}
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    aad = MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
    encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".partial")
    try:
        with archive.open("rb") as source, temporary.open("xb") as output:
            output.write(aad)
            for block in iter(lambda: source.read(1024 * 1024), b""):
                output.write(encryptor.update(block))
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    receipt = host_identity()
    deadline = time.monotonic() + 30 * 60  # Leave five minutes for sealing/upload within the 35-minute job.
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    checkout = args.source.resolve(strict=True)
    host = args.host.resolve(strict=True)
    public_key = args.key.resolve(strict=True)
    if (not checkout.is_relative_to(workspace) or not host.is_relative_to(workspace)
            or public_key != host / ".github/keys/mac-720-artifacts.pem" or args.key.is_symlink()):
        raise RuntimeError("Unexpected checkout or key location")
    task = Path(tempfile.mkdtemp(prefix="MemoUnited-private-release-", dir=os.environ["RUNNER_TEMP"]))
    private = task / "host"
    (private / "logs").mkdir(parents=True)
    source = task / "source"
    receipt.update(pipelineOk=False, steps=[], startedAt=now())
    if not bootstrap(private / "logs/bootstrap.log"):
        # No encryption engine: fail closed. Never upload any plaintext fallback.
        return 1
    try:
        status("Validate accepted private source", "running")
        copy_accepted_source(checkout, source, receipt, private / "logs/source-validation.log")
        status("Validate accepted private source", "passed")
        steps = original_pipeline(source)
        failed = preflight_failed = False
        for ordinal, step in enumerate(steps, 1):
            if preflight_failed or (failed and not step["always"]):
                receipt["steps"].append({"name": step["name"], "status": "skipped", "exitCode": None})
            else:
                result = execute(step, source, private, ordinal, deadline)
                receipt["steps"].append(result)
                if result["exitCode"]:
                    failed = True
                    preflight_failed = step.get("exposure_preflight", False)
        receipt["pipelineOk"] = not failed and len(receipt["steps"]) == 21
    except Exception as error:
        # Full exception data never reaches the public build console.
        with (private / "logs/host-failure.log").open("w", encoding="utf-8") as log:
            import traceback
            traceback.print_exc(file=log)
        receipt["pipelineOk"] = False
        receipt["hostFailureType"] = type(error).__name__
        status("Private source validation or execution", "failed")
    finally:
        receipt["finishedAt"] = now()
        status("Encrypt private release evidence", "running")
        try:
            archive = collect_payload(source, private, receipt)
            target = Path(os.environ["RUNNER_TEMP"]) / "MemoUnited-public-release-output" / ARTIFACT
            encrypt_artifact(archive, target, public_key, receipt)
            status("Encrypt private release evidence", "passed")
        except Exception:
            status("Encrypt private release evidence", "failed")
            return 1
    return 0 if receipt["pipelineOk"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Prevent source paths, traceback text, environment or commands leaking.
        status("Private release host", "failed")
        raise SystemExit(1) from None
