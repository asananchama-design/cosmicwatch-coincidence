# Run this whole script in ONE Google Colab code cell.
# Upload two complete text files from the SAME run when prompted.

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


def compare_runs(uploaded):
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    if len(uploaded) != 2:
        raise ValueError("Upload two complete files: one MASTER and one SLAVE from the same experiment.")
    runs = {}
    for name, raw in uploaded.items():
        rows, metadata = parse_run(raw, require_coincidence=False)
        role = metadata["role"]
        if role in runs:
            raise ValueError("Both files have the same role. Need MASTER_SINGLES and SLAVE_COINCIDENCE.")
        runs[role] = (name, rows, metadata)
    output = Path("master_slave_results")
    output.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    for role, label, color in [
        ("MASTER_SINGLES", "Master: recorded singles", "#1479CB"),
        ("SLAVE_COINCIDENCE", "Slave: accepted coincidences", "#E77816")
    ]:
        name, rows, metadata = runs[role]
        times = np.array([row["time_ms"] / 1000 for row in rows])
        counts = np.arange(1, len(rows) + 1)
        ax.step(np.r_[0, times, DURATION_S], np.r_[0, counts, len(rows)],
                where="post", label=f"{label} (N={len(rows)})", color=color, linewidth=2)
    ax.set(title="Master vs slave: cumulative recorded counts",
           xlabel="Each detector’s own elapsed time (seconds; clocks not synchronized)",
           ylabel="Cumulative recorded events", xlim=(0, DURATION_S))
    ax.set_ylim(0, max(1, max(len(item[1]) for item in runs.values()) * 1.1))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    png=output/"master_vs_slave.png"
    pdf=output/"master_vs_slave.pdf"
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    plt.show()
    plt.close(fig)
    master_n = len(runs["MASTER_SINGLES"][1])
    slave_n = len(runs["SLAVE_COINCIDENCE"][1])
    summary = (
        f"Master file: {runs['MASTER_SINGLES'][0]}\n"
        f"Slave file: {runs['SLAVE_COINCIDENCE'][0]}\n"
        f"Master recorded singles: {master_n}\n"
        f"Slave accepted coincidences: {slave_n}\n"
        f"Slave local triggers (summary only): {runs['SLAVE_COINCIDENCE'][2]['local_triggers']}\n"
        f"Difference of recorded totals (master minus slave): {master_n - slave_n}\n\n"
        "Each file covers 60 seconds on its OWN clock. This plot does not synchronize the clocks.\n"
        "Use files from the same experiment; the software cannot verify simultaneous exposure.\n"
        "The two curves apply different selections: master singles versus slave coincidences.\n"
        "The difference is not a detector-efficiency measurement or an event-by-event mismatch count.\n"
        "Slave local_triggers is NOT a master count; rejected slave trigger timestamps are not saved.\n"
        "Coincidence timing/pulse amplitudes cannot be reconstructed for the master from the slave file.\n"
    )
    print(summary)
    report=output/"comparison_summary.txt"
    report.write_text(summary,encoding="utf-8")
    archive=output/"master_slave_results.zip"
    with ZipFile(archive,"w",ZIP_DEFLATED) as z:
        for p in (png,pdf,report): z.write(p,arcname=p.name)
    return archive


from google.colab import files

uploaded = files.upload()
archive = compare_runs(uploaded)


files.download(str(archive))
