// naiad-mobile.jsx — Smartphone dashboard (390×844 portrait)

const NaiadMobileDashboard = ({ theme = "dark" }) => {
  const [masterOn, setMasterOn] = useState(true);
  const [emergencyArmed, setEmergencyArmed] = useState(false);

  return (
    <div
      className="naiad"
      data-theme={theme}
      style={{
        width: 430, height: 932,
        display: "flex", flexDirection: "column",
        background: "var(--n-bg)",
      }}
    >
      {/* status bar */}
      <div style={{
        height: 44, padding: "0 22px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        fontSize: 14, fontWeight: 600,
      }} className="mono">
        <span>21:46</span>
        <span style={{ color: "var(--n-fg-muted)" }}>● ● ● ●</span>
      </div>

      {/* header */}
      <header className="n-wavebed" style={{
        padding: "8px 20px 16px",
        display: "flex", flexDirection: "column", gap: 14,
        position: "relative",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <NaiadMark size={24} />
          <button className="n-iconbtn" style={{ width: 40, height: 40 }} title="Profil">
            <ISettings size={17} />
          </button>
        </div>

        {/* master row */}
        <div style={{ display: "flex", gap: 10, alignItems: "stretch" }}>
          <div style={{ flex: 1 }}>
            <button
              className={"n-master" + (masterOn ? "" : " off")}
              onClick={() => setMasterOn(!masterOn)}
              style={{ width: "100%", justifyContent: "flex-start", height: 56, gap: 14, paddingLeft: 8 }}
            >
              <span className="knob" />
              <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1, alignItems: "flex-start" }}>
                <span className="n-eyebrow">System</span>
                <span style={{ fontSize: 15, fontWeight: 500 }}>{masterOn ? "Aktiv" : "Aus"}</span>
              </div>
            </button>
          </div>
          <button
            className="n-btn danger"
            onClick={() => emergencyArmed ? (setMasterOn(false), setEmergencyArmed(false)) : setEmergencyArmed(true)}
            style={{ height: 56, padding: "0 18px", flexDirection: "column", gap: 2 }}
            title="Notaus"
          >
            <IAlert size={16} />
            <span style={{ fontSize: 11 }}>{emergencyArmed ? "Bestätigen" : "Notaus"}</span>
          </button>
        </div>

        <WeatherStrip compact />
      </header>

      {/* scroll body */}
      <main style={{
        flex: 1, overflowY: "auto", padding: "0 20px 20px",
        display: "flex", flexDirection: "column", gap: 14,
        scrollbarWidth: "none",
      }}>
        {/* Today block — next runs primary, adjustment secondary */}
        <div className="n-card" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Next run — PRIMARY */}
          <div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span className="n-eyebrow">Nächster Lauf</span>
              <span className="mono" style={{ fontSize: 12, color: "var(--n-teal-300)", fontWeight: 500 }}>
                {NAIAD_DATA.today.next.relative}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginTop: 6 }}>
              <span style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" }}>{NAIAD_DATA.today.next.seq}</span>
              <span className="mono" style={{ fontSize: 14, color: "var(--n-fg-soft)" }}>{NAIAD_DATA.today.next.duration}</span>
            </div>
            <span className="mono" style={{ fontSize: 14, color: "var(--n-teal-200)", marginTop: 2, display: "block" }}>
              {NAIAD_DATA.today.next.when}
            </span>
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--n-line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <span className="n-eyebrow" style={{ fontSize: 9 }}>Danach</span>
                <span style={{ fontSize: 14, color: "var(--n-fg-soft)", fontWeight: 500 }}>{NAIAD_DATA.today.after.seq}</span>
              </div>
              <span className="mono" style={{ fontSize: 12, color: "var(--n-fg-muted)" }}>
                {NAIAD_DATA.today.after.when} · {NAIAD_DATA.today.after.duration}
              </span>
            </div>
          </div>

          <div className="n-divider" />

          {/* Adjustment — SECONDARY */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="n-eyebrow">Anpassung</span>
                <span style={{ fontSize: 10, color: "var(--n-teal-300)", display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--n-teal-300)" }} />
                  auto
                </span>
              </div>
              {NAIAD_DATA.today.breakdown.map((b, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5 }}>
                  <span style={{ color: "var(--n-fg-muted)" }}>{b.label}</span>
                  <span className="mono" style={{
                    color: b.positive === false ? "var(--n-paused)" :
                           b.positive === true  ? "var(--n-leaf-300)" : "var(--n-fg-soft)",
                  }}>{b.delta}</span>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 2 }}>
              <span className="n-bignum" style={{ fontSize: 36, color: "var(--n-teal-200)", lineHeight: 1 }}>
                {NAIAD_DATA.today.factor}
              </span>
              <span style={{ fontSize: 16, color: "var(--n-fg-muted)" }}>%</span>
            </div>
          </div>
        </div>

        {/* Sequences */}
        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "0 2px" }}>
            <span className="n-eyebrow">Sequenzen</span>
            <span className="n-label" style={{ fontSize: 11 }}>
              <span style={{ color: "var(--n-teal-200)" }}>1 läuft</span> · 3 bereit
            </span>
          </div>
          {NAIAD_DATA.sequences.map(s => (
            <SequenceCard key={s.id} seq={s} />
          ))}
        </section>

        {/* Valves */}
        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "0 2px" }}>
            <span className="n-eyebrow">Ventile</span>
            <span className="n-label" style={{ fontSize: 11, color: "var(--n-teal-200)" }}>1 live</span>
          </div>
          <ValveGrid cols={2} />
        </section>

        {/* Week chart */}
        <div className="n-card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
            <div>
              <span className="n-eyebrow">Verbrauch</span>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4 }}>
                <span className="n-bignum" style={{ fontSize: 26 }}>1.847 L</span>
                <span style={{ fontSize: 12, color: "var(--n-fg-muted)" }}>diese Woche</span>
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <span className="mono" style={{ fontSize: 14, color: "var(--n-teal-200)" }}>142 L</span>
              <div className="n-label" style={{ fontSize: 11 }}>heute</div>
            </div>
          </div>
          <WeekBars height={100} />
        </div>
      </main>

      <BottomNav active="dashboard" />
    </div>
  );
};

window.NaiadMobileDashboard = NaiadMobileDashboard;
