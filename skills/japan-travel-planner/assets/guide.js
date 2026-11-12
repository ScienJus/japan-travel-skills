"use strict";
(() => {
  const plan = JSON.parse(document.getElementById("plan-data").textContent);
  const words = {
    en: {
      demo: "DEMONSTRATION", days: "days", cities: "cities", places: "places", nights: "nights", dayTrip: "visit only",
      revision: "Plan snapshot", all: "All", itinerary: "Daily itinerary", itineraryKicker: "DATES / BASES / CONNECTIONS",
      export: "Download plan JSON", locations: "Places & map", filterScope: "City and category filter places only. The day selector also updates the itinerary and transport.",
      city: "City", kind: "Category", hotel: "Hotels", attraction: "Attractions", restaurant: "Restaurants", transport: "Stations & stops",
      fixed: "Fixed commitment", selected: "Selected", candidate: "Candidate", backup: "Backup", verified: "Checked within source scope", unverified: "Unverified", illustrative: "Illustrative",
      overnight: "Overnight", noBase: "No overnight stay", hotelPending: "Hotel not selected", empty: "No places match these filters.",
      missing: "No sourced coordinates; retained in the list", position: "Coordinate provenance", questions: "Open decisions", none: "No open decisions recorded; this does not certify the trip.",
      map: "Location overview · not navigation", fit: "Fit", basemap: "Load GSI basemap", hideMap: "Hide basemap", zoomFirst: "Zoom in to load a basemap",
      mapOff: "Road map not loaded. Click ‘Load GSI basemap’ to show it. Markers show locations, not walking routes.", mapOn: "GSI basemap · zoom 9–16. Markers are reference points, not confirmed entrances.",
      mapFailed: "Basemap could not load; the network or browser may be blocking it. Place details and links remain usable; no automatic retry.", basemapUnavailable: "Basemap unavailable",
      network: "The basemap loads automatically from GSI. Requests send the visible tile area and normal network metadata, not the plan records. You can hide the basemap to stop further tile requests.",
      footer: "Read-only travel planning. This file contains the complete plan; filters do not remove records. Review private details before sharing.",
      related: "Related places", pointCount: "with sourced coordinates", noPoints: "No sourced coordinates in this view", scope: "Scope", checked: "Checked",
    },
    "zh-CN": {
      demo: "演示行程", days: "天", cities: "个城市", places: "个地点", nights: "晚", dayTrip: "仅游览",
      revision: "行程快照", all: "全部", itinerary: "每天怎么走", itineraryKicker: "日期 / 住宿 / 交通",
      export: "下载行程 JSON", locations: "地点与地图", filterScope: "城市和类型只筛选地点；切换日期会同步更新当天安排和交通。",
      city: "城市", kind: "地点类型", hotel: "酒店", attraction: "景点", restaurant: "餐厅", transport: "车站与站点",
      fixed: "固定安排", selected: "已选方案", candidate: "候选", backup: "备选", verified: "已核对（见来源范围）", unverified: "待核对", illustrative: "示意信息",
      overnight: "住宿", noBase: "当天无住宿安排", hotelPending: "酒店待选", empty: "此筛选下没有地点。",
      missing: "无可靠坐标，保留在清单中", position: "坐标来源与精度", questions: "出发前待确认", none: "未记录待办，不代表整段旅程已获核实。",
      map: "位置关系 · 非导航路线", fit: "适应范围", basemap: "加载地理院底图", hideMap: "关闭底图", zoomFirst: "放大到城市范围后可加载底图",
      mapOff: "尚未加载道路底图。点击「加载地理院底图」查看；圆点仅表示地点位置，不是步行路线。", mapOn: "地理院底图 · 缩放 9–16 级。坐标是参考点，不保证是入口。",
      mapFailed: "底图加载失败，可能受网络或浏览器限制。地点与链接仍可查看，不自动重试。", basemapUnavailable: "底图不可用",
      network: "默认从国土地理院加载底图，仅发送可见区域的瓦片请求和常规网络信息，不上传行程记录。关闭底图后不再请求新的瓦片。",
      footer: "只读旅行规划。此文件包含完整行程，筛选不会删除或脱敏记录；分享前请检查私人信息。",
      related: "相关地点", pointCount: "个有来源坐标", noPoints: "当前视图没有可靠坐标", scope: "核对范围", checked: "核对日期",
    },
    ja: {
      demo: "モデルコース", days: "日間", cities: "都市", places: "か所", nights: "泊", dayTrip: "日帰り",
      revision: "旅程スナップショット", all: "すべて", itinerary: "日ごとの旅程", itineraryKicker: "日付 / 宿泊 / 移動",
      export: "旅程JSONをダウンロード", locations: "訪問先と地図", filterScope: "都市と種類は訪問先の絞り込みに使います。日付を切り替えると旅程と交通も連動します。",
      city: "都市", kind: "種類", hotel: "ホテル", attraction: "観光", restaurant: "飲食店", transport: "駅・停留所",
      fixed: "確定済み", selected: "選択済み", candidate: "候補", backup: "代替案", verified: "確認済み（出典の範囲内）", unverified: "未確認", illustrative: "参考情報",
      overnight: "宿泊", noBase: "宿泊なし", hotelPending: "ホテル未定", empty: "条件に合う訪問先がありません。",
      missing: "出典のある座標は未取得。一覧に掲載しています。", position: "座標の出典と精度", questions: "出発前の確認事項", none: "未確認事項の記録はありません。旅程全体の確認を示すものではありません。",
      map: "位置の目安 · 経路案内とは異なります", fit: "全体表示", basemap: "地理院地図を表示", hideMap: "背景地図を閉じる", zoomFirst: "拡大すると背景地図を表示できます",
      mapOff: "背景地図は未表示です。「地理院地図を表示」を押すと道路を確認できます。マーカーは地点の位置で、徒歩ルートではありません。", mapOn: "地理院地図 · ズーム9〜16。マーカーは位置の目安で、入口の位置は要確認です。",
      mapFailed: "背景地図を取得できません。通信やブラウザーで制限されている可能性があります。訪問先やリンクは引き続き表示でき、自動再試行はしません。", basemapUnavailable: "背景地図を取得できません",
      network: "背景地図は地理院から自動取得します。表示範囲のタイルと通常の通信情報のみを送信し、旅程データは送信しません。背景地図を閉じると、新たなタイルの取得を停止します。",
      footer: "読み取り専用の旅行計画です。ファイルには旅程全体が含まれます。共有する前に個人情報をご確認ください。",
      related: "関連する訪問先", pointCount: "か所に出典付きの座標あり", noPoints: "この表示範囲に出典付きの座標がありません", scope: "確認範囲", checked: "確認日",
    },
  };
  const t = words[plan.language];
  const $ = id => document.getElementById(id);
  const byId = rows => new Map(rows.map(row => [row.id, row]));
  const cities = byId(plan.cities), places = byId(plan.places), legs = byId(plan.legs);
  // Empty filter values cannot collide with validated nonempty record identifiers.
  const state = {day: "", city: "", kind: "", selected: null, zoom: 10, center: null, tiles: true, tileFailed: false};
  const colors = {hotel: "#4c6452", attraction: "#b26243", restaurant: "#9a6b27", transport: "#477489"};
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const link = (text, href) => {
    const node = make("a", text);
    node.href = href; node.target = "_blank"; node.rel = "noopener noreferrer";
    return node;
  };
  const sourceLinks = sources => {
    const node = make("div", undefined, "source-links");
    for (const source of sources) {
      const a = link(source.title, source.url);
      a.title = [source.scope, source.checked_on].filter(Boolean).join(" · ");
      node.append(a);
    }
    return node;
  };
  const selectedDays = () => plan.days.filter(day => state.day === "" || day.id === state.day);
  const dayPlaceIds = () => new Set(selectedDays().flatMap(day => [
    day.base_place_id, ...day.visits.map(visit => visit.place_id),
    ...day.leg_ids.flatMap(id => [legs.get(id).from_place_id, legs.get(id).to_place_id]),
  ]).filter(Boolean));
  const visiblePlaces = () => {
    const used = dayPlaceIds();
    return plan.places.filter(place => (state.day === "" || used.has(place.id))
      && (state.city === "" || place.city_id === state.city)
      && (state.kind === "" || place.kind === state.kind));
  };
  const map = $("map"), ns = "http://www.w3.org/2000/svg";
  let mapWidth = 0;
  const svg = (tag, attributes) => {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    return node;
  };
  const project = point => {
    const latitude = point.lat * Math.PI / 180;
    return [(point.lon + 180) / 360, (1 - Math.log(Math.tan(Math.PI / 4 + latitude / 2)) / Math.PI) / 2];
  };

  function drawMap(fit = false) {
    const rows = visiblePlaces(), located = rows.filter(place => place.coordinates);
    const w = Math.max(280, Math.round(map.getBoundingClientRect().width)), h = w < 500 ? 320 : 420;
    mapWidth = w;
    map.setAttribute("viewBox", `0 0 ${w} ${h}`); map.setAttribute("height", h);
    map.replaceChildren();
    if (fit || !state.center) {
      const points = located.map(place => project(place.coordinates));
      const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
      state.center = points.length ? [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] : [0.875, 0.4];
      const spanX = Math.max(...xs) - Math.min(...xs), spanY = Math.max(...ys) - Math.min(...ys);
      state.zoom = points.length > 1 ? Math.max(1, Math.min(15, Math.floor(Math.log2(Math.min((w - 100) / (256 * (spanX || 0.00001)), (h - 100) / (256 * (spanY || 0.00001))))))) : 13;
    }
    const scale = 256 * 2 ** state.zoom;
    const left = state.center[0] * scale - w / 2, top = state.center[1] * scale - h / 2;
    const tileLayer = svg("g", {"aria-hidden": "true"}); map.append(tileLayer);
    if (state.tiles && !state.tileFailed && state.zoom >= 9 && located.length) {
      const tileCount = 2 ** state.zoom;
      for (let x = Math.floor(left / 256); x <= Math.floor((left + w) / 256); x++) {
        for (let y = Math.floor(top / 256); y <= Math.floor((top + h) / 256); y++) {
          if (x < 0 || y < 0 || x >= tileCount || y >= tileCount) continue;
          const image = svg("image", {x: x * 256 - left, y: y * 256 - top, width: 256, height: 256,
            href: `https://cyberjapandata.gsi.go.jp/xyz/pale/${state.zoom}/${x}/${y}.png`});
          image.addEventListener("error", () => {
            if (!image.isConnected) return;
            state.tileFailed = true; state.tiles = false; tileLayer.replaceChildren(); updateMapStatus(located.length);
          }, {once: true});
          tileLayer.append(image);
        }
      }
    } else {
      for (let x = 0; x < w; x += 60) map.append(svg("line", {x1: x, x2: x, y1: 0, y2: h, stroke: "#d8e1d6", "stroke-width": 1}));
      for (let y = 0; y < h; y += 60) map.append(svg("line", {x1: 0, x2: w, y1: y, y2: y, stroke: "#d8e1d6", "stroke-width": 1}));
    }
    if (!located.length) {
      const label = svg("text", {x: w / 2, y: h / 2, "text-anchor": "middle", fill: "#5e716b", "font-size": 14});
      label.textContent = t.noPoints; map.append(label);
    }
    // Draw the selected marker last so coincident points do not hide its highlight.
    rows.map((place, index) => ({place, index}))
      .sort((a, b) => Number(a.place.id === state.selected) - Number(b.place.id === state.selected))
      .forEach(({place, index}) => {
      if (!place.coordinates) return;
      const point = project(place.coordinates), x = point[0] * scale - left, y = point[1] * scale - top;
      if (x < -25 || y < -25 || x > w + 25 || y > h + 25) return;
      const group = svg("g", {transform: `translate(${x},${y})`, role: "button", tabindex: 0,
        "aria-label": `${index + 1}. ${place.name}`, "data-place-id": place.id,
        class: `map-marker${state.selected === place.id ? " selected" : ""}`});
      group.append(svg("circle", {r: 23, fill: "transparent", stroke: "none"}));
      group.append(svg("circle", {r: 15, fill: colors[place.kind]}));
      const label = svg("text", {}); label.textContent = index + 1; group.append(label);
      const select = () => choosePlace(place.id, false);
      group.addEventListener("click", select);
      group.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(); } });
      map.append(group);
    });
    const north = svg("text", {x: w - 18, y: 28, "text-anchor": "end", "font-size": 12, fill: "#173c38"});
    north.textContent = "N ↑"; map.append(north);
    updateMapStatus(located.length);
  }

  function updateMapStatus(count) {
    $("map-status").textContent = state.tileFailed ? t.mapFailed : !count ? t.noPoints
      : state.zoom < 9 ? t.zoomFirst : state.tiles ? t.mapOn : t.mapOff;
    $("basemap").textContent = state.tileFailed ? t.basemapUnavailable : (state.tiles ? t.hideMap : state.zoom < 9 ? t.zoomFirst : t.basemap);
    $("basemap").disabled = state.tileFailed || !count || (!state.tiles && state.zoom < 9);
    $("zoom-in").disabled = state.zoom >= 16;
    $("zoom-out").disabled = state.zoom <= 1;
  }

  function choosePlace(id, focusMap) {
    state.selected = id;
    document.querySelectorAll(".place-card").forEach(card => card.classList.toggle("selected", card.dataset.placeId === id));
    const place = places.get(id);
    if (focusMap && place.coordinates) { state.center = project(place.coordinates); state.zoom = 14; }
    drawMap();
    const card = document.querySelector(`.place-card[data-place-id="${id}"]`);
    if (!focusMap && card) card.scrollIntoView({block: "nearest"});
  }

  function renderSchedule() {
    $("day-plans").replaceChildren();
    for (const day of selectedDays()) {
      const article = make("article", undefined, "day-plan"); article.dataset.dayId = day.id;
      article.append(make("p", `${day.date} / ${day.city_ids.map(id => cities.get(id).name).join(" → ")}`, "day-date"), make("h3", day.title), make("p", day.summary, "day-summary"));
      for (const visit of day.visits) {
        const item = make("div", undefined, "visit"), info = make("div");
        const place = places.get(visit.place_id);
        info.append(make("h3", place.name), make("p", `${t[place.role]} · ${t[place.evidence]}`), make("p", visit.notes));
        item.append(make("time", visit.time), info); article.append(item);
      }
      for (const id of day.leg_ids) {
        const leg = legs.get(id), item = make("div", undefined, "leg"); item.dataset.legId = id;
        item.append(make("strong", `${places.get(leg.from_place_id).name} → ${places.get(leg.to_place_id).name}`),
          make("small", `${leg.time} · ${leg.mode} · ${t[leg.role]} · ${t[leg.evidence]}`), make("small", leg.notes), sourceLinks(leg.sources));
        for (const source of leg.sources) if (source.scope) item.append(make("small", `${t.scope}: ${source.scope}`));
        article.append(item);
      }
      const hotel = day.base_place_id ? places.get(day.base_place_id) : null;
      const hotelLabel = hotel ? `${hotel.name} · ${t[hotel.role]} · ${t[hotel.evidence]}` : t.hotelPending;
      const base = day.base_city_id ? `${cities.get(day.base_city_id).name} / ${hotelLabel}` : t.noBase;
      article.append(make("p", `${t.overnight}: ${base}`, "overnight"));
      $("day-plans").append(article);
    }
  }

  function renderPlaces() {
    const rows = visiblePlaces(); $("places").replaceChildren();
    $("place-count").textContent = `${rows.length} ${t.places} · ${rows.filter(p => p.coordinates).length} ${t.pointCount}`;
    if (!rows.length) $("places").append(make("p", t.empty, "empty"));
    rows.forEach((place, index) => {
      const article = make("article", undefined, "place-card"); article.dataset.placeId = place.id;
      const heading = make("h3", undefined, "place-title"), button = make("button", place.name);
      button.type = "button"; button.addEventListener("click", () => choosePlace(place.id, true));
      heading.append(make("span", index + 1, "number"), button);
      article.append(heading, make("div", `${t[place.kind]} · ${t[place.role]} · ${t[place.evidence]}`, "meta"), make("p", place.notes));
      for (const source of place.sources) {
        if (source.scope) article.append(make("p", `${t.scope}: ${source.scope}`));
      }
      article.append(sourceLinks(place.sources));
      if (place.coordinates) {
        const point = place.coordinates, detail = make("details");
        detail.append(make("summary", t.position), make("p", `${point.lat}, ${point.lon} · ${point.precision} · ${t.checked}: ${point.checked_on}`), link(t.position, point.source_url)); article.append(detail);
      } else article.append(make("p", t.missing));
      $("places").append(article);
    });
    drawMap(true);
  }

  document.documentElement.lang = plan.language; document.title = plan.title;
  $("title").textContent = plan.title; $("notice").textContent = plan.notice;
  $("demo").textContent = plan.demo ? t.demo : "";
  $("revision").textContent = `${t.revision}: ${plan.revision} · Asia/Tokyo`;
  for (const [count, label] of [[plan.days.length, t.days], [plan.cities.length, t.cities], [plan.places.length, t.places]]) {
    const item = make("div", undefined, "stat"); item.append(make("strong", count), make("span", label)); $("stats").append(item);
  }
  for (const city of plan.cities) {
    const nights = plan.days.filter(day => day.base_city_id === city.id).length;
    const item = make("div", `${city.name} · ${nights ? `${nights}${plan.language === "en" ? " " : ""}${t.nights}` : t.dayTrip}`, "base"); item.title = city.summary; $("bases").append(item);
  }
  for (const [id, label] of Object.entries({"schedule-heading": t.itinerary, "schedule-kicker": t.itineraryKicker, export: t.export,
    "places-heading": t.locations, "filter-scope": t.filterScope, "city-label": t.city, "kind-label": t.kind,
    "map-label": t.map, fit: t.fit, "network-note": t.network, "questions-heading": t.questions, footer: t.footer})) $(id).textContent = label;
  for (const [id, text] of [["", t.all], ...plan.days.map(day => [day.id, `${day.date.slice(5)} · ${day.title}`])]) {
    const button = make("button", text); button.type = "button"; button.dataset.dayId = id; button.setAttribute("aria-pressed", id === "" ? "true" : "false");
    button.addEventListener("click", () => {
      state.day = id; state.selected = null;
      $("days").querySelectorAll("button").forEach(node => node.setAttribute("aria-pressed", node === button ? "true" : "false"));
      renderSchedule(); renderPlaces();
    }); $("days").append(button);
  }
  for (const [id, entries] of [["city", [["", t.all], ...plan.cities.map(city => [city.id, city.name])]],
    ["kind", [["", t.all], ...["hotel", "attraction", "restaurant", "transport"].map(kind => [kind, t[kind]])]]]) {
    for (const [value, label] of entries) { const option = make("option", label); option.value = value; $(id).append(option); }
    $(id).addEventListener("change", event => {state[id] = event.target.value; state.selected = null; renderPlaces();});
  }
  for (const question of plan.open_questions.length ? plan.open_questions : [t.none]) $("questions").append(make("li", question));
  $("basemap").addEventListener("click", () => { state.tiles = !state.tiles; drawMap(); });
  $("fit").addEventListener("click", () => drawMap(true));
  $("zoom-in").addEventListener("click", () => { state.zoom = Math.min(16, state.zoom + 1); drawMap(); });
  $("zoom-out").addEventListener("click", () => { state.zoom = Math.max(1, state.zoom - 1); drawMap(); });
  $("export").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], {type: "application/json"}));
    const a = make("a"); a.href = url; a.download = "plan.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  renderSchedule(); renderPlaces();
  new ResizeObserver(() => {
    if (Math.max(280, Math.round(map.getBoundingClientRect().width)) !== mapWidth) drawMap(true);
  }).observe(map.parentElement);
})();
