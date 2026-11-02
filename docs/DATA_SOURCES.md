# Data sources

## NGA World Port Index through OCHA GIS

- **Source:** NGA World Port Index (Pub 150), exposed by the OCHA GIS hosted `global_world_seaport_index_202511` FeatureServer layer.
- **NGA reference:** https://msi.nga.mil/Publications/WPI
- **OCHA layer metadata:** https://gis.unocha.org/server/rest/services/Hosted/global_world_seaport_index_202511/FeatureServer/0
- **Access:** ArcGIS REST `query` operation. The implementation requests `where=1=1`, `outFields=*`, `returnGeometry=true`, `outSR=4326`, `f=geojson`.
- **Response:** GeoJSON FeatureCollection, point geometry, global dataset advertised at approximately 3,700 records; service maximum page is 2,000, so OCHA layer supports pagination. The production extractor currently requests one query and should detect/implement paging if live data exceeds max record count.
- **Fields used:** `index_no` (stable WPI identifier), `port_name`, `country`, point coordinates. Coordinates are returned in WGS84 because the query explicitly requests `outSR=4326`. If point geometry is null for a record, the extractor uses that record's explicit WPI `latitude`/`longitude` attributes. Two records did not have a usable name/coordinate combination and were counted invalid in the live run.
- **Update frequency:** No schedule stated in the layer metadata. The hosted layer is versioned by its name (`202511`); treat refresh cadence as unknown.
- **Attribution and license:** OCHA service metadata describes the dataset as World Port Index (Pub 150), but the layer's `Copyright Text` is empty. NGA identifies itself as publisher and the 2019 WPI says no U.S. Government copyright claim under Title 17. Attribute NGA WPI and OCHA GIS. Confirm reuse terms against the current WPI download and OCHA item metadata before downstream redistribution.
- **Limitations:** This is a mirror/hosted copy, not an invented NGA API. The NGA viewer is a JavaScript application with user download capability; no stable official programmatic download URL was discovered in the available documentation. The mirrored layer's country field is a two-letter code; source update date is not available per record. Ports are geography, not operational status.
- **Access tested:** Live query succeeded on 2026-11-02; 3,689 features were retrieved over two pages. 3,687 records normalized, 2 invalid, 0 duplicates. The results and per-source paths are recorded in the successful manifest.

## USGS Earthquake Catalog

- **Official documentation:** https://earthquake.usgs.gov/fdsnws/event/1/
- **Endpoint:** `https://earthquake.usgs.gov/fdsnws/event/1/query`
- **Access:** HTTP GET with documented `format=geojson`, `starttime`, and `endtime` parameters. Times sent as ISO 8601 UTC. No API key required.
- **Response:** GeoJSON FeatureCollection. Properties include `mag`, `magType`, `place`, `time` (epoch milliseconds), `url`, `status`, and `type`; point coordinates are longitude, latitude, depth km.
- **Update frequency:** USGS also documents real-time GeoJSON feeds; query results are catalog data and continuously updated. Query service recommends real-time feeds for display use.
- **Attribution/license:** U.S. Geological Survey earthquake catalog; cite USGS and retain original URLs. See USGS website terms for reuse and data caveats.
- **Limitations:** Properties may be null/absent; events can be updated or deleted. An event near a port is not evidence of closure or disruption.
- **Access tested:** Live query succeeded on 2026-11-02; 1,817 GeoJSON features retrieved and normalized for 2026-10-26 through 2026-11-02. See the successful run manifest.

## Open-Meteo Marine API (investigated only)

- **Official docs:** https://open-meteo.com/en/docs/marine-weather-api
- **Endpoint:** `/v1/marine` (documentation currently shows the marine endpoint; API host `marine-api.open-meteo.com`).
- **Parameters:** WGS84 `latitude` and `longitude` are required; lists can be comma-separated for multiple locations. Select `hourly` variables such as `wave_height` and `wave_period`; `timezone`, date interval, units, forecast length and `cell_selection` are optional or variable-dependent. `cell_selection=sea` can prefer a marine grid cell.
- **Response:** JSON with hourly/daily/current sections, units, and selected model metadata.
- **Coverage and cadence:** Model dependent. Docs describe hourly wave forecasts at about 5 km resolution, with several global and regional model sources and differing update schedules.
- **License / usage:** Open-Meteo distinguishes non-commercial and commercial/self-hosted usage. Commercial use of reserved API resources requires an API key. Attribution to Open-Meteo and underlying model providers is required by its terms; verify the applicable plan and current terms before production use.
- **Limitations:** Grid resolution/interpolation may be unsuitable near coasts and is not navigation guidance. Forecasts are conditions, not shipping delay or port disruption confirmation.
- **Access tested:** Documentation only; no API ingestion implemented on Day 1.
