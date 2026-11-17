"""Scoped conversation styles, using Case Finder's existing type and colors."""
from .theme import register_css

register_css("case360-conversation", """
.c360 {width:100%;
  max-width:1180px;
  margin:0 auto;
  gap:24px;
  color:var(--cf-ink)}
.c360-top {width:100%;
  align-items:center;
  justify-content:space-between;
  gap:12px}
.c360-brand {font-size:18px;
  font-weight:650;
  letter-spacing:-.025em}
.c360-beta {background:#edf2ff;
  color:#3456b0;
  border:1px solid #dce5fc;
  border-radius:6px;
  padding:2px 7px;
  font-size:11px;
  font-weight:650}
.c360-links {gap:18px;
  font-size:12px}
.c360-links a {color:#53637d;
  text-decoration:none}
.c360-heading {font-size:30px;
  font-weight:650;
  letter-spacing:-.035em;
  line-height:1.2;
  margin:8px 0 0}
.c360-subtitle {color:#58667b;
  line-height:1.6;
  max-width:760px}
.c360-steps {display:flex;
  gap:24px;
  width:100%;
  padding:0 0 18px;
  border-bottom:1px solid var(--cf-line);
  font-size:12px;
  color:#6b7280}
.c360-step {display:flex;
  gap:8px;
  align-items:center}
.c360-step-number {width:22px;
  height:22px;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  background:#eef1f6;
  font-size:11px}
.c360-step-active {color:#244fa8;
  font-weight:650}
.c360-step-active .c360-step-number {background:#e8efff;
  color:#244fa8}
.c360-grid {display:grid;
  grid-template-columns:minmax(0,1fr) 280px;
  gap:24px;
  width:100%;
  align-items:start}
.c360-main,.c360-side {min-width:0;
  width:100%;
  gap:18px}
.c360-side {position:sticky;
  top:0;
  gap:16px}
.c360-card {width:100%;
  border:1px solid var(--cf-line);
  border-radius:12px;
  padding:20px;
  background:#fff;
  gap:14px;
  box-shadow:0 2px 6px rgba(20,40,70,.025)}
.c360-side .c360-card {padding:16px;
  background:#fafbfd;
  box-shadow:none}
.c360-eyebrow {font-size:11px;
  letter-spacing:.07em;
  font-weight:650;
  text-transform:uppercase;
  color:#6b7587}
.c360-card-title {font-size:17px;
  font-weight:650;
  letter-spacing:-.015em}
.c360-status {font-size:14px;
  font-weight:550;
  line-height:1.5;
  color:#364c6d}
.c360-status-row {align-items:center;
  gap:9px;
  width:100%}
.c360-budget {font-size:12px;
  line-height:1.6;
  color:#58667b}
.c360-note {padding:10px 12px;
  border-radius:8px;
  background:#eff5ff;
  color:#365a91;
  font-size:12px;
  line-height:1.5;
  width:100%}
.c360-question {width:100%;
  gap:10px;
  padding:16px 0;
  border-bottom:1px solid #edf0f4}
.c360-question:last-child {border-bottom:0}
.c360-question-title {font-size:14px;
  line-height:1.65;
  color:#29374c;
  font-weight:500}
.c360-question-count {font-size:11px;
  color:#61718a;
  font-weight:650;
  letter-spacing:.04em}
.c360 .q-field--outlined .q-field__control {border-radius:8px;
  background:white}
.c360 .q-field--disabled {opacity:1!important}
.c360 .q-field--disabled .q-field__native {color:#334155!important}
.c360 .q-btn {border-radius:7px;
  box-shadow:none;
  font-size:13px;
  min-height:38px}
.c360 .q-btn.bg-primary {background:#2563eb!important}
.c360-actions {width:100%;
  gap:8px;
  align-items:center}
.c360-dialogue {width:100%;
  gap:0}
.c360-continue {width:100%;
  background:white;
  padding-top:16px;
  gap:12px}
.c360-activity-item {font-size:12px;
  color:#52627a;
  line-height:1.6;
  border-left:2px solid #d5e1f8;
  padding-left:10px}
.c360 .q-expansion-item {width:100%;
  font-size:12px}
.c360 .q-item {min-height:36px;
  padding:8px 0}
.c360-source-name {font-size:11px;
  line-height:1.6;
  color:#53637d;
  overflow-wrap:anywhere}
.c360-detail-note {font-size:11px;
  color:#6b7587;
  line-height:1.6}
.c360-output {width:100%;
  min-width:0}
.c360-output:empty,.c360-dialogue:empty,.c360-side .nicegui-column:empty {display:none}
@media(max-width:1100px){.c360-grid{grid-template-columns:minmax(0,1fr) 230px;
  gap:18px}.c360-card{padding:16px}}
@media(max-width:850px){.c360-grid{grid-template-columns:1fr}.c360-side{position:static}.c360-heading{font-size:26px}.c360-top{align-items:flex-start}.c360-links{gap:10px}.c360-steps{gap:15px}}
""")
