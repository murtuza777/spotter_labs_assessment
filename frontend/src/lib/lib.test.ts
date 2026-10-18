import { describe, expect, it } from 'vitest'
import type { HeatmapResponse, PlannedRoute, TripPlan } from '../api/types'
import { formatDuration, formatRiskMiles } from './format'
import { boundsOf, cumulativeMiles, decodePolyline, interpolateAlong, interpolateSeries } from './geo'
import { buildHeatmapGeoJSON, frameOpacities, heatmapGeometry, toWeight } from './heatmap'
import { severityIndex } from './risk'
import { buildRouteModels, truckPosition, truckStatus } from './routeModel'
import { describeWeatherSource } from './weatherSource'

describe('decodePolyline', () => {
  it('decodes the Google reference example into [lon, lat]', () => {
    expect(decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@')).toEqual([
      [-120.2, 38.5],
      [-120.95, 40.7],
      [-126.453, 43.252],
    ])
  })
})

describe('geo helpers', () => {
  const line: [number, number][] = [
    [0, 0],
    [1, 0],
    [2, 0],
  ]
  it('interpolates along a polyline and clamps', () => {
    const cum = cumulativeMiles(line)
    expect(interpolateAlong(line, cum, cum[2] * 0.75)[0]).toBeCloseTo(1.5)
    expect(interpolateAlong(line, cum, -1)).toEqual([0, 0])
    expect(interpolateAlong(line, cum, 1e9)).toEqual([2, 0])
  })
  it('interpolates a series', () => {
    expect(interpolateSeries([0, 10, 20], [0, 100, 400], 15)).toBe(250)
    expect(interpolateSeries([0, 10], [5, 6], -3)).toBe(5)
  })
  it('computes bounds', () => {
    expect(boundsOf([line, [[-1, 3]]])).toEqual([
      [-1, 0],
      [2, 3],
    ])
    expect(boundsOf([])).toBeNull()
  })
})

describe('severityIndex', () => {
  it('maps thresholds onto band edges', () => {
    expect(severityIndex('gust', 0)).toBe(0)
    expect(severityIndex('gust', 25)).toBe(1)
    expect(severityIndex('gust', 30)).toBe(1.5)
    expect(severityIndex('gust', 55)).toBe(4)
    expect(severityIndex('gust', 90)).toBe(4)
    expect(severityIndex('rain', 0.25)).toBe(2)
    expect(severityIndex('snow', 2)).toBe(3)
    expect(severityIndex('risk', 3)).toBe(3)
  })
})

describe('heatmap', () => {
  const data: HeatmapResponse = {
    hours: ['a', 'b'],
    points: [
      [40, -105],
      [41, -106],
    ],
    grid_step_deg: 0.5,
    levels: ['low', 'moderate', 'high', 'severe', 'no_travel'],
    frames: {
      risk: [
        [0, 4],
        [2, null],
      ],
      gust: [
        [10, 60],
        [35, null],
      ],
      rain: [
        [0, 0],
        [0.1, null],
      ],
      snow: [
        [0, 0],
        [0, null],
      ],
    },
  }

  it('builds one point per cell with flat per-hour properties, skipping unknowns', () => {
    const fc = buildHeatmapGeoJSON(data)
    expect(fc.features).toHaveLength(2)
    expect(fc.features[0].geometry.coordinates).toEqual([-105, 40])
    expect(fc.features[0].properties).toMatchObject({ r0: 0.2, r1: 0.6, g1: 0.6 })
    expect(fc.features[1].properties).toMatchObject({ r0: 1 })
    expect(fc.features[1].properties).not.toHaveProperty('r1')
  })

  it('weights land on the color stops of each risk level', () => {
    expect([0, 1, 2, 3, 4].map((s) => toWeight('risk', s))).toEqual([0.2, 0.4, 0.6, 0.8, 1])
  })

  it('cross-fades the two hours around a fractional slider position', () => {
    expect(frameOpacities(3, 48)).toEqual({ 3: 1 })
    expect(frameOpacities(3.25, 48)).toEqual({ 3: 0.75, 4: 0.25 })
    expect(frameOpacities(48, 48)).toEqual({ 48: 1 })
    expect(frameOpacities(60, 48)).toEqual({ 48: 1 })
    expect(frameOpacities(-1, 48)).toEqual({ 0: 1 })
  })

  it('chooses intensity so a uniform grid reproduces its weight', () => {
    const { intensity } = heatmapGeometry(0.25, 0)
    // At the equator sx == sy, so intensity is independent of step: 1 / (0.3989 * 2pi * (1.6/3)^2)
    expect(intensity).toBeCloseTo(1 / (0.3989 * 2 * Math.PI * (1.6 / 3) ** 2), 6)
  })
})

describe('truckPosition', () => {
  const route = {
    id: 'A',
    distance_mi: 100,
    duration_s: 7200,
    geometry: '???_ibE', // lat 0: lon 0 -> lon 1
    checkpoints: [
      { mile: 0, eta: '2026-10-18T00:00:00Z' },
      { mile: 25, eta: '2026-10-18T01:00:00Z' },
      { mile: 100, eta: '2026-10-18T02:00:00Z' },
    ],
  } as unknown as PlannedRoute
  const plan = { request: { departure_time: '2026-10-18T00:00:00Z' }, routes: [route] } as unknown as TripPlan

  it('follows checkpoint ETAs, not a constant speed', () => {
    const [model] = buildRouteModels(plan)
    expect(model.cum[model.cum.length - 1]).toBeCloseTo(100)
    expect(truckPosition(model, 0.5).mile).toBeCloseTo(12.5)
    expect(truckPosition(model, 1.5).mile).toBeCloseTo(62.5)
    const end = truckPosition(model, 5)
    expect(end.mile).toBe(100)
    expect(end.arrived).toBe(true)
  })
})

describe('formatDuration', () => {
  it('formats hours and minutes', () => {
    expect(formatDuration(27278)).toBe('7h 35m')
    expect(formatDuration(600)).toBe('10m')
  })
})

describe('truckStatus', () => {
  const route = {
    id: 'A',
    distance_mi: 100,
    duration_s: 7200,
    checkpoints: [
      { index: 0, mile: 0, eta: '2026-10-18T00:00:00Z', risk: { level: 'low' } },
      { index: 1, mile: 25, eta: '2026-10-18T01:00:00Z', risk: { level: 'high' } },
      { index: 2, mile: 100, eta: '2026-10-18T02:00:00Z', risk: null },
    ],
  } as unknown as PlannedRoute

  it('reports mile and nearest checkpoint at the slider time', () => {
    const s = truckStatus(route, '2026-10-18T00:00:00Z', 1.1)
    expect(s.mile).toBeCloseTo(32.5)
    expect(s.nearest.index).toBe(1)
    expect(s.arrived).toBe(false)
  })

  it('covers both ends of the slider range', () => {
    expect(truckStatus(route, '2026-10-18T00:00:00Z', 0).mile).toBe(0)
    const end = truckStatus(route, '2026-10-18T00:00:00Z', 48)
    expect(end.arrived).toBe(true)
    expect(end.nearest.index).toBe(2)
  })
})

describe('formatRiskMiles', () => {
  it('never rounds a non-zero risk distance down to 0', () => {
    expect(formatRiskMiles(0)).toBe('0')
    expect(formatRiskMiles(0.04)).toBe('0.1')
    expect(formatRiskMiles(0.4)).toBe('0.4')
    expect(formatRiskMiles(9.91)).toBe('10.0')
    expect(formatRiskMiles(25.4)).toBe('25')
  })
})

describe('describeWeatherSource', () => {
  const all = (p: string) => ({ wind_mph: p, gust_mph: p, rain_in_hr: p, snow_in_hr: p })

  it('names a single provider', () => {
    expect(describeWeatherSource(all('weatherapi'))).toBe('WeatherAPI.com')
    expect(describeWeatherSource(all('nws'))).toBe('National Weather Service')
  })

  it('says which readings a fallback filled', () => {
    expect(describeWeatherSource({ ...all('weatherapi'), gust_mph: 'nws' })).toBe(
      'WeatherAPI.com; gusts from National Weather Service',
    )
    expect(describeWeatherSource({ ...all('weatherapi'), wind_mph: 'nws', gust_mph: 'nws', rain_in_hr: 'nws' })).toBe(
      'National Weather Service; snow from WeatherAPI.com',
    )
  })

  it('shows nothing without source data', () => {
    expect(describeWeatherSource(null)).toBeNull()
    expect(describeWeatherSource(undefined)).toBeNull()
    expect(describeWeatherSource({ wind_mph: '', gust_mph: '', rain_in_hr: '', snow_in_hr: '' })).toBeNull()
  })
})
