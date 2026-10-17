import 'maplibre-gl/dist/maplibre-gl.css'
import Map, { NavigationControl } from 'react-map-gl/maplibre'
import './maplibre'

// OpenFreeMap: free vector basemap, no API key.
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'

const CONTINENTAL_US = { longitude: -98.5, latitude: 39.8, zoom: 3.6 }

export function TripMap() {
  return (
    <Map initialViewState={CONTINENTAL_US} mapStyle={BASEMAP_STYLE} style={{ width: '100%', height: '100%' }}>
      <NavigationControl position="top-right" />
    </Map>
  )
}
