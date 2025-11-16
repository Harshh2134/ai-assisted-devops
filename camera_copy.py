#!/usr/bin/env python3
import os
import re
import base64
from telnet_login_final import telnet_login

DEFAULT_DATE = "20251111"
DEFAULT_OUTPUT = "./REC_DOWNLOADS"
CHUNK_SIZE = 1024 * 512  # 512 KB

PROMPT_PATTERN = r"\[root@anyka.*\]\$"
BASE64_RE = re.compile(r"[A-Za-z0-9+/=]+$")


def clean_output(text: str) -> str:
    ansi = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    return ansi.sub("", text)


def run_cmd(child, cmd: str) -> str:
    child.sendline(cmd)
    child.expect([PROMPT_PATTERN], timeout=20)
    return clean_output(child.before)


def list_hour_folders(child, date: str):
    base = f"/mnt/tf/video/00/{date}"
    output = run_cmd(child, f"ls {base}")
    return re.findall(r"\b\d{4}-\d{4}\b", output)


def list_ts_files(child, date: str, folder: str):
    remote = f"/mnt/tf/video/00/{date}/{folder}"
    output = run_cmd(child, f"ls {remote}")
    parts = re.split(r"\s+", output)
    return [p for p in parts if p.endswith(".TS")]


def _extract_base64(payload: str) -> str:
    """Keep only the base64 lines produced by the remote base64 utility."""
    chunk_lines = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("dd ") or line.startswith("BusyBox"):
            continue
        if BASE64_RE.fullmatch(line):
            chunk_lines.append(line)
    return "".join(chunk_lines)


def fast_download(child, remote_path: str, local_path: str):
    size_out = run_cmd(child, f"stat -c %s '{remote_path}'")
    match = re.search(r"\d+", size_out)
    if not match:
        print(f"❌ Size error: {remote_path}")
        return

    total_size = int(match.group(0))
    print(f"➡ Copying {os.path.basename(local_path)} ({total_size} bytes)")

    with open(local_path, "wb") as f:
        offset = 0

        while offset < total_size:
            count = min(CHUNK_SIZE, total_size - offset)
            cmd = (
                f"dd if='{remote_path}' bs=1 skip={offset} count={count} 2>/dev/null | base64"
            )

            child.sendline(cmd)
            child.expect([PROMPT_PATTERN], timeout=60)

            raw = clean_output(child.before)
            b64 = _extract_base64(raw)

            if b64:
                try:
                    f.write(base64.b64decode(b64))
                except base64.binascii.Error as exc:
                    raise RuntimeError(
                        f"Failed to decode base64 chunk at offset {offset}"
                    ) from exc
            else:
                raise RuntimeError(
                    f"No base64 data received for chunk starting at offset {offset}"
                )

            offset += count
            print(f"   {offset}/{total_size} bytes", end="\r")

    print(f"\n✔ DONE: {local_path}")


def download_all(child, ip: str, date: str, output: str):
    folders = list_hour_folders(child, date)

    for folder in folders:
        print(f"\n📂 FOLDER {folder}")
        local_folder = os.path.join(output, folder)
        os.makedirs(local_folder, exist_ok=True)

        files = list_ts_files(child, date, folder)

        for file in files:
            remote = f"/mnt/tf/video/00/{date}/{folder}/{file}"
            local = os.path.join(local_folder, file)
            fast_download(child, remote, local)

    print("\n🎉 All files copied successfully (single-thread safe mode)")


if __name__ == "__main__":
    print("=== ANYKA SD COPY (SAFE MODE) ===")

    ip = input("Enter Camera IP: ").strip()
    date = (
        input(f"Enter Date Folder (YYYYMMDD) [Default {DEFAULT_DATE}]: ").strip()
        or DEFAULT_DATE
    )
    output = input(
        f"Enter Output Folder [Default {DEFAULT_OUTPUT}]: "
    ).strip() or DEFAULT_OUTPUT

    child = telnet_login(ip)
    if child:
        download_all(child, ip, date, output)
