/* IAC Indicator Store — shared, framework-free loader for the Indicator Master.
 *
 * Reads the JSON produced by scripts/build_indicators.py:
 *   files/indicators/indicator_master.json   (registry: components, sources, indicators)
 *   files/indicators/values/<component>.json (raw value + 1–10 score per geography/year)
 *
 * Used by files/neighborhood-map.html (Indicator Selector). Written so the
 * Viability Calculator / profile pages can reuse the same API later:
 *
 *   const store = await IACIndicators.load('indicators/');   // path relative to the page
 *   store.selectorEntries()            -> [{component, entries:[{id,label,enabled,reason}]}]
 *   store.record(id, geoId, year?)     -> {raw, score, moe?, allocated?, derived?} | null
 *   store.score(id, geoId, year?)      -> 1–10 | null
 *   store.formatRaw(id, raw)           -> "21.5%", "$68,835", ...
 *   store.attachLegacy({zip: communityData, service_center: scData})
 *       lets record()/score() also answer for indicators whose values still
 *       live in community_data.json / service_centers.json (binding legacy_*).
 *
 * Nothing here touches the DOM.
 */
(function (global) {
  'use strict';

  // An indicator appears in the selector once it is defined; it is only
  // switchable-on (coloured) once a reviewer has marked it validated/published.
  var SELECTABLE = { defined: 1, validated: 1, published: 1 };
  var LIVE = { validated: 1, published: 1 };

  function IndicatorStore(master, valuesById) {
    this.master = master;
    this.values = valuesById || {};
    this.legacy = { zip: null, service_center: null };
    this.byId = {};
    var self = this;
    (master.indicators || []).forEach(function (ind) { self.byId[ind.id] = ind; });
  }

  IndicatorStore.prototype.indicator = function (id) { return this.byId[id] || null; };

  IndicatorStore.prototype.components = function () {
    return (this.master.components || []).slice().sort(function (a, b) {
      return a.display_order - b.display_order;
    });
  };

  IndicatorStore.prototype.source = function (sourceId) {
    return (this.master.sources || {})[sourceId] || null;
  };

  IndicatorStore.prototype.years = function (id) {
    var v = this.values[id];
    return v ? v.years.slice() : [];
  };

  IndicatorStore.prototype.latestYear = function (id) {
    var v = this.values[id];
    return v ? v.latest_year : null;
  };

  IndicatorStore.prototype.hasData = function (id) {
    var y = this.latestYear(id);
    return y != null && Object.keys(this.values[id].values[String(y)] || {}).length > 0;
  };

  IndicatorStore.prototype.isLive = function (id) {
    var ind = this.byId[id];
    return !!ind && !!LIVE[ind.status] && this.hasData(id);
  };

  // Indicators the selector should list (values_file indicators only — the
  // existing legacy options stay hard-coded in the page), grouped by component
  // in display order, then priority rank.
  IndicatorStore.prototype.selectorEntries = function () {
    var self = this;
    return this.components().map(function (comp) {
      var entries = self.master.indicators
        .filter(function (ind) {
          return ind.component_id === comp.id && ind.level === 'indicator' &&
                 ind.binding && ind.binding.type === 'values_file' && SELECTABLE[ind.status];
        })
        .sort(function (a, b) { return (a.priority_rank || 99) - (b.priority_rank || 99); })
        .map(function (ind) {
          var enabled = self.isLive(ind.id);
          var reason = enabled ? null : (self.hasData(ind.id) ? 'in review' : 'data pending');
          return { id: ind.id, label: ind.short_label || ind.name, enabled: enabled, reason: reason,
                   geoLevel: ind.geo_level, legend: ind.legend, indicator: ind };
        });
      return { component: comp, entries: entries };
    }).filter(function (g) { return g.entries.length > 0; });
  };

  IndicatorStore.prototype.attachLegacy = function (sources) {
    this.legacy.zip = sources.zip || this.legacy.zip;
    this.legacy.service_center = sources.service_center || this.legacy.service_center;
    return this;
  };

  IndicatorStore.prototype.record = function (id, geoId, year) {
    var ind = this.byId[id];
    if (!ind || geoId == null) return null;
    var b = ind.binding || {};
    if (b.type === 'values_file') {
      var v = this.values[id];
      if (!v) return null;
      var y = String(year != null ? year : v.latest_year);
      var rec = (v.values[y] || {})[String(geoId)];
      return rec || null;
    }
    var table = b.type === 'legacy_sc_field' ? this.legacy.service_center : this.legacy.zip;
    var row = table && table[String(geoId)];
    if (!row) return null;
    var raw = b.raw_field ? row[b.raw_field] : null;
    var score = b.score_field ? row[b.score_field] : null;
    if (raw == null && score == null) return null;
    return { raw: raw, score: score };
  };

  IndicatorStore.prototype.score = function (id, geoId, year) {
    var r = this.record(id, geoId, year);
    return r && typeof r.score === 'number' ? r.score : null;
  };

  IndicatorStore.prototype.formatRaw = function (id, raw) {
    var ind = this.byId[id];
    if (raw == null || !ind) return 'N/A';
    switch (ind.value_type) {
      case 'percent':  return Number(raw).toFixed(1) + '%';
      case 'currency': return '$' + Math.round(raw).toLocaleString();
      case 'count':    return Math.round(raw).toLocaleString();
      default:         return String(raw);
    }
  };

  // One-line provenance for the legend panel, e.g.
  // "ACS 5-Year … · 2024 · provisional scoring"
  IndicatorStore.prototype.provenance = function (id) {
    var ind = this.byId[id];
    if (!ind) return '';
    var src = this.source(ind.source_id);
    var parts = [];
    if (src) parts.push(src.publisher ? src.publisher.split(';')[0] : src.source_name);
    var y = this.latestYear(id);
    if (y) parts.push(String(y));
    if (ind.scoring && ind.scoring.status === 'provisional') parts.push('provisional scoring');
    return parts.join(' · ');
  };

  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status + ' ' + url);
      return r.json();
    });
  }

  function load(basePath) {
    var base = (basePath || 'indicators/').replace(/\/?$/, '/');
    return getJSON(base + 'indicator_master.json').then(function (master) {
      var files = {};
      (master.indicators || []).forEach(function (ind) {
        if (ind.binding && ind.binding.type === 'values_file' && SELECTABLE[ind.status]) {
          files[ind.binding.values_file] = 1;
        }
      });
      var valuesById = {};
      return Promise.all(Object.keys(files).map(function (f) {
        return getJSON(base + f).then(function (d) {
          Object.keys(d.indicators || {}).forEach(function (k) { valuesById[k] = d.indicators[k]; });
        }).catch(function (err) { console.warn('IACIndicators: could not load', f, err); });
      })).then(function () { return new IndicatorStore(master, valuesById); });
    });
  }

  global.IACIndicators = { load: load, IndicatorStore: IndicatorStore };
})(typeof window !== 'undefined' ? window : this);
