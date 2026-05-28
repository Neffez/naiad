// naiad-components.jsx — shared building blocks
// Depends on naiad-icons.jsx + naiad-data.jsx

const { useState, useEffect, useRef } = React;

// ---------- Brand / header pieces ----------

const NaiadMark = ({ size = 28, withWord = true }) =>
<div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
    <ILogo size={size} />
    {withWord &&
  <span style={{
    fontWeight: 500, fontSize: 17, letterSpacing: "-0.01em",
    color: "var(--n-fg)"
  }}>Naiad</span>
  }
  </div>;


// Master toggle (large, glanceable)
const MasterToggle = ({ on = true, onToggle, compact = false }) =>
<button
  className={"n-master" + (on ? "" : " off")}
  onClick={onToggle}
  style={{ height: compact ? 40 : 44 }}>
  
    <span className="knob" style={compact ? { width: 28, height: 28 } : null} />
    <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.1, alignItems: "flex-start" }}>
      <span className="n-eyebrow" style={{ fontSize: 9.5 }}>System</span>
      <span style={{ fontSize: 13, fontWeight: 500, color: on ? "var(--n-fg)" : "var(--n-fg-muted)" }}>
        {on ? "Aktiv" : "Aus"}
      </span>
    </span>
  </button>;


// Emergency stop (two-touch, requires hold)
const EmergencyStop = ({ armed, onArm, onFire }) =>
<button
  className="n-btn danger"
  onClick={armed ? onFire : onArm}
  style={{
    height: 44, gap: 8, paddingLeft: 14, paddingRight: 14,
    fontWeight: 600
  }}
  title="Notaus — System + alle Ventile sofort stoppen">
  
    <IAlert size={16} />
    <span>{armed ? "Bestätigen?" : "Notaus"}</span>
  </button>;


// Weather strip — temp, rain, wind, season
const WeatherStrip = ({ compact = false }) => {
  const w = NAIAD_DATA.weather;
  const items = [
  { icon: <ISun size={14} />, value: w.temp + "°", label: "Temperatur" },
  { icon: <IDrop size={14} />, value: w.rain24h + " mm", label: "Regen 24 h" },
  { icon: <IWind size={14} />, value: w.wind, label: "Wind" },
  { icon: <ICloud size={14} />, value: w.season, label: "Saison" }];

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: compact ? 14 : 18,
      padding: compact ? "0 6px" : "0 4px"
    }}>
      {items.map((it, i) =>
      <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, color: "var(--n-fg-soft)" }}>
          <span style={{ color: "var(--n-fg-muted)" }}>{it.icon}</span>
          <span className="mono" style={{ fontSize: 13, color: "var(--n-fg)" }}>{it.value}</span>
        </div>
      )}
    </div>);

};

// ---------- Sequence card ----------

// Variants:
//   size="dense"   – compact, used in old tablet/mobile lists
//   size="regular" – default; mobile list
//   size="rich"    – 1920-Visu variant: zone breakdown, big buttons, more live data

const SequenceCard = ({ seq, dense: denseProp = false, size, onStart, onSchedule, onPause }) => {
  const variant = size || (denseProp ? "dense" : "regular");
  if (variant === "rich") return <SequenceCardRich seq={seq} onStart={onStart} onSchedule={onSchedule} onPause={onPause} />;
  const dense = variant === "dense";

  const isRunning = seq.status === "running";
  const isPaused = seq.status === "paused";
  const isDisabled = seq.status === "disabled";

  const factor = seq.factor;
  const headerSize = dense ? 17 : 19;

  return (
    <div
      className={"n-card" + (isRunning ? " n-live-glow" : "")}
      style={{
        padding: dense ? "14px 16px" : "16px 18px",
        opacity: isDisabled ? 0.55 : 1,
        display: "flex", flexDirection: "column", gap: dense ? 10 : 12,
        position: "relative", overflow: "hidden"
      }}>
      
      {/* color band */}
      <span style={{
        position: "absolute", top: 0, left: 0, bottom: 0, width: 3,
        background: seq.color, opacity: isDisabled ? 0.3 : 0.85
      }} />

      {/* top row: name + status chip + factor */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: headerSize, fontWeight: 600, letterSpacing: "-0.01em" }}>
              {seq.name}
            </span>
            <StatusChip status={seq.status} />
          </div>
          <div className="n-label" style={{ fontSize: 12 }}>
            {isRunning && <span>Läuft seit {seq.elapsed} min · {seq.zones} {seq.zones === 1 ? "Zone" : "Zonen"}</span>}
            {isPaused && <span>Pausiert · Rest {seq.remaining} min</span>}
            {seq.status === "idle" && <span>Nächster Lauf · {seq.next} · {seq.zones} × {seq.perZone} min</span>}
            {isDisabled && <span style={{ color: "var(--n-fg-dim)" }}>{seq.note || "Deaktiviert"}</span>}
          </div>
        </div>

        {/* factor pill */}
        {!isDisabled &&
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2,
          flex: "0 0 auto"
        }}>
            <span
            className="mono"
            style={{
              fontSize: 18, fontWeight: 500, letterSpacing: "-0.02em",
              color: factor === 0 ? "var(--n-paused)" :
              factor > 100 ? "var(--n-teal-200)" : "var(--n-fg)"
            }}>
            {factor}%</span>
            <span className="n-eyebrow" style={{ fontSize: 9 }}>
              {seq.factorNote || "Faktor"}
            </span>
          </div>
        }
      </div>

      {/* progress (running only) */}
      {isRunning &&
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="n-progress" style={{ flex: 1 }}>
            <i style={{ width: `${seq.elapsed / seq.total * 100}%` }} />
          </div>
          <span className="mono" style={{
          fontSize: 13, color: "var(--n-teal-200)", letterSpacing: "-0.01em", fontWeight: 500
        }}>
            {seq.remaining} min Rest
          </span>
        </div>
      }

      {/* quick actions */}
      <div style={{ display: "flex", gap: 8, marginTop: dense ? 2 : 4 }}>
        <button
          className={"n-iconbtn" + (isRunning ? " paused-state" : " accent")}
          onClick={isRunning ? onPause : onStart}
          disabled={isDisabled}
          style={{ width: 44, height: 44, opacity: isDisabled ? 0.4 : 1 }}
          title={isRunning ? "Pausieren" : "Sofort starten"}>
          
          {isRunning ? <IPause size={18} /> : <IPlay size={16} />}
        </button>
        <button
          className="n-iconbtn"
          onClick={onSchedule}
          disabled={isDisabled}
          style={{ width: 44, height: 44, opacity: isDisabled ? 0.4 : 1 }}
          title="Planen">
          
          <ICal size={17} />
        </button>
        <button
          className="n-iconbtn"
          onClick={onPause}
          disabled={isDisabled || !isRunning}
          style={{ flex: 1, height: 44, opacity: isDisabled ? 0.4 : 1, gap: 8, fontSize: 12.5, color: "var(--n-fg-soft)", paddingLeft: 12, justifyContent: "flex-start" }}
          title="Heute aussetzen">
          
          <IClock size={15} />
          <span style={{ fontWeight: 500 }}>Heute aussetzen</span>
        </button>
      </div>
    </div>);

};

const StatusChip = ({ status }) =>
<span className={"n-chip " + status}>
    <span className="n-chip-dot" />
    {n_statusLabel(status)}
  </span>;


// Rich variant for the 1920-Visu — designed for ~460px wide cards.
const SequenceCardRich = ({ seq, onStart, onSchedule, onPause }) => {
  const isRunning = seq.status === "running";
  const isPaused = seq.status === "paused";
  const isDisabled = seq.status === "disabled";
  const factor = seq.factor;

  // construct zone breakdown
  const zoneNames = NAIAD_DATA.valves.
  filter((v) => v.name.toLowerCase().startsWith(seq.name.toLowerCase().slice(0, 4)) || v.name.toLowerCase().includes(seq.name.toLowerCase())).
  slice(0, seq.zones);
  const zones = zoneNames.length === seq.zones ?
  zoneNames.map((v, i) => ({ name: v.name, runtime: seq.perZone, live: v.state === "on" })) :
  Array.from({ length: seq.zones }, (_, i) => ({ name: `${seq.name} Zone ${i + 1}`, runtime: seq.perZone, live: false }));

  // estimated liters (running this regular slot, with current factor)
  const adjMinutes = seq.zones * seq.perZone * (factor / 100);
  const liters = Math.round(adjMinutes * 7.7);

  return (
    <div
      className={"n-card" + (isRunning ? " n-live-glow" : "")}
      style={{
        padding: "16px 20px 14px",
        opacity: isDisabled ? 0.55 : 1,
        display: "flex", flexDirection: "column", gap: 10,
        position: "relative", overflow: "hidden",
        height: "100%", lineHeight: "1"
      }}>
      
      <span style={{
        position: "absolute", top: 0, left: 0, bottom: 0, width: 4,
        background: seq.color, opacity: isDisabled ? 0.3 : 0.9
      }} />

      {/* top: name + chip ··· factor */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.015em" }}>{seq.name}</span>
            <StatusChip status={seq.status} />
          </div>
          <span className="n-label" style={{ fontSize: 13 }}>
            {seq.schedule} · {seq.zones} {seq.zones === 1 ? "Zone" : "Zonen"} {seq.perZone ? ` · regulär ${seq.perZone} min/Zone` : ""}
          </span>
        </div>
        {!isDisabled &&
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2, flex: "0 0 auto"
        }}>
            <span className="n-bignum" style={{
            fontSize: 40, lineHeight: 1, letterSpacing: "-0.02em",
            color: factor === 0 ? "var(--n-paused)" : factor > 100 ? "var(--n-teal-200)" : "var(--n-fg)", fontFamily: "Helvetica Neue"
          }}>{factor}%</span>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>
              {seq.factorNote || "Anpassung"}
            </span>
          </div>
        }
      </div>

      {/* live progress row (running) OR next-run row (idle/paused) */}
      {isRunning ?
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span className="n-bignum" style={{ fontSize: 38, color: "var(--n-teal-200)" }}>
                {seq.remaining}
              </span>
              <span style={{ fontSize: 13, color: "var(--n-fg-muted)" }}>min Rest</span>
            </div>
            <span className="mono" style={{ fontSize: 12, color: "var(--n-fg-muted)" }}>
              {seq.elapsed} / {seq.total} min
            </span>
          </div>
          <div className="n-progress" style={{ height: 6 }}>
            <i style={{ width: `${seq.elapsed / seq.total * 100}%` }} />
          </div>
          <div className="n-ripple-line" />
        </div> :
      isPaused ?
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span className="mono" style={{ fontSize: 24, fontWeight: 500, color: "var(--n-paused)" }}>
              {seq.remaining} min
            </span>
            <span style={{ fontSize: 12.5, color: "var(--n-fg-muted)" }}>Rest, pausiert</span>
          </div>
          <span className="mono" style={{ fontSize: 12, color: "var(--n-fg-muted)" }}>
            {seq.elapsed}/{seq.total} min gelaufen
          </span>
        </div> :
      !isDisabled ?
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "baseline",
        padding: "10px 12px",
        background: "rgba(255,255,255,0.018)",
        border: "1px solid var(--n-line)",
        borderRadius: 10
      }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>Nächster Lauf</span>
            <span className="mono" style={{ fontSize: 15, color: factor === 0 ? "var(--n-paused)" : "var(--n-fg)", fontWeight: 500 }}>
              {seq.next || seq.schedule}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-end" }}>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>Voraus. Verbrauch</span>
            <span className="mono" style={{ fontSize: 15, color: "var(--n-fg)", fontWeight: 500 }}>
              {liters} L
            </span>
          </div>
        </div> :

      <div style={{
        padding: "12px 12px", borderRadius: 10,
        border: "1px dashed var(--n-line-strong)",
        fontSize: 13, color: "var(--n-fg-dim)"
      }}>
          {seq.note || "In den Einstellungen deaktiviert. Sequenz wird beim Plan ignoriert."}
        </div>
      }

      {/* zone breakdown */}
      {!isDisabled &&
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span className="n-eyebrow" style={{ fontSize: 9.5 }}>Zonen</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {zones.map((z, i) =>
          <div key={i} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "4px 0", borderBottom: i < zones.length - 1 ? "1px dashed var(--n-line)" : "none",
            fontSize: 12.5
          }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <span style={{
                width: 6, height: 6, borderRadius: "50%",
                background: z.live ? "var(--n-teal-300)" : "var(--n-fg-dim)",
                boxShadow: z.live ? "0 0 0 3px rgba(94,200,216,0.18)" : "none",
                flex: "0 0 auto"
              }} />
                  <span style={{ color: z.live ? "var(--n-teal-200)" : "var(--n-fg-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {z.name}
                  </span>
                </div>
                <span className="mono" style={{ color: "var(--n-fg-muted)", fontSize: 12 }}>
                  {Math.round(z.runtime * (factor || 100) / 100)} min
                </span>
              </div>
          )}
          </div>
        </div>
      }

      <div style={{ flex: 1 }} />

      {/* quick actions */}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          className={"n-btn " + (isRunning ? "" : "primary")}
          onClick={isRunning ? onPause : onStart}
          disabled={isDisabled}
          style={{
            flex: 1, height: 44, minWidth: 0,
            padding: "0 12px", fontSize: 13,
            opacity: isDisabled ? 0.4 : 1,
            whiteSpace: "nowrap"
          }}
          title={isRunning ? "Pausieren" : "Sofort starten"}>
          
          {isRunning ? <IPause size={16} /> : <IPlay size={14} />}
          <span>{isRunning ? "Pause" : isPaused ? "Weiter" : "Start"}</span>
        </button>
        <button
          className="n-btn"
          onClick={onSchedule}
          disabled={isDisabled}
          style={{
            flex: 1, height: 44, minWidth: 0,
            padding: "0 12px", fontSize: 13,
            opacity: isDisabled ? 0.4 : 1,
            whiteSpace: "nowrap"
          }}
          title="Planen">
          
          <ICal size={15} />
          <span>Planen</span>
        </button>
        <button
          className="n-iconbtn"
          disabled={isDisabled}
          style={{ width: 44, height: 44, flex: "0 0 44px", opacity: isDisabled ? 0.4 : 1 }}
          title="Heute aussetzen">
          
          <IClock size={16} />
        </button>
      </div>
    </div>);

};

// ---------- Valve grid ----------

// Compact grid of 8 valves. cols defaults to 4 (2 rows). Pass cols=8 for a single row.
const ValveGrid = ({ cols = 4, valves = NAIAD_DATA.valves, dense = false }) =>
<div
  style={{
    display: "grid",
    gridTemplateColumns: `repeat(${cols}, 1fr)`,
    gap: dense ? 8 : 10
  }}>
  
    {valves.map((v) =>
  <div key={v.id} className={"n-valve " + v.state} style={{ minHeight: dense ? 74 : 88, padding: dense ? "10px 11px" : "12px 12px 10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <span className="led" />
          {v.state === "on" && v.runtime &&
      <span className="mono" style={{ fontSize: 11, color: "var(--n-teal-200)" }}>{v.runtime}</span>
      }
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{
        fontSize: 12, fontWeight: 500, lineHeight: 1.2,
        color: v.state === "on" ? "var(--n-teal-200)" : "var(--n-fg-soft)"
      }}>{v.name}</span>
          <span className="n-eyebrow" style={{ fontSize: 9 }}>
            {v.state === "on" ? "Live" : v.state === "paused" ? "Pause" : "Aus"}
          </span>
        </div>
      </div>
  )}
  </div>;


// ---------- Today summary block ----------

const TodayBlock = ({ dense = false }) => {
  const t = NAIAD_DATA.today;
  return (
    <div className="n-card" style={{ padding: dense ? "16px 18px" : "18px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="n-eyebrow">Heute · Anpassung</span>
        <span className="n-eyebrow" style={{ color: "var(--n-teal-300)" }}>auto</span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="n-bignum" style={{ fontSize: dense ? 52 : 60, color: "var(--n-teal-200)" }}>
          {t.factor}<span style={{ fontSize: "0.45em", color: "var(--n-fg-muted)", marginLeft: 4 }}>%</span>
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {t.breakdown.map((b, i) =>
        <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }}>
            <span style={{ color: "var(--n-fg-soft)" }}>{b.label}</span>
            <span className="mono" style={{
            color: b.positive === false ? "var(--n-paused)" :
            b.positive === true ? "var(--n-leaf-300)" : "var(--n-fg-muted)"
          }}>{b.delta}</span>
          </div>
        )}
      </div>

      <div className="n-divider" style={{ margin: "2px 0" }} />

      {/* next two runs */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <span className="n-eyebrow">Nächster Lauf</span>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 4 }}>
            <span style={{ fontSize: 16, fontWeight: 500, letterSpacing: "-0.01em" }}>{t.next.seq}</span>
            <span className="mono" style={{ fontSize: 13, color: "var(--n-fg-soft)" }}>{t.next.duration}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
            <span className="mono" style={{ fontSize: 12, color: "var(--n-teal-300)" }}>{t.next.when}</span>
            <span style={{ fontSize: 11, color: "var(--n-fg-muted)" }}>{t.next.relative}</span>
          </div>
        </div>
        <div style={{ opacity: 0.7 }}>
          <span className="n-eyebrow">Danach</span>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 4 }}>
            <span style={{ fontSize: 14, color: "var(--n-fg-soft)" }}>{t.after.seq}</span>
            <span className="mono" style={{ fontSize: 12, color: "var(--n-fg-muted)" }}>
              {t.after.when} · {t.after.duration}
            </span>
          </div>
        </div>
      </div>
    </div>);

};

// ---------- Weekly chart ----------

const WeekBars = ({ height = 130, showAxis = true }) => {
  const week = NAIAD_DATA.week;
  const seqs = NAIAD_DATA.sequences;
  const maxTotal = Math.max(...week.map((d) => d.override?.total ?? d.total));
  const niceMax = Math.ceil(maxTotal / 100) * 100;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height, paddingTop: 6 }}>
        {week.map((d, i) => {
          const parts = d.override?.parts ?? d.parts;
          const total = d.override?.total ?? d.total;
          const barH = total / niceMax * (height - 18);
          return (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, height: "100%" }}>
              <div style={{
                height: "100%", display: "flex", flexDirection: "column",
                justifyContent: "flex-end", width: "100%",
                minHeight: 4
              }}>
                <div style={{
                  height: Math.max(barH, 3),
                  display: "flex", flexDirection: "column-reverse",
                  borderRadius: 4, overflow: "hidden",
                  border: d.today ? "1px solid rgba(94,200,216,0.55)" : "1px solid var(--n-line)",
                  background: "rgba(255,255,255,0.02)",
                  position: "relative"
                }}>
                  {parts.map((p, j) => p > 0 &&
                  <div key={j} style={{
                    flexBasis: `${p / total * 100}%`,
                    background: seqs[j].color,
                    opacity: d.today ? 0.95 : 0.7
                  }} />
                  )}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, height: 28 }}>
                <span className="n-eyebrow" style={{ fontSize: 9.5, color: d.today ? "var(--n-teal-300)" : "var(--n-fg-muted)" }}>
                  {d.day}
                </span>
                <span className="mono" style={{ fontSize: 10.5, color: d.today ? "var(--n-fg)" : "var(--n-fg-muted)" }}>
                  {total} L
                </span>
              </div>
            </div>);

        })}
      </div>
    </div>);

};

// ---------- Stat ----------

const StatBlock = ({ label, value, unit, tone }) =>
<div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
    <span className="n-eyebrow">{label}</span>
    <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
      <span className="n-bignum" style={{ fontSize: 24, color: tone || "var(--n-fg)" }}>{value}</span>
      <span style={{ fontSize: 12, color: "var(--n-fg-muted)" }}>{unit}</span>
    </div>
  </div>;


// ---------- Sidebar (desktop) ----------

const Sidebar = ({ active = "dashboard" }) =>
<div className="n-side" style={{ width: 64, display: "flex", flexDirection: "column", alignItems: "center", padding: "16px 0", gap: 6 }}>
    <div style={{ marginBottom: 10 }}>
      <ILogo size={26} />
    </div>
    {[
  { id: "dashboard", icon: <IHome size={18} />, label: "Übersicht" },
  { id: "plan", icon: <ICal size={18} />, label: "Planen" },
  { id: "history", icon: <IChart size={18} />, label: "Verlauf" },
  { id: "settings", icon: <ISettings size={18} />, label: "Einstellungen" }].
  map((item) =>
  <button
    key={item.id}
    className={"n-iconbtn" + (active === item.id ? " accent" : "")}
    style={{ width: 44, height: 44 }}
    title={item.label}>
    
        {item.icon}
      </button>
  )}
  </div>;


// ---------- Bottom nav (embed / mobile) ----------

const BottomNav = ({ active = "dashboard" }) =>
<div style={{
  display: "flex", justifyContent: "space-around", alignItems: "center",
  background: "var(--n-bg-elev)", borderTop: "1px solid var(--n-line)",
  height: 64, padding: "0 4px"
}}>
    {[
  { id: "dashboard", icon: <IHome size={20} />, label: "Übersicht" },
  { id: "plan", icon: <ICal size={20} />, label: "Planen" },
  { id: "history", icon: <IChart size={20} />, label: "Verlauf" },
  { id: "settings", icon: <ISettings size={20} />, label: "Mehr" }].
  map((item) =>
  <button key={item.id} style={{
    flex: 1, height: 48, background: "transparent", border: 0, cursor: "pointer",
    display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
    color: active === item.id ? "var(--n-teal-200)" : "var(--n-fg-muted)",
    fontSize: 10.5, letterSpacing: "0.02em"
  }}>
        {item.icon}
        <span>{item.label}</span>
      </button>
  )}
  </div>;


Object.assign(window, {
  NaiadMark, MasterToggle, EmergencyStop, WeatherStrip,
  SequenceCard, StatusChip, ValveGrid, TodayBlock, WeekBars, StatBlock,
  Sidebar, BottomNav
});