// Self-contained US map projection — no map library, no external tiles.
//
// The Production Monitor impact map renders the vendored CONUS state outlines
// (src/data/us-states.geo.json, derived from public-domain US Census boundaries)
// and plots reporting stores + AWS regions by projecting real lng/lat with the
// SAME function, so points always line up with the outline. A latitude-corrected
// equirectangular projection is plenty for a national overview and keeps the
// whole thing offline-safe.

import geo from "../data/us-states.geo.json";

export const MAP_W = 960;
export const MAP_H = 560;
const PAD = 20;

// Continental-US bounds (padded a touch beyond the vendored geometry).
const BBOX = { minLng: -125, maxLng: -66.5, minLat: 24, maxLat: 49.6 };
const LAT_MID = (BBOX.minLat + BBOX.maxLat) / 2;
const COS = Math.cos((LAT_MID * Math.PI) / 180);

const GEO_W = (BBOX.maxLng - BBOX.minLng) * COS;
const GEO_H = BBOX.maxLat - BBOX.minLat;
const SCALE = Math.min((MAP_W - 2 * PAD) / GEO_W, (MAP_H - 2 * PAD) / GEO_H);
const OFF_X = (MAP_W - GEO_W * SCALE) / 2;
const OFF_Y = (MAP_H - GEO_H * SCALE) / 2;

/** Project a geographic coordinate to SVG viewBox space. */
export function project(lng: number, lat: number): [number, number] {
  const x = OFF_X + (lng - BBOX.minLng) * COS * SCALE;
  const y = OFF_Y + (BBOX.maxLat - lat) * SCALE;
  return [x, y];
}

type StateFeature = { id: string; name: string; polys: number[][][] };

/** Pre-projected `d` attributes for every state polygon (computed once). */
export const STATE_PATHS: string[] = (geo as { states: StateFeature[] }).states.flatMap((s) =>
  s.polys.map((poly) => {
    const d = poly
      .map(([lng, lat], i) => {
        const [x, y] = project(lng, lat);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
    return `${d} Z`;
  }),
);
