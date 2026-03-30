"""Generate a self-contained static HTML report.

The output is a single HTML file with all CSS, JS, and data inlined.
It can be opened in any browser without a server — ideal for sharing
incident timelines via email, file share, or chat.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from markupsafe import Markup

from ir_tracker.storage import Storage
from ir_tracker.web import _ts_to_display, _build_density, _build_cumulative

_HERE = Path(__file__).parent


def _build_lang_links(output_path: str, current_lang: str) -> list[dict]:
    """Build language toggle links based on output filename convention.

    Convention: timeline.html (EN), timeline-ja.html (JA), etc.
    """
    if not output_path:
        return []

    p = Path(output_path)
    stem = p.stem
    suffix = p.suffix

    # Derive base stem (strip existing lang suffix like -ja)
    base = stem
    for code in ("ja", "ko", "zh", "fr", "de", "es"):
        if stem.endswith(f"-{code}"):
            base = stem[: -(len(code) + 1)]
            break

    en_file = f"{base}{suffix}"
    links = [{"file": en_file, "label": "EN", "active": not current_lang}]

    if current_lang:
        links.append({"file": f"{base}-{current_lang}{suffix}", "label": current_lang.upper(), "active": True})
    else:
        links.append({"file": f"{base}-ja{suffix}", "label": "JA", "active": False})

    return links


def export_html(storage: Storage, lang: str = "", output_path: str = "") -> str:
    """Generate a self-contained HTML report string."""
    from jinja2 import Environment

    segments = storage.get_segments()
    msg_count = storage.get_message_count()
    time_range = storage.get_time_range()

    # Build segment data (same logic as web.py timeline_view)
    seg_data = []
    seg_messages: dict[int, list[dict]] = {}
    for seg in segments:
        item = {
            "id": seg["id"],
            "start_display": _ts_to_display(seg["start_ts"]),
            "end_display": _ts_to_display(seg["end_ts"]),
            "message_count": seg["message_count"],
            "state": seg["state"],
            "analysis": None,
        }

        analysis = storage.get_analysis(seg["id"])
        if analysis:
            data = json.loads(analysis["analysis_json"])
            if lang:
                trans_json = storage.get_translation(seg["id"], lang)
                if trans_json:
                    trans = json.loads(trans_json)
                    data["summary"] = trans.get("summary", data.get("summary", ""))
                    if trans.get("key_findings"):
                        data["key_findings"] = trans["key_findings"]
                    if trans.get("open_questions"):
                        data["open_questions"] = trans["open_questions"]
                    if trans.get("participants"):
                        data["active_participants"] = trans["participants"]
                    if trans.get("notable_events"):
                        data["notable_events"] = trans["notable_events"]
            item["analysis"] = data

        # Collect messages for this segment (for inline modal data)
        messages = storage.get_messages_in_range(seg["start_ts"], seg["end_ts"])
        seg_messages[seg["id"]] = [
            {
                "time": _ts_to_display(m["ts"]),
                "user": m["user_name"] or m["user_id"],
                "text": m["text"],
                "is_bot": bool(m["is_bot"]),
            }
            for m in messages
        ]

        seg_data.append(item)

    seg_data.reverse()

    # Current status
    current_status = ""
    current_severity = ""
    if seg_data and seg_data[0]["analysis"]:
        latest = seg_data[0]["analysis"]
        current_status = latest.get("status", "")
        current_severity = latest.get("severity", "")

    cumulative = _build_cumulative(storage, lang=lang)
    density = _build_density(storage)
    tokens = storage.get_token_usage()

    # Incident summary
    incident_type = storage.get_context("incident_type") or ""
    incident_summary = storage.get_context("incident_summary") or ""
    if lang:
        incident_type = storage.get_context(f"incident_type:{lang}") or incident_type
        incident_summary = storage.get_context(f"incident_summary:{lang}") or incident_summary

    css = Markup((_HERE / "static" / "style.css").read_text(encoding="utf-8"))

    def safe_tojson(v):
        """Serialize to JSON and mark as safe so Jinja2 won't HTML-escape it."""
        return Markup(json.dumps(v, ensure_ascii=False))

    # Build language toggle links for static export.
    # Uses output_path to derive sibling filenames.
    lang_links = _build_lang_links(output_path, lang)

    env = Environment(autoescape=True)
    template = env.from_string(_TEMPLATE)

    return template.render(
        css=css,
        segments=seg_data,
        seg_messages=seg_messages,
        lang=lang,
        lang_links=lang_links,
        density=density,
        incident_type=incident_type,
        incident_summary=incident_summary,
        stats={
            "messages": msg_count,
            "segments": len(segments),
            "analyzed": sum(1 for s in segments if s["state"] == "analyzed"),
            "current_status": current_status,
            "current_severity": current_severity,
            "time_range": (
                _ts_to_display(time_range[0]),
                _ts_to_display(time_range[1]),
            ) if time_range else None,
            "tokens": tokens,
        },
        cumulative=cumulative,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        tojson=safe_tojson,
    )


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ir-tracker — Incident Timeline</title>
<style>
{{ css }}
</style>
<script>
(function() { var t = localStorage.getItem('theme'); if (t) document.documentElement.setAttribute('data-theme', t); })();
</script>
</head>
<body>
<nav>
  <div class="nav-inner">
    <span class="logo">ir-tracker</span>
    <span style="color: var(--text-secondary); font-size: 13px;">Static export — {{ generated_at }}</span>
    {% if lang_links %}
    <div class="lang-toggle">
      {% for ll in lang_links %}
      <a href="{{ ll.file }}" class="lang-btn {{ 'active' if ll.active }}">{{ ll.label }}</a>
      {% endfor %}
    </div>
    {% endif %}
    <button class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">
      <span id="theme-icon">&#9790;</span>
    </button>
  </div>
</nav>
<div class="main-content">

{# ── Stats ── #}
<div class="stats-bar">
  <div class="stats">
    <div class="stat">
      <div class="number">{{ stats.messages }}</div>
      <div class="label">Messages</div>
    </div>
    <div class="stat">
      <div class="number">{{ stats.segments }}</div>
      <div class="label">Segments</div>
    </div>
    <div class="stat">
      <div class="number">{{ stats.analyzed }}</div>
      <div class="label">Analyzed</div>
    </div>
    {% if stats.current_status %}
    <div class="stat">
      <div class="label">Status</div>
      <div><span class="badge badge-status">{{ stats.current_status | upper }}</span></div>
    </div>
    {% endif %}
    {% if stats.current_severity %}
    <div class="stat">
      <div class="label">Severity</div>
      <div><span class="badge badge-{{ stats.current_severity }}">{{ stats.current_severity | upper }}</span></div>
    </div>
    {% endif %}
    {% if stats.tokens and stats.tokens.total > 0 %}
    <div class="stat">
      <div class="number">{{ "{:,}".format(stats.tokens.total) }}</div>
      <div class="label">Tokens</div>
      <div class="token-detail">Pro {{ "{:,}".format(stats.tokens.analysis) }} / Flash {{ "{:,}".format(stats.tokens.translation) }}</div>
    </div>
    {% endif %}
  </div>
  {% if stats.time_range %}
  <div style="color: var(--text-secondary); font-size: 13px; margin-top: 8px;">
    {{ stats.time_range.0 }} — {{ stats.time_range.1 }}
  </div>
  {% endif %}
</div>

{% if not segments %}
<div style="text-align: center; color: var(--text-secondary); padding: 60px 0;">
  No data available.
</div>
{% else %}

{# ── Incident summary ── #}
{% if incident_summary %}
<div class="incident-summary">
  {% if incident_type %}<div class="incident-type">{{ incident_type }}</div>{% endif %}
  <div class="incident-text">{{ incident_summary }}</div>
</div>
{% endif %}

{# ── Density chart ── #}
{% if density %}
<div class="density-chart">
  <div class="density-canvas-wrap" id="density-wrap">
    <canvas id="density-canvas"></canvas>
    <div class="density-tooltip" id="density-tooltip"></div>
  </div>
</div>
<script id="density-data" type="application/json">{{ tojson(density) }}</script>
{% endif %}

{# ── Two-column layout ── #}
<div class="layout">
  <div class="timeline-scroll">
    <div class="timeline">
      {% for seg in segments %}
      <div class="segment {{ seg.state }}" data-segment-id="{{ seg.id }}">
        <div class="segment-header">
          <span class="segment-time">{{ seg.start_display }} — {{ seg.end_display }}</span>
          <span class="segment-count">{{ seg.message_count }} msgs</span>
          {% if seg.state == 'analyzed' %}
            <span class="badge badge-low">Analyzed</span>
          {% elif seg.state == 'pending' %}
            <span class="badge" style="background: var(--warning); color: white;">Pending</span>
          {% elif seg.state == 'stale' %}
            <span class="badge" style="background: var(--info); color: white;">Stale</span>
          {% endif %}
        </div>

        {% if seg.analysis %}
        <div class="segment-card">
          <div class="segment-summary">{{ seg.analysis.summary }}</div>

          {% if seg.analysis.key_findings %}
          <div class="section-title">Key Findings</div>
          <ul class="finding-list">
            {% for f in seg.analysis.key_findings %}<li>{{ f }}</li>{% endfor %}
          </ul>
          {% endif %}

          {% if seg.analysis.active_participants %}
          <div class="section-title">Participants</div>
          {% for p in seg.analysis.active_participants %}
          <div class="participant">
            <span class="participant-name">@{{ p.user_name }}</span>
            <span class="participant-role">({{ p.inferred_role }})</span>
            <span class="participant-activity">{{ p.current_activity }}</span>
          </div>
          {% endfor %}
          {% endif %}

          {% if seg.analysis.notable_events %}
          <div class="section-title">Events</div>
          {% for e in seg.analysis.notable_events %}
          <div class="event">
            <span class="event-time">{{ e.time }}</span>
            {% if e.significance == 'high' %}🔴{% elif e.significance == 'medium' %}🟡{% else %}⚪{% endif %}
            <span>{{ e.description }}</span>
          </div>
          {% endfor %}
          {% endif %}

          {% if seg.analysis.open_questions %}
          <div class="section-title">Open Questions</div>
          <ul class="question-list">
            {% for q in seg.analysis.open_questions %}<li>{{ q }}</li>{% endfor %}
          </ul>
          {% endif %}
        </div>
        {% else %}
        <div class="segment-card" style="color: var(--text-secondary); font-style: italic;">
          Analysis pending
        </div>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  {% if cumulative %}
  <div class="panel-scroll">
    <div class="status-panel">
      <div class="panel-header">
        <h3>Current Situation</h3>
      </div>

      {% if stats.current_status %}
      <div class="section">
        <span class="badge badge-status">{{ stats.current_status | upper }}</span>
        {% if stats.current_severity %}
        <span class="badge badge-{{ stats.current_severity }}">{{ stats.current_severity | upper }}</span>
        {% endif %}
      </div>
      {% endif %}

      {% if cumulative.participants %}
      <div class="section">
        <div class="section-title">Active ({{ cumulative.participants | length }})</div>
        {% for user, activity in cumulative.participants.items() %}
        <div class="participant">
          <span class="participant-name">@{{ user }}</span>
          <span class="participant-activity">{{ activity }}</span>
        </div>
        {% endfor %}
      </div>
      {% endif %}

      <hr class="status-divider">

      {% if cumulative.findings %}
      <div class="section">
        <div class="section-title">Findings ({{ cumulative.findings | length }})</div>
        <ul class="finding-list">
          {% for f in cumulative.findings %}<li>{{ f }}</li>{% endfor %}
        </ul>
      </div>
      {% endif %}

      <hr class="status-divider">

      {% if cumulative.questions %}
      <div class="section">
        <div class="section-title">Open Questions ({{ cumulative.questions | length }})</div>
        <ul class="question-list">
          {% for q in cumulative.questions %}<li>{{ q }}</li>{% endfor %}
        </ul>
      </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
</div>
{% endif %}

{# ── Message modal ── #}
<div class="modal-overlay" id="msg-modal">
  <div class="modal">
    <div class="modal-header">
      <h3 id="modal-title">Messages</h3>
      <button class="modal-close" id="modal-close">&times;</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

{# ── Inline message data (no API needed) ── #}
<script id="seg-messages" type="application/json">{{ tojson(seg_messages) }}</script>

</div><!-- main-content -->

<script>
// Theme toggle
function toggleTheme() {
  var el = document.documentElement;
  var c = el.getAttribute('data-theme');
  var n = c === 'dark' ? 'light' : 'dark';
  if (!c) n = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark';
  el.setAttribute('data-theme', n);
  localStorage.setItem('theme', n);
  updateIcon(n);
}
function updateIcon(t) {
  var i = document.getElementById('theme-icon');
  if (i) i.textContent = t === 'dark' ? '\u263E' : '\u2600';
}
(function() {
  var t = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  updateIcon(t);
})();

// Message modal (reads from inline data, no fetch)
(function() {
  var modal = document.getElementById('msg-modal');
  var modalTitle = document.getElementById('modal-title');
  var modalBody = document.getElementById('modal-body');
  var modalClose = document.getElementById('modal-close');
  var allMessages = JSON.parse(document.getElementById('seg-messages').textContent);

  if (modal) {
    document.querySelectorAll('.segment[data-segment-id]').forEach(function(seg) {
      var header = seg.querySelector('.segment-header');
      if (header) {
        header.style.cursor = 'pointer';
        header.addEventListener('click', function() {
          var id = seg.dataset.segmentId;
          var data = allMessages[id] || [];
          modalTitle.textContent = seg.querySelector('.segment-time').textContent + ' (' + data.length + ' msgs)';
          modalBody.textContent = '';
          if (!data.length) {
            var empty = document.createElement('div');
            empty.style.color = 'var(--text-secondary)';
            empty.textContent = 'No messages.';
            modalBody.appendChild(empty);
          } else {
            var list = document.createElement('div');
            list.className = 'msg-list';
            data.forEach(function(m) {
              var row = document.createElement('div');
              row.className = m.is_bot ? 'msg msg-bot' : 'msg';
              var timeEl = document.createElement('span');
              timeEl.className = 'msg-time';
              timeEl.textContent = m.time;
              var userEl = document.createElement('span');
              userEl.className = 'msg-user';
              userEl.textContent = m.user;
              var textEl = document.createElement('span');
              textEl.className = 'msg-text';
              textEl.textContent = m.text;
              row.appendChild(timeEl);
              row.appendChild(userEl);
              row.appendChild(textEl);
              list.appendChild(row);
            });
            modalBody.appendChild(list);
          }
          modal.classList.add('active');
        });
      }
    });

    modalClose.addEventListener('click', function() { modal.classList.remove('active'); });
    modal.addEventListener('click', function(e) {
      if (e.target === modal) modal.classList.remove('active');
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') modal.classList.remove('active');
    });
  }
})();

// Density chart
(function() {
  var el = document.getElementById('density-data');
  if (!el) return;
  var data = JSON.parse(el.textContent);
  if (!data.length) return;

  var canvas = document.getElementById('density-canvas');
  var tip = document.getElementById('density-tooltip');
  var wrap = document.getElementById('density-wrap');
  var dpr = window.devicePixelRatio || 1;

  function getColor(v) {
    return getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  }

  function draw() {
    var W = wrap.clientWidth;
    var H = 80;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    var ml = 36, mr = 12, mt = 4, mb = 20;
    var cw = W - ml - mr, ch = H - mt - mb;
    var maxCount = Math.max.apply(null, data.map(function(d){ return d.count; }));
    if (maxCount === 0) maxCount = 1;
    var axisColor = getColor('--text-secondary');
    var barColor = getColor('--accent');
    var bgLine = getColor('--border');

    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    var yTicks = _niceTicks(0, maxCount, 4);
    for (var i = 0; i < yTicks.length; i++) {
      var yVal = yTicks[i];
      var yPos = mt + ch - (yVal / maxCount) * ch;
      ctx.strokeStyle = bgLine; ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(ml, yPos); ctx.lineTo(W - mr, yPos); ctx.stroke();
      ctx.fillStyle = axisColor;
      ctx.fillText(String(yVal), ml - 4, yPos);
    }

    var barW = Math.max(cw / data.length - 1, 1);
    var gap = cw / data.length;
    ctx.fillStyle = barColor; ctx.globalAlpha = 0.7;
    for (var j = 0; j < data.length; j++) {
      var h = (data[j].count / maxCount) * ch;
      ctx.fillRect(ml + j * gap, mt + ch - h, Math.max(barW, 1.5), h);
    }
    ctx.globalAlpha = 1.0;

    ctx.strokeStyle = axisColor; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(ml, mt + ch); ctx.lineTo(W - mr, mt + ch); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ml, mt); ctx.lineTo(ml, mt + ch); ctx.stroke();

    ctx.fillStyle = axisColor; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    var sampleLabel = data[0].time;
    var labelW = ctx.measureText(sampleLabel).width + 16;
    var maxLabels = Math.max(2, Math.floor(cw / labelW));
    var step = Math.max(1, Math.ceil(data.length / maxLabels));
    for (var k = 0; k < data.length; k += step) {
      ctx.fillText(data[k].time, ml + k * gap + barW / 2, mt + ch + 4);
    }
    var lastIdx = data.length - 1;
    if (lastIdx % step !== 0) {
      var llx = ml + lastIdx * gap + barW / 2;
      var prevLabelX = ml + (lastIdx - (lastIdx % step)) * gap + barW / 2;
      if (llx - prevLabelX > labelW) ctx.fillText(data[lastIdx].time, llx, mt + ch + 4);
    }
  }

  function _niceTicks(lo, hi, count) {
    if (hi <= 0) return [0];
    var rough = (hi - lo) / count;
    var mag = Math.pow(10, Math.floor(Math.log10(rough)));
    var norm = rough / mag;
    var step;
    if (norm <= 1.5) step = mag; else if (norm <= 3) step = 2*mag; else if (norm <= 7) step = 5*mag; else step = 10*mag;
    step = Math.max(1, step);
    var ticks = [];
    for (var v = 0; v <= hi; v += step) ticks.push(Math.round(v));
    if (ticks[ticks.length-1] < hi) ticks.push(Math.round(hi));
    return ticks;
  }

  draw();
  window.addEventListener('resize', draw);

  canvas.addEventListener('mousemove', function(e) {
    var rect = canvas.getBoundingClientRect();
    var x = e.clientX - rect.left;
    var cw = rect.width - 36 - 12;
    var idx = Math.floor((x - 36) / cw * data.length);
    if (idx >= 0 && idx < data.length) {
      tip.textContent = data[idx].label + ' \u2014 ' + data[idx].count + ' msgs';
      tip.style.left = x + 'px'; tip.style.display = 'block';
    } else { tip.style.display = 'none'; }
  });
  canvas.addEventListener('mouseleave', function() { tip.style.display = 'none'; });
})();
</script>
</body>
</html>"""
