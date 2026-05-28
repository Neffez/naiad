// naiad-screens.jsx — Planner, History, Settings full-screen views (1920×1080)

// ═══════════════════════════════════════════════════════════════
//  Shared screen shell — sidebar + header + content area
// ═══════════════════════════════════════════════════════════════

const ScreenShell = ({ active, theme, embed, title, children }) => {
  const [masterOn, setMasterOn] = useState(true);

  return (
    <div
      className="naiad"
      data-theme={theme}
      style={{
        width: 1920, height: 1080,
        display: "flex",
        background: "var(--n-bg)",
        color: "var(--n-fg)",
      }}
    >
      {!embed && <TabletSidebar active={active} />}

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Top bar — matches tablet dashboard */}
        <header className="n-wavebed" style={{
          height: 88, padding: "0 36px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          borderBottom: "1px solid var(--n-line)",
          flex: "0 0 88px",
          gap: 24,
          position: "relative",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 28, minWidth: 0 }}>
            {embed && <NaiadMark size={26} />}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span className="n-eyebrow">Naiad</span>
              <span style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em" }}>{title}</span>
            </div>
            <div className="n-vdivider" style={{ height: 40 }} />
            <WeatherStrip />
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
              <span className="mono" style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>21:46</span>
              <span style={{ fontSize: 11.5, color: "var(--n-fg-muted)" }}>Mi · 27. Mai · KW 22</span>
            </div>
            <div className="n-vdivider" style={{ height: 40 }} />
            <MasterToggle on={masterOn} onToggle={() => setMasterOn(!masterOn)} />
          </div>
        </header>

        {/* Content */}
        <main style={{
          flex: 1, padding: "28px 44px 36px",
          display: "flex", flexDirection: "column",
          minHeight: 0,
          overflowY: "auto",
          scrollbarWidth: "none",
        }}>
          {children}
        </main>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
//  PLANNER screen
// ═══════════════════════════════════════════════════════════════

const NaiadPlannerScreen = ({ theme = "dark", embed = false }) => {
  const [selectedSeq, setSelectedSeq] = useState("");
  const [mode, setMode] = useState("hours"); // "hours" | "datetime"
  const [hoursValue, setHoursValue] = useState("4");
  const [dateValue, setDateValue] = useState("");
  const [timeValue, setTimeValue] = useState("");
  const [duration, setDuration] = useState("");
  const [planned, setPlanned] = useState([]);

  const handlePlan = () => {
    if (!selectedSeq) return;
    const seq = NAIAD_DATA.sequences.find((s) => s.id === selectedSeq);
    const entry = {
      id: Date.now(),
      seq: seq.name,
      color: seq.color,
      when: mode === "hours"
        ? `In ${hoursValue} Stunden`
        : `${dateValue} ${timeValue}`,
      duration: duration || `${seq.perZone} min (Standard)`,
    };
    setPlanned((p) => [...p, entry]);
  };

  return (
    <ScreenShell active="plan" theme={theme} embed={embed} title="Planen">
      <div style={{ maxWidth: 900, display: "flex", flexDirection: "column", gap: 22 }}>

        {/* Sequenz-Auswahl */}
        <div style={{ position: "relative" }}>
          <select
            value={selectedSeq}
            onChange={(e) => setSelectedSeq(e.target.value)}
            style={{
              width: "100%", height: 52, padding: "0 18px",
              background: "var(--n-card)",
              border: "1px solid var(--n-line-strong)",
              borderRadius: "var(--n-r-md)",
              color: selectedSeq ? "var(--n-fg)" : "var(--n-fg-muted)",
              fontSize: 15,
              fontFamily: "var(--n-sans)",
              appearance: "none",
              cursor: "pointer",
              outline: "none",
            }}
          >
            <option value="">— Sequenz wählen —</option>
            {NAIAD_DATA.sequences.filter((s) => s.status !== "disabled").map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <span style={{
            position: "absolute", right: 18, top: "50%", transform: "translateY(-50%)",
            color: "var(--n-fg-muted)", pointerEvents: "none",
          }}>
            <IChevDown size={18} />
          </span>
        </div>

        {/* Mode toggle: In Stunden / Zu Datum-Uhrzeit */}
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr",
          background: "var(--n-card)",
          border: "1px solid var(--n-line-strong)",
          borderRadius: "var(--n-r-md)",
          overflow: "hidden",
          height: 48,
        }}>
          {[
            { id: "hours", label: "In Stunden" },
            { id: "datetime", label: "Zu Datum/Uhrzeit" },
          ].map((opt) => (
            <button
              key={opt.id}
              onClick={() => setMode(opt.id)}
              style={{
                background: mode === opt.id
                  ? "linear-gradient(180deg, var(--n-teal-500), var(--n-teal-600))"
                  : "transparent",
                border: "none",
                color: mode === opt.id ? "#04181c" : "var(--n-fg-muted)",
                fontSize: 14,
                fontWeight: mode === opt.id ? 600 : 400,
                fontFamily: "var(--n-sans)",
                cursor: "pointer",
                transition: "all 160ms var(--n-ease)",
                borderRadius: mode === opt.id ? "var(--n-r-sm)" : 0,
                margin: mode === opt.id ? 4 : 0,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Conditional inputs */}
        {mode === "hours" ? (
          <div style={{
            display: "flex", alignItems: "center", gap: 0,
            background: "var(--n-card)",
            border: "1px solid var(--n-line-strong)",
            borderRadius: "var(--n-r-md)",
            height: 52,
            overflow: "hidden",
          }}>
            <input
              type="number"
              value={hoursValue}
              onChange={(e) => setHoursValue(e.target.value)}
              min="1" max="72"
              style={{
                flex: 1, height: "100%", padding: "0 18px",
                background: "transparent",
                border: "none",
                color: "var(--n-fg)",
                fontSize: 15,
                fontFamily: "var(--n-sans)",
                outline: "none",
                fontVariantNumeric: "tabular-nums",
              }}
              placeholder="Stunden"
            />
            <span style={{
              padding: "0 14px", color: "var(--n-fg-muted)", fontSize: 13,
              borderLeft: "1px solid var(--n-line)",
              height: "100%", display: "flex", alignItems: "center",
              background: "rgba(255,255,255,0.015)",
            }}>h</span>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <input
              type="date"
              value={dateValue}
              onChange={(e) => setDateValue(e.target.value)}
              style={{
                height: 52, padding: "0 18px",
                background: "var(--n-card)",
                border: "1px solid var(--n-line-strong)",
                borderRadius: "var(--n-r-md)",
                color: "var(--n-fg)",
                fontSize: 15,
                fontFamily: "var(--n-sans)",
                outline: "none",
                colorScheme: theme === "dark" ? "dark" : "light",
              }}
            />
            <input
              type="time"
              value={timeValue}
              onChange={(e) => setTimeValue(e.target.value)}
              style={{
                height: 52, padding: "0 18px",
                background: "var(--n-card)",
                border: "1px solid var(--n-line-strong)",
                borderRadius: "var(--n-r-md)",
                color: "var(--n-fg)",
                fontSize: 15,
                fontFamily: "var(--n-sans)",
                outline: "none",
                colorScheme: theme === "dark" ? "dark" : "light",
              }}
            />
          </div>
        )}

        {/* Dauer-Override */}
        <div style={{
          display: "flex", alignItems: "center", gap: 0,
          background: "var(--n-card)",
          border: "1px solid var(--n-line-strong)",
          borderRadius: "var(--n-r-md)",
          height: 52,
          overflow: "hidden",
        }}>
          <input
            type="number"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            min="1" max="120"
            style={{
              flex: 1, height: "100%", padding: "0 18px",
              background: "transparent",
              border: "none",
              color: duration ? "var(--n-fg)" : "var(--n-fg-muted)",
              fontSize: 15,
              fontFamily: "var(--n-sans)",
              outline: "none",
              fontVariantNumeric: "tabular-nums",
            }}
            placeholder="Dauer (min) — leer = Konfig-Standard"
          />
          <span style={{
            padding: "0 14px", color: "var(--n-fg-muted)", fontSize: 13,
            borderLeft: "1px solid var(--n-line)",
            height: "100%", display: "flex", alignItems: "center",
            background: "rgba(255,255,255,0.015)",
          }}>min</span>
        </div>

        {/* Planen button */}
        <button
          className="n-btn primary lg"
          onClick={handlePlan}
          style={{
            width: "100%", height: 52,
            fontSize: 15,
          }}
        >
          Planen
        </button>

        {/* Geplante Läufe */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
          {planned.length === 0 ? (
            <span style={{
              color: "var(--n-fg-muted)", fontSize: 14,
              textAlign: "center", padding: "16px 0",
            }}>
              Keine geplanten Läufe
            </span>
          ) : (
            planned.map((p) => (
              <div key={p.id} className="n-card" style={{
                padding: "14px 18px",
                display: "flex", alignItems: "center", justifyContent: "space-between",
                gap: 14,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{ width: 4, height: 28, background: p.color, borderRadius: 2 }} />
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 15, fontWeight: 600 }}>{p.seq}</span>
                    <span className="n-label" style={{ fontSize: 12 }}>{p.when} · {p.duration}</span>
                  </div>
                </div>
                <button
                  className="n-iconbtn"
                  onClick={() => setPlanned((prev) => prev.filter((x) => x.id !== p.id))}
                  style={{ width: 36, height: 36 }}
                  title="Entfernen"
                >
                  <IX size={15} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </ScreenShell>
  );
};

// ═══════════════════════════════════════════════════════════════
//  HISTORY screen
// ═══════════════════════════════════════════════════════════════

const HISTORY_DATA = [
  { zone: "Hochbeet",          seq: "Hochbeet",      started: "27.05. 21:30", dur: "15 min",  liters: 116, trigger: "Zeitplan" },
  { zone: "Beete Ost",         seq: "Beete",         started: "27.05. 04:00", dur: "94 min",  liters: 724, trigger: "Zeitplan" },
  { zone: "Beete Süd/West",    seq: "Beete",         started: "27.05. 04:00", dur: "94 min",  liters: 724, trigger: "Zeitplan" },
  { zone: "Hochbeet",          seq: "Hochbeet",      started: "26.05. 22:00", dur: "16 min",  liters: 123, trigger: "Zeitplan" },
  { zone: "Lichtschacht",      seq: "Lichtschacht",  started: "26.05. 05:00", dur: "47 min",  liters: 362, trigger: "Zeitplan" },
  { zone: "Hochbeet",          seq: "Hochbeet",      started: "25.05. 22:00", dur: "15 min",  liters: 116, trigger: "Zeitplan" },
  { zone: "Rasen Mitte",       seq: "Rasen",         started: "25.05. 05:00", dur: "42 min",  liters: 323, trigger: "Zeitplan" },
  { zone: "Rasen Südwesten",   seq: "Rasen",         started: "25.05. 05:00", dur: "42 min",  liters: 323, trigger: "Zeitplan" },
  { zone: "Rasen Norden",      seq: "Rasen",         started: "25.05. 05:00", dur: "42 min",  liters: 323, trigger: "Zeitplan" },
  { zone: "Hochbeet",          seq: "Hochbeet",      started: "24.05. 22:00", dur: "16 min",  liters: 123, trigger: "Manuell" },
  { zone: "Beete Ost",         seq: "Beete",         started: "24.05. 04:00", dur: "90 min",  liters: 693, trigger: "Zeitplan" },
  { zone: "Beete Süd/West",    seq: "Beete",         started: "24.05. 04:00", dur: "90 min",  liters: 693, trigger: "Zeitplan" },
];

const seqColorMap = {};
NAIAD_DATA.sequences.forEach((s) => { seqColorMap[s.name] = s.color; });

const NaiadHistoryScreen = ({ theme = "dark", embed = false }) => {
  const cols = [
    { key: "zone",    label: "Zone",        flex: 1.3 },
    { key: "seq",     label: "Sequenz",     flex: 1 },
    { key: "started", label: "Gestartet",   flex: 1.2 },
    { key: "dur",     label: "Dauer",       flex: 0.7 },
    { key: "liters",  label: "Liter",       flex: 0.7 },
    { key: "trigger", label: "Auslöser",    flex: 0.8 },
  ];

  return (
    <ScreenShell active="history" theme={theme} embed={embed} title="Verlauf">
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>

        {/* Summary bar */}
        <div style={{
          display: "flex", gap: 32, marginBottom: 22,
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span className="n-eyebrow">Letzte 7 Tage</span>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span className="mono" style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.02em" }}>1.847 L</span>
              <span style={{ fontSize: 12.5, color: "var(--n-teal-300)" }}>+12 % vs. KW 21</span>
            </div>
          </div>
          <div className="n-vdivider" style={{ height: 44 }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span className="n-eyebrow">Läufe gesamt</span>
            <span className="mono" style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.02em" }}>
              {HISTORY_DATA.length}
            </span>
          </div>
          <div className="n-vdivider" style={{ height: 44 }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span className="n-eyebrow">Ø Dauer / Lauf</span>
            <span className="mono" style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.02em" }}>
              {Math.round(HISTORY_DATA.reduce((a, r) => a + parseInt(r.dur), 0) / HISTORY_DATA.length)} min
            </span>
          </div>
        </div>

        {/* Table header */}
        <div style={{
          display: "flex", alignItems: "center",
          padding: "12px 18px",
          borderBottom: "1px solid var(--n-line-bright)",
        }}>
          {cols.map((c) => (
            <span key={c.key} className="n-eyebrow" style={{
              flex: c.flex, fontSize: 11, letterSpacing: "0.05em",
            }}>
              {c.label}
            </span>
          ))}
        </div>

        {/* Table rows */}
        {HISTORY_DATA.map((row, i) => (
          <div
            key={i}
            style={{
              display: "flex", alignItems: "center",
              padding: "13px 18px",
              borderBottom: "1px solid var(--n-line)",
              transition: "background 120ms",
              cursor: "default",
            }}
            onMouseOver={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
            onMouseOut={(e) => e.currentTarget.style.background = "transparent"}
          >
            <span style={{ flex: cols[0].flex, fontSize: 13.5, fontWeight: 500, display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{
                width: 4, height: 22, borderRadius: 2,
                background: seqColorMap[row.seq] || "var(--n-fg-dim)",
              }} />
              {row.zone}
            </span>
            <span style={{ flex: cols[1].flex, fontSize: 13.5, color: "var(--n-fg-soft)" }}>
              {row.seq}
            </span>
            <span className="mono" style={{ flex: cols[2].flex, fontSize: 13, color: "var(--n-fg-soft)" }}>
              {row.started}
            </span>
            <span className="mono" style={{ flex: cols[3].flex, fontSize: 13, color: "var(--n-fg-soft)" }}>
              {row.dur}
            </span>
            <span className="mono" style={{ flex: cols[4].flex, fontSize: 13, color: "var(--n-teal-200)" }}>
              {row.liters} L
            </span>
            <span style={{
              flex: cols[5].flex, fontSize: 12.5,
            }}>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "4px 10px",
                borderRadius: 999,
                border: "1px solid var(--n-line-strong)",
                background: row.trigger === "Manuell" ? "var(--n-paused-soft)" : "rgba(255,255,255,0.02)",
                color: row.trigger === "Manuell" ? "var(--n-paused)" : "var(--n-fg-muted)",
                fontSize: 11.5,
                fontWeight: 500,
              }}>
                {row.trigger === "Manuell" ? <IPlay size={11} /> : <IClock size={11} />}
                {row.trigger}
              </span>
            </span>
          </div>
        ))}
      </div>
    </ScreenShell>
  );
};

// ═══════════════════════════════════════════════════════════════
//  SETTINGS screen
// ═══════════════════════════════════════════════════════════════

const SettingsSection = ({ title, children }) => (
  <div style={{
    display: "flex", flexDirection: "column", gap: 0,
    border: "1px solid var(--n-line)",
    borderRadius: "var(--n-r-lg)",
    overflow: "hidden",
  }}>
    <div style={{
      padding: "14px 20px",
      background: "rgba(255,255,255,0.015)",
      borderBottom: "1px solid var(--n-line)",
    }}>
      <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.01em" }}>{title}</span>
    </div>
    {children}
  </div>
);

const SettingsRow = ({ label, children, last = false }) => (
  <div style={{
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "12px 20px",
    borderBottom: last ? "none" : "1px solid var(--n-line)",
    minHeight: 52,
  }}>
    <span style={{ fontSize: 14, color: "var(--n-fg-soft)" }}>{label}</span>
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      {children}
    </div>
  </div>
);

const NumInput = ({ value, unit, width = 72 }) => (
  <div style={{
    display: "flex", alignItems: "center", gap: 0,
    background: "var(--n-card-elev)",
    border: "1px solid var(--n-line-strong)",
    borderRadius: "var(--n-r-sm)",
    overflow: "hidden",
    height: 36,
  }}>
    <input
      type="number"
      defaultValue={value}
      style={{
        width: width,
        height: "100%",
        padding: "0 10px",
        background: "transparent",
        border: "none",
        color: "var(--n-fg)",
        fontSize: 14,
        fontFamily: "var(--n-sans)",
        fontVariantNumeric: "tabular-nums",
        textAlign: "right",
        outline: "none",
      }}
    />
    {unit && (
      <span style={{
        padding: "0 8px",
        color: "var(--n-fg-muted)",
        fontSize: 12,
        borderLeft: "1px solid var(--n-line)",
        height: "100%",
        display: "flex",
        alignItems: "center",
        background: "rgba(255,255,255,0.015)",
      }}>
        {unit}
      </span>
    )}
  </div>
);

const CheckToggle = ({ label, defaultChecked = false }) => (
  <label style={{
    display: "flex", alignItems: "center", gap: 8,
    cursor: "pointer", fontSize: 13, color: "var(--n-fg-muted)",
    userSelect: "none",
  }}>
    <input
      type="checkbox"
      defaultChecked={defaultChecked}
      style={{
        width: 16, height: 16,
        accentColor: "var(--n-teal-400)",
        cursor: "pointer",
      }}
    />
    {label}
  </label>
);

const NaiadSettingsScreen = ({ theme = "dark", embed = false }) => {
  return (
    <ScreenShell active="settings" theme={theme} embed={embed} title="Einstellungen">
      <div style={{ maxWidth: 900, display: "flex", flexDirection: "column", gap: 22 }}>

        {/* Sequenzen */}
        <SettingsSection title="Sequenzen">
          {NAIAD_DATA.sequences.map((s, i) => (
            <SettingsRow
              key={s.id}
              label={
                <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 4, height: 22, borderRadius: 2, background: s.color }} />
                  <span style={{ fontWeight: 500, color: "var(--n-fg)" }}>{s.name}</span>
                </span>
              }
              last={i === NAIAD_DATA.sequences.length - 1}
            >
              <NumInput value={s.perZone || 5} unit="min" />
              <CheckToggle label="Pause" />
            </SettingsRow>
          ))}
        </SettingsSection>

        {/* Temperatur-Faktor */}
        <SettingsSection title="Temperatur-Faktor">
          <SettingsRow label="Basis °C">
            <NumInput value={20} unit="°C" />
          </SettingsRow>
          <SettingsRow label="% pro °C">
            <NumInput value={7} unit="%" />
          </SettingsRow>
          <SettingsRow label="Min %">
            <NumInput value={80} unit="%" />
          </SettingsRow>
          <SettingsRow label="Max %" last>
            <NumInput value={150} unit="%" />
          </SettingsRow>
        </SettingsSection>

        {/* Regen-Faktor */}
        <SettingsSection title="Regen-Faktor">
          <SettingsRow label="Schwelle Prob %">
            <NumInput value={70} unit="%" />
          </SettingsRow>
          <SettingsRow label="Reduz. ab mm">
            <NumInput value={5} unit="mm" />
          </SettingsRow>
          <SettingsRow label="Null ab mm">
            <NumInput value={20} unit="mm" />
          </SettingsRow>
          <SettingsRow label="Forecast Decay" last>
            <NumInput value={0.5} unit="" width={60} />
          </SettingsRow>
        </SettingsSection>

        {/* System */}
        <SettingsSection title="System">
          <SettingsRow label="Firmware-Version">
            <span className="mono" style={{ fontSize: 13, color: "var(--n-fg-muted)" }}>v2.4.1</span>
          </SettingsRow>
          <SettingsRow label="MQTT Broker">
            <span className="mono" style={{ fontSize: 13, color: "var(--n-teal-200)" }}>mqtt://192.168.1.40:1883</span>
          </SettingsRow>
          <SettingsRow label="HA Integration">
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "4px 10px", borderRadius: 999,
              border: "1px solid rgba(94,200,216,0.30)",
              background: "var(--n-teal-glow)",
              color: "var(--n-teal-200)",
              fontSize: 12, fontWeight: 500,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--n-teal-300)" }} />
              Verbunden
            </span>
          </SettingsRow>
          <SettingsRow label="Log-Level" last>
            <select
              defaultValue="info"
              style={{
                height: 36, padding: "0 12px",
                background: "var(--n-card-elev)",
                border: "1px solid var(--n-line-strong)",
                borderRadius: "var(--n-r-sm)",
                color: "var(--n-fg)",
                fontSize: 13,
                fontFamily: "var(--n-sans)",
                outline: "none",
                cursor: "pointer",
              }}
            >
              <option value="debug">Debug</option>
              <option value="info">Info</option>
              <option value="warn">Warn</option>
              <option value="error">Error</option>
            </select>
          </SettingsRow>
        </SettingsSection>

      </div>
    </ScreenShell>
  );
};

Object.assign(window, {
  NaiadPlannerScreen, NaiadHistoryScreen, NaiadSettingsScreen,
  ScreenShell, SettingsSection, SettingsRow, NumInput, CheckToggle,
});
