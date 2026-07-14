# Three-Phase Power Meter Parameter Glossary (RAG Reference)

> **Source system:** This schema matches a three-phase AC energy/power-quality meter (e.g., ABB, Schneider, L&T, Secure, or Elite-class smart meters) recording interval data for R (Red/L1), Y (Yellow/L2), and B (Blue/L3) phases.
> **Design note:** Each entry below is a self-contained chunk — Parameter, Category, Definition, Unit, Formula, Standard Range, Fluctuation Meaning, Related Fields, and Reference Standard — so it can be retrieved and understood independently without surrounding context.

---

### Date
- **Category:** Timestamp
- **Definition:** Calendar date of the recorded interval.
- **Unit:** DD-MM-YYYY or YYYY-MM-DD
- **Formula:** N/A
- **Standard Range:** N/A
- **Fluctuation Meaning:** Not applicable; gaps in dates indicate data logging or communication failure at the meter/RTU.
- **Related Fields:** Time
- **Reference Standard:** IS 15959 / DLMS-COSEM data model (Indian smart meter data exchange standard)

---

### Time
- **Category:** Timestamp
- **Definition:** Time of day for the reading, usually aligned to a fixed interval (15-min, 30-min, or 1-hour blocks per IS 15959 / CEA metering regulations).
- **Unit:** HH:MM:SS
- **Formula:** N/A
- **Standard Range:** N/A
- **Fluctuation Meaning:** Irregular intervals suggest clock drift or communication dropouts; consistent intervals are required for accurate load-curve and demand analysis.
- **Related Fields:** Date, Num_Interruptions
- **Reference Standard:** IS 15959 Part 2

---

### Watts_Total / Watts_R / Watts_Y / Watts_B
- **Category:** Real (Active) Power
- **Definition:** Actual power consumed to perform useful work (heat, motion, light), per phase and combined.
- **Unit:** kW (or W)
- **Formula:** P = V × I × cos(φ), summed across phases for total
- **Standard Range:** Should stay under the sanctioned/contract demand of the connection; phase values should be within ~5–10% of each other in a balanced installation.
- **Fluctuation Meaning:** High fluctuation reflects intermittent loads (motor start/stop, HVAC cycling, welding). Sustained near-peak values signal risk of exceeding contract demand and incurring penalty charges.
- **Related Fields:** VA_Total, PF, Max_Demand_Delivered
- **Reference Standard:** IEC 62053-21/22 (active energy meter accuracy classes)

---

### VAR_Total / VAR_R / VAR_Y / VAR_B
- **Category:** Reactive Power
- **Definition:** Non-working power that oscillates between source and load to sustain magnetic/electric fields in inductive or capacitive equipment (motors, transformers, capacitor banks).
- **Unit:** kVAR
- **Formula:** Q = V × I × sin(φ)
- **Standard Range:** Ideally minimized relative to Watts (low Q/P ratio); utilities in India (and elsewhere) penalize consumers when PF drops below ~0.85–0.90, which corresponds to high VAR draw.
- **Fluctuation Meaning:** Spikes indicate inductive loads (motors, transformers) switching on without adequate capacitor compensation. Persistently high VAR increases I²R losses in cables.
- **Related Fields:** True_PF, Displacement_PF, VA_Total
- **Reference Standard:** IEC 61000-3-2 (reactive power/harmonic current limits)

---

### True_PF_Avg / True_PF_R / True_PF_Y / True_PF_B
- **Category:** Power Factor
- **Definition:** Ratio of real power to apparent power, incorporating both phase displacement and harmonic distortion effects — the "true" efficiency of power usage.
- **Unit:** Dimensionless, 0 to 1 (sometimes shown as lag/lead)
- **Formula:** True PF = Watts / VA
- **Standard Range:** Utility-optimal is 0.95–1.0; most Indian state utilities (e.g., under Electricity Supply Code) levy a low-PF penalty below 0.90–0.95 and give rebates above 0.95–0.98.
- **Fluctuation Meaning:** Frequent dips mean inefficient reactive power usage or harmonic pollution — both increase transmission losses and can trigger billing penalties.
- **Related Fields:** Displacement_PF, VAR_Total, VA_Total, I_THD
- **Reference Standard:** CEA (Installation and Operation of Meters) Regulations, 2006 (India); IEEE 1459-2010 (power definitions under distorted conditions)

---

### VA_Total / VA_R / VA_Y / VA_B
- **Category:** Apparent Power
- **Definition:** Vector sum of real and reactive power — represents the total load capacity the electrical supply (transformer, cables, generator) must be sized to deliver.
- **Unit:** kVA
- **Formula:** S = √(P² + Q²), or S = V × I
- **Standard Range:** Should remain below the rated kVA of the distribution transformer/service connection; typically utilities size supply at kVA, not kW.
- **Fluctuation Meaning:** Tracks combined effect of load and PF variation. Sustained high VA near transformer nameplate rating risks thermal overload and reduced transformer life.
- **Related Fields:** Watts_Total, VAR_Total, VAh_Received
- **Reference Standard:** IEC 60076 (transformer loading limits)

---

### VLL_Avg / V_RY / V_YB / V_BR
- **Category:** Voltage — Line-to-Line
- **Definition:** RMS voltage measured between each pair of phase conductors, and their average across all three pairs.
- **Unit:** Volts (V)
- **Formula:** VLL = √3 × VLN (in a balanced system)
- **Standard Range:** For a nominal 415V 3-phase system, IS 12360 permits ±6% (≈390–440V); IEC 60038 standard voltage tolerance is typically ±10%.
- **Fluctuation Meaning:** Sudden dips = voltage sags from large motor starts or grid disturbances; sustained highs risk insulation stress; large spread between R-Y/Y-B/B-R pairs indicates voltage unbalance.
- **Related Fields:** VLN_Avg, V_Unbal (R/Y/B)
- **Reference Standard:** IS 12360:1988; IEC 60038

---

### VLN_Avg / V_R / V_Y / V_B
- **Category:** Voltage — Line-to-Neutral (Phase Voltage)
- **Definition:** RMS voltage of each phase measured relative to neutral, and their average.
- **Unit:** Volts (V)
- **Formula:** VLN = VLL / √3
- **Standard Range:** For nominal 230V single-phase-equivalent supply, tolerance is typically ±6% (≈216–244V) per IS 12360 / CEA norms.
- **Fluctuation Meaning:** Uneven values among R/Y/B beyond ~2% difference indicate phase voltage unbalance, which is especially damaging to 3-phase induction motors (can cause 6–10× more heating per 1% unbalance, per NEMA MG1 derating curves).
- **Related Fields:** VLL_Avg, V_Unbal_R/Y/B
- **Reference Standard:** NEMA MG1-2016 (motor voltage unbalance derating); IEC 60034-26

---

### I_Total / I_R / I_Y / I_B
- **Category:** Current
- **Definition:** RMS current flowing in each phase conductor and the combined/vector total.
- **Unit:** Amperes (A)
- **Formula:** Measured directly via CT (current transformer); Total often reported as arithmetic or vector sum depending on meter configuration.
- **Standard Range:** Must remain below the rated ampacity of cables/breakers/CTs (commonly sized with 20–25% headroom above expected max load per IS 732 wiring code).
- **Fluctuation Meaning:** Large swings indicate cyclic loads (compressors, pumps, welding); one phase consistently higher than others indicates unbalanced single-phase loading on a 3-phase feeder.
- **Related Fields:** I_Unbal_R/Y/B, Neutral_I, I_THD
- **Reference Standard:** IS 732:2019 (wiring code); IEC 60364

---

### Frequency_Hz
- **Category:** Grid Frequency
- **Definition:** Instantaneous frequency of the AC supply waveform.
- **Unit:** Hertz (Hz)
- **Formula:** Measured via zero-crossing detection of voltage waveform.
- **Standard Range:** Nominal 50 Hz (India, most of world) or 60 Hz (N. America); Indian grid code (IEGC) mandates operation within 49.90–50.05 Hz under normal conditions.
- **Fluctuation Meaning:** Deviations beyond ±0.5 Hz indicate generation-demand imbalance on the grid or islanding/genset operation; can damage frequency-sensitive rotating equipment and cause under/over-speed tripping.
- **Related Fields:** Frequency_Max, Frequency_Min, RPM
- **Reference Standard:** Indian Electricity Grid Code (IEGC) 2010; IEC 60034-1

---

### Wh_Received
- **Category:** Cumulative Energy (Active, Imported)
- **Definition:** Total cumulative real energy imported ("received") from the grid since meter installation or last reset.
- **Unit:** Watt-hours (Wh) or kWh
- **Formula:** Integral of Watts_Total over time; interval consumption = Wh_Received(t2) − Wh_Received(t1).
- **Standard Range:** Always monotonically increasing; this is the primary billing quantity for energy charges.
- **Fluctuation Meaning:** N/A directly (cumulative), but the *rate of increase* between intervals reveals load profile — flat segments mean idle periods, steep slopes mean high consumption.
- **Related Fields:** Watts_Total, PF_Avg_Received
- **Reference Standard:** IEC 62053-21 (Class 1/2 active energy meters); IS 13779

---

### VAh_Received
- **Category:** Cumulative Energy (Apparent, Imported)
- **Definition:** Cumulative apparent energy imported, used where utilities bill on kVAh rather than kWh to discourage poor power factor.
- **Unit:** VA-hours (VAh) or kVAh
- **Formula:** Integral of VA_Total over time.
- **Standard Range:** Monotonically increasing; ratio kWh/kVAh over a billing period approximates the average PF.
- **Fluctuation Meaning:** A growing gap between Wh_Received and VAh_Received growth rates signals worsening power factor over time.
- **Related Fields:** True_PF_Avg, PF_Avg_Received
- **Reference Standard:** State Electricity Regulatory Commission (SERC) tariff orders — many Indian states now bill industrial/commercial consumers on kVAh

---

### VARh_Ind_Received / VARh_Cap_Received
- **Category:** Cumulative Reactive Energy
- **Definition:** Cumulative inductive reactive energy (VARh_Ind, consumer absorbing VARs — typical of motor loads) and capacitive reactive energy (VARh_Cap, consumer supplying/leading VARs — typical of over-compensated capacitor banks) imported over time.
- **Unit:** VAR-hours (VARh) or kVARh
- **Formula:** Integral of VAR_Total over time, split by sign/quadrant (lag vs. lead).
- **Standard Range:** Utilities typically want inductive VARh minimized without tipping into excessive capacitive (leading) VARh, which also draws penalties in many tariff structures.
- **Fluctuation Meaning:** Rising VARh_Cap suggests over-correction from capacitor banks (common at light load with fixed capacitors still connected) — should trigger automatic power factor controller (APFC) review.
- **Related Fields:** VAR_Total, True_PF_Avg
- **Reference Standard:** CEA Metering Regulations 2006, Schedule for reactive energy billing

---

### PF_Avg_Received
- **Category:** Cumulative Power Factor
- **Definition:** Average power factor computed from cumulative Wh and VAh over a billing/reporting cycle — a longer-term efficiency indicator less sensitive to momentary spikes than instantaneous PF.
- **Unit:** Dimensionless, 0–1
- **Formula:** PF_Avg = Wh_Received / VAh_Received (over the same period)
- **Standard Range:** Utility target typically ≥0.90–0.95 depending on state tariff regulations.
- **Fluctuation Meaning:** A month-over-month decline flags a systemic issue (aging capacitor bank, added inductive load) rather than a one-off event.
- **Related Fields:** True_PF_Avg, VAh_Received, Wh_Received
- **Reference Standard:** SERC tariff orders (India); IEEE 1459-2010

---

### Amps_Hour_Received
- **Category:** Cumulative Current
- **Definition:** Cumulative ampere-hours delivered — a less common metric, useful for correlating current draw with runtime, and occasionally used in DC-adjacent or battery-backed installations.
- **Unit:** Ampere-hours (Ah)
- **Formula:** Integral of I_Total over time.
- **Standard Range:** No universal standard range; context-dependent on load type.
- **Fluctuation Meaning:** Rate of increase parallels current draw trends; useful cross-check against I_Total readings for consistency validation.
- **Related Fields:** I_Total, Load_Hours_Received
- **Reference Standard:** N/A (supplementary diagnostic metric)

---

### Neutral_I
- **Category:** Neutral Current
- **Definition:** RMS current flowing in the neutral conductor of a 3-phase 4-wire system.
- **Unit:** Amperes (A)
- **Formula:** In an ideal balanced linear system, Neutral_I ≈ 0; in practice it's the vector sum of phase currents plus triplen (3rd, 9th, 15th...) harmonic contributions, which add arithmetically in the neutral rather than cancel.
- **Standard Range:** Should stay well below phase current; IEEE 1100 flags neutral current exceeding phase current as a red flag on systems with heavy non-linear (e.g., IT/electronic) loads.
- **Fluctuation Meaning:** Elevated neutral current signals phase current imbalance and/or high triplen-harmonic content from non-linear loads — a known cause of neutral conductor overheating and fires if the neutral is undersized.
- **Related Fields:** I_Unbal_R/Y/B, I_THD (R/Y/B)
- **Reference Standard:** IEEE 1100-2005 ("Emerald Book"); IS 3043 (earthing code)

---

### V_R_Harmonic / V_Y_Harmonic / V_B_Harmonic
- **Category:** Voltage Harmonics (summary/dominant harmonic magnitude)
- **Definition:** Magnitude of harmonic distortion present in each phase's voltage waveform, indicating deviation from a pure 50/60 Hz sine wave.
- **Unit:** % of fundamental, or Volts depending on meter configuration
- **Formula:** Derived via FFT decomposition of the voltage waveform into harmonic orders.
- **Standard Range:** IEEE 519-2014 recommends individual voltage harmonics under ~3% and total voltage THD under 5% for systems ≤69kV.
- **Fluctuation Meaning:** Rising values indicate more non-linear loads on the network (VFDs, UPS, arc furnaces) polluting the shared voltage bus, which can affect all connected equipment.
- **Related Fields:** V_R_THD_Pct, V_Y_THD_Pct, V_B_THD_Pct
- **Reference Standard:** IEEE 519-2014; IEC 61000-2-4

---

### I_R_Harmonic / I_Y_Harmonic / I_B_Harmonic
- **Category:** Current Harmonics (summary/dominant harmonic magnitude)
- **Definition:** Magnitude of harmonic distortion in each phase's current waveform, generated primarily by non-linear loads.
- **Unit:** % of fundamental, or Amperes
- **Formula:** FFT decomposition of the current waveform.
- **Standard Range:** IEEE 519-2014 sets current distortion limits (TDD) as a function of the ratio of short-circuit current to load current (Isc/IL), typically 5–20% depending on system size.
- **Fluctuation Meaning:** Sharp increases correlate with switching-on of non-linear equipment (VFDs, LED drivers, switch-mode power supplies); sustained high values accelerate transformer and cable heating.
- **Related Fields:** I_R_THD_Pct, K_Factor_I_R/Y/B
- **Reference Standard:** IEEE 519-2014

---

### Rising_Demand_Delivered
- **Category:** Demand (Instantaneous/Sliding Window)
- **Definition:** The currently-accumulating average demand value within the present demand integration window (e.g., a rolling 15/30-minute block), showing real-time progression toward that interval's final demand figure.
- **Unit:** kW or kVA
- **Formula:** Running average of power over the elapsed portion of the current demand window.
- **Standard Range:** Should stay below the sanctioned/contract demand at all times to avoid exceeding billing demand thresholds.
- **Fluctuation Meaning:** Rapid rises mid-window warn of an impending demand spike before the interval closes, useful for real-time load-shedding decisions.
- **Related Fields:** Max_Demand_Delivered, Watts_Total
- **Reference Standard:** CEA Metering Regulations 2006; utility demand-billing tariff schedules

---

### Max_Demand_Delivered
- **Category:** Demand (Peak, Billing)
- **Definition:** The highest average demand recorded over any single demand integration period within the billing cycle — the figure most utilities use to calculate demand charges.
- **Unit:** kW or kVA
- **Formula:** MAX of all Rising_Demand_Delivered values closed out during the billing period.
- **Standard Range:** Ideally kept close to (but not exceeding) the sanctioned contract demand; exceeding it typically incurs a demand-overdrawal penalty (often at a higher tariff slab).
- **Fluctuation Meaning:** A Max Demand much higher than the average load pattern (poor "load factor") indicates inefficient capacity utilization — the consumer pays for capacity that's rarely used.
- **Related Fields:** Rising_Demand_Delivered, VA_Total
- **Reference Standard:** State DISCOM tariff orders; CEA Metering Regulations 2006

---

### Displacement_PF_R / Displacement_PF_B
- **Category:** Displacement Power Factor
- **Definition:** Power factor computed using only the phase angle between the fundamental (50/60 Hz) voltage and current components, ignoring harmonic distortion — this is the classical "cosφ" power factor.
- **Unit:** Dimensionless, 0–1, lag/lead
- **Formula:** DPF = cos(φ₁), where φ₁ is the fundamental-frequency phase angle
- **Standard Range:** Same target band as True PF (≥0.90–0.95) for well-compensated systems.
- **Fluctuation Meaning:** A large gap between Displacement PF and True PF signals that harmonic distortion (not just reactive/inductive load) is degrading overall power factor — capacitor banks alone won't fix this; harmonic filters are needed.
- **Related Fields:** True_PF_R/Y/B, I_THD
- **Reference Standard:** IEEE 1459-2010

---

### RPM
- **Category:** Mechanical Speed (auxiliary sensor input)
- **Definition:** Rotational speed of a coupled mechanical element — typically a generator, turbine, or motor shaft monitored alongside the electrical meter (common in DG-set or small hydro/captive generation monitoring).
- **Unit:** Revolutions per minute (RPM)
- **Formula:** N/A (direct tachometer/encoder measurement)
- **Standard Range:** Depends on the machine's synchronous speed; for a 4-pole 50 Hz generator, synchronous speed = 1500 RPM (N = 120f/P).
- **Fluctuation Meaning:** Deviation from synchronous speed correlates directly with Frequency_Hz deviation; unstable RPM indicates governor/prime-mover control issues.
- **Related Fields:** Frequency_Hz, Frequency_Max/Min
- **Reference Standard:** IEC 60034-1

---

### Load_Hours_Received
- **Category:** Runtime Accumulator
- **Definition:** Cumulative hours during which the connection/load was energized and drawing power above a threshold.
- **Unit:** Hours (h)
- **Formula:** Sum of time intervals where Watts_Total > 0 (or above a configured threshold).
- **Standard Range:** N/A — used for maintenance scheduling and utilization/load-factor analysis (Load Factor = Average Demand / Max Demand).
- **Fluctuation Meaning:** N/A (cumulative); flat periods with no increase indicate the load was de-energized (planned shutdown or outage).
- **Related Fields:** Wh_Received, Max_Demand_Delivered
- **Reference Standard:** N/A (operational/maintenance metric)

---

### Num_Interruptions
- **Category:** Reliability
- **Definition:** Count of supply interruption events (momentary or sustained power loss) detected by the meter since installation or last reset.
- **Unit:** Count (integer)
- **Formula:** Incremented each time voltage drops below a configured threshold for longer than a defined duration.
- **Standard Range:** Ideally zero or very low; used as an input to utility reliability indices such as SAIFI (System Average Interruption Frequency Index) and SAIDI (...Duration Index).
- **Fluctuation Meaning:** A rising count over time indicates deteriorating supply reliability — feeder faults, weak grid sections, or equipment nearing failure upstream.
- **Related Fields:** Frequency_Min, VLL_Min, Watts_Min
- **Reference Standard:** IEEE 1366-2012 (reliability indices)

---

### V_Y_Phase_Angle / V_B_Phase_Angle
- **Category:** Voltage Phase Angle
- **Definition:** Angular displacement (in electrical degrees) of the Y-phase and B-phase voltage vectors relative to the R-phase reference vector.
- **Unit:** Degrees (°)
- **Formula:** Derived from vector/phasor analysis of the sampled waveforms.
- **Standard Range:** In a correctly-sequenced, balanced 3-phase system: V_Y ≈ −120° (or 240°) and V_B ≈ −240° (or 120°) relative to V_R.
- **Fluctuation Meaning:** Deviations from ~120°/240° spacing indicate phase sequence errors, single-phasing, or severe unbalance — critical to check before connecting rotating machinery (wrong sequence reverses motor rotation).
- **Related Fields:** V_Unbal_R/Y/B, VLN_Avg
- **Reference Standard:** IEC 60034-8 (terminal marking and rotation direction)

---

### I_R_Phase_Angle / I_Y_Phase_Angle / I_B_Phase_Angle
- **Category:** Current Phase Angle
- **Definition:** Angular displacement between each phase's current vector and its corresponding voltage vector — directly determines that phase's displacement power factor.
- **Unit:** Degrees (°)
- **Formula:** φ = angle(V_phase) − angle(I_phase); DPF = cos(φ)
- **Standard Range:** Closer to 0° = higher (better) power factor; industrial inductive loads commonly show 25–45° lagging without compensation.
- **Fluctuation Meaning:** Widening angle indicates increasing reactive (inductive) loading on that phase, e.g., more motors running or capacitor bank stages tripping offline.
- **Related Fields:** Displacement_PF_R/B, VAR_R/Y/B
- **Reference Standard:** IEEE 1459-2010

---

### V_Unbal_R / V_Unbal_Y / V_Unbal_B
- **Category:** Voltage Unbalance
- **Definition:** Percentage deviation of each phase's voltage from the average of all three phase voltages (NEMA definition), or from the true symmetrical-component negative-sequence ratio (IEC definition).
- **Unit:** Percent (%)
- **Formula:** %Unbalance = (Max deviation from average VLN) / (Average VLN) × 100
- **Standard Range:** IEEE/NEMA recommend keeping voltage unbalance under 1%; above 2% is considered problematic; above 5% risks serious motor damage.
- **Fluctuation Meaning:** Persistent unbalance indicates uneven single-phase load distribution across phases or a weak/asymmetric supply; each 1% voltage unbalance can cause roughly 6–10× that percentage in additional motor winding temperature rise (per NEMA derating curves).
- **Related Fields:** VLN_Avg, V_R/Y/B
- **Reference Standard:** NEMA MG1-2016 Part 14.35; IEC 60034-26

---

### I_Unbal_R / I_Unbal_Y / I_Unbal_B
- **Category:** Current Unbalance
- **Definition:** Percentage deviation of each phase's current from the average of all three phase currents.
- **Unit:** Percent (%)
- **Formula:** %Unbalance = (Max deviation from average I) / (Average I) × 100
- **Standard Range:** Ideally under 10%; current unbalance is typically several times larger than the voltage unbalance that causes it, since motor impedance changes non-linearly with voltage imbalance.
- **Fluctuation Meaning:** High/variable current unbalance points to unevenly distributed single-phase loads (lighting, small appliances) tapped across a 3-phase feeder rather than a supply-side fault.
- **Related Fields:** I_R/Y/B, Neutral_I
- **Reference Standard:** NEMA MG1-2016

---

### VLL_Max / VLL_Min, VLN_Max / VLN_Min, Amps_Max / Amps_Min, Frequency_Max / Frequency_Min, Watts_Max / Watts_Min, VAR_Max / VAR_Min, VA_Max / VA_Min, PF_Max / PF_Min
- **Category:** Interval Extremes (Min/Max within the recording window)
- **Definition:** The highest and lowest instantaneous values recorded for each respective parameter during the logging interval (rather than the interval-average value reported elsewhere in the row).
- **Unit:** Same unit as the corresponding base parameter (V, A, Hz, kW, kVAR, kVA, PF)
- **Formula:** MAX()/MIN() of all sub-samples taken within the interval, before averaging.
- **Standard Range:** Same acceptable bands as the corresponding parameter's standard range (see entries above); the point of Max/Min is to catch transient excursions that an interval average would smooth over and hide.
- **Fluctuation Meaning:** A wide Max−Min spread within a single interval reveals volatility invisible in averaged data — e.g., voltage sags from motor inrush, current spikes from short-duration faults, or brief frequency excursions during grid disturbances. This is critical for diagnosing power-quality events like sags, swells, and transients.
- **Related Fields:** Corresponding base parameter (e.g., Watts_Max/Min ↔ Watts_Total)
- **Reference Standard:** IEC 61000-4-30 (power quality measurement methods, Class A/S)

---

### V_R_THD_Pct / V_Y_THD_Pct / V_B_THD_Pct
- **Category:** Total Harmonic Distortion — Voltage
- **Definition:** Total Harmonic Distortion of the voltage waveform per phase — the ratio of the combined power of all harmonic components to the power of the fundamental (50/60 Hz) component, expressed as a percentage.
- **Unit:** Percent (%)
- **Formula:** THD = √(Σ V_n² for n=2 to ∞) / V₁ × 100, where V₁ is the fundamental and V_n are harmonic magnitudes
- **Standard Range:** IEEE 519-2014: voltage THD should stay under 5% for general systems (under 8% for dedicated systems); IEC 61000-2-2 sets similar compatibility levels for public LV networks.
- **Fluctuation Meaning:** Rising voltage THD indicates the shared supply is being polluted by harmonic-generating equipment somewhere on the network — affects all connected loads, not just the offending one.
- **Related Fields:** V_R/Y/B Harmonic, K_Factor_V_R/Y/B
- **Reference Standard:** IEEE 519-2014; IEC 61000-2-2

---

### I_R_THD_Pct / I_Y_THD_Pct / I_B_THD_Pct
- **Category:** Total Harmonic Distortion — Current
- **Definition:** Total Harmonic Distortion of the current waveform per phase, reflecting how non-sinusoidal the load's current draw is.
- **Unit:** Percent (%)
- **Formula:** THD = √(Σ I_n² for n=2 to ∞) / I₁ × 100
- **Standard Range:** IEEE 519-2014 uses Total Demand Distortion (TDD, referenced to max demand load current) rather than THD alone; typical limits range 5–20% depending on the Isc/IL ratio at the point of connection. Current THD is commonly much higher than voltage THD (VFDs/UPS loads can show 30–100%+).
- **Fluctuation Meaning:** Spikes correlate with switching-on of non-linear loads (variable frequency drives, switch-mode power supplies, LED lighting, UPS systems); persistently high values increase transformer/cable heating and can cause nuisance tripping of protective devices.
- **Related Fields:** I_R/Y/B Harmonic, K_Factor_I_R/Y/B, Neutral_I
- **Reference Standard:** IEEE 519-2014

---

### K_Factor_V_R / K_Factor_V_Y / K_Factor_V_B / K_Factor_I_R / K_Factor_I_Y / K_Factor_I_B
- **Category:** Transformer Harmonic Derating Factor
- **Definition:** A weighted index (developed by Underwriters Laboratories, UL 1561) quantifying the additional eddy-current heating that harmonic-rich voltage/current causes in a transformer, compared to an equivalent pure 50/60 Hz sine wave load of the same RMS magnitude.
- **Unit:** Dimensionless index, K=1 (minimum) upward
- **Formula:** K = Σ(I_h² × h²) / Σ(I_h²), where I_h is the RMS current at harmonic order h
- **Standard Range:** K=1 means no extra harmonic heating (pure linear load); K=4, K=13, K=20 are common "K-rated" transformer ratings sized for increasingly harmonic-rich loads (e.g., data centers, hospitals with heavy electronic loads often need K-13 or K-20 transformers).
- **Fluctuation Meaning:** A rising K-Factor over time signals growing harmonic-generating load on that circuit; if it exceeds the K-rating of the installed transformer, the transformer must be de-rated (run below nameplate capacity) or replaced with a higher K-rated unit to avoid premature failure from overheating.
- **Related Fields:** I_THD (R/Y/B), I_Harmonic (R/Y/B)
- **Reference Standard:** UL 1561; IEEE C57.110-2018 (transformer harmonic loading guide)

---

## Quick Reference: Standard Ranges at a Glance

| Parameter Group | Optimal / Compliant Range | Governing Standard |
|---|---|---|
| Power Factor (True/Displacement) | ≥ 0.90–0.95 | IEEE 1459-2010, SERC tariffs |
| Voltage (LN/LL) deviation from nominal | ±6% (±10% max per IEC) | IS 12360, IEC 60038 |
| Frequency | 49.90–50.05 Hz (India) | IEGC 2010 |
| Voltage Unbalance | < 1% ideal, < 2% acceptable | NEMA MG1, IEC 60034-26 |
| Current Unbalance | < 10% | NEMA MG1 |
| Voltage THD | < 5% (general), < 8% (dedicated) | IEEE 519-2014 |
| Current THD / TDD | 5–20% (load-dependent) | IEEE 519-2014 |
| Neutral Current | << Phase current | IEEE 1100-2005 |
| K-Factor | 1 (linear) to 20+ (harmonic-heavy) | UL 1561 |

**General interpretive rule:** Small, random fluctuation interval-to-interval is normal load variation. What matters diagnostically is *sustained* drift — growing unbalance %, rising THD/K-Factor, a widening gap between True PF and Displacement PF, or an increasing Num_Interruptions count — since these point to developing equipment stress, inefficiency, or supply-quality degradation rather than everyday load noise.
