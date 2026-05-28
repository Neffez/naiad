// naiad-dialog.jsx — Confirm dialog for "Sofort starten" + isolated component artboards

// ---------- Confirm dialog ----------

const ConfirmStartDialog = ({ seq, theme = "dark" }) => {
  const [durationOverride, setDurationOverride] = useState(seq.perZone || 42);
  const baseDuration = seq.perZone || 42;
  const zones = seq.zones || 3;
  const factor = seq.factor / 100 || 1.05;
  const estLiters = Math.round(zones * durationOverride * 7.7); // ~7.7 L/min/zone
  const factorBoost = Math.round((factor - 1) * 100);

  return (
    <div
      className="naiad"
      data-theme={theme}
      style={{
        width: 560, height: 720,
        background: "var(--n-bg)",
        position: "relative",
        overflow: "hidden",
        borderRadius: 18,
      }}
    >
      {/* faint dashboard hint behind */}
      <div style={{
        position: "absolute", inset: 0, opacity: 0.35, pointerEvents: "none",
      }}>
        <div style={{
          position: "absolute", top: 24, left: 24, right: 24,
          height: 56, borderRadius: 12, background: "var(--n-card)",
          border: "1px solid var(--n-line)",
        }} />
        <div style={{
          position: "absolute", top: 96, left: 24, right: 24, bottom: 24,
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
        }}>
          {[...Array(6)].map((_, i) => (
            <div key={i} style={{ background: "var(--n-card)", border: "1px solid var(--n-line)", borderRadius: 12 }} />
          ))}
        </div>
      </div>

      <div className="n-backdrop" />

      {/* dialog body */}
      <div className="n-dialog" style={{
        position: "absolute", left: "50%", top: "50%",
        transform: "translate(-50%, -50%)",
        width: 460,
        padding: 24,
        display: "flex", flexDirection: "column", gap: 18,
      }}>
        {/* head */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span className="n-eyebrow">Sofort starten</span>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 4, height: 28, background: seq.color, borderRadius: 2 }} />
              <span style={{ fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em" }}>{seq.name}</span>
            </div>
            <span className="n-label" style={{ fontSize: 12.5 }}>
              {seq.schedule} · regulär {seq.zones} × {seq.perZone} min
            </span>
          </div>
          <button className="n-iconbtn" style={{ width: 40, height: 40 }} title="Abbrechen">
            <IX size={16} />
          </button>
        </div>

        <div className="n-divider" />

        {/* summary line */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 0,
          padding: "10px 0",
          borderRadius: 12,
          background: "rgba(255,255,255,0.015)",
          border: "1px solid var(--n-line)",
        }}>
          <SummaryStat label="Zonen" value={zones} unit="" />
          <SummaryStat label="Je Zone" value={durationOverride} unit="min" highlight={durationOverride !== baseDuration} />
          <SummaryStat label="Wasser" value={estLiters} unit="L" mono />
        </div>

        {/* duration override slider */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span className="n-eyebrow">Dauer-Override</span>
            <button
              onClick={() => setDurationOverride(baseDuration)}
              style={{
                background: "transparent", border: 0, padding: 0, cursor: "pointer",
                color: "var(--n-fg-muted)", fontSize: 11.5,
                textDecoration: durationOverride !== baseDuration ? "underline" : "none",
              }}
            >
              Auf {baseDuration} min zurücksetzen
            </button>
          </div>
          <input
            type="range"
            min="5" max="90" step="5"
            value={durationOverride}
            onChange={(e) => setDurationOverride(+e.target.value)}
            className="n-slider"
            style={{ "--p": `${((durationOverride - 5) / 85) * 100}%` }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", color: "var(--n-fg-muted)", fontSize: 11 }}>
            <span className="mono">5 min</span>
            <span className="mono" style={{ color: "var(--n-fg)" }}>{durationOverride} min</span>
            <span className="mono">90 min</span>
          </div>
        </div>

        {/* warnings / context */}
        <div style={{
          display: "flex", alignItems: "flex-start", gap: 10,
          padding: "10px 12px",
          background: "var(--n-teal-glow)",
          border: "1px solid rgba(94,200,216,0.20)",
          borderRadius: 10,
          color: "var(--n-fg-soft)",
        }}>
          <span style={{ color: "var(--n-teal-300)", marginTop: 1 }}>
            <IGauge size={16} />
          </span>
          <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            Anpassungsfaktor <span className="mono" style={{ color: "var(--n-teal-200)" }}>+{factorBoost} %</span> wird
            <strong style={{ color: "var(--n-fg)", fontWeight: 500 }}> nicht </strong>
            angewendet — Sofortstart läuft mit eingestellter Dauer.
          </div>
        </div>

        {/* actions */}
        <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
          <button className="n-btn ghost lg" style={{ flex: 1 }}>Abbrechen</button>
          <button className="n-btn primary lg" style={{ flex: 1.4 }}>
            <IPlay size={14} />
            Jetzt starten
          </button>
        </div>
      </div>
    </div>
  );
};

const SummaryStat = ({ label, value, unit, mono, highlight }) => (
  <div style={{
    display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
    borderRight: "1px solid var(--n-line)",
    padding: "4px 8px",
  }}>
    <span className="n-eyebrow" style={{ fontSize: 9.5 }}>{label}</span>
    <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
      <span className={mono ? "mono" : "n-bignum"} style={{
        fontSize: mono ? 18 : 24, fontWeight: mono ? 500 : 400, color: highlight ? "var(--n-teal-200)" : "var(--n-fg)",
      }}>{value}</span>
      {unit && <span style={{ fontSize: 11, color: "var(--n-fg-muted)" }}>{unit}</span>}
    </div>
  </div>
);

// ---------- Sequence-card states artboard ----------

const SequenceStates = ({ theme = "dark" }) => {
  const variants = [
    {
      ...NAIAD_DATA.sequences[3], // hochbeet running
      _heading: "running",
      _desc: "live, mit Restzeit + Fortschritt",
    },
    {
      ...NAIAD_DATA.sequences[0], // beete idle
      _heading: "idle",
      _desc: "nächster Lauf + Anpassungsfaktor",
    },
    {
      // synthesise paused
      id: "rasen-p", name: "Rasen", status: "paused", schedule: "Mo + Do 05:00",
      zones: 3, perZone: 40, remaining: 24, total: 40, elapsed: 16,
      factor: 105, color: "#7fc8a8",
      _heading: "paused",
      _desc: "manuell unterbrochen, Restzeit wartet",
    },
    {
      ...NAIAD_DATA.sequences[4], // topf disabled
      _heading: "disabled",
      _desc: "ausgegraut, Quick-Actions inaktiv",
    },
  ];

  return (
    <div className="naiad" data-theme={theme} style={{
      width: 1280, height: 880, padding: 32,
      background: "var(--n-bg)",
      display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "auto 1fr 1fr",
      gap: 22,
    }}>
      <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="n-eyebrow">Komponente</span>
          <span style={{ fontSize: 22, fontWeight: 600 }}>SequenceCard — alle Status (Rich-Variante)</span>
        </div>
        <span className="n-label">Tap-Targets ≥ 56 px · Status-Chip + Farbband + Faktor-Pille + Zonen-Breakdown</span>
      </div>
      {variants.map((v, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span className={"n-chip " + v.status}>
              <span className="n-chip-dot" />
              {v._heading}
            </span>
            <span className="n-label" style={{ fontSize: 11.5 }}>{v._desc}</span>
          </div>
          <SequenceCard seq={v} size="rich" />
        </div>
      ))}
    </div>
  );
};

// ---------- Valve grid artboard ----------

const ValveGridArtboard = ({ theme = "dark" }) => {
  // demo: also show a paused valve
  const demo = NAIAD_DATA.valves.map((v, i) => i === 4 ? { ...v, state: "paused" } : v);
  return (
    <div className="naiad" data-theme={theme} style={{
      width: 1020, height: 820, padding: 28,
      background: "var(--n-bg)",
      display: "flex", flexDirection: "column", gap: 22,
    }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="n-eyebrow">Komponente</span>
          <span style={{ fontSize: 22, fontWeight: 600 }}>ValveGrid · 8 Ventile</span>
        </div>
        <span className="n-label">Türkis-pulsierend = aktiv · Bernstein = pausiert · Grau = aus</span>
      </div>

      {/* 8×1 */}
      <div>
        <span className="n-eyebrow" style={{ marginBottom: 10, display: "block" }}>8 × 1 (Schmal-Layout)</span>
        <ValveGrid cols={8} valves={demo} dense />
      </div>

      {/* 4×2 */}
      <div>
        <span className="n-eyebrow" style={{ marginBottom: 10, display: "block" }}>4 × 2 (Standard)</span>
        <ValveGrid cols={4} valves={demo} />
      </div>

      {/* 2×4 */}
      <div style={{ display: "flex", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <span className="n-eyebrow" style={{ marginBottom: 10, display: "block" }}>2 × 4 (Mobile)</span>
          <ValveGrid cols={2} valves={demo.slice(0, 6)} />
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start", paddingTop: 24 }}>
          <span className="n-eyebrow">Legende</span>
          <ValveLegend />
        </div>
      </div>
    </div>
  );
};

const ValveLegend = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    {[
      { state: "on",       label: "live · Wasserfluss aktiv" },
      { state: "paused",   label: "pausiert · wartet auf Resume" },
      { state: "off",      label: "aus · idle" },
      { state: "disabled", label: "deaktiviert · in Config aus" },
    ].map(({state, label}) => (
      <div key={state} style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className={"n-valve " + state} style={{
          width: 40, height: 40, minHeight: 0, padding: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <span className="led" />
        </div>
        <span style={{ fontSize: 12.5, color: "var(--n-fg-soft)" }}>{label}</span>
      </div>
    ))}
  </div>
);

Object.assign(window, { ConfirmStartDialog, SequenceStates, ValveGridArtboard });
