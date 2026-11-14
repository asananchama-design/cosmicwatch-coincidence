#!/usr/bin/env python3
"""Record both original CosmicWatch Nano serial ports concurrently on macOS.

Uses Python 3 standard library only. Run: python3 record_both_cosmicwatch.py
Keep the latest 60-second serial-only sketch on both boards, one of each role.
USB reset timing is approximate; this does NOT synchronize the detector clocks.
"""
import csv
import math
import re
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

DURATION_S = 60.0  # Matches the supplied one-minute Arduino sketch.
BIN_SECONDS = 10.0
REQUIRE_COINCIDENCE = True  # Reject master singles as coincidence data.
COLUMNS = [
    "event", "time_ms", "adc", "sipm_mv_estimate",
    "busy_us_before_event", "temp_c_estimate",
]


def parse_run(raw, require_coincidence=True):
    """Read the latest six-column serial format; reject incomplete/mixed runs."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Save a plain-text UTF-8 .txt file, not a Word/RTF document.") from exc
    if text.lstrip().startswith("{\\rtf"):
        raise ValueError("This is RTF. In TextEdit choose Format > Make Plain Text and save again.")

    rows, metadata = [], {}
    headers = starts = ends = run_titles = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        # Optional Arduino IDE display timestamp; does not alter Arduino time_ms.
        line = re.sub(r"^\s*\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*->\s*", "", line).strip()
        if not line:
            continue
        if line.startswith("#"):
            comment = line[1:].strip()
            run_titles += int(comment.startswith("CosmicWatch v2: 60-second acquisition"))
            starts += int(comment.startswith("START: recording for 60 seconds"))
            ends += int(comment.startswith("DONE: 60-second acquisition complete"))
            if "=" in comment:
                key, value = comment.split("=", 1)
                key, value = key.strip(), value.strip()
                if key in metadata:
                    raise ValueError(f"Repeated metadata '{key}': save only one run per file.")
                metadata[key] = value
            continue
        fields = [value.strip() for value in next(csv.reader([line]))]
        if fields == COLUMNS:
            headers += 1
            continue
        if len(fields) != len(COLUMNS):
            raise ValueError(f"Line {line_number}: expected six comma-separated values. "
                             "Copy the complete output from the latest serial-only sketch.")
        if headers != 1 or starts != 1 or ends:
            raise ValueError(f"Line {line_number}: event outside a single START/DONE run.")
        try:
            row = dict(zip(COLUMNS, [float(value) for value in fields]))
        except ValueError as exc:
            raise ValueError(f"Line {line_number}: nonnumeric or damaged event row.") from exc
        if not all(math.isfinite(value) for value in row.values()):
            raise ValueError(f"Line {line_number}: nonfinite value (nan/inf).")
        for key in ("event", "time_ms", "adc", "busy_us_before_event"):
            if row[key] != int(row[key]):
                raise ValueError(f"Line {line_number}: {key} must be an integer.")
            row[key] = int(row[key])
        if row["event"] != len(rows) + 1:
            raise ValueError(f"Line {line_number}: missing, repeated, or restarted event number.")
        if not 0 <= row["time_ms"] < DURATION_S * 1000:
            raise ValueError(f"Line {line_number}: event lies outside the 60-second run.")
        if not 0 <= row["adc"] <= 1023:
            raise ValueError(f"Line {line_number}: ADC must be between 0 and 1023.")
        if not 0 <= row["busy_us_before_event"] <= row["time_ms"] * 1000 + 999:
            raise ValueError(f"Line {line_number}: invalid cumulative busy time.")
        if rows and (row["time_ms"] < rows[-1]["time_ms"] or
                     row["busy_us_before_event"] < rows[-1]["busy_us_before_event"]):
            raise ValueError(f"Line {line_number}: time/busy time went backwards; check for combined runs.")
        rows.append(row)

    if (headers, starts, ends, run_titles) != (1, 1, 1, 1):
        raise ValueError("Include exactly one complete run: title, role, column header, "
                         "START, all event rows, DONE, and final totals. Do not combine resets.")
    role = metadata.get("role")
    if role not in ("SLAVE_COINCIDENCE", "MASTER_SINGLES"):
        raise ValueError("Missing/unknown # role. Copy the run header too.")
    if require_coincidence and role != "SLAVE_COINCIDENCE":
        raise ValueError("This is MASTER singles data. Upload the SLAVE file for coincidence graphs.")
    for key in ("accepted_events", "local_triggers", "local_busy_us"):
        try:
            metadata[key] = int(metadata[key])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Missing/invalid # {key} summary. Copy through the final totals.") from exc
    if metadata["accepted_events"] != len(rows):
        raise ValueError("Event-row count does not match accepted_events. Some output is missing.")
    if metadata["local_triggers"] < len(rows):
        raise ValueError("Invalid summary: fewer local triggers than accepted events.")
    minimum_busy = rows[-1]["busy_us_before_event"] if rows else 0
    if not minimum_busy <= metadata["local_busy_us"] <= DURATION_S * 1e6:
        raise ValueError("Invalid final busy-time summary.")
    return rows, metadata


import argparse
import fcntl
import glob
import json
import os
import select
import struct
import subprocess
import sys
import termios
import time
from datetime import datetime

TITLE = b"# CosmicWatch v2: 60-second acquisition"
FINISH = "# Copy this output to a text file."


class Capture:
    def __init__(self, port, path):
        self.port = port
        self.path = Path(path)
        self.buffer = bytearray()
        self.started = False
        self.finished = False
        self.role = None
        self.count = 0
        self.start_received = None
        self.received_bytes = 0
        self.preview_lines = 0
        self.handle = self.path.open("xb")
        self.raw_path = self.path.with_suffix(".raw.bin")
        self.raw_handle = self.raw_path.open("xb")

    def feed(self, chunk, now):
        self.received_bytes += len(chunk)
        self.raw_handle.write(chunk)
        self.raw_handle.flush()
        self.buffer.extend(chunk)
        if len(self.buffer) > 100000:
            raise ValueError(f"{self.port}: no valid line endings; check firmware/baud.")
        while b"\n" in self.buffer:
            raw, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            raw = bytes(raw).rstrip(b"\r")
            if not self.started and raw and self.preview_lines < 6:
                print(f"  RECEIVED [{Path(self.port).name}]: {ascii(raw[:200].decode('utf-8', errors='backslashreplace'))}", flush=True)
                self.preview_lines += 1
            if b"CosmicWatch standalone detector test" in raw or b"mode=LOCAL_SINGLES" in raw:
                raise ValueError(f"{self.port}: the STANDALONE TEST sketch is still installed. "
                                 "Upload CosmicWatch_Master_Serial.ino to the master and "
                                 "CosmicWatch_Slave_Serial.ino to the slave before paired recording.")
            if raw.startswith(b"### CosmicWatch: The Desktop Muon Detector"):
                raise ValueError(f"{self.port}: an older firmware format was received. "
                                 "Upload the supplied Master_Serial/Slave_Serial sketches.")
            location = raw.find(TITLE)
            if location >= 0:
                if self.started:
                    raise ValueError(f"{self.port}: reset during capture. Start a new paired run.")
                raw = raw[location:]
                self.started = True
                self.start_received = now
            if not self.started:
                continue  # Ignore bootloader/startup bytes before the run header.
            if self.finished:
                if raw.strip():
                    raise ValueError(f"{self.port}: unexpected data after a finished run.")
                continue
            self.handle.write(raw + b"\n")
            self.handle.flush()
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"{self.port}: corrupt serial text after run start.") from exc
            if line.startswith("# role="):
                self.role = line.split("=", 1)[1].strip()
                if self.role not in ("MASTER_SINGLES", "SLAVE_COINCIDENCE"):
                    raise ValueError(f"{self.port}: unknown detector role.")
                print(f"  {self.port}: {self.role}", flush=True)
            if line and line[0].isdigit():
                self.count += 1
            if line.startswith(FINISH):
                parse_run(self.path.read_bytes(), require_coincidence=False)
                self.finished = True
                print(f"  COMPLETE: {self.role}, {self.count} recorded events", flush=True)

    def close(self):
        if not self.handle.closed:
            self.handle.close()
        if not self.raw_handle.closed:
            self.raw_handle.close()


def open_serial(port):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, termios.TIOCEXCL)
        settings = termios.tcgetattr(fd)
        settings[0] = 0
        settings[1] = 0
        settings[2] = termios.CLOCAL | termios.CREAD | termios.CS8 | termios.HUPCL
        settings[3] = 0
        settings[4] = settings[5] = termios.B115200
        settings[6][termios.VMIN] = 0
        settings[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        termios.tcflush(fd, termios.TCIFLUSH)
    except BaseException:
        os.close(fd)
        raise
    return fd


def close_serial(fd):
    try:
        fcntl.ioctl(fd, termios.TIOCNXCL)
    except OSError:
        pass
    os.close(fd)


def reset_pair(fds):
    flag = struct.pack("I", termios.TIOCM_DTR)
    # Deassert both first, then assert both in quick succession. Each Nano's
    # bootloader/USB adapter adds its own delay; this is not a shared clock.
    for fd in fds:
        fcntl.ioctl(fd, termios.TIOCMBIC, flag)
    time.sleep(0.15)
    for fd in fds:
        termios.tcflush(fd, termios.TCIFLUSH)
    for fd in fds:
        fcntl.ioctl(fd, termios.TIOCMBIS, flag)


def choose_ports(explicit=None):
    if explicit:
        ports = explicit
    else:
        available = sorted(set(glob.glob("/dev/cu.usbserial*") +
                               glob.glob("/dev/cu.usbmodem*")))
        print("USB serial ports:")
        for index, port in enumerate(available, 1):
            print(f"  {index}: {port}")
        if len(available) < 2:
            raise ValueError("Two USB serial ports are required. Connect BOTH detectors with USB DATA cables.")
        if len(available) == 2:
            ports = available
        else:
            selected = input("Enter the TWO detector numbers, separated by a space: ").split()
            if len(selected) != 2:
                raise ValueError("Choose exactly two detector ports.")
            try:
                indices = [int(number) for number in selected]
                if any(index < 1 or index > len(available) for index in indices):
                    raise ValueError()
                ports = [available[index - 1] for index in indices]
            except (ValueError, IndexError) as exc:
                raise ValueError("Invalid port selection.") from exc
    if len(ports) != 2 or ports[0] == ports[1]:
        raise ValueError("Choose two DIFFERENT serial ports.")
    return ports


def capture_pair(fds, captures, timeout=100.0, manual_reset=False, start_timeout=20.0):
    began = time.monotonic()
    next_status = began + 10
    waiting_notified = False
    while not all(capture.finished for capture in captures):
        now = time.monotonic()
        if now - began > timeout:
            pending = [capture.port for capture in captures if not capture.finished]
            raise TimeoutError("No complete 60-second run from: " + ", ".join(pending) +
                               ". Run --diagnose --manual-reset to inspect actual serial output.")
        ready, _, _ = select.select(fds, [], [], 0.2)
        for fd in ready:
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if chunk:
                captures[fds.index(fd)].feed(chunk, time.monotonic())
        known_roles = [capture.role for capture in captures if capture.role]
        if len(known_roles) == 2 and len(set(known_roles)) != 2:
            raise ValueError("Both boards have the same role. Upload MASTER_MODE=1 to one and 0 to the other.")
        if now - began > 8 and not waiting_notified and not all(c.started for c in captures):
            for capture in captures:
                if not capture.started:
                    print(f"Waiting for {capture.port}: {capture.received_bytes} bytes received, "
                          "no expected run header.", flush=True)
            if manual_reset:
                print("Manual-reset mode is active. A missing header can mean no serial data, "
                      "different firmware, or unreadable bytes; it is not a zero-event result.", flush=True)
            else:
                print("Automatic reset has not produced both headers. Use --diagnose --manual-reset "
                      "if this attempt fails.", flush=True)
            waiting_notified = True
        if now - began > start_timeout and not all(c.started for c in captures):
            pending = "; ".join(f"{c.port}: {c.received_bytes} bytes" for c in captures if not c.started)
            raise TimeoutError("No expected start header after 20 seconds (" + pending + "). "
                               "Raw bytes were saved for diagnosis. Run --diagnose --manual-reset.")
        if now >= next_status:
            status = "; ".join(f"{c.role or Path(c.port).name}: {c.count} events" for c in captures)
            print(f"Recording ... {status}", flush=True)
            next_status = now + 10


def diagnose_ports(fds, ports, output, duration=25.0):
    """Show unfiltered serial text without requiring any particular firmware."""
    buffers = [bytearray() for _ in fds]
    totals = [0 for _ in fds]
    shown = [0 for _ in fds]
    logs = []
    observed = []
    print("DIAGNOSTIC: listening to both ports for 25 seconds; this is not a measurement run.", flush=True)
    try:
        for i in range(len(fds)):
            logs.append((output / f"port_{i + 1}.raw.bin").open("xb"))
        began = time.monotonic()
        while time.monotonic() - began < duration:
            ready, _, _ = select.select(fds, [], [], 0.2)
            for fd in ready:
                i = fds.index(fd)
                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    continue
                totals[i] += len(chunk)
                logs[i].write(chunk)
                logs[i].flush()
                if totals[i] == len(chunk):
                    message = f"FIRST BYTES [{ports[i]}]: {ascii(chunk[:100].decode('utf-8', errors='backslashreplace'))}"
                    print(message, flush=True)
                    observed.append(message)
                buffers[i].extend(chunk)
                while b"\n" in buffers[i]:
                    line, _, rest = buffers[i].partition(b"\n")
                    buffers[i] = bytearray(rest)
                    if shown[i] < 12:
                        message = f"RECEIVED [{ports[i]}]: {ascii(bytes(line).rstrip(bytes([13])).decode('utf-8', errors='backslashreplace')[:240])}"
                        print(message, flush=True)
                        observed.append(message)
                        shown[i] += 1
                if len(buffers[i]) > 10000:
                    buffers[i].clear()  # Raw file retains bytes without line endings.
        print("\nDIAGNOSTIC FINISHED:", flush=True)
        for port, total in zip(ports, totals):
            message = f"{port}: {total} bytes received"
            print(message, flush=True)
            observed.append(message)
        summary = output / "diagnostic_summary.txt"
        summary.write_text("\n".join(observed) + "\n", encoding="utf-8")
        print(f"Summary saved: {summary}", flush=True)
        print("Share diagnostic_summary.txt or the RECEIVED lines. Do not upload diagnostic files to Colab.", flush=True)
        return totals
    finally:
        for handle in logs:
            handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ports", nargs=2, metavar=("PORT1", "PORT2"))
    parser.add_argument("--manual-reset", action="store_true")
    parser.add_argument("--diagnose", action="store_true", help="Show actual serial bytes for 25 seconds without filtering headers")
    parser.add_argument("--no-open", action="store_true", help="Do not reveal results in Finder")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise ValueError("This recorder is written for macOS.")
    ports = choose_ports(args.ports)
    print("\nClose Arduino IDE and any older serial capture windows first.")
    input("When both detectors and the coincidence cable are connected, press Return to record: ")
    prefix = "cosmicwatch_diagnostic_" if args.diagnose else "cosmicwatch_pair_"
    output = Path.home() / "Desktop" / (prefix + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    output.mkdir()
    print(f"Saving to: {output}", flush=True)
    fds, captures = [], []
    successful = False
    try:
        for index, port in enumerate(ports, 1):
            fd = open_serial(port)
            fds.append(fd)
            if not args.diagnose:
                captures.append(Capture(port, output / f"port_{index}.partial.txt"))
            actual = termios.tcgetattr(fd)
            print(f"Opened {port}: input baud={actual[4]}, output baud={actual[5]}", flush=True)
        if args.manual_reset:
            input("Both ports are open. Press Return, then immediately RESET BOTH detectors close together: ")
            for fd in fds:
                termios.tcflush(fd, termios.TCIFLUSH)
            print("READY: press both physical RESET buttons now.", flush=True)
        else:
            print("Opening both ports at 115200 baud and requesting a reset of both Nanos...", flush=True)
            try:
                reset_pair(fds)
            except OSError as exc:
                raise RuntimeError("USB automatic reset is unavailable. Rerun with --manual-reset.") from exc
            print("Recording both detectors. Do not press RESET or reopen Arduino IDE.", flush=True)
        if args.diagnose:
            diagnose_ports(fds, ports, output)
            successful = True
            return
        capture_pair(fds, captures, manual_reset=args.manual_reset)
        for capture in captures:
            capture.close()
        roles = {capture.role for capture in captures}
        if roles != {"MASTER_SINGLES", "SLAVE_COINCIDENCE"}:
            raise ValueError("Need exactly one master and one slave.")
        details = []
        for capture in captures:
            rows, metadata = parse_run(capture.path.read_bytes(), require_coincidence=False)
            name = "master.txt" if capture.role == "MASTER_SINGLES" else "slave.txt"
            final = output / name
            capture.path.rename(final)
            details.append({"file": name, "port": capture.port, "role": capture.role,
                            "accepted_events": len(rows), "local_triggers": metadata["local_triggers"],
                            "header_received_monotonic_s": capture.start_received})
        gap = abs(captures[0].start_received - captures[1].start_received)
        report = {"files": details, "host_header_arrival_gap_s": gap,
                  "note": "Host arrival gap is diagnostic only, NOT the detector start-time offset. "
                          "USB resets and independent Nano clocks are not precision synchronization."}
        (output / "capture_info.json").write_text(json.dumps(report, indent=2) + "\n")
        successful = True
        print("\nSAVED BOTH FILES: master.txt and slave.txt", flush=True)
        print(f"Header arrival gap observed by the computer: {gap:.3f} s (not a clock calibration).")
        print("Upload ONLY master.txt and slave.txt together to the Master_vs_Slave Colab notebook.")
    finally:
        for capture in captures:
            capture.close()
        for fd in fds:
            close_serial(fd)
        if not successful:
            print(f"Session did not complete. Partial/raw files, if any, remain in {output}", flush=True)
    if successful and not args.no_open:
        subprocess.run(["open", str(output)], check=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCapture cancelled. Ports closed; incomplete files are not valid Colab runs.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nERROR: {exc}\nIf a port is busy, quit Arduino IDE and close previous capture windows.", file=sys.stderr)
        sys.exit(1)
