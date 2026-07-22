import type { CloudHealth, GeoStore, ProductionGeo } from "../types";
import { MAP_H, MAP_W, project, STATE_PATHS } from "../lib/usMap";

// Fixed, brand-neutral hues — one per sales channel (dots) and one per cloud
// health state (AWS region nodes + connectors).
const CHANNEL_COLOR: Record<string, string> = {
  retail: "#3b82f6",
  indirect: "#8b5cf6",
  d2d: "#f59e0b",
  inside_sales: "#14b8a6",
};
const CHANNEL_ORDER: Array<[string, string]> = [
  ["retail", "Retail"],
  ["indirect", "Indirect"],
  ["d2d", "Door-to-Door"],
  ["inside_sales", "Inside Sales"],
];
const STATUS_COLOR: Record<string, string> = {
  green: "#22c55e",
  yellow: "#eab308",
  red: "#ef4444",
};
const STATUS_LABEL: Record<string, string> = {
  green: "Healthy",
  yellow: "Elevated",
  red: "Critical",
};

function storeRadius(count: number, max: number): number {
  const t = max > 0 ? count / max : 0;
  return 5 + Math.sqrt(t) * 9; // 5–14px
}

function CloudNode({ cloud }: { cloud: CloudHealth }) {
  const [x, y] = project(cloud.lng, cloud.lat);
  const color = STATUS_COLOR[cloud.status] ?? STATUS_COLOR.green;
  return (
    <g className={`impactmap-cloud impactmap-cloud--${cloud.status}`}>
      <title>
        {`${cloud.label} (${cloud.aws_region}) — ${STATUS_LABEL[cloud.status]}\n`}
        {`${cloud.count} escalations vs ~${cloud.baseline}/day baseline · ${cloud.store_count} stores · ${cloud.channels.length} channels`}
      </title>
      {cloud.status !== "green" && (
        <circle className="impactmap-cloud-pulse" cx={x} cy={y} r={18} fill={color} />
      )}
      <circle cx={x} cy={y} r={15} fill={color} stroke="#fff" strokeWidth={2.5} />
      <text x={x} y={y + 4} textAnchor="middle" className="impactmap-cloud-count">
        {cloud.count}
      </text>
      <text x={x} y={y + 30} textAnchor="middle" className="impactmap-cloud-label">
        {cloud.label}
      </text>
      <text x={x} y={y + 43} textAnchor="middle" className="impactmap-cloud-sub">
        {cloud.aws_region} · {STATUS_LABEL[cloud.status]}
      </text>
    </g>
  );
}

function StoreDot({ store, max }: { store: GeoStore; max: number }) {
  const [x, y] = project(store.lng, store.lat);
  const color = CHANNEL_COLOR[store.channel] ?? "#64748b";
  return (
    <circle
      className="impactmap-store"
      cx={x}
      cy={y}
      r={storeRadius(store.count, max)}
      fill={color}
      fillOpacity={0.82}
      stroke="#fff"
      strokeWidth={1.2}
    >
      <title>
        {`${store.name} — ${store.city}, ${store.state}\n`}
        {`${store.channel_label} · ${store.count} escalation${store.count === 1 ? "" : "s"}`}
      </title>
    </circle>
  );
}

export default function ProductionImpactMap({ geo }: { geo: ProductionGeo }) {
  const stores = geo.stores ?? [];
  const clouds = geo.clouds ?? [];
  const maxCount = stores.reduce((m, s) => Math.max(m, s.count), 0);
  const cloudById = new Map(clouds.map((c) => [c.id, c]));
  const empty = stores.length === 0 && clouds.every((c) => c.count === 0);

  return (
    <div className="panel impactmap">
      <div className="impactmap-head">
        <div>
          <h3 className="prod-panel-title" style={{ marginBottom: 2 }}>
            Impact map — escalation geography &amp; cloud health
          </h3>
          <p className="dash-sub">
            Reporting stores plotted by location · dot size = escalation volume, color = channel ·
            AWS region nodes show red/yellow/green health vs each region's baseline
          </p>
        </div>
        <div className="impactmap-stats">
          <div className="impactmap-stat">
            <span className="impactmap-stat-val">{geo.unique_stores}</span>
            <span className="impactmap-stat-lbl">unique stores</span>
          </div>
          <div className="impactmap-stat">
            <span className="impactmap-stat-val">{geo.channels_impacted}/4</span>
            <span className="impactmap-stat-lbl">channels</span>
          </div>
          {clouds.map((c) => (
            <div key={c.id} className={`impactmap-stat impactmap-stat--${c.status}`}>
              <span className="impactmap-stat-val">{c.count}</span>
              <span className="impactmap-stat-lbl">{c.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="impactmap-canvas">
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="impactmap-svg" role="img"
             aria-label="US map of escalation locations and AWS region health">
          {/* State outlines */}
          <g className="impactmap-states">
            {STATE_PATHS.map((d, i) => (
              <path key={i} d={d} />
            ))}
          </g>

          {/* Connectors: each store → its cloud region, tinted by region health */}
          <g className="impactmap-links">
            {stores.map((s) => {
              const c = cloudById.get(s.cloud);
              if (!c) return null;
              const [sx, sy] = project(s.lng, s.lat);
              const [cx, cy] = project(c.lng, c.lat);
              return (
                <line
                  key={s.id}
                  x1={sx} y1={sy} x2={cx} y2={cy}
                  stroke={STATUS_COLOR[c.status]}
                  strokeWidth={1}
                  strokeOpacity={0.18}
                />
              );
            })}
          </g>

          {/* Reporting stores */}
          <g>
            {stores.map((s) => (
              <StoreDot key={s.id} store={s} max={maxCount} />
            ))}
          </g>

          {/* AWS regions */}
          <g>
            {clouds.map((c) => (
              <CloudNode key={c.id} cloud={c} />
            ))}
          </g>
        </svg>

        {empty && (
          <div className="impactmap-empty">No escalations with location data in the window.</div>
        )}
      </div>

      {/* Legend */}
      <div className="impactmap-legend">
        <div className="impactmap-legend-group">
          <span className="impactmap-legend-title">Channel</span>
          {CHANNEL_ORDER.map(([key, label]) => (
            <span key={key} className="impactmap-legend-item">
              <span className="impactmap-swatch" style={{ background: CHANNEL_COLOR[key] }} />
              {label}
            </span>
          ))}
        </div>
        <div className="impactmap-legend-group">
          <span className="impactmap-legend-title">Cloud health</span>
          {(["green", "yellow", "red"] as const).map((st) => (
            <span key={st} className="impactmap-legend-item">
              <span className="impactmap-swatch impactmap-swatch--ring" style={{ background: STATUS_COLOR[st] }} />
              {STATUS_LABEL[st]}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
