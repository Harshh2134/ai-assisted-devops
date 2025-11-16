#!/usr/bin/env python3

import base64
import os
import re
from typing import List, Optional

from telnet_login_final import telnet_login

DEFAULT_DATE = "20251111"
DEFAULT_OUTPUT = "./REC_DOWNLOADS"
CHUNK_SIZE = 1024 * 512  # 512 KB

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
PROMPT_RE = re.compile(r"\[root@anyka.*\]\$")
BASE64_LINE_RE = re.compile(r"[A-Za-z0-9+/=]+")
CHUNK_BEGIN = "__CHUNK_BEGIN__"
CHUNK_END = "__CHUNK_END__"


def clean_output(text: Optional[str]) -> str:
    """Strip ANSI escapes and carriage returns from telnet output."""
    if not text:
        return ""

    cleaned = ANSI_RE.sub("", text)
    return cleaned.replace("\r", "")


def run_cmd(child, cmd: str, timeout: int = 20) -> str:
    """Execute a command on the remote device and return its stdout."""
    child.sendline(cmd)
    child.expect(PROMPT_RE, timeout=timeout)

    raw = clean_output(child.before)
    lines = [line for line in raw.splitlines() if line.strip()]

    if lines and lines[0].strip() == cmd:
        lines = lines[1:]

    return "\n".join(lines)


def list_hour_folders(child, date: str) -> List[str]:
    base = f"/mnt/tf/video/00/{date}"
    output = run_cmd(child, f"ls {base}")
    return re.findall(r"\b\d{4}-\d{4}\b", output)


def list_ts_files(child, date: str, folder: str) -> List[str]:
    remote = f"/mnt/tf/video/00/{date}/{folder}"
    output = run_cmd(child, f"ls {remote}")
    parts = re.split(r"\s+", output.strip())
    return [p for p in parts if p.endswith(".TS")]


def _extract_base64_payload(raw: str) -> str:
    """Return a contiguous base64 payload delimited by chunk markers."""
    match = re.search(
        rf"{CHUNK_BEGIN}\s*(?P<data>.+?)\s*{CHUNK_END}",
        raw,
        flags=re.DOTALL,
    )

    if not match:
        return ""

    payload = match.group("data")
    fragments = BASE64_LINE_RE.findall(payload)
    return "".join(fragments)


def fast_download(child, remote_path: str, local_path: str) -> None:
    size_out = run_cmd(child, f"wc -c < '{remote_path}'")
    lines = [line.strip() for line in size_out.splitlines() if line.strip()]

    match_line = next((line for line in reversed(lines) if line.isdigit()), "")

    if not match_line:
        print(f"❌ Size error: {remote_path}")
        return

    total_size = int(match_line)
    print(f"➡ Copying {os.path.basename(local_path)} ({total_size} bytes)")

    with open(local_path, "wb") as f:
        offset = 0

        while offset < total_size:
            count = min(CHUNK_SIZE, total_size - offset)
            dd_cmd = f"dd if='{remote_path}' bs=1 skip={offset} count={count} 2>/dev/null"
            cmd = (
                f"(printf '{CHUNK_BEGIN}\\n'; {dd_cmd} | base64; printf '\\n{CHUNK_END}\\n')"
            )

            child.sendline(cmd)
            child.expect(PROMPT_RE, timeout=120)

            raw = clean_output(child.before)
            b64 = _extract_base64_payload(raw)

            if not b64:
                print(f"\n⚠️ Empty chunk detected at offset {offset}. Retrying...")
                continue

            try:
                f.write(base64.b64decode(b64, validate=True))
            except Exception as exc:  # noqa: BLE001
                print(f"\n❌ Failed to decode chunk at offset {offset}: {exc}")
                break

            offset += count
            print(f"   {offset}/{total_size} bytes", end="\r")

    print(f"\n✔ DONE: {local_path}")


def download_all(child, date: str, output: str) -> None:
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


def main() -> None:
    print("=== ANYKA SD COPY (SAFE MODE) ===")

    ip = input("Enter Camera IP: ").strip()
    date = input(f"Enter Date Folder (YYYYMMDD) [Default {DEFAULT_DATE}]: ").strip() or DEFAULT_DATE
    output = input(f"Enter Output Folder [Default {DEFAULT_OUTPUT}]: ").strip() or DEFAULT_OUTPUT

    child = telnet_login(ip)
    if child:
        download_all(child, date, output)


if __name__ == "__main__":
    main()
