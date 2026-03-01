// Idaho Turkey Hunt Map - Mapbox GL JS logic
// Token placeholders are replaced by map_builder.py before serving.

mapboxgl.accessToken = '__MAPBOX_TOKEN__';

// ── Embedded GeoJSON data ─────────────────────────────────────────────────────
const turkeyGmuData    = __TURKEY_GMU__;
const speciesRangeData = __SPECIES_RANGE__;
const officesData      = __OFFICES__;
const accessYesData    = __ACCESS_YES__;
const motorizedTrailsData = __MOTORIZED_TRAILS__;
const trailsData          = __TRAILS__;
const waterData        = __WATER__;
const campgroundsData  = __CAMPGROUNDS__;
const closedAreasData  = __CLOSED_AREAS__;
const burnedAreasData      = __BURNED_AREAS__;
const loggingAreasData     = __LOGGING_AREAS__;
const decidForestData      = __DECIDUOUS_FOREST__;
const croplandData         = __CROPLAND__;
const snowCoverData    = __SNOW_COVER__;
const publicAccessData = __PUBLIC_ACCESS__;
const idfgWmaData      = __IDFG_WMA__;
const TOM_MARKER_IMG   = '__TOM_MARKER_IMG__';   // base64 PNG, empty if file missing

// ── State ─────────────────────────────────────────────────────────────────────
let markerModeActive = false;
let userMarkers      = [];
let layerVisibility  = {};   // saved before a basemap style switch
let _layersAdded     = false; // guard: only re-init layers on style SWITCH, not initial load
let _popupsAttached  = false; // guard: unified click handler registered only once
let activePopup      = null;  // single shared popup instance

const LAYER_GROUPS = {
  'toggle-gmu':     ['gmu-fill', 'gmu-shade', 'gmu-shadow', 'gmu-outline-glow', 'gmu-outline', 'gmu-label'],
  'toggle-range':   ['range-fill'],
  'toggle-access':  ['access-fill', 'access-outline'],
  'toggle-offices': ['offices-circle', 'offices-label'],
  'toggle-motorized': ['motorized-line'],
  'toggle-trails':    ['trails-line'],
  'toggle-water':   ['water-fill', 'water-fill-outline', 'water-line', 'water-label'],
  'toggle-camps':   ['camps-circle', 'camps-label'],
  'toggle-closed':  ['closed-fill', 'closed-outline'],
  'toggle-burned':       ['burned-fill'],
  'toggle-logging':      ['logging-fill'],
  'toggle-decid-forest': ['decid-forest-fill', 'decid-forest-outline'],
  'toggle-cropland':     ['cropland-fill', 'cropland-outline'],
  'toggle-snow':    ['snow-fill', 'snow-outline'],
  'toggle-public':  ['public-fill', 'public-outline'],
  'toggle-wma':     ['wma-fill', 'wma-outline'],
};

const BASEMAP_STYLES = {
  satellite: 'mapbox://styles/mapbox/satellite-streets-v12',
  outdoors:  'mapbox://styles/mapbox/outdoors-v12',
  topo:      'mapbox://styles/mapbox/outdoors-v12',
};

// ── Map init ──────────────────────────────────────────────────────────────────
const map = new mapboxgl.Map({
  container: 'map',
  style:     BASEMAP_STYLES.satellite,
  center:    [__CENTER_LNG__, __CENTER_LAT__],
  zoom:      __ZOOM__,
  pitch:     25,
});

// ── Address search geocoder (top-left, above zoom controls) ──────────────────
let _searchMarker = null;
if (typeof MapboxGeocoder !== 'undefined') {
  const geocoder = new MapboxGeocoder({
    accessToken: mapboxgl.accessToken,
    mapboxgl: mapboxgl,
    placeholder: '🔍 Search address or place...',
    proximity: { longitude: __CENTER_LNG__, latitude: __CENTER_LAT__ },
    bbox: [-117.5, 41.5, -111.0, 49.0],
    marker: false,
  });
  map.addControl(geocoder, 'top-left');
  geocoder.on('result', e => {
    const [lng, lat] = e.result.geometry.coordinates;
    if (_searchMarker) _searchMarker.remove();
    const el = document.createElement('div');
    el.style.cssText = 'width:32px;height:32px;border-radius:50%;background:#e74c3c;display:flex;align-items:center;justify-content:center;font-size:18px;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.7);cursor:pointer;';
    el.textContent = '📍';
    _searchMarker = new mapboxgl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lng, lat])
      .setPopup(new mapboxgl.Popup({ offset: 20 }).setHTML(
        `<div class='p-title'>📍 ${e.result.place_name}</div>`
      ))
      .addTo(map);
    _searchMarker.getPopup().addTo(map);
  });
  geocoder.on('clear', () => {
    if (_searchMarker) { _searchMarker.remove(); _searchMarker = null; }
  });
}

map.addControl(new mapboxgl.NavigationControl(),  'top-left');
map.addControl(new mapboxgl.FullscreenControl(),  'top-left');
map.addControl(new mapboxgl.ScaleControl({ unit: 'imperial' }), 'bottom-right');
map.addControl(new mapboxgl.GeolocateControl({
  positionOptions: { enableHighAccuracy: true },
  trackUserLocation: true, showUserHeading: true,
}), 'top-left');

// Mapbox Draw - optional; map still works if CDN fails
let draw = null;
try {
  draw = new MapboxDraw({
    displayControlsDefault: false,
    controls: {},
    styles: [
      { id: 'gl-draw-line',            type: 'line',   filter: ['all', ['==', '$type', 'LineString'], ['!=', 'mode', 'static']], paint: { 'line-color': '#DAA520', 'line-width': 2.5, 'line-dasharray': [2, 1] } },
      { id: 'gl-draw-polygon-fill',    type: 'fill',   filter: ['all', ['==', '$type', 'Polygon'],    ['!=', 'mode', 'static']], paint: { 'fill-color': '#DAA520', 'fill-opacity': 0.15 } },
      { id: 'gl-draw-polygon-stroke',  type: 'line',   filter: ['all', ['==', '$type', 'Polygon'],    ['!=', 'mode', 'static']], paint: { 'line-color': '#DAA520', 'line-width': 2 } },
      { id: 'gl-draw-point',           type: 'circle', filter: ['all', ['==', '$type', 'Point'],      ['==', 'meta', 'vertex']], paint: { 'circle-radius': 5, 'circle-color': '#DAA520' } },
    ],
  });
} catch (e) {
  console.warn('MapboxDraw not available:', e);
}

// ── Initial map load ──────────────────────────────────────────────────────────
// Use map.on('load') for the FIRST setup.
// map.on('style.load') re-runs layers only after a basemap switch (see setBasemap()).
map.on('load', () => {
  _layersAdded = true;
  initLayers();
  if (draw) { try { map.addControl(draw, 'top-left'); } catch (_) {} }
  loadSavedMarkers();
  updateLegend();
  // Auto-enable Turkey marker mode so the user can place markers immediately
  selectMarkerType('turkey');
  // Show the welcome modal on first load
  openAboutModal();
});

// Re-init layers after setStyle() wipes all custom sources/layers.
// The _layersAdded guard prevents this from double-firing on initial load.
map.on('style.load', () => {
  if (!_layersAdded) return;
  initLayers();
  if (draw) { try { map.addControl(draw, 'top-left'); } catch (_) {} }
  updateLegend();
});

// ── Layer initialization (called on load + after basemap switch) ──────────────
function initLayers() {

  // Terrain
  if (!map.getSource('mapbox-dem')) {
    map.addSource('mapbox-dem', {
      type: 'raster-dem',
      url:  'mapbox://mapbox.mapbox-terrain-dem-v1',
      tileSize: 512, maxzoom: 14,
    });
  }
  map.setTerrain({ source: 'mapbox-dem', exaggeration: 1.4 });

  // 1. Species Range (off by default)
  map.addSource('species-range', { type: 'geojson', data: speciesRangeData });
  map.addLayer({ id: 'range-fill', type: 'fill', source: 'species-range',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#FF6600', 'fill-opacity': 0.38 },
  });

  // 3. AccessYes Properties (off by default)
  map.addSource('access-yes', { type: 'geojson', data: accessYesData });
  map.addLayer({ id: 'access-fill', type: 'fill', source: 'access-yes',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#27AE60', 'fill-opacity': 0.35 },
  });
  map.addLayer({ id: 'access-outline', type: 'line', source: 'access-yes',
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#1E8449', 'line-width': 1.2, 'line-opacity': 0.9 },
  });

  // 4 & 5. Turkey GMU (on by default)
  map.addSource('turkey-gmu', { type: 'geojson', data: turkeyGmuData });

  // Deduplicated label source: one point per unique GMU+Season (highest-priority Hunt_Type wins).
  // Prevents duplicate labels when multiple polygon features exist for the same GMU+Season.
  const GMU_PRIORITY = { Controlled: 3, Youth: 2, General: 1 };
  const labelMap = {};
  (turkeyGmuData.features || []).forEach(f => {
    const key = (f.properties.GMU || '') + '|' + (f.properties.Season || '');
    const existing = labelMap[key];
    const thisP = GMU_PRIORITY[f.properties.Hunt_Type] || 0;
    const prevP = existing ? (GMU_PRIORITY[existing.Hunt_Type] || 0) : -1;
    if (!existing || thisP > prevP) {
      // Store centroid of this feature's geometry as the label point
      let coords;
      try { coords = turf.centroid(f).geometry.coordinates; }
      catch (_) {
        const b = turf.bbox(f);
        coords = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
      }
      labelMap[key] = { coords, props: f.properties };
    }
  });
  const labelGeoJSON = {
    type: 'FeatureCollection',
    features: Object.values(labelMap).map(({ coords, props }) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: coords },
      properties: props,
    })),
  };
  map.addSource('turkey-gmu-labels', { type: 'geojson', data: labelGeoJSON });

  // Drop shadow - offset black fill; persists at higher zoom levels now
  map.addLayer({ id: 'gmu-shadow', type: 'fill', source: 'turkey-gmu',
    filter: ['==', ['get', 'Season'], 'Spring'],
    paint: {
      'fill-color': '#000000',
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0.45, 9, 0.30, 12, 0.12, 15, 0.04],
      'fill-translate': [6, 6],
      'fill-translate-anchor': 'viewport',
    },
  });
  // Transparent fill - click target only (border-only visual style)
  map.addLayer({ id: 'gmu-fill', type: 'fill', source: 'turkey-gmu',
    filter: ['==', ['get', 'Season'], 'Spring'],
    paint: { 'fill-color': '#000000', 'fill-opacity': 0 },
  });
  // Interior shade - bright green tint that fades to invisible as you zoom in
  map.addLayer({ id: 'gmu-shade', type: 'fill', source: 'turkey-gmu',
    filter: ['==', ['get', 'Season'], 'Spring'],
    paint: {
      'fill-color': '#00FF7F',
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0.18, 9, 0.08, 11, 0],
    },
  });
  // Outline glow - wider blurred dark halo behind the boundary for a drop-shadow effect
  map.addLayer({ id: 'gmu-outline-glow', type: 'line', source: 'turkey-gmu',
    filter: ['==', ['get', 'Season'], 'Spring'],
    paint: {
      'line-color': '#002211',
      'line-width': ['interpolate', ['linear'], ['zoom'], 5, 8, 10, 14],
      'line-opacity': 0.45,
      'line-blur': 6,
    },
  });
  // Bright green thick boundary (spring-green, distinct from neon #39FF14 deciduous layer)
  map.addLayer({ id: 'gmu-outline', type: 'line', source: 'turkey-gmu',
    filter: ['==', ['get', 'Season'], 'Spring'],
    paint: {
      'line-color': '#00FF7F',
      'line-width': ['interpolate', ['linear'], ['zoom'], 5, 2.5, 10, 4.5],
      'line-opacity': 0.95,
    },
  });
  // Label - filter is updated by applyGmuFilters():
  //   Spring or both → Spring only (one label per GMU, no duplicates)
  //   Fall only → Fall (so labels still appear when Spring is unchecked)
  map.addLayer({ id: 'gmu-label', type: 'symbol', source: 'turkey-gmu-labels',
    filter: ['==', ['get', 'Season'], 'Spring'],
    layout: {
      'text-field':            ['concat', 'Unit ', ['coalesce', ['get', 'GMU'], '']],
      'text-size':             ['interpolate', ['linear'], ['zoom'], 6, 13, 11, 22],
      'text-font':             ['literal', ['Open Sans Bold', 'Arial Unicode MS Bold']],
      'text-anchor':           'center',
      'text-allow-overlap':    false,
      'text-ignore-placement': false,
      'symbol-sort-key': 0,
    },
    paint: {
      'text-color':      '#1a1a1a',
      'text-halo-color': 'rgba(255,255,255,0.90)',
      'text-halo-width': 2.5,
      'text-opacity':    0.68,
    },
  });

  // 6. Water Features - NHD Small Scale (off by default)
  //    feature_type = "flowline" (LineString rivers/streams)
  //                   "waterbody" (Polygon lakes/ponds)
  map.addSource('water', { type: 'geojson', data: waterData });

  // Lake / pond fill
  map.addLayer({ id: 'water-fill', type: 'fill', source: 'water',
    filter: ['==', ['get', 'feature_type'], 'waterbody'],
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#2980b9', 'fill-opacity': 0.5 },
  });

  // Lake / pond outline
  map.addLayer({ id: 'water-fill-outline', type: 'line', source: 'water',
    filter: ['==', ['get', 'feature_type'], 'waterbody'],
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#1a5276', 'line-width': 0.8, 'line-opacity': 0.8 },
  });

  // River / stream lines - perennial darker, intermittent lighter
  map.addLayer({ id: 'water-line', type: 'line', source: 'water',
    filter: ['==', ['get', 'feature_type'], 'flowline'],
    layout: { visibility: 'none', 'line-cap': 'round', 'line-join': 'round' },
    paint:  {
      'line-color': ['case', ['boolean', ['get', 'perennial'], true], '#2471a3', '#85c1e9'],
      'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.8, 12, 2.5],
      'line-opacity': 0.9,
    },
  });

  // Water name labels (rivers and named lakes) - visible at zoom 9+
  map.addLayer({ id: 'water-label', type: 'symbol', source: 'water',
    filter: ['!=', ['coalesce', ['get', 'name'], ''], ''],
    layout: {
      visibility: 'none',
      'text-field': ['get', 'name'],
      'text-font': ['DIN Pro Italic', 'Arial Unicode MS Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 9, 10, 13, 13],
      'symbol-placement': ['case',
        ['==', ['get', 'feature_type'], 'flowline'], 'line',
        'point'
      ],
      'text-offset': [0, 0.5],
      'text-anchor': 'top',
      'text-max-angle': 30,
    },
    paint: {
      'text-color': '#1a5276',
      'text-halo-color': 'rgba(255,255,255,0.8)',
      'text-halo-width': 1.5,
    },
    minzoom: 9,
  });

  // 8a. Motorized Roads & Trails - MVUM (off by default)
  // Color by surface type: paved=blue, gravel=gold, native/dirt=orange-red, default=gray
  map.addSource('motorized-trails', { type: 'geojson', data: motorizedTrailsData });
  map.addLayer({ id: 'motorized-line', type: 'line', source: 'motorized-trails',
    layout: { visibility: 'none', 'line-cap': 'round', 'line-join': 'round' },
    paint:  {
      // Color by final_class (unified across BLM PLAN_MODE_TRNSPRT + USFS MVUM class/surface)
      'line-color': ['match', ['upcase', ['coalesce', ['get', 'final_class'], '']],
        // Paved / highway
        'PAVED',                   '#74b9ff',
        'HIGHWAY',                 '#74b9ff',
        'HIGHWAY VEHICLE USE',     '#74b9ff',
        'HIGHWAY_VEHICLE_USE',     '#74b9ff',
        'PAVED-ROAD',              '#74b9ff',
        // Gravel / aggregate / improved
        'GRAVEL',                  '#fdcb6e',
        'AGGREGATE',               '#fdcb6e',
        'GRAVEL-ROAD',             '#fdcb6e',
        'IMPROVED SURFACE',        '#fdcb6e',
        'IMPROVED',                '#fdcb6e',
        // Native / dirt / primitive / high-clearance
        'NATIVE MATERIAL',         '#e17055',
        'NATIVE_MATERIAL',         '#e17055',
        'DIRT',                    '#e17055',
        'PRIMITIVE',               '#e17055',
        'HIGH CLEARANCE VEHICLE',  '#e17055',
        'HIGH_CLEARANCE_VEHICLE',  '#e17055',
        'HIGH CLEARANCE',          '#e17055',
        'HIGH_CLEARANCE',          '#e17055',
        'NATIVE-ROAD',             '#e17055',
        '#b2bec3'
      ],
      'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.0, 12, 2.8],
      'line-opacity': 0.9,
    },
  });

  // 8b. Non-motorized Trails - MVUM (off by default)
  // Warm earthy dashed line to distinguish from roads at a glance
  map.addSource('trails', { type: 'geojson', data: trailsData });
  map.addLayer({ id: 'trails-line', type: 'line', source: 'trails',
    layout: { visibility: 'none', 'line-cap': 'butt', 'line-join': 'round' },
    paint:  {
      'line-color':     '#c0392b',
      'line-width':     ['interpolate', ['linear'], ['zoom'], 6, 0.8, 12, 2.0],
      'line-opacity':   0.85,
      'line-dasharray': [2, 3],
    },
  });

  // 9. Campgrounds - render ⛺ via canvas so emoji shows on satellite imagery
  if (!map.hasImage('campground-icon')) {
    const sz = 64;
    const cv = document.createElement('canvas');
    cv.width = sz; cv.height = sz;
    const ctx = cv.getContext('2d');
    ctx.font = `${Math.round(sz * 0.72)}px serif`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('⛺', sz / 2, sz / 2);
    map.addImage('campground-icon', ctx.getImageData(0, 0, sz, sz));
  }
  map.addSource('campgrounds', { type: 'geojson', data: campgroundsData });
  map.addLayer({ id: 'camps-circle', type: 'symbol', source: 'campgrounds',
    layout: {
      visibility:           'none',
      'icon-image':         'campground-icon',
      'icon-size':          0.55,
      'icon-anchor':        'center',
      'icon-allow-overlap': true,
    },
    paint: { 'icon-opacity': 0.95 },
  });
  map.addLayer({ id: 'camps-label', type: 'symbol', source: 'campgrounds',
    minzoom: 10,
    layout: { visibility: 'none', 'text-field': ['coalesce', ['get', 'site_name'], 'Campground'], 'text-size': 10, 'text-anchor': 'top', 'text-offset': [0, 1], 'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'] },
    paint:  { 'text-color': '#f5deb3', 'text-halo-color': '#000', 'text-halo-width': 1.2 },
  });

  // 10. Regional Offices - 🏛️ emoji via canvas (emoji won't render in SDF glyph layers)
  if (!map.hasImage('offices-icon')) {
    const sz = 64;
    const cv = document.createElement('canvas');
    cv.width = sz; cv.height = sz;
    const ctx = cv.getContext('2d');
    ctx.font = `${Math.round(sz * 0.72)}px serif`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('🏛️', sz / 2, sz / 2);
    map.addImage('offices-icon', ctx.getImageData(0, 0, sz, sz));
  }
  map.addSource('offices', { type: 'geojson', data: officesData });
  map.addLayer({ id: 'offices-circle', type: 'symbol', source: 'offices',
    layout: {
      visibility:           'none',
      'icon-image':         'offices-icon',
      'icon-size':          0.55,
      'icon-anchor':        'center',
      'icon-allow-overlap': true,
    },
    paint: { 'icon-opacity': 0.95 },
  });
  map.addLayer({ id: 'offices-label', type: 'symbol', source: 'offices',
    layout: { visibility: 'none', 'text-field': ['coalesce', ['get', 'office_name'], 'IDFG Office'], 'text-size': 11, 'text-anchor': 'top', 'text-offset': [0, 1], 'text-font': ['Open Sans Semibold', 'Arial Unicode MS Regular'] },
    paint:  { 'text-color': '#DAA520', 'text-halo-color': '#000', 'text-halo-width': 1.5 },
  });

  // 11. Closed Areas (off by default)
  map.addSource('closed-areas', { type: 'geojson', data: closedAreasData });
  map.addLayer({ id: 'closed-fill', type: 'fill', source: 'closed-areas',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#e74c3c', 'fill-opacity': 0.35 },
  });
  map.addLayer({ id: 'closed-outline', type: 'line', source: 'closed-areas',
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#c0392b', 'line-width': 2, 'line-dasharray': [3, 2], 'line-opacity': 0.9 },
  });

  // 12. Burned Areas (off by default)
  map.addSource('burned-areas', { type: 'geojson', data: burnedAreasData });
  map.addLayer({ id: 'burned-fill', type: 'fill', source: 'burned-areas',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#e67e22', 'fill-opacity': 0.40 },
  });
  // 13. Logging Clearings (off by default)
  map.addSource('logging-areas', { type: 'geojson', data: loggingAreasData });
  map.addLayer({ id: 'logging-fill', type: 'fill', source: 'logging-areas',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#d4e157', 'fill-opacity': 0.38 },
  });

  // 13b. Deciduous Forest - NLCD DN=41 (off by default)
  map.addSource('decid-forest', { type: 'geojson', data: decidForestData });
  map.addLayer({ id: 'decid-forest-fill', type: 'fill', source: 'decid-forest',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#39FF14', 'fill-opacity': 0.35 },
  });
  map.addLayer({ id: 'decid-forest-outline', type: 'line', source: 'decid-forest',
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#228B22', 'line-width': 0.8, 'line-opacity': 0.70 },
  });

  // 13c. Cropland - NLCD DN=82 (off by default)
  map.addSource('cropland', { type: 'geojson', data: croplandData });
  map.addLayer({ id: 'cropland-fill', type: 'fill', source: 'cropland',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#d4a017', 'fill-opacity': 0.40 },
  });
  map.addLayer({ id: 'cropland-outline', type: 'line', source: 'cropland',
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#7d5a00', 'line-width': 0.8, 'line-opacity': 0.7 },
  });

  // 14. Current Snow Cover - NIC IMS (off by default)
  map.addSource('snow-cover', { type: 'geojson', data: snowCoverData });
  map.addLayer({ id: 'snow-fill', type: 'fill', source: 'snow-cover',
    layout: { visibility: 'none' },
    paint:  {
      'fill-color':   '#dff0ff',
      'fill-opacity': 0.60,
    },
  });
  map.addLayer({ id: 'snow-outline', type: 'line', source: 'snow-cover',
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#a8d4f5', 'line-width': 1.2, 'line-opacity': 0.85 },
  });

  // 15. Public Access - Idaho SMA land ownership (off by default)
  map.addSource('public-access', { type: 'geojson', data: publicAccessData });
  map.addLayer({ id: 'public-fill', type: 'fill', source: 'public-access',
    layout: { visibility: 'none' },
    paint:  {
      'fill-color': ['match', ['get', 'agency'],
        'BLM',   '#f5e642',
        'USFS',  '#2ca050',
        'NPS',   '#5c8a35',
        'FWS',   '#4a90d9',
        'IDL',   '#b0b0b0',
        'IDFG',  '#a0b4c8',
        'BOR',   '#2980b9',
        'DOD',   '#8e44ad',
        'BIA',   '#e67e22',
        '#cccccc'
      ],
      // Private or unrecognized ownership = fully transparent
      'fill-opacity': ['match', ['coalesce', ['get', 'agency'], ''],
        ['BLM', 'USFS', 'NPS', 'FWS', 'IDL', 'IDFG', 'BOR', 'DOD', 'BIA'], 0.28,
        0
      ],
    },
  });
  map.addLayer({ id: 'public-outline', type: 'line', source: 'public-access',
    layout: { visibility: 'none' },
    paint:  { 'line-color': 'rgba(0,0,0,0.25)', 'line-width': 0.6, 'line-opacity': 0.7 },
  });

  // 16. IDFG Wildlife Management Areas (off by default)
  map.addSource('idfg-wma', { type: 'geojson', data: idfgWmaData });
  map.addLayer({ id: 'wma-fill', type: 'fill', source: 'idfg-wma',
    layout: { visibility: 'none' },
    paint:  { 'fill-color': '#1abc9c', 'fill-opacity': 0.25 },
  });
  map.addLayer({ id: 'wma-outline', type: 'line', source: 'idfg-wma',
    layout: { visibility: 'none' },
    paint:  { 'line-color': '#16a085', 'line-width': 1.5, 'line-opacity': 0.9 },
  });
  // wma-label intentionally omitted - WMA name labels removed per user request

  // ── Restore visibility after a basemap switch ─────────────────────────────
  Object.entries(layerVisibility).forEach(([id, vis]) => {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
  });

  applyGmuFilters();

  // ── State boundaries from Mapbox built-in composite source ───────────────────
  try {
    map.addLayer({
      id: 'state-borders',
      type: 'line',
      source: 'composite',
      'source-layer': 'admin',
      filter: ['all', ['==', ['get', 'admin_level'], 1], ['==', ['get', 'maritime'], 'false']],
      paint: {
        'line-color': '#ffffff',
        'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1.5, 8, 2.5, 12, 3],
        'line-opacity': 0.65,
        'line-dasharray': [5, 2],
      },
    });
  } catch (_) {}

  // ── Render order: polygon fills → lines → circles/symbols ───────────────────
  // Move line layers above all polygon fills
  ['access-outline', 'water-fill-outline', 'water-line',
   'decid-forest-outline', 'cropland-outline', 'snow-outline', 'public-outline',
   'wma-outline', 'closed-outline', 'motorized-line', 'trails-line', 'gmu-outline',
  ].forEach(id => { if (map.getLayer(id)) map.moveLayer(id); });
  // Move point/symbol layers above all lines
  ['water-label', 'gmu-label',
   'camps-circle', 'camps-label', 'offices-circle', 'offices-label',
  ].forEach(id => { if (map.getLayer(id)) map.moveLayer(id); });

  attachPopups();

  // Pointer cursor on clickable layers
  ['gmu-fill','access-fill','offices-circle','water-line','water-fill','motorized-line','trails-line','camps-circle','closed-fill','burned-fill','logging-fill','decid-forest-fill','cropland-fill','snow-fill','public-fill','wma-fill'].forEach(lyr => {
    map.on('mouseenter', lyr, () => { if (!markerModeActive) map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', lyr, () => { if (!markerModeActive) map.getCanvas().style.cursor = ''; });
  });
}

// ── Popup section toggle (global - called from inline onclick inside popup HTML) ──
window.togglePopupSection = function(hdr) {
  const isOpen = hdr.classList.contains('p-sec-open');
  hdr.classList.toggle('p-sec-open', !isOpen);
  hdr.nextElementSibling.classList.toggle('p-sec-hidden', isOpen);
  hdr.querySelector('.p-chev').textContent = isOpen ? '▾' : '▴';
};

// ── Draggable popups (mouse drag on handle repositions anchor) ────────────────
function makePopupDraggable(popup) {
  const el = popup.getElement();
  const handle = el.querySelector('.popup-drag-handle');
  if (!handle) return;

  let dragging = false, startX, startY, startLngLat;

  handle.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    dragging   = true;
    startX     = e.clientX;
    startY     = e.clientY;
    startLngLat = popup.getLngLat();
    map.dragPan.disable();
    e.stopPropagation();
    e.preventDefault();
  });

  const onMove = e => {
    if (!dragging) return;
    const origin = map.project(startLngLat);
    popup.setLngLat(map.unproject([origin.x + (e.clientX - startX), origin.y + (e.clientY - startY)]));
  };
  const onUp = () => {
    if (dragging) { dragging = false; map.dragPan.enable(); }
  };

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup',   onUp);
  popup.on('close', () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup',   onUp);
  });
}

// ── Popups ────────────────────────────────────────────────────────────────────
function attachPopups() {
  if (_popupsAttached) return;
  _popupsAttached = true;

  const CLICKABLE = [
    'gmu-fill', 'closed-fill', 'wma-fill', 'access-fill', 'offices-circle',
    'camps-circle', 'burned-fill', 'logging-fill', 'water-fill', 'water-line',
    'motorized-line', 'trails-line', 'decid-forest-fill', 'cropland-fill',
    'snow-fill', 'public-fill',
  ];

  function badge(t) {
    if (t === 'Controlled') return `<span class='p-badge badge-draw'>🎯 Controlled</span>`;
    if (t === 'Youth')      return `<span class='p-badge badge-youth'>🟢 Youth</span>`;
    return `<span class='p-badge badge-otc'>🗺️ General / OTC</span>`;
  }
  function fmtAcres(v) {
    return v != null ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }) + ' ac' : 'N/A';
  }

  function section(layerId, p) {
    switch (layerId) {
      case 'gmu-fill': {
        let allHunts = [];
        try { allHunts = JSON.parse(p.all_hunts_json || '[]'); } catch (_) {}
        const seasonIcon  = p.Season === 'Spring' ? '🌿' : '🍂';
        const allTypes    = new Set(allHunts.map(h => h.Hunt_Type));
        const primaryType = allTypes.has('General') ? 'General' : allTypes.has('Controlled') ? 'Controlled' : p.Hunt_Type;
        const seen = new Set();
        const huntRows = allHunts.map(h => {
          const key = `${h.Hunt_Type}|${h.Hunt_Number}|${h.Sex}|${h.Date}`;
          if (seen.has(key)) return '';
          seen.add(key);
          const restrict = h.Restrictions ? `<tr><td colspan='3' class='p-restrict'>${h.Restrictions}</td></tr>` : '';
          return `<tr><td>${badge(h.Hunt_Type)}${h.Hunt_Number ? ` #${h.Hunt_Number}` : ''}</td><td>${h.Sex || 'N/A'}</td><td>${h.Date || 'N/A'}</td></tr>${restrict}`;
        }).join('');
        return { icon: '🦃', title: `GMU ${p.GMU || 'N/A'}`, body: `
          <table class='p-table'>
            <tr><td>Season</td>       <td>${seasonIcon} ${p.Season || 'N/A'}</td></tr>
            <tr><td>Primary Type</td> <td>${badge(primaryType)}</td></tr>
            ${p.Sex ? `<tr><td>Sex Allowed</td><td>${p.Sex}</td></tr>` : ''}
            <tr><td>Area</td>         <td>${fmtAcres(p.area_acres)}</td></tr>
          </table>
          ${allHunts.length ? `<div class='p-divider'></div>
          <div class='p-section'>Hunt Opportunities</div>
          <table class='p-table p-hunts-table'>
            <thead><tr><th>Type / Hunt #</th><th>Sex Allowed</th><th>Dates</th></tr></thead>
            <tbody>${huntRows}</tbody>
          </table>` : ''}
          <div class='p-note'>📋 <a href='https://idfg.idaho.gov/sites/default/files/2026-2027_uplandgame_web.pdf' target='_blank' style='color:#74b9ff'>2026-27 Upland Game Regulations ↗</a></div>` };
      }
      case 'access-fill':
        return { icon: '🟢', title: p.property_name || 'AccessYes! Location', body: `
          <table class='p-table'>
            <tr><td>Acres</td>   <td>${fmtAcres(p.acres)}</td></tr>
            <tr><td>County</td>  <td>${p.county          || 'N/A'}</td></tr>
            <tr><td>Access</td>  <td>${p.access_type     || 'Public hunting'}</td></tr>
            <tr><td>Species</td> <td>${p.species_allowed || 'See regulations'}</td></tr>
            <tr><td>Opens</td>   <td>${p.open_date       || 'See posting'}</td></tr>
            <tr><td>Closes</td>  <td>${p.close_date      || 'See posting'}</td></tr>
            <tr><td>Notes</td>   <td>${p.restrictions    || 'None listed'}</td></tr>
          </table>
          <div class='p-note'>🔒 Private land - access via IDFG agreement only</div>` };

      case 'offices-circle':
        return { icon: '🏛️', title: p.office_name || 'IDFG Regional Office', body: `
          <table class='p-table'>
            <tr><td>Region</td>  <td>${p.region      || 'N/A'}</td></tr>
            <tr><td>Address</td> <td>${p.full_address || p.address || 'N/A'}</td></tr>
            <tr><td>Phone</td>   <td>${p.phone        || 'N/A'}</td></tr>
            <tr><td>Hours</td>   <td>${p.hours        || 'N/A'}</td></tr>
            ${p.email   ? `<tr><td>Email</td>  <td>${p.email}</td></tr>` : ''}
            ${p.website ? `<tr><td>Website</td><td><a href='${p.website}' target='_blank' style='color:#74b9ff'>Visit</a></td></tr>` : ''}
          </table>
          <div class='p-note'>📋 Stop here for surplus tags, maps, and local intel</div>` };

      case 'water-line': {
        const wt = p.water_type || '';
        const isIntermittent = wt === 'intermittent_stream' ||
                               p.perennial === false || p.perennial === 'false';
        const typeLabel = isIntermittent ? '🌊 Spring Runoff Stream' : '💧 Year Round River / Stream';
        const flowLabel = isIntermittent ? '⚡ Spring Runoff / Intermittent' : '✅ Year Round / Perennial';
        const title     = p.name || (isIntermittent ? 'Spring Runoff Stream' : 'River / Stream');
        const waterNote = isIntermittent
          ? '🦃 Spring runoff draws early-season turkeys to drink - scout stream bottoms at dawn'
          : '🦃 Year-round corridors are key travel routes - set up near crossings at first light';
        return { icon: '🏞️', title, body: `
          <table class='p-table'>
            <tr><td>Type</td><td>${typeLabel}</td></tr>
            <tr><td>Flow</td><td>${flowLabel}</td></tr>
          </table>
          <div class='p-note'>${waterNote}</div>` };
      }
      case 'water-fill':
        return { icon: '🏔️', title: p.name || 'Lake / Reservoir', body: `
          <table class='p-table'>
            <tr><td>Type</td>     <td>🏔️ Lake / Reservoir</td></tr>
            <tr><td>Permanent</td><td>✅ Year Round</td></tr>
          </table>
          <div class='p-note'>🦃 Lakes and ponds attract turkeys for water and bugging - focus edges at sunrise and evening</div>` };

      case 'motorized-line': {
        const classIcon = fc => {
          const v = (fc || '').toUpperCase();
          if (v.includes('PAVED') || v.includes('HIGHWAY')) return '🔵';
          if (v.includes('GRAVEL') || v.includes('AGGREGATE') || v.includes('IMPROVED')) return '🟡';
          if (v.includes('NATIVE') || v.includes('DIRT') || v.includes('PRIMITIVE') || v.includes('HIGH')) return '🟠';
          return '⚪';
        };
        return { icon: '🛣️', title: p.route_name || 'Motorized Route', body: `
          <table class='p-table'>
            <tr><td>Class</td>    <td>${classIcon(p.final_class || p.surface_type)} ${p.final_class || 'N/A'}</td></tr>
            <tr><td>Surface</td>  <td>${p.surface_type     || 'N/A'}</td></tr>
            <tr><td>Seasonal</td> <td>${p.seasonal_closure || 'N/A'}</td></tr>
            <tr><td>District</td> <td>${p.jurisdiction     || 'N/A'}</td></tr>
            <tr><td>Source</td>   <td>${p.source           || 'USFS MVUM'}</td></tr>
          </table>` };
      }
      case 'trails-line':
        return { icon: '🥾', title: p.route_name || 'Trail', body: `
          <table class='p-table'>
            <tr><td>Surface</td>  <td>${p.surface_type     || 'N/A'}</td></tr>
            <tr><td>Seasonal</td> <td>${p.seasonal_closure || 'N/A'}</td></tr>
            <tr><td>District</td> <td>${p.jurisdiction     || 'N/A'}</td></tr>
            <tr><td>Source</td>   <td>${p.source           || 'USFS MVUM'}</td></tr>
          </table>
          <div class='p-note'>🦃 Trails access ridgelines and drainages - great for scouting</div>` };

      case 'closed-fill':
        return { icon: '🚫', title: p.area_name || 'Area Closed to Turkey Hunting', body: `
          <table class='p-table'>
            <tr><td>Closure</td> <td><span class='p-badge badge-closed'>Turkey Hunting Closed</span></td></tr>
            <tr><td>Type</td>    <td>${p.closure_type || 'N/A'}</td></tr>
            <tr><td>Season</td>  <td>${p.season       || 'N/A'}</td></tr>
            <tr><td>Notes</td>   <td>${p.notes        || 'See current IDFG regulations'}</td></tr>
          </table>
          <div class='p-note'>⚠️ Verify current closures at idfg.idaho.gov</div>` };

      case 'burned-fill':
        return { icon: '🔥', title: 'Historical Fire', body: `
          <div class='p-note'>🦃 Post-fire areas often hold excellent turkey habitat</div>` };

      case 'logging-fill':
        return { icon: '🌲', title: 'Timber Harvest Area', body: `
          <table class='p-table'>
            <tr><td>Activity</td> <td>${p.activity || 'Timber Harvest'}</td></tr>
          </table>
          <div class='p-note'>🦃 Clearings provide strutting ground and early-season feeding</div>` };

      case 'decid-forest-fill':
        return { icon: '🌳', title: 'Deciduous Forest', body: `
          <div class='p-note' style='font-style:normal'>Areas dominated by trees generally greater than 5 meters tall, and greater than 20% of total vegetation cover. More than 75% of the tree species shed foliage simultaneously in response to seasonal change.</div>
          <div class='p-note'>🦃 Prime Roosting Locations</div>` };

      case 'cropland-fill':
        return { icon: '🌾', title: 'Cultivated Cropland', body: `
          <table class='p-table'>
            <tr><td>NLCD Class</td><td>82 - Cultivated Crops</td></tr>
          </table>
          <div class='p-note'>🦃 Fall foraging - waste grain and invertebrates</div>` };

      case 'snow-fill':
        return { icon: '❄️', title: 'Current Snow Cover', body: `
          <table class='p-table'>
            <tr><td>Source</td><td>${p.source || 'NIC IMS'}</td></tr>
            <tr><td>Date</td>  <td>${p.date   || 'N/A'}</td></tr>
          </table>
          <div class='p-note'>🦃 Snow may concentrate turkeys in lower-elevation open areas</div>` };

      case 'public-fill':
        return { icon: '🗺️', title: `${p.agency || 'Public'} Land`, body: `
          <table class='p-table'>
            <tr><td>Agency</td> <td>${p.agency || p.agncy_name || 'N/A'}</td></tr>
            <tr><td>Acres</td>  <td>${fmtAcres(p.gis_acres)}</td></tr>
          </table>` };

      case 'wma-fill':
        return { icon: '🦌', title: p.wma_name || 'IDFG WMA', body: `
          <table class='p-table'>
            <tr><td>WMA ID</td><td>${p.wma_id != null ? p.wma_id : 'N/A'}</td></tr>
            <tr><td>Acres</td> <td>${fmtAcres(p.acres)}</td></tr>
          </table>
          <div class='p-note'>🦃 WMAs provide public hunting access - check IDFG regulations</div>` };

      case 'camps-circle':
        return { icon: '⛺', title: p.site_name || 'Campground', body: `
          <table class='p-table'>
            <tr><td>Type</td>       <td>${p.site_type  || 'N/A'}</td></tr>
            <tr><td>Reservable</td> <td>${p.reservable || 'Unknown'}</td></tr>
            <tr><td>Phone</td>      <td>${p.phone      || 'N/A'}</td></tr>
            ${p.url ? `<tr><td>Website</td><td><a href='${p.url}' target='_blank' style='color:#74b9ff'>Recreation.gov</a></td></tr>` : ''}
          </table>` };

      default: return null;
    }
  }

  map.on('click', e => {
    if (markerModeActive) return;

    const activeLayers = CLICKABLE.filter(id => {
      if (!map.getLayer(id)) return false;
      const vis = map.getLayoutProperty(id, 'visibility');
      return !vis || vis === 'visible';
    });
    const features = map.queryRenderedFeatures(e.point, { layers: activeLayers });
    if (!features.length) return;

    // One section per layer - first feature per layer wins
    const seenLayers = new Set();
    const sections   = [];
    for (const f of features) {
      if (seenLayers.has(f.layer.id)) continue;
      seenLayers.add(f.layer.id);
      const s = section(f.layer.id, f.properties);
      if (s) sections.push(s);
    }
    if (!sections.length) return;

    let html;
    if (sections.length === 1) {
      const s = sections[0];
      html = `<div class='p-title'>${s.icon} ${s.title}</div><div class='p-divider'></div>${s.body}`;
    } else {
      html = sections.map((s, i) => `
        <div class='p-sec-hdr${i === 0 ? ' p-sec-open' : ''}' onclick='togglePopupSection(this)'>
          <span class='p-sec-label'>${s.icon} ${s.title}</span>
          <span class='p-chev'>${i === 0 ? '▴' : '▾'}</span>
        </div>
        <div class='p-sec-body${i === 0 ? '' : ' p-sec-hidden'}'>
          ${s.body}
        </div>`).join('<div class="p-sec-sep"></div>');
    }
    // Prepend drag handle so users can reposition the popup
    html = `<div class='popup-drag-handle' title='Drag to move'>⠿</div>` + html;

    if (activePopup) activePopup.remove();
    activePopup = new mapboxgl.Popup({ maxWidth: '360px' })
      .setLngLat(e.lngLat)
      .setHTML(html)
      .addTo(map);
    activePopup.on('close', () => { activePopup = null; });
    makePopupDraggable(activePopup);
  });

}

function _deadCode() { // old per-layer handlers kept here only to preserve git blame; never called
  map.on('click', 'gmu-fill', e => {
    const p = e.features[0].properties;
    let allHunts = [];
    try { allHunts = JSON.parse(p.all_hunts_json || '[]'); } catch (_) {}

    function badge(t) {
      if (t === 'Controlled') return `<span class='p-badge badge-draw'>🎯 Controlled</span>`;
      if (t === 'Youth')      return `<span class='p-badge badge-youth'>🟢 Youth</span>`;
      return `<span class='p-badge badge-otc'>🗺️ General / OTC</span>`;
    }
    const area        = p.area_acres  != null ? Number(p.area_acres).toLocaleString() + ' acres' : 'N/A';
    const seasonIcon  = p.Season === 'Spring' ? '🌿' : '🍂';

    // Display primary type: General > Controlled > fallback (never lead with Youth)
    const allTypes = new Set(allHunts.map(h => h.Hunt_Type));
    const primaryDisplayType = allTypes.has('General') ? 'General'
      : allTypes.has('Controlled') ? 'Controlled'
      : p.Hunt_Type;

    const seen = new Set();
    const huntRows = allHunts.map(h => {
      const key = `${h.Hunt_Type}|${h.Hunt_Number}|${h.Date}`;
      if (seen.has(key)) return '';
      seen.add(key);
      const restrict = h.Restrictions ? `<tr><td colspan='2' class='p-restrict'>${h.Restrictions}</td></tr>` : '';
      return `<tr><td>${badge(h.Hunt_Type)}${h.Hunt_Number ? ` #${h.Hunt_Number}` : ''}</td><td>${h.Date || 'N/A'}</td></tr>${restrict}`;
    }).join('');

    new mapboxgl.Popup({ maxWidth: '340px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🦃 GMU ${p.GMU || 'N/A'}</div>
        <div class='p-divider'></div>
        <table class='p-table'>
          <tr><td>Season</td>      <td>${seasonIcon} ${p.Season || 'N/A'}</td></tr>
          <tr><td>Primary Type</td><td>${badge(primaryDisplayType)}</td></tr>
          <tr><td>Area</td>        <td>${area}</td></tr>
        </table>
        ${allHunts.length ? `
          <div class='p-divider'></div>
          <div class='p-section'>Hunt Opportunities</div>
          <table class='p-table p-hunts-table'>
            <thead><tr><th>Type / Hunt #</th><th>Dates</th></tr></thead>
            <tbody>${huntRows}</tbody>
          </table>` : ''}
        <div class='p-note'>📋 Verify dates at idfg.idaho.gov before hunting</div>
      `)
      .addTo(map);
  });

  // AccessYes
  map.on('click', 'access-fill', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '290px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🟢 AccessYes! Location</div>
        <div class='p-divider'></div>
        <table class='p-table'>
          <tr><td>Name</td>    <td>${p.property_name   || 'N/A'}</td></tr>
          <tr><td>Acres</td>   <td>${p.acres != null ? Number(p.acres).toLocaleString() : 'N/A'}</td></tr>
          <tr><td>County</td>  <td>${p.county          || 'N/A'}</td></tr>
          <tr><td>Access</td>  <td>${p.access_type     || 'Public hunting'}</td></tr>
          <tr><td>Species</td> <td>${p.species_allowed || 'See regulations'}</td></tr>
          <tr><td>Opens</td>   <td>${p.open_date       || 'See posting'}</td></tr>
          <tr><td>Closes</td>  <td>${p.close_date      || 'See posting'}</td></tr>
          <tr><td>Notes</td>   <td>${p.restrictions    || 'None listed'}</td></tr>
        </table>
        <div class='p-note'>🔒 Private land - access via IDFG agreement only</div>
      `)
      .addTo(map);
  });

  // Regional Offices
  map.on('click', 'offices-circle', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '270px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🏛️ ${p.office_name || 'IDFG Regional Office'}</div>
        <div class='p-divider'></div>
        <table class='p-table'>
          <tr><td>Region</td>  <td>${p.region      || 'N/A'}</td></tr>
          <tr><td>Address</td> <td>${p.full_address || p.address || 'N/A'}</td></tr>
          <tr><td>Phone</td>   <td>${p.phone        || 'N/A'}</td></tr>
          <tr><td>Hours</td>   <td>${p.hours        || 'N/A'}</td></tr>
          ${p.email   ? `<tr><td>Email</td>  <td>${p.email}</td></tr>` : ''}
          ${p.website ? `<tr><td>Website</td><td><a href='${p.website}' target='_blank' style='color:#74b9ff'>Visit</a></td></tr>` : ''}
        </table>
        <div class='p-note'>📋 Stop here for surplus tags, maps, and local intel</div>
      `)
      .addTo(map);
  });

  // Water Features - flowlines (rivers / streams)
  map.on('click', 'water-line', e => {
    const p = e.features[0].properties;
    const label = p.perennial === true || p.perennial === 'true' ? '✅ Perennial' : '⚠️ Intermittent / Seasonal';
    new mapboxgl.Popup({ maxWidth: '240px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🏞️ ${p.name || 'Unnamed Stream / River'}</div>
        <table class='p-table'>
          <tr><td>Type</td>     <td>River / Stream</td></tr>
          <tr><td>Flow</td>     <td>${label}</td></tr>
        </table>
        <div class='p-note'>${p.perennial === true || p.perennial === 'true'
          ? '🦃 Year-round corridors are key travel routes - set up near crossings at first light'
          : '🦃 Spring runoff draws early-season turkeys to drink - scout stream bottoms at dawn'}</div>
      `)
      .addTo(map);
  });

  // Water Features - waterbodies (lakes / ponds)
  map.on('click', 'water-fill', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '240px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🏔️ ${p.name || 'Unnamed Lake / Pond'}</div>
        <table class='p-table'>
          <tr><td>Type</td>     <td>Lake / Pond</td></tr>
          <tr><td>Permanent</td><td>✅ Yes</td></tr>
        </table>
        <div class='p-note'>🦃 Lakes and ponds attract turkeys for water and bugging - focus edges at sunrise and evening</div>
      `)
      .addTo(map);
  });

  // Motorized Roads & Trails
  map.on('click', 'motorized-line', e => {
    const p = e.features[0].properties;
    const classIcon = fc => {
      const v = (fc || '').toUpperCase();
      if (v.includes('PAVED') || v.includes('HIGHWAY')) return '🔵';
      if (v.includes('GRAVEL') || v.includes('AGGREGATE') || v.includes('IMPROVED')) return '🟡';
      if (v.includes('NATIVE') || v.includes('DIRT') || v.includes('PRIMITIVE') || v.includes('HIGH')) return '🟠';
      return '⚪';
    };
    const icon = classIcon(p.final_class || p.surface_type);
    new mapboxgl.Popup({ maxWidth: '270px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🛣️ ${p.route_name || 'Motorized Route'}</div>
        <table class='p-table'>
          <tr><td>Class</td>    <td>${icon} ${p.final_class || 'N/A'}</td></tr>
          <tr><td>Surface</td>  <td>${p.surface_type || 'N/A'}</td></tr>
          <tr><td>Seasonal</td> <td>${p.seasonal_closure || 'N/A'}</td></tr>
          <tr><td>District</td> <td>${p.jurisdiction || 'N/A'}</td></tr>
          <tr><td>Source</td>   <td>${p.source || 'USFS MVUM'}</td></tr>
        </table>
      `)
      .addTo(map);
  });

  // Non-motorized Trails
  map.on('click', 'trails-line', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '270px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🥾 ${p.route_name || 'Trail'}</div>
        <table class='p-table'>
          <tr><td>Surface</td>  <td>${p.surface_type || 'N/A'}</td></tr>
          <tr><td>Seasonal</td> <td>${p.seasonal_closure || 'N/A'}</td></tr>
          <tr><td>District</td> <td>${p.jurisdiction || 'N/A'}</td></tr>
          <tr><td>Source</td>   <td>${p.source || 'USFS MVUM'}</td></tr>
        </table>
        <div class='p-note'>🦃 Trails access ridgelines and drainages - great for scouting on foot</div>
      `)
      .addTo(map);
  });

  // Closed Areas
  map.on('click', 'closed-fill', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '270px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🚫 ${p.area_name || 'Closed Area'}</div>
        <div class='p-divider'></div>
        <table class='p-table'>
          <tr><td>Closure</td> <td><span class='p-badge badge-closed'>Turkey Hunting Closed</span></td></tr>
          <tr><td>Type</td>    <td>${p.closure_type || 'N/A'}</td></tr>
          <tr><td>Season</td>  <td>${p.season       || 'N/A'}</td></tr>
          <tr><td>Notes</td>   <td>${p.notes        || 'See current IDFG regulations'}</td></tr>
        </table>
        <div class='p-note'>⚠️ Verify current closures at idfg.idaho.gov</div>
      `)
      .addTo(map);
  });

  // Burned Areas
  map.on('click', 'burned-fill', e => {
    new mapboxgl.Popup({ maxWidth: '240px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🔥 Historical Fire</div>
        <div class='p-note'>🦃 Post-fire areas often hold excellent turkey habitat</div>
      `)
      .addTo(map);
  });

  // Logging
  map.on('click', 'logging-fill', e => {
    const p = e.features[0].properties;
    const acres = p.gis_acres != null ? Number(p.gis_acres).toLocaleString(undefined, { maximumFractionDigits: 1 }) : 'N/A';
    new mapboxgl.Popup({ maxWidth: '270px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🌲 Timber Harvest Area</div>
        <div class='p-divider'></div>
        <table class='p-table'>
          <tr><td>Activity</td>  <td>${p.activity  || 'Timber Harvest'}</td></tr>
          <tr><td>Completed</td> <td>${p.date_done ? p.date_done.split('T')[0] : 'N/A'}</td></tr>
          <tr><td>Acres</td>     <td>${acres}</td></tr>
          <tr><td>Forest</td>    <td>${p.forest    || 'N/A'}</td></tr>
        </table>
        <div class='p-note'>🦃 Clearings provide strutting ground and early-season feeding</div>
      `)
      .addTo(map);
  });

  // Deciduous Forest
  map.on('click', 'decid-forest-fill', e => {
    new mapboxgl.Popup({ maxWidth: '240px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🌳 Deciduous Forest</div>
        <table class='p-table'>
          <tr><td>NLCD Class</td><td>41 - Deciduous Forest</td></tr>
        </table>
        <div class='p-note'>🦃 Fall roosting habitat - mast (acorn) foraging</div>
      `)
      .addTo(map);
  });

  // Cropland
  map.on('click', 'cropland-fill', e => {
    new mapboxgl.Popup({ maxWidth: '240px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🌾 Cultivated Cropland</div>
        <table class='p-table'>
          <tr><td>NLCD Class</td><td>82 - Cultivated Crops</td></tr>
        </table>
        <div class='p-note'>🦃 Fall foraging - waste grain and invertebrates</div>
      `)
      .addTo(map);
  });

  // Snow Cover
  map.on('click', 'snow-fill', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '240px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>❄️ Current Snow Cover</div>
        <table class='p-table'>
          <tr><td>Source</td> <td>${p.source || 'NIC IMS'}</td></tr>
          <tr><td>Date</td>   <td>${p.date   || 'N/A'}</td></tr>
        </table>
        <div class='p-note'>🦃 Snow may concentrate turkeys in lower-elevation open areas</div>
      `)
      .addTo(map);
  });

  // Public Access (Idaho SMA)
  map.on('click', 'public-fill', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '260px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🗺️ Public Access - ${p.agency || 'Unknown'}</div>
        <table class='p-table'>
          <tr><td>Agency</td> <td>${p.agency || p.agncy_name || 'N/A'}</td></tr>
          <tr><td>Acres</td>  <td>${p.gis_acres != null ? Number(p.gis_acres).toLocaleString(undefined, {maximumFractionDigits:0}) : 'N/A'}</td></tr>
        </table>
      `)
      .addTo(map);
  });

  // IDFG Wildlife Management Areas
  map.on('click', 'wma-fill', e => {
    const p = e.features[0].properties;
    const acres = p.acres != null ? Number(p.acres).toLocaleString() : 'N/A';
    new mapboxgl.Popup({ maxWidth: '270px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>🦌 ${p.wma_name || 'IDFG WMA'}</div>
        <div class='p-divider'></div>
        <table class='p-table'>
          <tr><td>WMA ID</td> <td>${p.wma_id != null ? p.wma_id : 'N/A'}</td></tr>
          <tr><td>Acres</td>  <td>${acres}</td></tr>
        </table>
        <div class='p-note'>🦃 WMAs provide public hunting access - check IDFG regulations for species and season rules</div>
      `)
      .addTo(map);
  });

  // Campgrounds
  map.on('click', 'camps-circle', e => {
    const p = e.features[0].properties;
    new mapboxgl.Popup({ maxWidth: '250px' })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div class='p-title'>⛺ ${p.site_name || 'Campground'}</div>
        <table class='p-table'>
          <tr><td>Type</td>       <td>${p.site_type  || 'N/A'}</td></tr>
          <tr><td>Reservable</td> <td>${p.reservable || 'Unknown'}</td></tr>
          <tr><td>Phone</td>      <td>${p.phone      || 'N/A'}</td></tr>
          ${p.url ? `<tr><td>Website</td><td><a href='${p.url}' target='_blank' style='color:#74b9ff'>Recreation.gov</a></td></tr>` : ''}
        </table>
      `)
      .addTo(map);
  });
}

// ── Draw measurement events ───────────────────────────────────────────────────
map.on('draw.create', updateMeasurements);
map.on('draw.update', updateMeasurements);
map.on('draw.delete', () => { document.getElementById('measure-display').textContent = ''; });

// ── Map click for marker placement ───────────────────────────────────────────
// Note: the popup click handler already has `if (markerModeActive) return;`
// so there is no popup conflict. We must NOT filter by queryRenderedFeatures
// here because the GMU polygon covers the entire hunting area - doing so would
// silently swallow every click and prevent the form from ever opening.
map.on('click', e => {
  if (!markerModeActive || _markerFormOpen || !selectedMarkerType) return;
  openMarkerForm(e.lngLat);
});

// ── About / Welcome modal ────────────────────────────────────────────────────
function openAboutModal() {
  const el = document.getElementById('about-overlay');
  if (el) el.classList.remove('hidden');
}
function closeAboutModal() {
  const el = document.getElementById('about-overlay');
  if (el) el.classList.add('hidden');
}

// ── Panel toggle ──────────────────────────────────────────────────────────────
function togglePanel(panelName) {
  ['layers', 'legend', 'tools', 'weather', 'season'].forEach(name => {
    const panel = document.getElementById(name + '-panel');
    const btn   = document.getElementById('btn-panel-' + name);
    if (!panel || !btn) return;
    if (name === panelName) {
      const isOpen = panel.classList.contains('open');
      panel.classList.toggle('open', !isOpen);
      btn.classList.toggle('active', !isOpen);
      // Auto-fetch forecast when weather panel opens
      if (name === 'weather' && !isOpen) getWeather();
    } else {
      panel.classList.remove('open');
      btn.classList.remove('active');
    }
  });
}

// ── Weather forecast (NWS API - no key required) ───────────────────────────
// Default location: Boise, Idaho
let _wxLat = 43.6150;
let _wxLng = -116.2023;

// On map click: update forecast location and refresh if panel is open
map.on('click', function(e) {
  _wxLat = e.lngLat.lat;
  _wxLng = e.lngLat.lng;
  if (document.getElementById('weather-panel').classList.contains('open')) {
    getWeather();
  }
});

function wxIcon(forecast) {
  const f = (forecast || '').toLowerCase();
  if (f.includes('thunder'))                      return '⛈️';
  if (f.includes('blizzard'))                     return '🌨️';
  if (f.includes('snow'))                         return '❄️';
  if (f.includes('freezing') || f.includes('ice'))return '🌨️';
  if (f.includes('sleet'))                        return '🌨️';
  if (f.includes('rain') || f.includes('shower')) return '🌧️';
  if (f.includes('drizzle'))                      return '🌦️';
  if (f.includes('fog') || f.includes('haze'))    return '🌫️';
  if (f.includes('windy') || f.includes('breezy'))return '💨';
  if (f.includes('overcast') || f.includes('cloudy')) return '☁️';
  if (f.includes('partly'))                       return '⛅';
  if (f.includes('mostly sunny') || f.includes('mostly clear')) return '🌤️';
  if (f.includes('sunny') || f.includes('clear')) return '☀️';
  return '🌤️';
}

function renderWeather(periods) {
  // Pair day + night periods; NWS returns up to 14 periods alternating day/night
  let html = '<div class="wx-grid">';
  for (let i = 0; i < periods.length && i < 14; i++) {
    const p = periods[i];
    const isDay = p.isDaytime !== false;
    if (!isDay) continue;  // render one card per daytime period only
    const night = periods[i + 1] && periods[i + 1].isDaytime === false ? periods[i + 1] : null;
    html += `
      <div class="wx-card">
        <div class="wx-day">${p.name}</div>
        <div class="wx-icon">${wxIcon(p.shortForecast)}</div>
        <div class="wx-desc">${p.shortForecast}</div>
        <div class="wx-temps">
          <span class="wx-hi">${p.temperature}°${p.temperatureUnit}</span>
          ${night ? `<span class="wx-lo"> / ${night.temperature}°</span>` : ''}
        </div>
        <div class="wx-wind">💨 ${p.windSpeed} ${p.windDirection}</div>
      </div>`;
  }
  html += '</div>';
  document.getElementById('weather-content').innerHTML = html;
}

async function getWeather(useCenterOverride) {
  if (useCenterOverride) {
    const center = map.getCenter();
    _wxLat = center.lat;
    _wxLng = center.lng;
  }
  const lat = _wxLat.toFixed(4);
  const lng = _wxLng.toFixed(4);

  document.getElementById('weather-content').innerHTML =
    '<div class="wx-loading">Loading forecast…</div>';
  document.getElementById('weather-location').textContent =
    `${Math.abs(lat)}°N, ${Math.abs(lng)}°W`;

  try {
    // Step 1: NWS points - returns the grid endpoint for this lat/lng
    const ptResp = await fetch(
      `https://api.weather.gov/points/${lat},${lng}`,
      { headers: { 'User-Agent': 'IdahoTurkeyHuntMap/1.0' } }
    );
    if (!ptResp.ok) throw new Error('Location not supported by NWS (must be in the US)');
    const ptData = await ptResp.json();

    const forecastUrl = ptData.properties?.forecast;
    if (!forecastUrl) throw new Error('No forecast endpoint returned');

    const loc = ptData.properties?.relativeLocation?.properties;
    if (loc?.city) {
      document.getElementById('weather-location').textContent =
        `Near ${loc.city}, ${loc.state}`;
    }

    // Step 2: Fetch the 7-day forecast
    const fxResp = await fetch(forecastUrl,
      { headers: { 'User-Agent': 'IdahoTurkeyHuntMap/1.0' } }
    );
    if (!fxResp.ok) throw new Error('Forecast data unavailable');
    const fxData = await fxResp.json();

    const periods = fxData.properties?.periods;
    if (!periods || periods.length === 0) throw new Error('No forecast periods returned');

    renderWeather(periods);
  } catch (err) {
    document.getElementById('weather-content').innerHTML =
      `<div class="wx-error">⚠️ ${err.message}</div>`;
  }
}

// ── Season filter ─────────────────────────────────────────────────────────────
function applySeasonFilter() {
  if (activePopup) { activePopup.remove(); activePopup = null; }
  applyGmuFilters();
}

function applyGmuFilters() {
  if (!map.getLayer('gmu-fill')) return;
  const showSpring = document.getElementById('filter-spring')?.checked ?? true;
  const showFall   = document.getElementById('filter-fall')?.checked   ?? false;
  let filter;
  if      (showSpring && showFall) filter = ['in', ['get', 'Season'], ['literal', ['Spring', 'Fall']]];
  else if (showSpring)             filter = ['==', ['get', 'Season'], 'Spring'];
  else if (showFall)               filter = ['==', ['get', 'Season'], 'Fall'];
  else                             filter = ['==', ['literal', false], true]; // show nothing
  // Label filter: Spring (or both) → Spring only, preventing duplicates.
  // Fall only → Fall, so labels still appear when Spring is unchecked.
  const labelFilter = (!showSpring && showFall)
    ? ['==', ['get', 'Season'], 'Fall']
    : ['==', ['get', 'Season'], 'Spring'];
  ['gmu-fill', 'gmu-shade', 'gmu-shadow', 'gmu-outline-glow', 'gmu-outline'].forEach(id => {
    if (map.getLayer(id)) map.setFilter(id, filter);
  });
  if (map.getLayer('gmu-label')) map.setFilter('gmu-label', labelFilter);
}

// ── Basemap switcher ──────────────────────────────────────────────────────────
function setBasemap(style) {
  // Capture current visibility so initLayers() can restore it after setStyle()
  layerVisibility = {};
  Object.values(LAYER_GROUPS).flat().forEach(id => {
    if (map.getLayer(id)) layerVisibility[id] = map.getLayoutProperty(id, 'visibility') || 'visible';
  });
  document.querySelectorAll('.basemap-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + style).classList.add('active');
  map.setStyle(BASEMAP_STYLES[style] || BASEMAP_STYLES.satellite);
}

// ── Layer toggles ─────────────────────────────────────────────────────────────
function toggleGroup(checkbox) {
  const layers = LAYER_GROUPS[checkbox.id] || [];
  const vis    = checkbox.checked ? 'visible' : 'none';
  layers.forEach(id => {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
    layerVisibility[id] = vis;
  });
  updateLegend();
}

// ── Dynamic legend: show/hide blocks based on which layers are toggled on ─────
function updateLegend() {
  document.querySelectorAll('#legend-panel [data-for]').forEach(block => {
    const anyOn = block.dataset.for.split(',').some(tid => {
      const cb = document.getElementById(tid.trim());
      return cb && cb.checked;
    });
    block.style.display = anyOn ? '' : 'none';
  });
}


// ── Draw & measurements ───────────────────────────────────────────────────────
function startDraw(mode) {
  if (!draw) return;
  if (mode === 'line')    draw.changeMode('draw_line_string');
  if (mode === 'polygon') draw.changeMode('draw_polygon');
}
function clearDraw() {
  if (draw) draw.deleteAll();
  document.getElementById('measure-display').textContent = '';
}
function updateMeasurements() {
  if (!draw) return;
  const data = draw.getAll();
  let msg = '';
  data.features.forEach(f => {
    if (f.geometry.type === 'LineString') msg = `Distance: ${turf.length(f, { units: 'miles' }).toFixed(2)} mi`;
    else if (f.geometry.type === 'Polygon') msg = `Area: ${(turf.area(f) / 4046.86).toFixed(1)} acres`;
  });
  document.getElementById('measure-display').textContent = msg;
}

// ── User Markers ──────────────────────────────────────────────────────────────
const MARKER_TYPES = {
  turkey:   { icon: '🦃', color: '#8B0000', label: 'Turkey Sighting' }, // sub-type set in form
  gobbler:  { icon: '📢', color: '#A93226', label: 'Heard Gobbler' },
  sign:     { icon: '🪶', color: '#E67E22', label: 'Turkey Sign' },     // feather = tracks/scratch sign
  camp:     { icon: '🏕️', color: '#6D4C41', label: 'Camp' },
  blind:    { icon: '🛖', color: '#1A237E', label: 'Blind/Stand' },     // hut = hunting blind
  decoys:   { icon: '🦆', color: '#1565C0', label: 'Decoys' },          // duck silhouette = decoy
  deer:     { icon: '🦌', color: '#795548', label: 'Deer' },            // brown
  bear:     { icon: '🐻', color: '#424242', label: 'Bear' },
  other:    { icon: '🐾', color: '#546E7A', label: 'Other Animal' },    // paw print
  glass:    { icon: '🔍', color: '#00695C', label: 'Glassing Spot' },
  waypoint: { icon: '📍', color: '#6A1B9A', label: 'Waypoint' },
};

let selectedMarkerType = null;
let distanceLines = {};   // markerId → { lineId, midId, dist }
let _pendingMarker   = null;   // mapboxgl.Marker shown while form is open; removed on cancel
let _markerConfirmed = false;  // set true in confirmMarker so popup.on('close') doesn't remove it
let _markerFormOpen  = false;  // true while form popup is showing; keeps unified handler from firing

function selectMarkerType(type) {
  selectedMarkerType = type;
  document.querySelectorAll('.mk-type-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('mk-btn-' + type);
  if (btn) btn.classList.add('active');
  markerModeActive = true;
  document.getElementById('btn-place-marker').classList.add('active');
  map.getCanvas().style.cursor = 'crosshair';
}

function toggleMarkerMode() {
  markerModeActive = !markerModeActive;
  document.getElementById('btn-place-marker').classList.toggle('active', markerModeActive);
  map.getCanvas().style.cursor = markerModeActive ? 'crosshair' : '';
  if (!markerModeActive)
    document.querySelectorAll('.mk-type-btn').forEach(b => b.classList.remove('active'));
}

function openMarkerForm(lnglat) {
  // Keep markerModeActive = true while form is open - prevents the unified map click
  // handler (registered later in initLayers) from firing for this same click event
  // and replacing the marker form popup with a layer info popup.
  _markerFormOpen = true;
  document.getElementById('btn-place-marker').classList.remove('active');
  document.querySelectorAll('.mk-type-btn').forEach(b => b.classList.remove('active'));
  map.getCanvas().style.cursor = '';

  const mt = MARKER_TYPES[selectedMarkerType] || MARKER_TYPES.waypoint;
  const isWaypoint = selectedMarkerType === 'waypoint';
  const isTurkey   = selectedMarkerType === 'turkey';
  const now = new Date();
  const dateStr = now.toLocaleString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
    year: 'numeric', hour: 'numeric', minute: '2-digit'
  });

  // ── Step 1: place the dot immediately so the user sees where it lands ──────
  _markerConfirmed = false;
  if (_pendingMarker) { _pendingMarker.remove(); _pendingMarker = null; }

  const pw = document.createElement('div');
  pw.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:2px;pointer-events:none;opacity:0.72;';
  const pe = document.createElement('div');
  pe.className = `user-marker-el marker-type-${selectedMarkerType}`;
  pe.style.borderColor = mt.color;
  pe.textContent = mt.icon;
  const pl = document.createElement('div');
  pl.className = 'user-marker-label';
  pl.textContent = mt.label;
  pw.appendChild(pe); pw.appendChild(pl);
  _pendingMarker = new mapboxgl.Marker({ element: pw, anchor: 'top' })
    .setLngLat([lnglat.lng, lnglat.lat]).addTo(map);

  // ── Step 2: show the editing form popup anchored to the placed dot ──────────
  const popup = new mapboxgl.Popup({ closeButton: true, maxWidth: '270px' })
    .setLngLat(lnglat)
    .setHTML(`
      <div class='marker-popup-content'>
        <div class='p-title'>${mt.icon} ${mt.label}</div>
        <div class='p-divider'></div>
        ${isTurkey ? `
          <label>Turkey Type</label>
          <select id='mk-turkey-subtype' class='marker-input' style='width:100%;background:#2a2a2a;color:#eee;border:1px solid rgba(255,255,255,0.2);border-radius:6px;padding:5px;margin-bottom:6px;font-size:13px'>
            <option value='Tom'>Tom</option>
            <option value='Hen'>Hen</option>
            <option value='Jake'>Jake</option>
            <option value='Group'>Group / Flock</option>
          </select>
        ` : ''}
        ${isWaypoint ? `
          <label>Title</label>
          <input id='mk-title' class='marker-input' type='text' placeholder='Waypoint name...'>
          <label>Date / Time</label>
          <input id='mk-datetime' class='marker-input' type='text' value='${dateStr}'>
        ` : ''}
        <label>Comment</label>
        <textarea id='mk-comment' class='marker-input' rows='2' placeholder='Notes...'></textarea>
        <div id='mk-dist-preview' style='font-size:11px;color:#74b9ff;min-height:14px;margin-bottom:4px'></div>
        <div style='display:flex;gap:6px;margin-top:4px'>
          <button class='marker-confirm-btn' onclick='confirmMarker(${lnglat.lng},${lnglat.lat})'>✔ Save</button>
          <button class='marker-cancel-btn' onclick='if(activePopup){activePopup.remove();activePopup=null;}'>Cancel</button>
        </div>
      </div>`)
    .addTo(map);
  activePopup = popup;

  // When form closes (Cancel, X, or after confirm), reset marker mode state
  popup.on('close', () => {
    _markerFormOpen    = false;
    markerModeActive   = false;
    selectedMarkerType = null;
    document.querySelectorAll('.mk-type-btn').forEach(b => b.classList.remove('active'));
    activePopup = null;
    if (!_markerConfirmed && _pendingMarker) {
      _pendingMarker.remove();
      _pendingMarker = null;
    }
  });

  // Async GPS distance preview
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(pos => {
      const dist = turf.distance(
        turf.point([pos.coords.longitude, pos.coords.latitude]),
        turf.point([lnglat.lng, lnglat.lat]),
        { units: 'miles' }
      ).toFixed(2);
      const el = document.getElementById('mk-dist-preview');
      if (el) el.textContent = `📏 ${dist} mi from your location`;
    }, () => {});
  }
}

function confirmMarker(lng, lat) {
  // Capture all type-dependent values BEFORE clearing selectedMarkerType
  const markerType = selectedMarkerType;
  const mt         = MARKER_TYPES[markerType] || MARKER_TYPES.waypoint;
  const isWaypoint = markerType === 'waypoint';
  const isTurkey   = markerType === 'turkey';
  const subtypeEl      = document.getElementById('mk-turkey-subtype');
  const turkeySubType  = subtypeEl ? subtypeEl.value : null;
  const displayLabel   = (isTurkey && turkeySubType) ? `${turkeySubType} Sighting` : mt.label;
  const titleEl  = document.getElementById('mk-title');
  const title    = titleEl ? (titleEl.value.trim() || displayLabel) : displayLabel;
  const comment  = (document.getElementById('mk-comment')?.value || '').trim();
  const datetime = isWaypoint ? (document.getElementById('mk-datetime')?.value || '') : '';
  // Signal popup.on('close') not to remove the pending dot, then clean everything up
  _markerFormOpen  = false;
  _markerConfirmed = true;
  markerModeActive = false;
  selectedMarkerType = null;
  document.querySelectorAll('.mk-type-btn').forEach(b => b.classList.remove('active'));
  if (_pendingMarker) { _pendingMarker.remove(); _pendingMarker = null; }
  if (activePopup) { activePopup.remove(); activePopup = null; }
  const data = { lng, lat, type: markerType, turkeySubType, title, comment, datetime, id: Date.now() };
  placeUserMarker(data);
  userMarkers.push(data);
  saveMarkers();
}

function addDistanceLine(fromLngLat, toLngLat, markerId) {
  const lineId = 'dist-line-' + markerId;
  const midId  = 'dist-mid-'  + markerId;
  const dist   = turf.distance(turf.point(fromLngLat), turf.point(toLngLat), { units: 'miles' }).toFixed(2);
  const lineGj = { type: 'Feature', geometry: { type: 'LineString', coordinates: [fromLngLat, toLngLat] } };
  const mid    = turf.midpoint(turf.point(fromLngLat), turf.point(toLngLat));
  const midGj  = { type: 'FeatureCollection', features: [{ ...mid, properties: { label: dist + ' mi' } }] };
  if (map.getSource(lineId)) {
    map.getSource(lineId).setData(lineGj);
    map.getSource(midId).setData(midGj);
  } else {
    map.addSource(lineId, { type: 'geojson', data: lineGj });
    map.addLayer({ id: lineId, type: 'line', source: lineId,
      paint: { 'line-color': '#74b9ff', 'line-width': 2, 'line-dasharray': [3, 3], 'line-opacity': 0.85 } });
    map.addSource(midId, { type: 'geojson', data: midGj });
    map.addLayer({ id: midId, type: 'symbol', source: midId,
      layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-anchor': 'center',
                'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'] },
      paint: { 'text-color': '#74b9ff', 'text-halo-color': '#000', 'text-halo-width': 1.5 } });
  }
  distanceLines[markerId] = { lineId, midId, dist };
}

function removeDistanceLine(markerId) {
  const dl = distanceLines[markerId];
  if (!dl) return;
  [dl.lineId, dl.midId].forEach(id => {
    if (map.getLayer(id))   map.removeLayer(id);
    if (map.getSource(id))  map.removeSource(id);
  });
  delete distanceLines[markerId];
  if (activePopup) { activePopup.remove(); activePopup = null; }
}

function drawLineToMarker(markerId, lng, lat) {
  if (!navigator.geolocation) { alert('Location unavailable - enable GPS permissions.'); return; }
  navigator.geolocation.getCurrentPosition(
    pos => { addDistanceLine([pos.coords.longitude, pos.coords.latitude], [lng, lat], markerId);
             if (activePopup) { activePopup.remove(); activePopup = null; } },
    ()  => { alert('Could not get your location. Check GPS/browser permissions.'); }
  );
}

function placeUserMarker(data) {
  const mt = MARKER_TYPES[data.type] || MARKER_TYPES.waypoint;
  const displayLabel = data.title || (data.turkeySubType ? `${data.turkeySubType} Sighting` : mt.label);

  // Wrapper: circle on top, text label below
  const wrapper = document.createElement('div');
  wrapper.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:2px;cursor:pointer;';

  const el = document.createElement('div');
  el.className = `user-marker-el marker-type-${data.type}`;
  el.title = displayLabel;
  el.style.borderColor = mt.color;
  el.textContent = mt.icon;

  const labelEl = document.createElement('div');
  labelEl.className = 'user-marker-label';
  labelEl.textContent = displayLabel;

  wrapper.appendChild(el);
  wrapper.appendChild(labelEl);

  const marker = new mapboxgl.Marker({ element: wrapper, anchor: 'top' })
    .setLngLat([data.lng, data.lat]).addTo(map);
  wrapper.addEventListener('click', ev => {
    ev.stopPropagation();
    const dl = distanceLines[data.id];
    const distRow  = dl ? `<tr><td>Distance</td><td>📏 ${dl.dist} mi</td></tr>` : '';
    const lineBtn  = dl
      ? `<button class='marker-delete-btn' style='background:rgba(231,76,60,0.15);color:#e74c3c' onclick='removeDistanceLine(${data.id})'>✖ Remove Line</button>`
      : `<button class='marker-delete-btn' style='background:rgba(116,185,255,0.15);color:#74b9ff;border-color:rgba(116,185,255,0.4)' onclick='drawLineToMarker(${data.id},${data.lng},${data.lat})'>📏 Line from me</button>`;
    const typeLabel = data.turkeySubType ? `${data.turkeySubType} Sighting` : mt.label;
    new mapboxgl.Popup({ maxWidth: '250px' })
      .setLngLat([data.lng, data.lat])
      .setHTML(`
        <div class='marker-popup-content'>
          <div class='p-title'>${mt.icon} ${displayLabel}</div>
          <table class='p-table'>
            <tr><td>Type</td>   <td>${typeLabel}</td></tr>
            ${data.datetime ? `<tr><td>Date/Time</td><td>${data.datetime}</td></tr>` : ''}
            ${data.comment ? `<tr><td>Comment</td><td>${data.comment}</td></tr>` : ''}
            <tr><td>Coords</td><td>${data.lat.toFixed(5)}, ${data.lng.toFixed(5)}</td></tr>
            ${distRow}
          </table>
          <div style='display:flex;gap:5px;margin-top:7px;flex-wrap:wrap'>
            ${lineBtn}
            <button class='marker-delete-btn' onclick='deleteMarker(${data.id})'>🗑️ Delete</button>
          </div>
        </div>`)
      .addTo(map);
  });
  data._mapboxMarker = marker;
}

function deleteMarker(id) {
  const idx = userMarkers.findIndex(m => m.id === id);
  if (idx === -1) return;
  const m = userMarkers[idx];
  if (m._mapboxMarker) m._mapboxMarker.remove();
  removeDistanceLine(id);
  userMarkers.splice(idx, 1);
  saveMarkers();
  if (activePopup) { activePopup.remove(); activePopup = null; }
}

function clearAllMarkers() {
  userMarkers.forEach(m => {
    if (m._mapboxMarker) m._mapboxMarker.remove();
    removeDistanceLine(m.id);
  });
  userMarkers = [];
  saveMarkers();
}

function updateMarkerLegend() {
  const container = document.getElementById('marker-legend-container');
  if (!container) return;
  // Collect unique marker types present on the map, preserving MARKER_TYPES order
  const usedTypes = Object.keys(MARKER_TYPES).filter(t =>
    userMarkers.some(m => m.type === t)
  );
  if (usedTypes.length === 0) {
    container.innerHTML = '';
    return;
  }
  const rows = usedTypes.map(t => {
    const mt = MARKER_TYPES[t];
    return `<div class='leg-row'>
      <div class='leg-circle' style='background:rgba(18,22,18,0.88);border:2px solid ${mt.color}'></div>
      ${mt.icon} ${mt.label}
    </div>`;
  });
  container.innerHTML = `<div class='leg-section'>My Markers</div>${rows.join('')}`;
}

function saveMarkers() {
  const toSave = userMarkers.map(({ lng, lat, type, turkeySubType, title, comment, datetime, id }) =>
    ({ lng, lat, type, turkeySubType, title, comment, datetime, id }));
  try { localStorage.setItem('turkey_markers', JSON.stringify(toSave)); } catch (_) {}
  updateMarkerLegend();
}

function loadSavedMarkers() {
  try {
    const saved = JSON.parse(localStorage.getItem('turkey_markers') || '[]');
    saved.forEach(data => {
      // Migrate old format to current types
      if (!MARKER_TYPES[data.type]) {
        const oldType = data.type;
        const legacyMap = { roost: 'waypoint', sign: 'sign', sighting: 'turkey',
                            tom: 'turkey', jake: 'turkey', hen: 'turkey', elk: 'other' };
        data.type = legacyMap[oldType] || 'waypoint';
        // Preserve turkey sub-type from old separate marker types
        if (oldType === 'tom')      data.turkeySubType = 'Tom';
        else if (oldType === 'jake') data.turkeySubType = 'Jake';
        else if (oldType === 'hen')  data.turkeySubType = 'Hen';
      }
      if (!data.title) data.title = MARKER_TYPES[data.type]?.label || data.type;
      if (!data.comment && data.notes) data.comment = data.notes;
      placeUserMarker(data);
      userMarkers.push(data);
    });
  } catch (_) {}
  updateMarkerLegend();
}
