export type LngLat = [number, number]

/** Decode a Google encoded polyline into [lon, lat] pairs (GeoJSON order). */
export function decodePolyline(encoded: string, precision = 5): LngLat[] {
  const factor = 10 ** precision
  const coords: LngLat[] = []
  let index = 0
  let lat = 0
  let lon = 0
  const next = (): number => {
    let result = 0
    let shift = 0
    let byte: number
    do {
      byte = encoded.charCodeAt(index++) - 63
      result |= (byte & 0x1f) << shift
      shift += 5
    } while (byte >= 0x20)
    return result & 1 ? ~(result >> 1) : result >> 1
  }
  while (index < encoded.length) {
    lat += next()
    lon += next()
    coords.push([lon / factor, lat / factor])
  }
  return coords
}

const EARTH_RADIUS_MI = 3958.7613
const rad = (d: number) => (d * Math.PI) / 180

export function haversineMi([lon1, lat1]: LngLat, [lon2, lat2]: LngLat): number {
  const dLat = rad(lat2 - lat1)
  const dLon = rad(lon2 - lon1)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function cumulativeMiles(coords: LngLat[]): number[] {
  const out = [0]
  for (let i = 1; i < coords.length; i++) out.push(out[i - 1] + haversineMi(coords[i - 1], coords[i]))
  return out
}

/** First index i with arr[i] > x (arr ascending). */
function upperBound(arr: number[], x: number): number {
  let lo = 0
  let hi = arr.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (arr[mid] <= x) lo = mid + 1
    else hi = mid
  }
  return lo
}

export function interpolateAlong(coords: LngLat[], cum: number[], mile: number): LngLat {
  if (mile <= 0) return coords[0]
  const total = cum[cum.length - 1]
  if (mile >= total) return coords[coords.length - 1]
  const i = upperBound(cum, mile) - 1
  const seg = cum[i + 1] - cum[i]
  const t = seg === 0 ? 0 : (mile - cum[i]) / seg
  const [x1, y1] = coords[i]
  const [x2, y2] = coords[i + 1]
  return [x1 + (x2 - x1) * t, y1 + (y2 - y1) * t]
}

/** Piecewise-linear lookup: y at x, given ascending xs. Clamped at both ends. */
export function interpolateSeries(xs: number[], ys: number[], x: number): number {
  if (x <= xs[0]) return ys[0]
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1]
  const i = upperBound(xs, x) - 1
  const span = xs[i + 1] - xs[i]
  return span === 0 ? ys[i + 1] : ys[i] + ((ys[i + 1] - ys[i]) * (x - xs[i])) / span
}

export type Bounds = [[number, number], [number, number]]

export function boundsOf(lines: LngLat[][]): Bounds | null {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const line of lines)
    for (const [x, y] of line) {
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }
  return Number.isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null
}
