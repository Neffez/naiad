// naiad-data.jsx — mock data + helpers, shared across all artboards

// Each sequence carries: id, name, status, factor%, zones, todayDurationMin per zone,
// schedule label, color, and (if running) remaining seconds + elapsed.

const NAIAD_DATA = {
  master: true,
  weather: {
    temp: 24,
    rain24h: 2,
    wind: "ruhig",
    season: "Sommer",
    notes: "Wind blockt Rasen-Sequenz seit 06:14",
  },
  today: {
    factor: 105,
    breakdown: [
      { label: "Temperatur", delta: "+5 %", positive: true },
      { label: "Regen",      delta: "±0 %", positive: null },
      { label: "Wind",       delta: "Rasen blockiert", positive: false },
    ],
    next: {
      when: "Heute 22:00",
      relative: "in 2 h 14 min",
      seq: "Hochbeet",
      duration: "15 min",
    },
    after: {
      when: "Morgen 05:00",
      seq: "Lichtschacht",
      duration: "45 min",
    },
    litersToday: 142,
    litersWeek: 1847,
  },
  sequences: [
    {
      id: "beete",
      name: "Beete",
      status: "idle",
      schedule: "Mi 04:00",
      next: "Mi 04:00",
      zones: 2,
      perZone: 90,
      factor: 105,
      color: "#5ec8d8",
    },
    {
      id: "rasen",
      name: "Rasen",
      status: "idle",
      schedule: "Mo + Do 05:00",
      next: "Do 05:00",
      zones: 3,
      perZone: 40,
      factor: 0,
      factorNote: "Wind blockt",
      color: "#7fc8a8",
    },
    {
      id: "lichtschacht",
      name: "Lichtschacht",
      status: "idle",
      schedule: "Di + Fr 05:00",
      next: "Morgen 05:00",
      zones: 1,
      perZone: 45,
      factor: 105,
      color: "#9aa9c8",
    },
    {
      id: "hochbeet",
      name: "Hochbeet",
      status: "running",
      schedule: "täglich 22:00",
      zones: 1,
      perZone: 15,
      elapsed: 7,        // min
      remaining: 8,      // min
      total: 15,
      factor: 105,
      color: "#d6b56a",
    },
    {
      id: "topf",
      name: "Topfpflanzen",
      status: "disabled",
      schedule: "—",
      zones: 1,
      perZone: 0,
      factor: 0,
      color: "#6d7a7e",
      note: "Topf disabled",
    },
  ],
  valves: [
    { id: "v1", name: "Hochbeet",            state: "on",       runtime: "7 min" },
    { id: "v2", name: "Rasen Mitte",         state: "off" },
    { id: "v3", name: "Rasen Südwesten",     state: "off" },
    { id: "v4", name: "Rasen Norden",        state: "off" },
    { id: "v5", name: "Beete Ost",           state: "off" },
    { id: "v6", name: "Beete Süd/West",      state: "off" },
    { id: "v7", name: "Lichtschacht + Terr.", state: "off" },
    { id: "v8", name: "Topfpflanzen",        state: "off" },
  ],
  // 7-day stacked liters per sequence (Mo–So), in liters
  // Index order matches sequences[0..4]
  week: [
    { day: "Mo", parts: [0, 412, 0, 16, 0],     total: 428 },
    { day: "Di", parts: [0, 0, 178, 16, 0],     total: 194 },
    { day: "Mi", parts: [338, 0, 0, 16, 0],     total: 354 },
    { day: "Do", parts: [0, 380, 0, 16, 0],     total: 396 },
    { day: "Fr", parts: [0, 0, 178, 16, 0],     total: 194 },
    { day: "Sa", parts: [0, 0, 0, 16, 0],       total: 16 },
    { day: "So", parts: [0, 0, 0, 16, 0],       total: 16, today: true,
                                                 // partial — only 142 L so far today,
                                                 // but show today=142 L total
      override: { parts: [0, 0, 0, 142, 0], total: 142 } },
  ],
};

// helpers
function n_statusLabel(s) {
  return { idle: "Bereit", running: "Läuft", paused: "Pausiert", disabled: "Deaktiviert" }[s] || s;
}

function n_seqLiters(seq) {
  if (seq.status === "disabled") return 0;
  return seq.zones * seq.perZone * Math.max(seq.factor, 1) * 0.0667; // ~rough L/min
}

window.NAIAD_DATA = NAIAD_DATA;
window.n_statusLabel = n_statusLabel;
window.n_seqLiters = n_seqLiters;
