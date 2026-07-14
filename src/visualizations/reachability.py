from __future__ import annotations

import geopandas as gpd

try:
    import folium
except Exception:  # pragma: no cover - optional dependency guard
    folium = None


def create_overlap_reachability_map(
    reach_gdf: gpd.GeoDataFrame,
    origin_lat: float,
    origin_lon: float,
    day_str: str,
    time_str: str,
) -> object:
    """Create a true isochrone map with 10-minute bands from a fixed origin."""
    if folium is None:
        raise ImportError("folium não está disponível para gerar visualizações de mapa")

    # Nota: NÃO usar resolve_reference_day(day_str) aqui - essa função ignora
    # deliberadamente o argumento recebido e devolve sempre o dia útil mais próximo de hoje
    # (ver docstring em overlap/transit.py), o que reescrevia silenciosamente qualquer dia de
    # referência fixo escolhido pelo chamador (ex.: REACHABILITY_REFERENCE_DAY em config.py) de
    # volta para "hoje" só na legenda, apesar dos dados terem sido calculados para o dia certo.
    ref_day_str = day_str

    def _add_mouse_origin_marker(map_obj: object) -> None:
        map_name = map_obj.get_name()
        mouse_origin_script = f"""
        (function attachMouseOrigin() {{
            var mapObj = window.{map_name};
            if (!mapObj) {{
                setTimeout(attachMouseOrigin, 50);
                return;
            }}

            mapObj.getContainer().style.cursor = 'crosshair';

            var originHalo = L.circleMarker([{origin_lat}, {origin_lon}], {{
                radius: 14,
                color: '#111111',
                fillColor: '#ffffff',
                fillOpacity: 0.18,
                opacity: 0.85,
                weight: 1.2,
                interactive: false
            }}).addTo(mapObj);

            var originPoint = L.circleMarker([{origin_lat}, {origin_lon}], {{
                radius: 7,
                color: '#b30000',
                fillColor: '#e34a33',
                fillOpacity: 1.0,
                weight: 2
            }}).addTo(mapObj);

            originPoint.bindTooltip('Origem dinâmica ({ref_day_str} {time_str})', {{sticky: true, permanent: false}});

            mapObj.on('mousemove', function(e) {{
                originHalo.setLatLng(e.latlng);
                originPoint.setLatLng(e.latlng);
                originHalo.bringToFront();
                originPoint.bringToFront();
                originPoint.setTooltipContent(
                    'Origem dinâmica ({ref_day_str} {time_str})' +
                    '<br>Lat: ' + e.latlng.lat.toFixed(5) +
                    ' | Lon: ' + e.latlng.lng.toFixed(5)
                );
            }});
        }})();
        """
        map_obj.get_root().script.add_child(folium.Element(mouse_origin_script))

    gdf = reach_gdf.copy()
    if gdf.empty or "geometry" not in gdf.columns:
        m = folium.Map(location=[origin_lat, origin_lon], zoom_start=13, tiles="cartodbpositron", control_scale=True)
        _add_mouse_origin_marker(m)
        return m

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[gdf.geometry.is_valid].copy()
    gdf["reach_min"] = gdf["reach_min"].astype(float)

    try:
        metric_crs = gdf.estimate_utm_crs()
        gdf_metric = gdf.to_crs(metric_crs) if metric_crs else gdf.to_crs("EPSG:3857")
    except Exception:
        gdf_metric = gdf.to_crs("EPSG:3857")

    color_by_band = {
        "0-10": "#1a9850",
        "10-20": "#66bd63",
        "20-30": "#a6d96a",
        "30-40": "#fee08b",
        "40-50": "#f46d43",
        "50-60": "#d73027",
    }

    # Keep feature count manageable without fixed hardcoded values: tolerance scales with map extent
    # and total vertex complexity of the current dataset.
    def _vertex_count(geom: object) -> int:
        if geom is None or geom.is_empty:
            return 0
        gtype = geom.geom_type
        if gtype == "Polygon":
            ext = len(getattr(geom.exterior, "coords", []))
            holes = sum(len(r.coords) for r in geom.interiors)
            return int(ext + holes)
        if gtype == "MultiPolygon":
            return int(sum(_vertex_count(g) for g in geom.geoms))
        if hasattr(geom, "coords"):
            return int(len(geom.coords))
        return 0

    total_vertices = int(sum(_vertex_count(geom) for geom in gdf_metric.geometry.values))
    minx, miny, maxx, maxy = gdf_metric.total_bounds
    diagonal_m = float(((maxx - minx) ** 2 + (maxy - miny) ** 2) ** 0.5)
    if total_vertices > 0 and diagonal_m > 0:
        dynamic_tolerance_m = diagonal_m / max(total_vertices ** 0.5 * 3.0, 1.0)
        if dynamic_tolerance_m > 0:
            gdf_metric = gdf_metric.copy()
            gdf_metric.geometry = gdf_metric.geometry.simplify(dynamic_tolerance_m, preserve_topology=True)

    gdf_ll = gdf_metric.to_crs("EPSG:4326").copy()
    gdf_centers = gdf_metric.copy()
    gdf_centers.geometry = gdf_centers.geometry.centroid
    gdf_centers_ll = gdf_centers.to_crs("EPSG:4326")
    gdf_ll["center_lat"] = gdf_centers_ll.geometry.y.astype(float)
    gdf_ll["center_lon"] = gdf_centers_ll.geometry.x.astype(float)
    gdf_ll["area_km2"] = (gdf_metric.geometry.area.astype(float) / 1_000_000.0)

    dynamic_zones = gdf_ll[["reach_min", "center_lat", "center_lon", "reach_mode", "area_km2", "geometry"]].copy()
    dynamic_zones = dynamic_zones[dynamic_zones.geometry.notna()].copy()
    dynamic_zones = dynamic_zones[dynamic_zones.geometry.is_valid].copy()

    if dynamic_zones.empty:
        m = folium.Map(location=[origin_lat, origin_lon], zoom_start=13, tiles="cartodbpositron", control_scale=True)
        _add_mouse_origin_marker(m)
        return m

    def _band_from_reach(v: float | None) -> str:
        if v is None:
            return "50-60"
        val = float(v)
        if val <= 10:
            return "0-10"
        if val <= 20:
            return "10-20"
        if val <= 30:
            return "20-30"
        if val <= 40:
            return "30-40"
        if val <= 50:
            return "40-50"
        return "50-60"

    dynamic_zones["band_label"] = dynamic_zones["reach_min"].map(_band_from_reach)
    dynamic_zones["band_mode"] = dynamic_zones["reach_mode"].fillna("transporte público").astype(str)

    area_lookup = {
        band: float(dynamic_zones.loc[dynamic_zones["band_label"] == band, "area_km2"].sum())
        for band in color_by_band.keys()
    }
    pt_count = int((dynamic_zones["reach_mode"].astype(str) == "transporte público").sum())
    walk_count = int((dynamic_zones["reach_mode"].astype(str) == "a pé").sum())

    m = folium.Map(
        location=[origin_lat, origin_lon],
        zoom_start=13,
        tiles="cartodbpositron",
        control_scale=True,
        prefer_canvas=False,
    )

    def _style_fn(feature):
        label = str(feature["properties"].get("band_label", "50-60"))
        fill_color = color_by_band.get(label, "#1a9850")
        return {
            "fillColor": fill_color,
            "color": "#ffffff",
            "weight": 1.3,
            "dashArray": None,
            "fillOpacity": 0.55,
        }

    iso_layer = folium.GeoJson(
        data=dynamic_zones,
        name="Isócronas (10 min)",
        smooth_factor=0.9,
        style_function=_style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=["band_label", "area_km2", "band_mode"],
            aliases=["Intervalo (min)", "Área (km²)", "Modo dominante"],
            localize=True,
            sticky=True,
            style=(
                "background-color: #ffffff;"
                " color: #222222;"
                " border: 1px solid #999999;"
                " border-radius: 4px;"
                " box-shadow: 0 1px 3px rgba(0,0,0,0.2);"
                " padding: 6px;"
                " font-size: 12px;"
            ),
        ),
    ).add_to(m)

    _add_mouse_origin_marker(m)

    map_name = m.get_name()
    iso_layer_name = iso_layer.get_name()
    dynamic_iso_script = f"""
    (function attachDynamicIsoColor() {{
        var mapObj = window.{map_name};
        var isoLayer = window.{iso_layer_name};
        if (!mapObj || !isoLayer) {{
            setTimeout(attachDynamicIsoColor, 50);
            return;
        }}

        var baseOrigin = L.latLng({origin_lat}, {origin_lon});
        var WALK_METERS_PER_MIN = 80.0;

        function colorByBand(label) {{
            if (label === '0-10') return '#1a9850';
            if (label === '10-20') return '#66bd63';
            if (label === '20-30') return '#a6d96a';
            if (label === '30-40') return '#fee08b';
            if (label === '40-50') return '#f46d43';
            return '#d73027';
        }}

        function hatchStrokeColor(label) {{
            var hex = String(colorByBand(label)).replace('#', '');
            var r = parseInt(hex.slice(0, 2), 16);
            var g = parseInt(hex.slice(2, 4), 16);
            var b = parseInt(hex.slice(4, 6), 16);
            return 'rgb(' + Math.max(0, Math.round(r * 0.35)) + ',' + Math.max(0, Math.round(g * 0.35)) + ',' + Math.max(0, Math.round(b * 0.35)) + ')';
        }}

        var patternsReady = false;

        function ensurePatternDefs() {{
            if (patternsReady) return true;

            var svg = null;
            isoLayer.eachLayer(function(layer) {{
                if (!svg && layer && layer._path && layer._path.ownerSVGElement) {{
                    svg = layer._path.ownerSVGElement;
                }}
            }});
            if (!svg) return false;

            var defs = svg.querySelector('defs[data-iso-patterns="1"]');
            if (!defs) {{
                defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
                defs.setAttribute('data-iso-patterns', '1');
                svg.insertBefore(defs, svg.firstChild);
            }}

            var labels = ['0-10', '10-20', '20-30', '30-40', '40-50', '50-60'];
            labels.forEach(function(label) {{
                var pid = 'iso_walk_hatch_' + label.replace('-', '_');
                if (defs.querySelector('#' + pid)) return;

                var pattern = document.createElementNS('http://www.w3.org/2000/svg', 'pattern');
                pattern.setAttribute('id', pid);
                pattern.setAttribute('patternUnits', 'userSpaceOnUse');
                pattern.setAttribute('width', '8');
                pattern.setAttribute('height', '8');
                pattern.setAttribute('patternTransform', 'rotate(45)');

                var bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                bg.setAttribute('x', '0');
                bg.setAttribute('y', '0');
                bg.setAttribute('width', '8');
                bg.setAttribute('height', '8');
                bg.setAttribute('fill', colorByBand(label));
                pattern.appendChild(bg);

                var stripe = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                stripe.setAttribute('x1', '0');
                stripe.setAttribute('y1', '0');
                stripe.setAttribute('x2', '0');
                stripe.setAttribute('y2', '8');
                stripe.setAttribute('stroke', hatchStrokeColor(label));
                stripe.setAttribute('stroke-opacity', '0.9');
                stripe.setAttribute('stroke-width', '2');
                pattern.appendChild(stripe);

                defs.appendChild(pattern);
            }});

            patternsReady = true;
            return true;
        }}

        function applyFillPattern(layer, label, modeLabel, latlng) {{
            if (!layer) return;

            var fillValue = colorByBand(label);

            if (layer.setStyle) {{
                layer.setStyle({{
                    fillColor: fillValue,
                    fillOpacity: 0.55
                }});
            }}

            if (layer._path) {{
                layer._path.style.fill = fillValue;
                layer._path.setAttribute('fill', fillValue);
            }}
        }}

        function styleByMode(modeLabel) {{
            return {{ color: '#ffffff', weight: 1.3, dashArray: null, fillOpacity: 0.55 }};
        }}

        function bandFromReach(mins) {{
            if (mins <= 10) return '0-10';
            if (mins <= 20) return '10-20';
            if (mins <= 30) return '20-30';
            if (mins <= 40) return '30-40';
            if (mins <= 50) return '40-50';
            return '50-60';
        }}

        function updateLegendAreaMap(areaByBand) {{
            var keys = ['0-10', '10-20', '20-30', '30-40', '40-50', '50-60'];
            keys.forEach(function(k) {{
                var id = 'legend-area-' + k.replace('-', '_');
                var el = document.getElementById(id);
                if (el) el.textContent = (areaByBand[k] || 0).toFixed(3) + ' km²';
            }});
            var total = (areaByBand['0-10'] || 0) + (areaByBand['10-20'] || 0);
            var totalEl = document.getElementById('legend-area-total-20');
            if (totalEl) totalEl.textContent = total.toFixed(3) + ' km²';
        }}

        function updateLegendModeCounts(modeCounts) {{
            var ptEl = document.getElementById('legend-count-pt');
            if (ptEl) ptEl.textContent = String(modeCounts['transporte público'] || 0);

            var walkEl = document.getElementById('legend-count-walk');
            if (walkEl) walkEl.textContent = String(modeCounts['a pé'] || 0);
        }}

        function refreshIsochrones(latlng) {{
            var areaByBand = {{'0-10': 0, '10-20': 0, '20-30': 0, '30-40': 0, '40-50': 0, '50-60': 0}};
            var modeCounts = {{'transporte público': 0, 'a pé': 0}};
            isoLayer.eachLayer(function(layer) {{
                if (!layer || !layer.feature || !layer.feature.properties) return;
                var props = layer.feature.properties;
                var cLat = Number(props.center_lat);
                var cLon = Number(props.center_lon);
                var baseReach = Number(props.reach_min);
                if (!isFinite(cLat) || !isFinite(cLon) || !isFinite(baseReach)) return;

                var cPoint = L.latLng(cLat, cLon);
                var dNow = mapObj.distance(latlng, cPoint);
                var dBase = mapObj.distance(baseOrigin, cPoint);
                var estMin = baseReach + ((dNow - dBase) / WALK_METERS_PER_MIN);
                var walkMin = dNow / WALK_METERS_PER_MIN;
                var bandLabel = bandFromReach(estMin);
                var mode = walkMin <= estMin ? 'a pé' : 'transporte público';

                props.band_label = bandLabel;
                props.band_mode = mode;

                var styleMode = styleByMode(mode);
                if (layer.setStyle) {{
                    layer.setStyle({{
                        fillColor: colorByBand(bandLabel),
                        color: styleMode.color,
                        weight: styleMode.weight,
                        dashArray: styleMode.dashArray,
                        fillOpacity: styleMode.fillOpacity
                    }});
                }}
                applyFillPattern(layer, bandLabel, mode, latlng);

                var areaKm2 = Number(props.area_km2 || 0);
                if (isFinite(areaKm2)) {{
                    areaByBand[bandLabel] = (areaByBand[bandLabel] || 0) + areaKm2;
                }}

                modeCounts[mode] = (modeCounts[mode] || 0) + 1;
            }});
            updateLegendAreaMap(areaByBand);
            updateLegendModeCounts(modeCounts);
        }}

        var latestLatLng = null;
        var rafScheduled = false;
        var lastComputedLatLng = null;
        var lastRunAt = 0;
        var lastDurationMs = 16;

        function currentMinMoveMeters() {{
            var b = mapObj.getBounds();
            var diagonal = mapObj.distance(b.getSouthWest(), b.getNorthEast());
            var scaled = diagonal / 220.0;
            return Math.max(6, Math.min(120, scaled));
        }}

        function currentMinIntervalMs() {{
            return Math.max(16, Math.min(220, lastDurationMs * 1.5));
        }}

        function shouldRecompute(latlng, force) {{
            if (force) return true;
            if (!lastComputedLatLng) return true;
            return mapObj.distance(latlng, lastComputedLatLng) >= currentMinMoveMeters();
        }}

        function scheduleRefresh(latlng, force) {{
            latestLatLng = latlng;
            if (rafScheduled) return;

            rafScheduled = true;
            window.requestAnimationFrame(function() {{
                rafScheduled = false;
                if (!latestLatLng) return;

                var now = performance.now();
                if (!force && now - lastRunAt < currentMinIntervalMs()) return;
                if (!shouldRecompute(latestLatLng, force)) return;

                var t0 = performance.now();
                refreshIsochrones(latestLatLng);
                var t1 = performance.now();

                lastDurationMs = Math.max(8, t1 - t0);
                lastRunAt = now;
                lastComputedLatLng = latestLatLng;
            }});
        }}

        function bindMove() {{
            ensurePatternDefs();
            mapObj.on('mousemove', function(e) {{
                scheduleRefresh(e.latlng, false);
            }});
            mapObj.on('click', function(e) {{
                scheduleRefresh(e.latlng, true);
            }});
            scheduleRefresh(baseOrigin, true);
        }}

        // Segunda fonte de posição, além do mousemove nativo acima: o dashboard FeedNPlay
        // (feednplay_dashboard.html) reencaminha por postMessage a presença detetada pela
        // câmara de topo (ver src/feednplay/bridge.py) - evaluate_js do bridge só chega ao
        // documento de topo, nunca diretamente a este iframe, daí o postMessage em vez de um
        // CustomEvent local. x/y vêm normalizados 0-1 (esquerda/direita, perto/longe) dentro da
        // zona de interação da câmara - por agora mapeados 1:1 para a área do próprio mapa,
        // tal como um mousemove sintético. Sem presença nenhuma (`active: false`), volta à
        // origem por omissão em vez de ficar preso na última posição. Isto NÃO substitui
        // bindMove() - as duas fontes coexistem, por isso este ficheiro continua a funcionar
        // sozinho num browser normal (sem o bridge) tal como antes.
        function bindFnpPosition() {{
            window.addEventListener('message', function(event) {{
                var payload = event.data && event.data.__fnpPosition;
                if (!payload) return;

                if (!payload.active) {{
                    scheduleRefresh(baseOrigin, true);
                    return;
                }}

                var rect = mapObj.getContainer().getBoundingClientRect();
                var point = L.point(payload.x * rect.width, payload.y * rect.height);
                var latlng = mapObj.containerPointToLatLng(point);
                scheduleRefresh(latlng, false);
            }});
        }}

        bindMove();
        bindFnpPosition();
    }})();
    """
    m.get_root().script.add_child(folium.Element(dynamic_iso_script))

    total_20 = area_lookup.get("0-10", 0.0) + area_lookup.get("10-20", 0.0)
    no_pt_warning = (
        "<div style='margin-top:6px; color:#9c2f00; font-size:11px;'><strong>Aviso:</strong> sem vantagem de transporte público para o horário calculado.</div>"
        if pt_count == 0
        else ""
    )

    legend_html = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; border: 1px solid #999; padding: 10px 12px;
                font-size: 12px; line-height: 1.3;">
    <div style="font-weight: 600; margin-bottom: 6px;">Mapa de Isócronas (intervalos de 10 min)</div>
                <div style="font-size:11px; margin-bottom:6px; color:#333;"><strong>Data/Hora de cálculo:</strong> {day} {time}</div>
                <div><span style="display:inline-block;width:12px;height:12px;background:#1a9850;margin-right:6px;"></span>0-10: <span id="legend-area-0_10">{a0:.3f} km²</span></div>
                <div><span style="display:inline-block;width:12px;height:12px;background:#66bd63;margin-right:6px;"></span>10-20: <span id="legend-area-10_20">{a1:.3f} km²</span></div>
                <div><span style="display:inline-block;width:12px;height:12px;background:#a6d96a;margin-right:6px;"></span>20-30: <span id="legend-area-20_30">{a2:.3f} km²</span></div>
                <div><span style="display:inline-block;width:12px;height:12px;background:#fee08b;margin-right:6px;"></span>30-40: <span id="legend-area-30_40">{a3:.3f} km²</span></div>
                <div><span style="display:inline-block;width:12px;height:12px;background:#f46d43;margin-right:6px;"></span>40-50: <span id="legend-area-40_50">{a4:.3f} km²</span></div>
                <div><span style="display:inline-block;width:12px;height:12px;background:#d73027;margin-right:6px;"></span>50-60: <span id="legend-area-50_60">{a5:.3f} km²</span></div>
                <div style="margin-top:6px;padding-top:6px;border-top:1px solid #ddd;"><strong>Zonas por modo:</strong></div>
                <div style="font-size:11px;">Transporte público: <strong id="legend-count-pt">{pt_count}</strong></div>
                <div style="font-size:11px;">A pé: <strong id="legend-count-walk">{walk_count}</strong></div>
                <div style="margin-top:6px;padding-top:6px;border-top:1px solid #ddd;"><strong>Total ≤ 20 min:</strong> <span id="legend-area-total-20">{at:.3f} km²</span></div>
                {no_pt_warning}
    </div>
    """.format(
        day=ref_day_str,
        time=time_str,
        a0=area_lookup.get("0-10", 0.0),
        a1=area_lookup.get("10-20", 0.0),
        a2=area_lookup.get("20-30", 0.0),
        a3=area_lookup.get("30-40", 0.0),
        a4=area_lookup.get("40-50", 0.0),
        a5=area_lookup.get("50-60", 0.0),
        at=total_20,
        pt_count=pt_count,
        walk_count=walk_count,
        no_pt_warning=no_pt_warning,
    )
    m.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl(collapsed=False).add_to(m)
    return m
