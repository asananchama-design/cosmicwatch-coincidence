/*
  CosmicWatch v2: one-minute coincidence run, SERIAL OUTPUT ONLY.
  No SD card or SD library is required.

  Original 16 MHz ATmega328P Nano / CosmicWatch v2 PCB only.
  Upload with MASTER_MODE = 1 to the MASTER.
  Upload with MASTER_MODE = 0 to the SLAVE.
  Connect the proper CosmicWatch coincidence cable.
  Serial Monitor: 115200 baud.

  Master prints singles; SLAVE prints coincidence events.
  Runs automatically for 60 seconds, then stops until reset.
  Both boards have independent timers: reset them together for overlap.
  Opening Serial Monitor normally resets the attached board.

  This retains the original D6 level-check coincidence scheme and the
  original voltage/temperature calibration assumptions. Printed busy time
  is local processing time, not the combined live time of both detectors.
  Compile-tested for both roles; not hardware-tested.
*/

#include <EEPROM.h>

#ifndef MASTER_MODE
#define MASTER_MODE 1  // CHANGE: 1 for MASTER, 0 for SLAVE.
#endif

#if !defined(__AVR_ATmega328P__) || F_CPU != 16000000UL
#error "Select the original 16 MHz ATmega328P Arduino Nano."
#endif
#if MASTER_MODE != 0 && MASTER_MODE != 1
#error "MASTER_MODE must be 0 or 1."
#endif

const byte LED_PIN = 3;
const byte COINCIDENCE_PIN = 6;
const int SIGNAL_THRESHOLD = 50;
const int RESET_THRESHOLD = 25;
const unsigned long RUN_DURATION_US = 60000000UL;

char detectorName[40];
unsigned long runStartUs = 0;
unsigned long eventCount = 0;
unsigned long localTriggers = 0;
unsigned long totalBusyUs = 0;
bool running = false;

const float cal[] = {
  -9.085681659276021e-27, 4.6790804314609205e-23,
  -1.0317125207013292e-19, 1.2741066484319192e-16,
  -9.684460759517656e-14, 4.6937937442284284e-11,
  -1.4553498837275352e-08, 2.8216624998078298e-06,
  -0.000323032620672037, 0.019538631135788468,
  -0.3774384056850066, 12.324891083404246
};

void readDetectorName() {
  byte i = 0;
  for (; i < sizeof(detectorName) - 1; ++i) {
    byte c = EEPROM.read(i);
    if (c == 0 || c == 255) break;
    detectorName[i] = (c >= 32 && c <= 126) ? char(c) : '?';
  }
  detectorName[i] = '\0';
  if (i == 0) strcpy(detectorName, "UNNAMED");
}

float sipmVoltage(float adc) {
  float value = cal[0];
  for (byte i = 1; i < sizeof(cal) / sizeof(cal[0]); ++i)
    value = value * adc + cal[i];
  return value;
}

void printHeader(Print &out) {
  out.println(F("# CosmicWatch v2: 60-second acquisition"));
  out.print(F("# role="));
  out.println(MASTER_MODE ? F("MASTER_SINGLES") : F("SLAVE_COINCIDENCE"));
  out.print(F("# detector=")); out.println(detectorName);
  out.println(F("# SiPM voltage and temperature use original assumed calibration."));
  out.println(F("event,time_ms,adc,sipm_mv_estimate,busy_us_before_event,temp_c_estimate"));
}

void printEvent(Print &out, unsigned long timeMs, int adc,
                float voltage, unsigned long busyBefore, float temperature) {
  out.print(eventCount); out.print(',');
  out.print(timeMs); out.print(',');
  out.print(adc); out.print(',');
  out.print(voltage, 3); out.print(',');
  out.print(busyBefore); out.print(',');
  out.println(temperature, 2);
}

// Count explicit busy intervals only within the 60-second acquisition window.
void accountBusy(unsigned long beganUs) {
  unsigned long beginElapsed = beganUs - runStartUs;
  unsigned long endElapsed = micros() - runStartUs;
  if (endElapsed > RUN_DURATION_US) endElapsed = RUN_DURATION_US;
  if (beginElapsed < endElapsed) totalBusyUs += endElapsed - beginElapsed;
}

void finishRun() {
  running = false;
  if (MASTER_MODE) digitalWrite(COINCIDENCE_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  Serial.println(F("# DONE: 60-second acquisition complete."));
  Serial.print(F("# accepted_events=")); Serial.println(eventCount);
  Serial.print(F("# local_triggers=")); Serial.println(localTriggers);
  Serial.print(F("# local_busy_us=")); Serial.println(totalBusyUs);
  Serial.println(F("# Copy this output to a text file. Reset starts a new run."));
  Serial.flush();
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(COINCIDENCE_PIN, LOW); // Master idle LOW; slave pull-up OFF.
  pinMode(COINCIDENCE_PIN, MASTER_MODE ? OUTPUT : INPUT);
  Serial.begin(115200);

  analogReference(EXTERNAL); // Requires the original CosmicWatch v2 AREF circuit.
  ADCSRA &= ~(_BV(ADPS0) | _BV(ADPS1) | _BV(ADPS2));
  ADCSRA |= _BV(ADPS0) | _BV(ADPS1); // Prescaler 8, as in original sketch.
  readDetectorName();

  printHeader(Serial);
  Serial.println(F("# START: recording for 60 seconds..."));
  Serial.flush();
  analogRead(A0);
  runStartUs = micros();
  running = true;
}

void loop() {
  if (!running) return;
  if ((unsigned long)(micros() - runStartUs) >= RUN_DURATION_US) {
    finishRun();
    return;
  }

  unsigned long busyStart = micros();
  if (analogRead(A0) > SIGNAL_THRESHOLD) {
    unsigned long eventElapsedUs = micros() - runStartUs;
    // Never accept a new event timestamp at or beyond the deadline.
    if (eventElapsedUs >= RUN_DURATION_US) {
      finishRun();
      return;
    }
    int adc = analogRead(A0);

    // Original CosmicWatch coincidence sequence: retain these A3 reads
    // because they contribute to the master pulse / slave sampling timing.
    if (MASTER_MODE) digitalWrite(COINCIDENCE_PIN, HIGH);
    analogRead(A3);
    bool keep = MASTER_MODE || (digitalRead(COINCIDENCE_PIN) == HIGH);
    analogRead(A3);
    if (MASTER_MODE) digitalWrite(COINCIDENCE_PIN, LOW);

    ++localTriggers;
    if (keep) {
      ++eventCount;
      unsigned long busyBefore = totalBusyUs;
      float temperature = (((analogRead(A3) + analogRead(A3) + analogRead(A3))
                            / 3.0f * (3300.0f / 1024.0f)) - 500.0f) / 10.0f;
      float voltage = sipmVoltage(adc);
      digitalWrite(LED_PIN, HIGH);
      printEvent(Serial, eventElapsedUs / 1000UL, adc,
                 voltage, busyBefore, temperature);
      digitalWrite(LED_PIN, LOW);
    }

    // Do not let a long pulse/noisy input keep the run alive past one minute.
    while (analogRead(A0) > RESET_THRESHOLD) {
      if ((unsigned long)(micros() - runStartUs) >= RUN_DURATION_US) break;
    }
    accountBusy(busyStart);
  }

  if ((unsigned long)(micros() - runStartUs) >= RUN_DURATION_US) {
    finishRun();
    return;
  }
}
