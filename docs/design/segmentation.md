# Segmentation Engine — Detailed Design

## Purpose

Divide a continuous stream of Slack messages into analyzable segments.
Each segment should represent a coherent "episode" of the incident response.

## Why Not Analyze Everything at Once?

1. **Cost**: Re-analyzing the entire conversation on every update is wasteful.
   Only new/changed segments need analysis.
2. **Context window**: Even with 1M tokens, very long incidents (days) may
   exceed limits. Segments keep each analysis within bounds.
3. **Temporal clarity**: Segments provide natural timeline boundaries for the
   status view ("what happened in the last 30 minutes?").

## Algorithm

### Step 1: Build candidate windows

Divide all messages into fixed-size time windows (default: 30 minutes).

```
Messages:  m1  m2  m3 .... m15  m16 ... m20  [gap 2h]  m21  m22 ...
Windows:   |--- W1 (30m) ---|--- W2 (30m) -|           |--- W3 ---|
```

### Step 2: Detect gaps

If the gap between two consecutive messages exceeds `gap_threshold` (default:
60 minutes), force a segment boundary regardless of the window position.

```
m20 at 10:00, m21 at 12:30 → gap = 2.5h > 1h → boundary between m20 and m21
```

### Step 3: Merge sparse windows

If a window has fewer than `min_messages` (default: 3), merge it with the
adjacent window that is closer in time.

```
W1: 15 messages
W2: 2 messages    → merge into W1 (adjacent, same activity burst)
W3: 20 messages
```

### Step 4: Split dense windows (entropy detection)

Calculate message rate (messages per minute) within each window.
If a window contains a rate change exceeding `rate_change_factor` (default: 3x):

```
W1 first half:  2 msg/min
W1 second half: 8 msg/min  → 4x change → split W1 at the inflection point
```

This captures moments when the incident escalates or a new finding triggers
a burst of activity.

### Step 5: Assign segment states

For each resulting segment:
- If all messages are new (not in any previous segment): `pending`
- If the segment existed before but has new messages: `stale`
- If unchanged: leave as `analyzed`

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `segment_window_minutes` | 30 | Base time window size |
| `gap_threshold_minutes` | 60 | Minimum gap to force a boundary |
| `min_messages` | 3 | Merge threshold for sparse windows |
| `rate_change_factor` | 3.0 | Split threshold for activity spikes |

## Edge Cases

| Case | Handling |
|---|---|
| Single message in the entire DB | One segment with 1 message; analyzed but flagged as "insufficient data" |
| All messages within 1 minute | One segment; no splitting needed |
| Incident spanning multiple days | Gap detection creates natural day boundaries |
| Messages arrive out of order | Ingest layer sorts by `ts`; segmentation always works on sorted data |
| Re-ingestion adds messages to an existing segment's time range | Segment state changes to `stale`; re-analysis triggered |

## Data Flow

```
messages (sorted by ts)
    │
    ▼
[Step 1] Fixed windows
    │
    ▼
[Step 2] Gap detection → split at gaps
    │
    ▼
[Step 3] Merge sparse windows
    │
    ▼
[Step 4] Split dense windows (entropy)
    │
    ▼
[Step 5] Assign states (pending/stale/analyzed)
    │
    ▼
segments table (upsert)
```
