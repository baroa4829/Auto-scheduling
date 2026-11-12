const pptxgen = require("pptxgenjs");
const out = process.argv[2];

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 (16:9)
pres.theme = { headFontFace: "Malgun Gothic", bodyFontFace: "Malgun Gothic" };
pres.title = "A→B mask 회로 변경점 분석";

const F = "Malgun Gothic";
const NAVY = "1F2A44", INK = "2B2F36", MUTED = "6B7280", LINE = "C9D1DA";
const PANEL = "F3F5F8", SIM = "9AA5B1", MEAS = "0F7C80", BAD = "C8102E", OK = "0F7C80";
const CHG = "E07A1F"; // changed-block accent

const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const T = (text, o) => s.addText(text, Object.assign({ isTextBox: true, fontFace: F, color: INK, margin: 0 }, o));

// ---------- Header ----------
T("예시 · 가상 데이터", { x: 0.45, y: 0.22, w: 1.5, h: 0.26, fontSize: 10, color: "FFFFFF", bold: true,
  align: "center", valign: "middle", shape: pres.ShapeType.roundRect, rectRadius: 0.06, fill: { color: MUTED } });
T("VREF 버퍼 A→B mask 변경점 분석 · 모드별 DC level 검증", { x: 2.1, y: 0.2, w: 10.8, h: 0.3, fontSize: 12, color: MUTED });
T([
  { text: "모드별 DC 변화는 Sim 예측대로 재현", options: { color: NAVY } },
  { text: " — 단, Standby는 Sim 대비 −8.2 mV 추가 shift", options: { color: BAD } },
], { x: 0.45, y: 0.55, w: 12.45, h: 0.55, fontSize: 22, bold: true, valign: "middle" });
T("판단 기준은 \"값이 바뀌었는가\"가 아니라 \"설계 의도(Sim)만큼 바뀌었는가\" — 변화량(Δ)을 Sim Δ 및 측정 산포(±3σ)와 비교",
  { x: 0.45, y: 1.1, w: 12.45, h: 0.32, fontSize: 13, color: MUTED });

// ---------- Panels ----------
const PY = 1.55, PH = 4.4;
s.addShape(pres.ShapeType.roundRect, { x: 0.45, y: PY, w: 5.95, h: PH, fill: { color: PANEL }, line: { color: PANEL }, rectRadius: 0.08, objectName: "LeftPanel" });
s.addShape(pres.ShapeType.roundRect, { x: 6.6, y: PY, w: 6.3, h: PH, fill: { color: PANEL }, line: { color: PANEL }, rectRadius: 0.08, objectName: "RightPanel" });

const header = (n, text, x) => {
  s.addShape(pres.ShapeType.ellipse, { x, y: PY + 0.15, w: 0.32, h: 0.32, fill: { color: NAVY }, line: { color: NAVY } });
  T(n, { x, y: PY + 0.15, w: 0.32, h: 0.32, fontSize: 12, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  T(text, { x: x + 0.42, y: PY + 0.13, w: 5.4, h: 0.36, fontSize: 15, bold: true, color: NAVY, valign: "middle" });
};
header("1", "회로 변경점 (A-mask → B-mask)", 0.65);
header("2", "모드별 DC level 변화량: Sim 예측 vs 측정", 6.8);

// ---------- Left: block schematic ----------
const box = (label, x, y, w, h, changed, sub) => {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.05,
    fill: { color: changed ? "FDF1E6" : "FFFFFF" }, line: { color: changed ? CHG : "8A94A3", width: changed ? 2 : 1 } });
  T(sub ? [{ text: label, options: { bold: true, breakLine: true } }, { text: sub, options: { fontSize: 9, color: MUTED } }] : label,
    { x, y, w, h, fontSize: 11, bold: !sub, align: "center", valign: "middle" });
};
const ln = (x1, y1, x2, y2, dash) => s.addShape(pres.ShapeType.line, {
  x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
  line: { color: dash ? "8A94A3" : INK, width: dash ? 1 : 1.5, dashType: dash ? "dash" : "solid" } });

// control bus (dashed)
const CY = 2.42;
ln(2.15, CY, 5.75, CY, true);
ln(3.4, CY, 3.4, 3.2, true);
ln(5.75, CY, 5.75, 3.12, true);
box("Mode Decoder", 0.75, 2.17, 1.4, 0.5, false, "Normal / LP / STB");
T("mode ctrl", { x: 4.1, y: CY - 0.24, w: 0.9, h: 0.2, fontSize: 9, color: MUTED });

// main path
ln(2.15, 3.48, 2.6, 3.48);
ln(4.2, 3.48, 5.75, 3.48);
box("I_REF", 0.75, 3.2, 1.4, 0.55);
box("Bias Mirror", 2.6, 3.2, 1.6, 0.55, true, "1 : N (모드별)");
s.addShape(pres.ShapeType.ellipse, { x: 4.53, y: 3.41, w: 0.14, h: 0.14, fill: { color: INK }, line: { color: INK } });
T("VOUT", { x: 4.3, y: 3.12, w: 0.6, h: 0.22, fontSize: 10, bold: true, align: "center" });
// R_L branch
ln(4.6, 3.48, 4.6, 3.9);
box("R_L", 4.3, 3.9, 0.6, 0.36);
T("GND", { x: 4.3, y: 4.3, w: 0.6, h: 0.18, fontSize: 9, color: MUTED, align: "center" });
// Standby branch
box("SW_STB", 5.35, 3.12, 0.8, 0.36, true);
ln(5.75, 3.48, 5.75, 3.9);
box("R_STB", 5.45, 3.9, 0.6, 0.36, true);
T("GND", { x: 5.45, y: 4.3, w: 0.6, h: 0.18, fontSize: 9, color: MUTED, align: "center" });
// change tags
const tag = (t, x, y, w) => T(t, { x, y, w, h: 0.24, fontSize: 9.5, bold: true, color: "FFFFFF", fill: { color: CHG },
  shape: pres.ShapeType.roundRect, rectRadius: 0.05, align: "center", valign: "middle" });
tag("① 변경", 2.6, 3.84, 0.65);
tag("② 신규", 5.35, 2.82, 0.65);

// change table
const th = (t) => ({ text: t, options: { bold: true, color: "FFFFFF", fill: { color: NAVY }, align: "center" } });
const td = (t, o = {}) => ({ text: t, options: Object.assign({ align: "center" }, o) });
s.addTable([
  [th("#"), th("변경 내용"), th("영향 모드"), th("Sim ΔVOUT")],
  [td("①", { color: CHG, bold: true }), td("Bias mirror 비율 N = 4 → 3", { align: "left" }), td("LP"), td("−25.0 mV", { bold: true })],
  [td("②", { color: CHG, bold: true }), td("SW_STB + R_STB 병렬 경로 추가", { align: "left" }), td("Standby"), td("−10.0 mV", { bold: true })],
  [td("–", { color: MUTED }), td("변경 없음 (Control 모드)", { align: "left", color: MUTED }), td("Normal", { color: MUTED }), td("0.0 mV", { color: MUTED })],
], { x: 0.65, y: 4.7, w: 5.55, colW: [0.35, 3.0, 0.95, 1.25], rowH: 0.27, fontFace: F, fontSize: 10, color: INK,
  fill: { color: "FFFFFF" }, border: { type: "solid", pt: 0.5, color: LINE }, valign: "middle", margin: 0.04 });

// ---------- Right: chart ----------
s.addChart(pres.ChartType.bar, [
  { name: "Sim 예측 Δ", labels: ["Normal", "LP", "Standby"], values: [0.0, -25.0, -10.0] },
  { name: "측정 Δ (B−A)", labels: ["Normal", "LP", "Standby"], values: [0.8, -24.3, -18.2] },
], {
  x: 6.75, y: 2.0, w: 6.0, h: 2.35, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60,
  chartColors: [SIM, MEAS], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "+0.0;−0.0;0.0",
  dataLabelFontSize: 10, dataLabelColor: INK, dataLabelFontFace: F,
  valAxisMinVal: -30, valAxisMaxVal: 5, valAxisMajorUnit: 10, valAxisTitle: "ΔVOUT (mV)", showValAxisTitle: true,
  valAxisTitleFontSize: 9, valAxisTitleColor: MUTED, valAxisLabelFontSize: 9, valAxisLabelColor: MUTED,
  catAxisLabelFontSize: 11, catAxisLabelColor: INK, catAxisLabelPos: "high", catAxisLabelFontFace: F,
  valGridLine: { color: "DDE2E8", size: 0.5 }, catGridLine: { style: "none" },
  showLegend: true, legendPos: "t", legendFontSize: 10, legendFontFace: F, legendColor: INK,
  plotArea: { fill: { color: PANEL } }, fill: PANEL,
});
// callout for mismatch
T([{ text: "Gap −8.2 mV", options: { bold: true, breakLine: true } }, { text: "측정 > Sim (3σ 초과)", options: { fontSize: 9 } }],
  { x: 11.3, y: 3.92, w: 1.45, h: 0.4, fontSize: 11, color: BAD, align: "center", valign: "middle",
    fill: { color: "FFFFFF" }, line: { color: BAD, width: 1 }, shape: pres.ShapeType.roundRect, rectRadius: 0.05 });

// data table
const ok = (t) => td(t, { color: OK, bold: true });
const bad = (t) => td(t, { color: BAD, bold: true });
s.addTable([
  [th("모드"), th("A-mask"), th("B-mask"), th("Δ측정"), th("ΔSim"), th("±3σ"), th("판정")],
  [td("Normal"), td("1200.3"), td("1201.1"), td("+0.8"), td("0.0"), td("9.3"), ok("유의차 없음 · 의도대로")],
  [td("LP"), td("1100.5"), td("1076.2"), td("−24.3"), td("−25.0"), td("8.7"), ok("유의차 O · Sim 일치")],
  [td("Standby"), td("1050.2"), td("1032.0"), bad("−18.2"), td("−10.0"), td("9.0"), bad("유의차 O · Sim 불일치")],
], { x: 6.8, y: 4.45, w: 5.9, colW: [0.8, 0.72, 0.72, 0.68, 0.62, 0.55, 1.81], rowH: 0.27, fontFace: F, fontSize: 10, color: INK,
  fill: { color: "FFFFFF" }, border: { type: "solid", pt: 0.5, color: LINE }, valign: "middle", margin: 0.04 });
T("단위 mV · 모드별 n = 30 die (A/B 각 1 lot, 25 ℃) · ±3σ = Δ의 측정 산포 기준", { x: 6.8, y: 5.66, w: 5.9, h: 0.2, fontSize: 9, color: MUTED });

// ---------- Bottom: takeaways ----------
const BY = 6.12, BH = 1.08;
s.addShape(pres.ShapeType.roundRect, { x: 0.45, y: BY, w: 12.45, h: BH, fill: { color: "EAF4F4" }, line: { color: "EAF4F4" }, rectRadius: 0.08, objectName: "Takeaways" });
T("판단\n포인트", { x: 0.6, y: BY, w: 0.85, h: BH, fontSize: 13, bold: true, color: MEAS, valign: "middle", align: "center" });
const cols = [
  ["설계 의도 재현 확인", "Normal(control)은 변화 없음, LP는 Sim 대비 0.7 mV 이내 → 변경 ①은 의도대로 동작"],
  ["Standby 불일치 원인", "Pre-layout Sim이 SW_STB Ron·배선 기생 R 미반영 → PEX Sim −16.9 mV로 Gap 1.3 mV까지 설명"],
  ["Next Step", "Standby DC spec margin 재확인 · 이후 변경점 검증은 PEX Sim 기준으로 통일"],
];
cols.forEach(([h, b], i) => {
  const x = 1.6 + i * 3.8;
  T([{ text: h, options: { bold: true, color: i === 1 ? BAD : NAVY, breakLine: true } }, { text: b, options: { fontSize: 11 } }],
    { x, y: BY + 0.12, w: 3.6, h: BH - 0.24, fontSize: 12.5, valign: "middle", paraSpaceAfter: 2 });
});

s.addNotes("예시 슬라이드(가상 데이터). 메시지: 모드별 DC가 바뀐 것 자체가 아니라, 변화량이 Sim 예측과 일치하는지가 변경점 검증의 핵심. Normal은 control, LP는 일치, Standby는 불일치 → PEX Sim으로 기생 성분이 원인임을 설명.");

pres.writeFile({ fileName: out }).then(() => console.log("wrote", out));
