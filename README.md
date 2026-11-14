# CosmicWatch: record and compare two detectors

This guide explains how to record a 60-second CosmicWatch coincidence measurement on a Mac and graph the results in Google Colab. Data are saved to the computer as text files. An SD card is not used.

The supplied firmware targets original CosmicWatch v2 hardware with a 16 MHz ATmega328P Arduino Nano. It is not a general sketch for other CosmicWatch versions or bare Arduino boards.

## 1. Understand what each detector records

| Role | What it records |
| --- | --- |
| Master | Every local trigger accepted by the firmware's threshold logic; these are called singles. |
| Slave | A local trigger only when the master's coincidence signal is also active. |

The slave usually saves fewer events because coincidence is an additional requirement. This does not by itself mean the slave is damaged.

For example, one completed measurement produced **68 master local triggers**, **57 slave local triggers**, and **8 slave accepted coincidences**. The slave detected 57 local pulses, but only 8 passed the coincidence selection. Rejected slave pulses appear in the final total, not as individual event rows.

The coincidence cable carries the trigger signal; it does not send the master's event list to the computer. Each detector therefore needs its own USB data connection to record both streams.

**The uploaded sketch assigns the role.** Being on top, having a particular USB port, or having a “MASTER” sticker does not assign it. In these sketches, the roles are fixed; reset order does not choose them.

## 2. Equipment and software

- Two original CosmicWatch v2 detectors with original, unmodified Arduino Nano hardware.
- The appropriate CosmicWatch coincidence cable.
- Two USB data cables and, if needed, a USB hub.
- A Mac with [Arduino IDE](https://www.arduino.cc/en/software/) and [Python 3](https://www.python.org/downloads/macos/).
- Access to [Google Colab](https://colab.research.google.com/).

The Mac recorder uses Python's standard library; it needs no additional pip packages. It uses macOS serial-device paths and is not a Windows recorder.

### Repository files

| File | Use |
| --- | --- |
| [Master sketch](CosmicWatch_Master_Serial/CosmicWatch_Master_Serial.ino) | Upload to the top/master detector in this experiment. |
| [Slave sketch](CosmicWatch_Slave_Serial/CosmicWatch_Slave_Serial.ino) | Upload to the bottom/slave detector. |
| [Mac recorder](record_both_cosmicwatch.py) | Run in Terminal to save both data streams. |
| [Colab notebook](CosmicWatch_Master_vs_Slave.ipynb) | Upload to Colab to compare a matching pair of files. |
| [Colab Python code](CosmicWatch_Comparison_Colab.py) | Alternative: paste the entire file into one Colab code cell. |

Keep each `.ino` file inside its matching folder. These are the actual code files; no code needs to be copied out of this README.

## 3. Upload the correct code to each detector

Do this before the first measurement, after replacing a detector, or after using a standalone test sketch.

1. Stop any running Terminal recorder with **Control + C**. A command prompt ending in `%` means that recorder has stopped.
2. Disconnect both detectors from power and disconnect the coincidence cable.
3. Connect only the intended master to the Mac by USB.
4. Open `CosmicWatch_Master_Serial/CosmicWatch_Master_Serial.ino` in Arduino IDE.
5. Select **Arduino Nano** under the board settings and select its USB serial port under **Tools → Port**.
6. Select the processor/bootloader appropriate to the board. Some original-style Nanos require **ATmega328P (Old Bootloader)**.
7. Click **Upload** and wait for a successful upload. Label this physical detector “MASTER.”
8. Unplug it. Connect only the intended slave and repeat using `CosmicWatch_Slave_Serial/CosmicWatch_Slave_Serial.ino`. Label it “SLAVE.”
9. Quit Arduino IDE with **Command + Q**.

Connecting one detector at a time identifies its port without guessing. Port names can change when devices or USB connections change. EEPROM names such as `Leonardo` or `UNNAMED` are detector labels, not the Arduino board model or role.

The supplied sketches use 115200 baud, a signal threshold of 50 ADC counts, and a reset threshold of 25 ADC counts. Leave these unchanged during a comparison.

## 4. Connect and position the pair

1. With both detectors unpowered, connect the coincidence cable fully at both ends.
2. Position the detectors flat, directly above each other, with their cases aligned. Keep the spacing fixed and record the arrangement.
3. Connect both detectors to the same Mac with their own USB data cables.
4. Keep Arduino IDE closed while Terminal records.

This two-USB arrangement assumes original, unmodified v2/Nano hardware. The coincidence cable also carries power; do not treat it as an ordinary interchangeable signal cable for other hardware.

## 5. Record a full 60-second run

In Terminal, change to the folder containing this repository's files and run:

```bash
python3 record_both_cosmicwatch.py --manual-reset
```

If changing folders is unfamiliar, type `python3` followed by a space, drag `record_both_cosmicwatch.py` from Finder into Terminal, then append a space and `--manual-reset` before pressing Return.

1. Follow the Return prompts. If asked to select ports, choose the two detector ports.
2. When **READY** appears, press and release both physical reset buttons once, close together.
3. Check that the recorder identifies one `MASTER_SINGLES` and one `SLAVE_COINCIDENCE`.
4. Leave both detectors and the computer connection alone. Do not open Arduino IDE, reset again, or unplug anything during acquisition.
5. Wait for both `COMPLETE` messages and:

```text
SAVED BOTH FILES: master.txt and slave.txt
```

Each detector measures for 60 seconds on its own clock, then stops until reset. Setup, USB startup, and saving can make the whole command take longer than one minute. Manual reset starts the measurements near each other; it does not synchronize their clocks precisely.

The recorder creates a new timestamped folder on the Desktop for each run, containing `master.txt`, `slave.txt`, and capture metadata. Keep the matching text files together. There is no need to copy Terminal output manually.

Run the same command again for the next measurement. Stop an unfinished recording with **Control + C**, not Command + C. Keeping an idle Terminal window open is fine.

## 6. Graph the results in Google Colab

1. Open [Google Colab](https://colab.research.google.com/).
2. Select **File → Upload notebook** and choose `CosmicWatch_Master_vs_Slave.ipynb`.
3. Select **Runtime → Run all**.
4. When **Choose Files** appears in the running notebook, open one completed run's Desktop folder.
5. Hold **Command** and select **both `master.txt` and `slave.txt` from that same folder**, then click Open.
6. View the graph and printed totals. The notebook also requests a ZIP download containing a PNG graph, PDF graph, and text summary.

There are two different uploads: first the `.ipynb` notebook containing the code, then the two `.txt` data files when the code asks for them. Upload one matching pair at a time. To graph another run, run the notebook again and select that run's files.

Alternatively, create a blank Colab notebook, paste the entire contents of `CosmicWatch_Comparison_Colab.py` into one code cell, and press **Shift + Enter**.

### Read the graph correctly

- Blue: cumulative master singles.
- Orange: cumulative slave accepted coincidences.
- Horizontal axis: each detector's own elapsed time in seconds.
- Vertical axis: cumulative recorded events.

This notebook creates the master-versus-slave cumulative plot and a summary. It does not automatically combine multiple runs or create the separate 10-second-bin and ADC-histogram plots discussed for single-run analysis.

The curves apply different event selections. Their separation is not a detector-efficiency measurement or a count of individually matched/missed particles. The graph does not support time-of-flight measurements or precise event matching between detectors.

## 7. What is inside the text files?

Each complete file contains a role header, a START message, event rows, a DONE message, and final totals.

```text
event,time_ms,adc,sipm_mv_estimate,busy_us_before_event,temp_c_estimate
```

| Column or summary | Meaning |
| --- | --- |
| `event` | Consecutive recorded event number in this file. |
| `time_ms` | Milliseconds since this detector began acquisition. |
| `adc` | Raw ADC measurement; not a calibrated particle energy. |
| `sipm_mv_estimate` | Estimated SiPM voltage using inherited calibration assumptions. |
| `busy_us_before_event` | Accumulated local processing busy time before this event, in microseconds. |
| `temp_c_estimate` | Estimated temperature using inherited calibration assumptions. |
| `accepted_events` | Number of saved event rows. |
| `local_triggers` | Number of locally detected triggers, including slave triggers rejected by coincidence. |
| `local_busy_us` | Total measured local busy time for this detector; not the combined dead time of the pair. |

Do not remove the headers or footers: the notebook uses them to check completeness and identify the roles. The last event can occur before 60 seconds even when the full 60-second run completed.

## 8. Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Resource busy` | Quit Arduino IDE and stop older recorders with Control + C. Only one program should open each serial port. |
| Only one detector port appears | Check the second USB data cable, hub, and connection. |
| Both detectors show the same role | Upload the correct master and slave sketches to the correct physical boards. |
| `CosmicWatch standalone detector test` or `LOCAL_SINGLES` appears | The standalone test firmware is still installed. Restore both coincidence sketches. |
| No expected run header | Use the diagnostic command below; inspect actual received text before changing settings. |
| Garbled text | Confirm 115200 baud. A brief startup fragment does not establish a fault; persistent corruption needs investigation. |
| Slave identifies itself but saves zero events | Check that the master is also actively measuring during the same minute, that the cable is connected, and that geometry is unchanged. Inspect the slave's `local_triggers` total. |
| Slave has local triggers but zero accepted events | Local detection is occurring; investigate the master signal, coincidence connection, timing, and alignment. This alone does not identify the faulty component. |
| Opening Serial Monitor makes a new START appear | Opening the port can reset the connected Nano. The other detector might already have finished. Restart both together for a paired run. |
| Only partial files or a capture error | Keep the files for troubleshooting, but do not label them a complete measurement or upload them as one. Repeat after fixing the cause. |
| Notebook rejects files | Use two complete files from the same run, with opposite roles. Do not upload diagnostic output, standalone-test data, or multiple concatenated runs. |

Run a short serial diagnostic from the repository folder:

```bash
python3 record_both_cosmicwatch.py --diagnose --manual-reset
```

Follow the prompts and reset both boards when READY appears. This diagnostic lasts **25 seconds**, deliberately shorter than a measurement. It saves received raw bytes and `diagnostic_summary.txt` in a Desktop diagnostic folder. These are troubleshooting files, not Colab measurement inputs.

If a detector was replaced, upload the required sketch to the replacement and identify its current port again. A sticker on the case does not configure new hardware.

## 9. Results collected so far

These are examples from this experiment, not specifications or guaranteed count rates for CosmicWatch.

### Standalone checks before coincidence measurements

Standalone tests count local pulses and must not be mixed with coincidence results.

| Detector | Five separate 60-second counts | Mean local pulses/minute |
| --- | --- | ---: |
| Original top | 67, 88, 69, 62, 61 | 69.4 |
| Replacement bottom, detector #3 | 59, 66, 63, 74, 72 | 66.8 |

The original top also had an earlier 72-count test; an earlier bottom detector had one 46-count test. A single lower count did not establish hardware damage. These standalone results describe the earlier detector choices, not necessarily the later replacement top.

### Coincidence runs

| Pair/configuration | Run duration | Master singles | Slave coincidences |
| --- | ---: | ---: | ---: |
| Earlier pair | 60 s | 68 | 8 |
| Replacement-top pair, run 1 | 60 s | 50 | 10 |
| Replacement-top pair, run 2 | 60 s | 69 | 7 |
| Replacement-top pair, run 3 | 60 s | 55 | 12 |
| Replacement-top pair total | 180 s | 174 | 29 |

The replacement-top pair averaged **9.7 recorded coincidences per minute** over these three runs. That is not sufficient evidence that it is more accurate than the earlier pair, which has only one recorded minute in this comparison. Two additional runs were planned; they are not included here because their results have not been provided.

## 10. How to compare performance fairly

1. Keep the same bottom detector, geometry, location, thresholds, and firmware; change only the top detector.
2. Collect equal exposure for both pairs. Ten or more complete one-minute runs per pair is a useful starting point, not a guarantee of a statistically conclusive result.
3. Record the physical detector identities and arrangement for each run. Interleave configurations if practical to reduce the effect of changing conditions.
4. Compare total counts divided by total recording time, not just whichever individual run was largest. Include zero-count complete runs.
5. Check geometry dependence in a separate test: compare stacked detectors with one shifted sideways. Reduced overlap should reduce true shared-particle detections, although backgrounds and geometry affect the result.

**Repeatability/precision and accuracy are different.** Repeating a measurement estimates its variability. More recorded events do not prove closer agreement with the true particle rate. Absolute accuracy or detection efficiency requires an independent reference or a properly designed reference-trigger experiment; a three-detector arrangement would require additional design and different acquisition logic.

Do not call `slave coincidences / master singles` detector efficiency without accounting for geometry, background, trigger selection, timing acceptance, and detector response. Do not lengthen the coincidence window merely to obtain larger counts; that also changes accidental acceptance.

## Validation and limitations

Both supplied Arduino roles were compile-tested for the original Nano target. The recorder/parser were checked using simulated serial inputs. User runs also demonstrated completed manual-reset captures with both roles and saved files. This is functional evidence, not a calibrated validation of detection efficiency, the coincidence window, ADC accuracy, or absolute clock timing.

The recorder's reported header-arrival gap is a computer-side diagnostic. It is not a clock calibration. Voltage and temperature estimates retain assumptions from the original code. Local busy-time totals must not be treated as a complete live-time correction for the pair.

No SD-card code or hardware changes are needed for this workflow. No changes have been published to GitHub automatically.

## Sources and attribution

- [CosmicWatch v2 project and original code](https://github.com/spenceraxani/CosmicWatch-Desktop-Muon-Detector-v2).
- [Axani, Frankiewicz, and Conrad: The CosmicWatch Desktop Muon Detector](https://arxiv.org/html/1801.03029v2), including the original coincidence concept and hardware description.
- [Arduino: why opening Serial Monitor can restart a sketch](https://support.arduino.cc/hc/en-us/articles/4839084114460-If-your-board-runs-the-sketch-twice).
- [Google Colab file input/output examples](https://colab.research.google.com/notebooks/io.ipynb).

The supplied firmware is a modified serial-only, fixed-role, 60-second workflow based on the CosmicWatch v2 approach. Preserve attribution and review the upstream project's licensing when redistributing derived code; this guide does not assign a new license to it.
