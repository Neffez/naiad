// naiad-tablet.jsx — Visu-Touchscreen dashboard (1920×1080 landscape, no scroll)

const NaiadTabletDashboard = ({ theme = "dark", embed = false }) => {
  const [masterOn, setMasterOn] = useState(true);
  const [emergencyArmed, setEmergencyArmed] = useState(false);

  return (
    <div
      className="naiad"
      data-theme={theme}
      style={{
        width: 1920, height: 1080,
        display: "flex",
        background: "var(--n-bg)",
        color: "var(--n-fg)"
      }}>
      
      {/* sidebar - hidden in embed (HA sidebar takes over) */}
      {!embed && <TabletSidebar active="dashboard" />}

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Top bar */}
        <header className="n-wavebed" style={{
          height: 88, padding: "0 36px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          borderBottom: "1px solid var(--n-line)",
          flex: "0 0 88px",
          gap: 24,
          position: "relative"
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 28, minWidth: 0 }}>
            {embed && <NaiadMark size={26} />}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span className="n-eyebrow">Übersicht</span>
              <span style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em" }}>Garten</span>
            </div>
            <div className="n-vdivider" style={{ height: 40 }} />
            <WeatherStrip />
            {NAIAD_DATA.weather.notes &&
            <>
                <div className="n-vdivider" style={{ height: 28 }} />
                <span style={{
                fontSize: 12.5, color: "var(--n-paused)",
                display: "inline-flex", alignItems: "center", gap: 8,
                padding: "6px 10px", borderRadius: 8,
                background: "var(--n-paused-soft)",
                border: "1px solid rgba(217,166,72,0.25)"
              }}>
                  <IAlert size={14} />
                  {NAIAD_DATA.weather.notes}
                </span>
              </>
            }
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
              <span className="mono" style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>21:46</span>
              <span style={{ fontSize: 11.5, color: "var(--n-fg-muted)" }}>Mi · 27. Mai · KW 22</span>
            </div>
            <div className="n-vdivider" style={{ height: 40 }} />
            <MasterToggle on={masterOn} onToggle={() => setMasterOn(!masterOn)} />
            <EmergencyStop
              armed={emergencyArmed}
              onArm={() => setEmergencyArmed(true)}
              onFire={() => {setEmergencyArmed(false);setMasterOn(false);}} />
            
          </div>
        </header>

        {/* Main grid — 3 columns, fills 992px tall */}
        <main style={{
          flex: 1, padding: "22px 36px 28px",
          display: "grid",
          gridTemplateColumns: "360px 1fr 500px",
          gap: 22,
          minHeight: 0
        }}>
          {/* col 1 — Today + week summary */}
          <div style={{ display: "flex", flexDirection: "column", gap: 22, minHeight: 0 }}>
            <TodayBlockRich />
          </div>

          {/* col 2 — sequence grid 2×3 (rich cards) */}
          <section style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "0 2px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span className="n-eyebrow">Sequenzen</span>
                <span style={{ fontSize: 16, fontWeight: 500 }}>5 konfiguriert</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 12.5 }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--n-teal-200)" }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--n-teal-300)" }} />
                  1 läuft
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--n-fg-muted)" }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--n-fg-dim)" }} />
                  3 bereit
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--n-fg-dim)" }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--n-fg-dim)" }} />
                  1 aus
                </span>
              </div>
            </div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gridAutoRows: "1fr",
              gap: 14,
              flex: 1, minHeight: 0
            }}>
              {NAIAD_DATA.sequences.map((s) =>
              <SequenceCard key={s.id} seq={s} size="rich" />
              )}
              <AddSequenceTile />
            </div>
          </section>

          {/* col 3 — Valves + chart */}
          <section style={{ display: "flex", flexDirection: "column", gap: 18, minHeight: 0 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span className="n-eyebrow">Ventile · Live</span>
                  <span style={{ fontSize: 16, fontWeight: 500 }}>8 Zonen</span>
                </div>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--n-teal-200)", fontSize: 12.5 }}>
                  <span className="n-drop" />
                  1 live · 142 L heute
                </span>
              </div>
              <ValveGrid cols={2} />
            </div>

            <div className="n-card" style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12, flex: 1, minHeight: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span className="n-eyebrow">Verbrauch · 7 Tage</span>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                    <span className="mono" style={{ fontSize: 22, fontWeight: 500 }}>1.847 L</span>
                    <span style={{ fontSize: 11.5, color: "var(--n-teal-300)" }}>+12 % vs. KW 21</span>
                  </div>
                </div>
                <span className="mono" style={{ fontSize: 11, color: "var(--n-fg-muted)" }}>L / Tag</span>
              </div>
              <WeekBars height={150} />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, paddingTop: 4 }}>
                {NAIAD_DATA.sequences.map((s) =>
                <span key={s.id} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 11.5, color: "var(--n-fg-muted)" }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
                    {s.name}
                  </span>
                )}
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>);

};

// ---- supporting pieces for the rich layout ----

const TabletSidebar = ({ active }) =>
<div className="n-side" style={{
  width: 80, display: "flex", flexDirection: "column", alignItems: "center",
  padding: "24px 0", gap: 8
}}>
    <div style={{ marginBottom: 12 }}><ILogo size={30} /></div>
    {[
  { id: "dashboard", icon: <IHome size={22} />, label: "Übersicht" },
  { id: "plan", icon: <ICal size={22} />, label: "Planen" },
  { id: "history", icon: <IChart size={22} />, label: "Verlauf" },
  { id: "settings", icon: <ISettings size={22} />, label: "Einstellungen" }].
  map((item) =>
  <button key={item.id} className={"n-iconbtn" + (active === item.id ? " accent" : "")}
  style={{ width: 56, height: 56 }} title={item.label}>
        {item.icon}
      </button>
  )}
    <div style={{ flex: 1 }} />
    <button className="n-iconbtn" style={{ width: 56, height: 56 }} title="Theme">
      <IMoon size={20} />
    </button>
  </div>;


const TodayBlockRich = () => {
  const t = NAIAD_DATA.today;
  return (
    <div className="n-card" style={{ padding: "22px 24px", display: "flex", flexDirection: "column", gap: 16, position: "relative", overflow: "hidden", flex: 1 }}>
      <div className="n-ambient-waves" />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="n-eyebrow">Nächste Bewässerungen</span>
      </div>

      {/* Next run — PRIMARY, highlighted card */}
      <div style={{
        padding: "14px 16px", borderRadius: 12,
        background: "var(--n-teal-glow)",
        border: "1px solid rgba(94,200,216,0.15)",
        display: "flex", flexDirection: "column", gap: 6
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.015em" }}>{t.next.seq}</span>
          <span className="mono" style={{ fontSize: 13, color: "var(--n-teal-300)", fontWeight: 500 }}>
            {t.next.relative}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <span className="mono" style={{ fontSize: 18, color: "var(--n-teal-200)", fontWeight: 500 }}>
            {t.next.when}
          </span>
          <span className="mono" style={{ fontSize: 14, color: "var(--n-fg-soft)" }}>{t.next.duration}</span>
        </div>
      </div>

      {/* After — secondary */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "10px 14px",
        background: "rgba(255,255,255,0.018)",
        border: "1px solid var(--n-line)",
        borderRadius: 10
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span className="n-eyebrow" style={{ fontSize: 9.5 }}>Danach</span>
          <span style={{ fontSize: 16, fontWeight: 500 }}>{t.after.seq}</span>
        </div>
        <span className="mono" style={{ fontSize: 13, color: "var(--n-fg-muted)" }}>
          {t.after.when} · {t.after.duration}
        </span>
      </div>

      <div style={{ flex: 1 }} />
      <div className="n-divider" />

      {/* Adjustment factor — compact / tertiary */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="n-eyebrow">Anpassung</span>
            <span style={{ fontSize: 10, color: "var(--n-teal-300)", display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--n-teal-300)" }} />
              auto
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {t.breakdown.map((b, i) =>
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5 }}>
                <span style={{ color: "var(--n-fg-soft)", minWidth: 80 }}>{b.label}</span>
                <span className="mono" style={{
                color: b.positive === false ? "var(--n-paused)" :
                b.positive === true ? "var(--n-leaf-300)" : "var(--n-fg-muted)",
                fontWeight: 500
              }}>{b.delta}</span>
              </div>
            )}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 2 }}>
          <span className="n-bignum" style={{
            fontSize: 42, color: "var(--n-teal-200)",
            letterSpacing: "-0.03em", fontFamily: "Helvetica Neue", lineHeight: 1
          }}>
            {t.factor}
          </span>
          <span style={{ fontSize: 16, color: "var(--n-fg-muted)", fontFamily: "var(--n-serif)" }}>%</span>
        </div>
      </div>
    </div>);

};



const AddSequenceTile = () =>
<button style={{
  height: "100%", width: "100%",
  background: "transparent",
  border: "1.5px dashed var(--n-line-strong)",
  borderRadius: 14,
  color: "var(--n-fg-muted)",
  display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
  gap: 10, cursor: "pointer",
  transition: "all 120ms var(--n-ease)",
  minHeight: 200
}}
onMouseOver={(e) => {e.currentTarget.style.borderColor = "var(--n-teal-500)";e.currentTarget.style.color = "var(--n-teal-200)";}}
onMouseOut={(e) => {e.currentTarget.style.borderColor = "var(--n-line-strong)";e.currentTarget.style.color = "var(--n-fg-muted)";}}>
  
    <div style={{
    width: 44, height: 44, borderRadius: "50%",
    border: "1.5px dashed currentColor",
    display: "flex", alignItems: "center", justifyContent: "center"
  }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M12 5v14M5 12h14" />
      </svg>
    </div>
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <span style={{ fontSize: 14, fontWeight: 500 }}>Neue Sequenz</span>
      <span style={{ fontSize: 11.5, color: "var(--n-fg-muted)" }}>Zonen, Zeitplan, Anpassung</span>
    </div>
  </button>;


window.NaiadTabletDashboard = NaiadTabletDashboard;