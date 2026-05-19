// ==UserScript==
// @name         PDF Tool → CMS Auto-Fill (Project Plans)
// @namespace    https://housing.com
// @version      2.9
// @description  Auto-fills CMS Project Plans form. Title is left to CMS auto-fill. Supports Main Other Type, Amenities Type, and Construction Status fields.
// @author       Housing.com
// @match        https://cms.housing.com/project_plan_add.php*
// @match        https://cms.housing.com/project_plans_add.php*
// @match        https://cms.housing.com/project_img_add.php*
// @connect      pdftoimages-ljco.onrender.com
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const API = 'https://pdftoimages-ljco.onrender.com';

  const SS_MODE = '_cms_plan_auto_fill';
  const SS_SAVED = '_cms_plan_just_saved';
  const SS_PENDING = '_cms_plan_submit_pending';
  const SS_LAST_ACTION = '_cms_plan_last_action';

  let currentItem = null;
  let panelEl = null;
  let launchBtn = null;
  let autoMode = false;
  let queueRemaining = 0;
  let autoClickTimer = null;
  let ajaxPollTimer = null;

  const MAIN_OTHER_MASTER = [
    'Living Area',
    'Dining Area',
    'Bedroom',
    'Bathroom',
    'Kitchen',
    'Balcony',
    'Lobby',
    'Plot',
    'Kids Bedroom',
    'Terrace',
    'Pooja Room',
    'Study Room',
    'Servant Room'
  ];

  const AMENITIES_MASTER = [
    '24 X 7 Security', '24x7 CCTV Surveillance', '24X7 Water Supply', 'Acupressure Center',
    'Acupressure Pathway', 'Adventure Club', 'Aerobics Room', 'Air Conditioned', 'Amphitheater',
    'Amusement Area', 'Anti-termite Treatment', 'Archery Club', 'Assembly Area', 'ATM',
    'Auto Service Station', 'Automated Car Wash', 'Ayurveda Centre', 'Badminton Court',
    'Banquet Hall', 'Bar/ Chill-out Lounge', 'Barbecue Area', 'Basketball Court', 'Beach access',
    'Beach Volley Ball Court', 'Billiards/ Snooker Table', 'Board Games', 'Boom Barriers',
    'Bowling Alley', 'Bus Shelter', 'Business Center', 'Business Suites', 'Cafeteria', 'Car Lift',
    'Car Parking', 'Car Wash Area', 'Card Room', 'Carrom', 'Central Cooling System', 'Changing Room',
    'Chess Board', "Children's play area", 'Cigar Lounge', 'Cineplex', 'Closed Car Parking',
    'Club House', 'Club Rooftop', 'Community Buildings', 'Community Hall', 'Compound Wall',
    'Concierge Service', 'Conference Room', 'Cricket arena', 'Cricket Pitch',
    'Cycling & Jogging Track', 'Dart Board', 'Day Care Center', 'DG Availability', 'Discotheque',
    'Dock', 'Doctor on call', 'Double Glazed Windows', 'Earthquake Resistant Structure',
    'Electrical meter Room', 'Electrification', 'Energy management',
    'Entrance Gate Security Cabin', 'Entrance Lobby', 'Escalators', 'EV Charging Point',
    'Exotic Plantation', 'Facilities for Disabled', 'Feng Shui', 'Fire Alarm',
    'Fire Escape Staircases', 'Fire Fighting System',
    'Fire Protection And Fire Safety Requirements', 'Fire Retardant Structure',
    'Fire Sprinklers', 'Fitness Center', 'Flower Garden', 'Food Court', 'Foosball',
    'Football Field', 'Footpaths/ Pedestrian', 'Fountains', 'Full Power Backup', 'Futsal',
    'Garbage Disposal', 'Gated Community', 'Gazebo', 'Golf Course', 'Grade A Building',
    'Greenhouse Farming', 'Grocery Shop', 'Gymnasium', 'Health Facilities', 'Helipad',
    'High Speed Elevators', 'High-tech Alarm System', 'Hockey Ground', 'Hospital',
    'Indoor Games', 'Infinity Pool', 'Intercom', 'Internal Roads & Footpaths', 'Internet/ Wi-Fi',
    'Jacuzzi', 'Jogging Track', "Kid's Pool", 'Landscape Garden and Tree Planting',
    'Landscaped Gardens', 'Laundromat', 'Lawn Tennis Court', 'Letter Box', 'Library', 'Lift(s)',
    'Light shows', 'Lockers', 'Maintenance Staff', 'Manicured Garden', 'Medical Facilities',
    'Medical Store/ Pharmacy', 'Milk Booth', 'Mini Theatre', 'Motion Sensor',
    'Multi - Level Parking', 'Multipurpose Hall', 'Multipurpose Room', 'Natural Pond',
    'Nature Club', 'Observatories', 'Open Air Theatre', 'Open Car Parking', 'Open Gym',
    'Open Parking', 'Opera House', 'Organic Farming', 'Partial Power Backup', 'Party Hall',
    'Party Lawn', 'Paved Compound', 'Pergola', 'Pet Grooming', 'Petrol Pump', 'Pickleball Court',
    'Piped Gas Connection', 'Place for Worship', 'Polo Ground', 'Projector Wall', 'Race Course',
    'Rain Water Harvesting', 'Reading Lounge', 'Receiving Station',
    'Reception/ Waiting Room', 'Recreation Facilities', 'Reflexology Park',
    'Reserved Parking', 'Rest House for Drivers', 'Restaurant', 'RO Water System', 'Salon',
    'Sauna Bath', 'School', 'Security Cabin', 'Security Guards', 'Semi Open Car Parking',
    'Senior Citizen Sitout', 'Sensor operated doors and lifts', 'Server Room', 'Service Lift',
    'Sewage Treatment Plant', 'Shooting range', 'Shopping Mall', 'Skating Rink',
    'Smoke Detectors', 'Solar Lighting', 'Solar Power System', 'Solar Water Heating',
    'Solid Waste Management And Disposal', 'Spa', 'Spa/ Sauna/ Steam', 'Sports Area',
    'Sports Complex', 'Sports Facility', 'Squash Court', 'Staff Quarter', 'Steam Room',
    'Storm Water Drains', 'Street Lighting', 'Sub-Station', 'Sun Bathing', 'Sun Deck',
    'Swimming Pool', 'Table Tennis', 'Taxi/ Bus Terminal', 'Temple', 'Tennis Court',
    'Terrace Garden', 'Theme Park', 'Two Wheeler Parking', 'Utility Shops', 'Vaastu Compliant',
    'Valet Parking', 'Vastu Compliant', 'Vertical Garden', 'Video Door Security',
    'Visitor Parking', 'Volleyball Court', 'Waiting Lounge', 'Wall Climbing',
    'Water Conservation', 'Rain water Harvesting', 'Water Softener Plant', 'Water Sports',
    'Water Storage', 'Water Supply', 'Yoga/ Meditation Area', 'Zebra Crossing', 'Others'
  ];

  const PAYMENT_PLAN_MASTER = [
    'Construction Linked Payment (CLP)',
    'Time Linked Payment (TLP)',
    'Subvention Scheme',
    'Down Payment',
  ];

  GM_addStyle(`
    #_cms_launch_btn {
      position: fixed; bottom: 24px; right: 24px; z-index: 999998;
      background: #4f46e5; color: #fff; border: none; border-radius: 50px;
      padding: 12px 20px; font-size: 14px; font-weight: 700; cursor: pointer;
      box-shadow: 0 4px 20px rgba(79,70,229,.5);
      display: flex; align-items: center; gap: 8px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    #_cms_launch_btn .lbadge {
      background: rgba(255,255,255,.25);
      border-radius: 99px;
      font-size: 11px;
      padding: 2px 7px;
      font-weight: 800;
    }

    #_cms_queue_panel {
      position: fixed; bottom: 24px; right: 24px; z-index: 999999;
      width: 420px; background: #1e1f26; color: #f0f1f5; border-radius: 14px;
      overflow: hidden; box-shadow: 0 8px 40px rgba(0,0,0,.5);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px;
    }
    #_cms_queue_panel header {
      background: #4f46e5; padding: 11px 14px; display: flex; align-items: center; gap: 8px;
    }
    #_cms_queue_panel header strong { flex: 1; font-size: 13px; }
    #_cms_queue_panel .hbadge {
      font-size: 10px; background: rgba(255,255,255,.2);
      border-radius: 99px; padding: 1px 7px; font-weight: 800;
    }
    #_cms_queue_panel header button {
      background: none; border: none; color: rgba(255,255,255,.85);
      cursor: pointer; font-size: 17px; line-height: 1;
      padding: 2px 5px; border-radius: 5px;
    }
    #_cms_queue_panel header button:hover { background: rgba(255,255,255,.2); }

    #_cms_panel_body { padding: 13px 15px 8px; }
    .q-row { margin-bottom: 7px; }
    .q-label {
      font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #9ca3af;
    }
    .q-val {
      font-weight: 600; font-size: 12px; color: #e5e7eb; word-break: break-word;
    }
    #_cms_progress { font-size: 11px; color: #9ca3af; margin-top: 2px; }
    #_cms_status_msg {
      font-size: 11px; padding: 5px 0 2px; min-height: 18px;
      color: #fbbf24; font-weight: 500;
    }
    #_cms_debug {
      font-size: 10px; color: #9ca3af; padding: 6px 0 0; line-height: 1.8;
      border-top: 1px solid #2d3748; margin-top: 6px; max-height: 360px; overflow: auto;
    }
    #_cms_debug .ok  { color: #34d399; }
    #_cms_debug .bad { color: #f87171; }
    #_cms_debug .warn { color: #fbbf24; }

    #_cms_panel_footer {
      padding: 10px 14px 13px; border-top: 1px solid #2d3748;
      display: flex; gap: 7px; flex-wrap: wrap;
    }
    #_cms_panel_footer button {
      flex: 1; min-width: 60px; padding: 8px 0; border: none; border-radius: 8px;
      cursor: pointer; font-size: 12px; font-weight: 700;
    }
    ._cms_btn_fill { background: #4f46e5; color: #fff; }
    ._cms_btn_done { background: #059669; color: #fff; }
    ._cms_btn_skip { background: #374151; color: #d1d5db; }
    ._cms_btn_stop { background: #7f1d1d; color: #fecaca; }
  `);

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function norm(s) {
    return String(s || '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function uniq(arr) {
    return [...new Set(arr.filter(Boolean))];
  }

  function intOrNull(v) {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
  }

  function isVisible(el) {
    return !!(
      el &&
      el.offsetParent !== null &&
      getComputedStyle(el).display !== 'none' &&
      getComputedStyle(el).visibility !== 'hidden'
    );
  }

  function clearAutoClickTimer() {
    if (autoClickTimer) {
      clearInterval(autoClickTimer);
      autoClickTimer = null;
    }
  }

  function clearAjaxWatcher() {
    if (ajaxPollTimer) {
      clearInterval(ajaxPollTimer);
      ajaxPollTimer = null;
    }
  }

  function clearSubmitFlags() {
    sessionStorage.removeItem(SS_PENDING);
    sessionStorage.removeItem(SS_LAST_ACTION);
  }

  function setStatus(msg) {
    const el = document.getElementById('_cms_status_msg');
    if (el) el.textContent = msg;
    console.log('[CMS Plans]', msg);
  }

  function setDebug(lines) {
    const el = document.getElementById('_cms_debug');
    if (!el) return;
    el.innerHTML = lines.map(([kind, txt]) => {
      const cls = kind === 'ok' ? 'ok' : kind === 'warn' ? 'warn' : 'bad';
      const icon = kind === 'ok' ? '✓' : kind === 'warn' ? '⚠' : '✗';
      return `<span class="${cls}">${icon} ${txt}</span><br>`;
    }).join('');
  }

  function dispatchValueEvents(el) {
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    try { el.dispatchEvent(new Event('blur', { bubbles: true })); } catch (_) {}
  }

  function candidateContainersForLabel(label, tags) {
    const needle = norm(label);
    const els = Array.from(document.querySelectorAll(tags || 'td,th,div,p,span,label'))
      .filter(isVisible)
      .filter(el => norm(el.textContent).includes(needle));

    els.sort((a, b) => a.textContent.length - b.textContent.length);
    return els;
  }

  function findControlsByLabel(label, selector, maxCount = Infinity) {
    const out = [];
    const seen = new Set();

    const containers = candidateContainersForLabel(label);
    for (const el of containers) {
      const found = Array.from(el.querySelectorAll(selector)).filter(isVisible);
      for (const f of found) {
        if (!seen.has(f)) {
          seen.add(f);
          out.push(f);
          if (out.length >= maxCount) return out;
        }
      }

      const next = el.nextElementSibling;
      if (next) {
        const foundNext = Array.from(next.querySelectorAll(selector)).filter(isVisible);
        for (const f of foundNext) {
          if (!seen.has(f)) {
            seen.add(f);
            out.push(f);
            if (out.length >= maxCount) return out;
          }
        }
      }

      const parent = el.parentElement;
      if (parent) {
        const foundParent = Array.from(parent.querySelectorAll(selector)).filter(isVisible);
        for (const f of foundParent) {
          if (!seen.has(f)) {
            seen.add(f);
            out.push(f);
            if (out.length >= maxCount) return out;
          }
        }
      }
    }

    return out;
  }

  function findSelectImmediatelyAfterLabel(labelText) {
    const needle = norm(labelText);
    const containers = Array.from(document.querySelectorAll('td,th,div,p,span,label'))
      .filter(isVisible)
      .filter(el => norm(el.textContent).includes(needle));

    for (const el of containers) {
      const walker = document.createTreeWalker(
        el,
        NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
        null,
        false
      );

      let passedLabel = false;
      let node;

      while ((node = walker.nextNode())) {
        if (!passedLabel && node.nodeType === Node.TEXT_NODE && norm(node.textContent).includes(needle)) {
          passedLabel = true;
          continue;
        }

        if (passedLabel && node.nodeType === Node.ELEMENT_NODE && node.tagName === 'SELECT' && isVisible(node)) {
          return node;
        }
      }

      const next = el.nextElementSibling;
      if (next) {
        const sel = next.querySelector('select');
        if (sel && isVisible(sel)) return sel;
      }
    }

    return null;
  }

  function findHowManySelect() {
    return findControlsByLabel('how many files would you like to upload', 'select', 1)[0] ||
           findControlsByLabel('how many files', 'select', 1)[0] ||
           null;
  }

  function findImageTypeSelect() {
    return findControlsByLabel('image type', 'select', 1)[0] || null;
  }

  function findSourceSelect() {
    return findControlsByLabel('source', 'select', 1)[0] || null;
  }

  function findCommentsInput() {
    return findControlsByLabel('comments', 'textarea, input[type="text"]', 1)[0] || null;
  }

  function findVisibleFileInputs() {
    return Array.from(document.querySelectorAll('input[type="file"]')).filter(isVisible);
  }

  function findTaggedDateInputs() {
    return findControlsByLabel('tagged date', 'input[type="text"], textarea');
  }

  function findTowerSelects() {
    return findControlsByLabel('tower', 'select');
  }

  // knownTypeEl: the already-found Image Type select — passed in so exclusion is stable.
  // selectsBeforeTypeSet: snapshot of visible selects taken BEFORE image type was changed;
  //   any select visible NOW but not in the snapshot is the newly-shown secondary dropdown.
  function findSecondaryTypeSelect(category, knownTypeEl, selectsBeforeTypeSet) {
    const c = norm(category);

    const excluded = new Set(
      [knownTypeEl || findImageTypeSelect(), findSourceSelect(), findHowManySelect()].filter(Boolean)
    );

    // Strategy 1 (most reliable): find a select that appeared AFTER the image type was set.
    // Skip numeric-text-only selects (e.g. Display Order: "1","2","3"…) which may appear
    // at the same time as the secondary type dropdown but are not what we want.
    if (selectsBeforeTypeSet) {
      for (const sel of document.querySelectorAll('select')) {
        if (!isVisible(sel)) continue;
        if (excluded.has(sel)) continue;
        if (selectsBeforeTypeSet.has(sel)) continue;
        const allOpts = Array.from(sel.options);
        const nonEmpty = allOpts.filter(o => o.value !== '');
        // Skip pure count/order pickers (every option TEXT is a plain integer)
        if (nonEmpty.length > 0 && nonEmpty.every(o => /^\d+$/.test((o.text || '').trim()))) continue;
        return sel;
      }
    }

    // Strategy 2: label-based search — multiple variants to handle different CMS pages.
    const labelMap = {
      'main other': [
        'main other type', 'main-other type', 'main other sub type',
        'main other subtype', 'main other image type', 'other type'
      ],
      'amenities': [
        'amenities type', 'amenity type', 'amenities sub type',
        'amenities subtype', 'amenities image type'
      ],
      'payment plan': [
        'payment plan type', 'payment type', 'payment plan sub type',
        'payment plan subtype', 'payment plan category'
      ]
    };
    for (const v of (labelMap[c] || [])) {
      const sel = findSelectImmediatelyAfterLabel(v);
      if (sel && !excluded.has(sel)) return sel;
    }

    // Strategy 3: any visible non-excluded select with options matching the master list.
    const master = c === 'amenities' ? AMENITIES_MASTER
                 : c === 'main other' ? MAIN_OTHER_MASTER
                 : c === 'payment plan' ? PAYMENT_PLAN_MASTER
                 : [];
    if (master.length) {
      const masterKeys = new Set(master.map(canonicalKey));
      for (const sel of document.querySelectorAll('select')) {
        if (!isVisible(sel)) continue;
        if (excluded.has(sel)) continue;
        const matchCount = Array.from(sel.options)
          .filter(o => masterKeys.has(canonicalKey(o.text || o.value))).length;
        if (matchCount >= 1) return sel;
      }
    }

    // Strategy 4 (last resort): any non-excluded visible select that is NOT a pure
    // count/order picker. Crucially, we do NOT require opts.length > 1 — the secondary
    // dropdown may only have its placeholder loaded when this runs (options load via AJAX
    // after image type changes). retrySelect will keep calling us until options appear.
    for (const sel of document.querySelectorAll('select')) {
      if (!isVisible(sel)) continue;
      if (excluded.has(sel)) continue;
      const allOpts = Array.from(sel.options);
      if (allOpts.length === 0) continue;  // completely empty, not rendered yet
      const nonEmpty = allOpts.filter(o => o.value !== '');
      // Skip selects where every non-placeholder option TEXT is a plain integer
      if (nonEmpty.length > 0 && nonEmpty.every(o => /^\d+$/.test((o.text || '').trim()))) continue;
      return sel;
    }

    return null;
  }

  function findRadiosByLabel(needle) {
    const radios = findControlsByLabel(needle, 'input[type="radio"]');
    if (radios.length) return radios;
    return Array.from(document.querySelectorAll('input[type="radio"]')).filter(isVisible);
  }

  function findAddMoreBtn() {
    return Array.from(document.querySelectorAll('input, button')).find(b => {
      const txt = norm(b.value || b.textContent || '');
      return txt.includes('add more');
    }) || null;
  }

  function findSaveBtn() {
    return Array.from(document.querySelectorAll('input, button')).find(b => {
      const txt = norm(b.value || b.textContent || '');
      return txt === 'save' || txt.startsWith('save');
    }) || null;
  }

  function setInput(el, value) {
    if (!el) return false;
    try {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value')?.set;
      if (setter) setter.call(el, value);
      else el.value = value;
    } catch (_) {
      el.value = value;
    }
    dispatchValueEvents(el);
    return true;
  }

  function selectByAliases(selectEl, aliases) {
    if (!selectEl || !aliases || !aliases.length) return false;

    const normalizedAliases = aliases.map(norm).filter(Boolean);
    const options = Array.from(selectEl.options);

    for (let i = 0; i < options.length; i++) {
      const txt = norm(options[i].text);
      const val = norm(options[i].value);
      if (normalizedAliases.includes(txt) || normalizedAliases.includes(val)) {
        selectEl.selectedIndex = i;
        dispatchValueEvents(selectEl);
        return true;
      }
    }

    for (let i = 0; i < options.length; i++) {
      const txt = norm(options[i].text);
      const val = norm(options[i].value);
      if (normalizedAliases.some(a => txt.includes(a) || a.includes(txt) || val.includes(a) || a.includes(val))) {
        selectEl.selectedIndex = i;
        dispatchValueEvents(selectEl);
        return true;
      }
    }

    return false;
  }

  async function retrySelect(getter, aliases, tries = 15, delay = 350) {
    for (let i = 0; i < tries; i++) {
      const el = getter();
      if (el && selectByAliases(el, aliases)) return true;
      await sleep(delay);
    }
    return false;
  }

  async function retryInput(getter, value, tries = 8, delay = 250) {
    for (let i = 0; i < tries; i++) {
      const el = getter();
      if (el && setInput(el, value)) return true;
      await sleep(delay);
    }
    return false;
  }

  function selectNumericOption(selectEl, desiredCount) {
    if (!selectEl) return false;
    const desired = intOrNull(desiredCount) || 1;
    const options = Array.from(selectEl.options);

    for (let i = 0; i < options.length; i++) {
      const txt = norm(options[i].text);
      const val = norm(options[i].value);
      if (txt === String(desired) || val === String(desired)) {
        selectEl.selectedIndex = i;
        dispatchValueEvents(selectEl);
        return true;
      }
    }

    for (let i = 0; i < options.length; i++) {
      const txt = norm(options[i].text);
      const val = norm(options[i].value);
      if (txt.includes(String(desired)) || val.includes(String(desired))) {
        selectEl.selectedIndex = i;
        dispatchValueEvents(selectEl);
        return true;
      }
    }

    return false;
  }

  function setRadioByAliases(radios, aliases) {
    if (!radios || !radios.length) return false;
    const targets = aliases.map(norm).filter(Boolean);

    for (const r of radios) {
      const lbl = norm(
        r.labels?.[0]?.textContent ||
        r.closest('label')?.textContent ||
        r.parentElement?.textContent ||
        r.value ||
        ''
      );

      if (targets.some(t => lbl.includes(t) || t.includes(lbl))) {
        r.checked = true;
        r.dispatchEvent(new Event('change', { bubbles: true }));
        r.dispatchEvent(new Event('click', { bubbles: true }));
        return true;
      }
    }

    return false;
  }

  function getGroupItems(item) {
    if (Array.isArray(item?.group_items) && item.group_items.length) return item.group_items;
    if (Array.isArray(item?.items) && item.items.length) return item.items;
    if (Array.isArray(item?.files) && item.files.length) return item.files;
    return [item];
  }

  function getDesiredFileCount(item, groupItems) {
    const candidates = [
      item?.how_many_files,
      item?.upload_count,
      item?.file_count,
      item?.files_count,
      item?.group_count,
      item?.group_size,
      item?.total_files,
      item?.total_in_group,
      item?.count,
      groupItems?.length
    ];

    for (const c of candidates) {
      const n = intOrNull(c);
      if (n) return n;
    }
    return 1;
  }

  function sourceAliasesFromItem(src) {
    const s = norm(src);
    const map = {
      'web': ['developer website', 'website', 'web'],
      'developer website': ['developer website', 'website', 'web'],
      'pdf': ['brochure', 'pdf'],
      'enrich': ['brochure', 'pdf'],
      'brochure': ['brochure', 'pdf'],
      '99ac': ['99 acres', '99ac', '99acres'],
      '99 acres': ['99 acres', '99ac', '99acres'],
      '99acres': ['99 acres', '99ac', '99acres'],
      'rera': ['rera', 'rera website'],
      'gov': ['rera', 'rera website'],
      'ci team': ['ci team'],
      'marketing team': ['marketing team'],
      'sales team': ['sales team'],
      'square yard': ['square yard'],
      'other competition': ['other competition']
    };
    return uniq([...(map[s] || []), src, s]);
  }

  function typeAliasesFromItem(category) {
    const c = norm(category);
    const map = {
      'top view (aerial view)': ['top view', 'aerial view', 'top view (aerial view)'],
      'project logo': ['project logo', 'logo'],
      'payment plan': ['payment plan'],
      'layout plan': ['layout plan'],
      'location plan': ['location plan'],
      'site plan': ['site plan'],
      'master plan': ['master plan'],
      'cluster plan': ['cluster plan'],
      'elevation': ['elevation'],
      'main other': ['main other'],
      'amenities': ['amenities'],
      'qr code': ['qr code', 'qr'],
      'construction status': ['construction status']
    };
    return uniq([...(map[c] || []), category, c]);
  }

  function stripExtension(filename) {
    return String(filename || '').replace(/\.[^.]+$/, '');
  }

  function canonicalKey(s) {
    return String(s || '')
      .toLowerCase()
      .replace(/[_-]+/g, ' ')
      .replace(/[()'.]/g, '')
      .replace(/&/g, ' and ')
      .replace(/\//g, ' ')
      .replace(/\b24x7\b/g, '24 x 7')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function titleCaseToken(s) {
    return String(s || '')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .split(' ')
      .map(w => w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : '')
      .join(' ');
  }

  function parseCategoryAndSubtypeFromFilename(filename) {
    const base = stripExtension(filename);

    const patterns = [
      { category: 'Main Other', regex: /^Main_Other_-_(.+?)__(.+)$/i },
      { category: 'Amenities', regex: /^Amenities_-_(.+?)__(.+)$/i },
      { category: 'Construction Status', regex: /^Construction_Status(?:_-_(.+?))?__(.+)$/i }
    ];

    for (const p of patterns) {
      const m = base.match(p.regex);
      if (m) {
        return {
          category: p.category,
          subtype: m[1] ? titleCaseToken(m[1]) : null
        };
      }
    }

    return { category: null, subtype: null };
  }

  function resolveSubtype(category, item) {
    const parsed = parseCategoryAndSubtypeFromFilename(item?.filename || '');
    const raw =
      item?.subtype ||
      item?.sub_type ||
      item?.secondary_type ||
      item?.second_info ||
      item?.sub_category ||
      item?.subcategory ||
      item?.amenities_type ||
      item?.main_other_type ||
      parsed.subtype;

    if (!raw) return null;

    const rawKey = canonicalKey(raw);

    const master =
      norm(category) === 'amenities' ? AMENITIES_MASTER :
      norm(category) === 'main other' ? MAIN_OTHER_MASTER :
      norm(category) === 'payment plan' ? PAYMENT_PLAN_MASTER :
      [];

    if (!master.length) return raw;

    const exact = master.find(x => canonicalKey(x) === rawKey);
    if (exact) return exact;

    const fuzzy = master.find(x => canonicalKey(x).includes(rawKey) || rawKey.includes(canonicalKey(x)));
    if (fuzzy) return fuzzy;

    return raw;
  }

  function getTaggedDateValue(item) {
    return item?.status_date ||       // 99Acres construction status date (from backend)
           item?.tagged_date ||
           item?.tag_date ||
           item?.construction_date ||
           item?.date ||
           null;
  }

  function getTowerValue(item) {
    return item?.tower || item?.tower_name || null;
  }

  function getEffectiveCategory(item) {
    const parsed = parseCategoryAndSubtypeFromFilename(item?.filename || '');
    return item?.category || parsed.category || null;
  }

  async function waitForFileInputs(expectedCount) {
    const timeoutMs = 5000;
    const start = Date.now();

    while (Date.now() - start < timeoutMs) {
      const fileCount = findVisibleFileInputs().length;
      if (fileCount >= expectedCount) return true;
      await sleep(250);
    }
    return false;
  }

  const _MONTH_NUM = {
    jan:'01', feb:'02', mar:'03', apr:'04', may:'05', jun:'06',
    jul:'07', aug:'08', sep:'09', oct:'10', nov:'11', dec:'12'
  };
  function _monthNum(s) { return _MONTH_NUM[String(s).slice(0,3).toLowerCase()] || '01'; }

  function normalizeDateForCms(raw) {
    if (!raw) return '';
    const s = String(raw).trim();

    // Already YYYY-MM-DD — pass through unchanged
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;

    // DD-MM-YYYY → YYYY-MM-DD
    const ddmm = s.match(/^(\d{2})-(\d{2})-(\d{4})$/);
    if (ddmm) return `${ddmm[3]}-${ddmm[2]}-${ddmm[1]}`;

    // DD/MM/YYYY → YYYY-MM-DD
    const ddmm2 = s.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (ddmm2) return `${ddmm2[3]}-${ddmm2[2]}-${ddmm2[1]}`;

    // YYYY/MM/DD → YYYY-MM-DD
    const iso2 = s.match(/^(\d{4})\/(\d{2})\/(\d{2})$/);
    if (iso2) return `${iso2[1]}-${iso2[2]}-${iso2[3]}`;

    // "15 Nov, 2023" or "15 November 2023"
    const m1 = s.match(/(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})/);
    if (m1) return `${m1[3]}-${_monthNum(m1[2])}-${m1[1].padStart(2,'0')}`;

    // "November 2023" or "Nov, 2023" or "Nov 2023" — from 99Acres status_date
    const m2 = s.match(/([A-Za-z]+),?\s+(\d{4})/);
    if (m2) return `${m2[2]}-${_monthNum(m2[1])}-01`;

    // "2023-11" (year-month only)
    const m3 = s.match(/^(\d{4})-(\d{2})$/);
    if (m3) return `${m3[1]}-${m3[2]}-01`;

    return s;
  }

  function detectMimeFromBytes(buffer) {
    const bytes = new Uint8Array(buffer.slice(0, 16));

    if (
      bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4E && bytes[3] === 0x47 &&
      bytes[4] === 0x0D && bytes[5] === 0x0A && bytes[6] === 0x1A && bytes[7] === 0x0A
    ) return 'image/png';

    if (bytes[0] === 0xFF && bytes[1] === 0xD8 && bytes[2] === 0xFF) return 'image/jpeg';

    if (
      bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46 &&
      bytes[3] === 0x38 && (bytes[4] === 0x37 || bytes[4] === 0x39) && bytes[5] === 0x61
    ) return 'image/gif';

    if (
      bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
    ) return 'image/webp';

    const ascii = Array.from(bytes).map(b => String.fromCharCode(b)).join('');
    if (ascii.includes('ftypavif')) return 'image/avif';
    if (ascii.includes('ftypheic') || ascii.includes('ftypheif')) return 'image/heic';

    return 'application/octet-stream';
  }

  function ensureExt(filename, ext) {
    if (!filename) return 'image' + ext;
    return /\.[a-z0-9]+$/i.test(filename)
      ? filename.replace(/\.[^.]+$/, ext)
      : filename + ext;
  }

  function convertToJpeg(arrayBuffer, filename) {
    return new Promise((resolve, reject) => {
      const blob = new Blob([arrayBuffer]);
      const url = URL.createObjectURL(blob);
      const img = new Image();

      img.onload = () => {
        URL.revokeObjectURL(url);

        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;

        const ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('Canvas context unavailable'));
          return;
        }

        ctx.drawImage(img, 0, 0);

        canvas.toBlob(async jpegBlob => {
          if (!jpegBlob) {
            reject(new Error('JPEG conversion failed'));
            return;
          }

          const buf = await jpegBlob.arrayBuffer();
          resolve({
            buffer: buf,
            filename: ensureExt(filename, '.jpg'),
            mime: 'image/jpeg',
            converted: true
          });
        }, 'image/jpeg', 0.92);
      };

      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error('Image decode failed'));
      };

      img.src = url;
    });
  }

  async function normalizeFile(buffer, filename) {
    const mime = detectMimeFromBytes(buffer);

    if (mime === 'image/jpeg') return { buffer, filename: ensureExt(filename, '.jpg'), mime, converted: false };
    if (mime === 'image/png') return { buffer, filename: ensureExt(filename, '.png'), mime, converted: false };
    if (mime === 'image/gif') return { buffer, filename: ensureExt(filename, '.gif'), mime, converted: false };

    // Guard: if the first bytes look like JSON ({) or HTML (<), this is an error response, not an image.
    const firstByte = new Uint8Array(buffer.slice(0, 1))[0];
    if (firstByte === 0x7B || firstByte === 0x3C) {
      throw new Error('Server returned an error page — session may have expired, re-scrape');
    }

    return convertToJpeg(buffer, filename || 'image.jpg');
  }

  function injectFile(fileInputEl, arrayBuffer, filename, mime) {
    try {
      const file = new File([arrayBuffer], filename, {
        type: mime,
        lastModified: Date.now()
      });

      const dt = new DataTransfer();
      dt.items.add(file);
      fileInputEl.files = dt.files;
      fileInputEl.dispatchEvent(new Event('change', { bubbles: true }));
      fileInputEl.dispatchEvent(new Event('input', { bubbles: true }));
      return !!(fileInputEl.files && fileInputEl.files.length > 0);
    } catch (e) {
      console.error('injectFile failed', e);
      return false;
    }
  }

  function apiGet(path) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'GET',
        url: API + path,
        onload: r => {
          try { resolve(JSON.parse(r.responseText)); }
          catch (e) { reject(e); }
        },
        onerror: () => reject(new Error('Network error — is the PDF tool server running?'))
      });
    });
  }

  function apiPost(path, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'POST',
        url: API + path,
        headers: { 'Content-Type': 'application/json' },
        data: body ? JSON.stringify(body) : '{}',
        onload: r => {
          try { resolve(JSON.parse(r.responseText)); }
          catch (e) { reject(e); }
        },
        onerror: () => reject(new Error('Network error'))
      });
    });
  }

  function fetchImageBuffer(sessionId, imageId) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'GET',
        url: `${API}/image/${sessionId}/${imageId}`,
        responseType: 'arraybuffer',
        onload: r => {
          if (r.status !== 200) {
            reject(new Error(`HTTP ${r.status} — session may have expired, re-scrape`));
          } else if (!r.response || r.response.byteLength < 100) {
            reject(new Error('Empty or truncated response'));
          } else {
            resolve(r.response);
          }
        },
        onerror: () => reject(new Error('Image download failed'))
      });
    });
  }

  function pageHasCmsError() {
    const selectors = [
      '.alert-danger',
      '.alert-error',
      '.error',
      '.error-msg',
      '.validation-error',
      'font[color="red"]',
      'font[color="#ff0000"]',
      '[class*="error"]'
    ];

    const txt = Array.from(document.querySelectorAll(selectors.join(',')))
      .filter(isVisible)
      .map(el => norm(el.innerText || el.textContent || ''))
      .join(' | ');

    if (!txt) return false;

    const known = [
      'you can upload only',
      'image type is required',
      'please select',
      'required field',
      'invalid file',
      'file type not allowed',
      'could not save',
      'error occurred',
      'please upload'
    ];

    return known.some(k => txt.includes(k));
  }

  function pageHasCmsSuccess() {
    const selectors = [
      '.alert-success',
      '.success',
      '.success-msg',
      '.msg-success',
      '[class*="success"]'
    ];

    const txt = Array.from(document.querySelectorAll(selectors.join(',')))
      .filter(isVisible)
      .map(el => norm(el.innerText || el.textContent || ''))
      .join(' | ');

    const hints = [
      'saved successfully',
      'successfully saved',
      'added successfully',
      'updated successfully',
      'success'
    ];

    return hints.some(h => txt.includes(h));
  }

  function formLooksReset() {
    const typeEl = findImageTypeSelect();
    const sourceEl = findSourceSelect();
    const fileInputs = findVisibleFileInputs();

    const typeReset = !typeEl || typeEl.selectedIndex <= 0;
    const sourceReset = !sourceEl || sourceEl.selectedIndex <= 0;
    const fileReset = !fileInputs.length || fileInputs.every(el => !el.files || el.files.length === 0);

    return (typeReset && sourceReset && fileReset) || fileReset;
  }

  function updatePanelInfo(item, index, total) {
    if (!panelEl) return;
    const category = getEffectiveCategory(item) || item.category || '—';
    document.getElementById('_cms_qfile').textContent = item.filename || '—';
    document.getElementById('_cms_qcat').textContent = category;
    document.getElementById('_cms_qsrc').textContent = item.source || '—';
    document.getElementById('_cms_qreal').textContent = item.image_reality || 'Actual';
    document.getElementById('_cms_qtitle').textContent = stripExtension(item.filename || '') || '—';
    document.getElementById('_cms_progress').textContent = `Item ${index + 1} of ${total}`;
    document.getElementById('_cms_debug').innerHTML = '';
  }

  function createPanel() {
    panelEl = document.createElement('div');
    panelEl.id = '_cms_queue_panel';
    panelEl.innerHTML = `
      <header>
        <strong>⬆ CMS Plans Queue <span class="hbadge" id="_cms_modebadge">AUTO</span></strong>
        <button id="_cms_toggle" title="Minimise">−</button>
        <button id="_cms_close" title="Close">×</button>
      </header>
      <div id="_cms_panel_body">
        <div id="_cms_status_msg">Loading…</div>
        <div class="q-row"><div class="q-label">File</div><div class="q-val" id="_cms_qfile">—</div></div>
        <div class="q-row"><div class="q-label">Category</div><div class="q-val" id="_cms_qcat">—</div></div>
        <div class="q-row"><div class="q-label">Source</div><div class="q-val" id="_cms_qsrc">—</div></div>
        <div class="q-row"><div class="q-label">Reality</div><div class="q-val" id="_cms_qreal">—</div></div>
        <div class="q-row"><div class="q-label">Info</div><div class="q-val" id="_cms_qtitle">—</div></div>
        <div id="_cms_progress"></div>
        <div id="_cms_debug"></div>
      </div>
      <div id="_cms_panel_footer">
        <button class="_cms_btn_fill" id="_cms_btn_fill">Re-fill</button>
        <button class="_cms_btn_done" id="_cms_btn_done">Done ›</button>
        <button class="_cms_btn_skip" id="_cms_btn_skip">Skip</button>
        <button class="_cms_btn_stop" id="_cms_btn_stop">Stop</button>
      </div>
    `;
    document.body.appendChild(panelEl);

    let minimised = false;

    document.getElementById('_cms_toggle').addEventListener('click', () => {
      minimised = !minimised;
      document.getElementById('_cms_panel_body').style.display = minimised ? 'none' : '';
      document.getElementById('_cms_panel_footer').style.display = minimised ? 'none' : '';
      document.getElementById('_cms_toggle').textContent = minimised ? '+' : '−';
    });

    document.getElementById('_cms_close').addEventListener('click', () => {
      autoMode = false;
      clearAutoClickTimer();
      clearAjaxWatcher();
      sessionStorage.removeItem(SS_MODE);
      sessionStorage.removeItem(SS_SAVED);
      clearSubmitFlags();
      panelEl.remove();
      panelEl = null;
      createLaunchButton();
    });

    document.getElementById('_cms_btn_fill').addEventListener('click', () => {
      clearAutoClickTimer();
      if (currentItem) fillPlanForm(currentItem);
    });

    document.getElementById('_cms_btn_done').addEventListener('click', async () => {
      await markDone();
    });

    document.getElementById('_cms_btn_skip').addEventListener('click', async () => {
      await apiPost('/cms-queue/skip');
      await fetchNext(autoMode);
    });

    document.getElementById('_cms_btn_stop').addEventListener('click', () => {
      autoMode = false;
      clearAutoClickTimer();
      clearAjaxWatcher();
      sessionStorage.removeItem(SS_MODE);
      clearSubmitFlags();
      setStatus('Auto mode stopped — review and submit manually.');
      document.getElementById('_cms_modebadge').textContent = 'MANUAL';
    });
  }

  function createLaunchButton() {
    launchBtn = document.createElement('button');
    launchBtn.id = '_cms_launch_btn';
    launchBtn.innerHTML = `⬆ Start Plans Queue <span class="lbadge" id="_cms_lcount">…</span>`;
    document.body.appendChild(launchBtn);

    apiGet('/cms-queue/status').then(d => {
      const el = document.getElementById('_cms_lcount');
      if (el) el.textContent = d.remaining > 0 ? `${d.remaining}` : '0';
      if (d.remaining === 0) launchBtn.style.opacity = '.55';
    }).catch(() => {
      const el = document.getElementById('_cms_lcount');
      if (el) el.textContent = '?';
    });

    launchBtn.addEventListener('click', () => {
      launchBtn.remove();
      launchBtn = null;
      autoMode = true;
      sessionStorage.setItem(SS_MODE, '1');
      createPanel();
      fetchNext(true);
    });
  }

  async function markDone() {
    setStatus('Marking done…');
    await apiPost('/cms-queue/done');
    await fetchNext(autoMode);
  }

  async function fetchNext(autoFill) {
    setStatus('Loading next queue item…');

    try {
      const data = await apiGet('/cms-queue/next');

      if (data.done || !data.item) {
        setStatus('✓ Queue complete');
        sessionStorage.removeItem(SS_MODE);
        clearSubmitFlags();
        currentItem = null;

        if (panelEl) {
          ['_cms_qfile', '_cms_qcat', '_cms_qsrc', '_cms_qreal', '_cms_qtitle'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '—';
          });
          document.getElementById('_cms_progress').textContent = 'All done';
        }
        return;
      }

      currentItem = data.item;
      queueRemaining = data.remaining;
      updatePanelInfo(data.item, data.index, data.total);

      if (autoFill) {
        await sleep(300);
        await fillPlanForm(data.item);
      }
    } catch (e) {
      setStatus('⚠ ' + e.message);
    }
  }

  function startAjaxWatcher(action) {
    clearAjaxWatcher();

    const startedAt = Date.now();

    ajaxPollTimer = setInterval(async () => {
      if (Date.now() - startedAt > 12000) {
        clearAjaxWatcher();
        setStatus('No submit confirmation detected — please review manually.');
        return;
      }

      if (pageHasCmsError()) {
        clearAjaxWatcher();
        clearAutoClickTimer();
        clearSubmitFlags();
        setStatus('⚠ CMS save error detected — fix and submit again.');
        return;
      }

      if (pageHasCmsSuccess() || formLooksReset()) {
        clearAjaxWatcher();
        clearAutoClickTimer();
        clearSubmitFlags();

        try {
          setStatus('✓ Saved! Marking queue item done…');
          await apiPost('/cms-queue/done');

          if (action === 'add_more') {
            await fetchNext(true);
          } else {
            await fetchNext(false);
          }
        } catch (e) {
          setStatus('⚠ ' + e.message);
        }
      }
    }, 350);
  }

  function attachFormListeners() {
    const form = document.querySelector('form');
    if (!form || form._cmsPlansWatched) return;
    form._cmsPlansWatched = true;

    form.addEventListener('submit', () => {
      sessionStorage.setItem(SS_SAVED, '1');
      sessionStorage.setItem(SS_PENDING, '1');
      sessionStorage.setItem(SS_MODE, '1');
    });

    const addMoreBtn = findAddMoreBtn();
    if (addMoreBtn && !addMoreBtn._cmsPlansWatched) {
      addMoreBtn._cmsPlansWatched = true;
      addMoreBtn.addEventListener('click', () => {
        sessionStorage.setItem(SS_PENDING, '1');
        sessionStorage.setItem(SS_LAST_ACTION, 'add_more');
        if (autoMode) startAjaxWatcher('add_more');
      });
    }

    const saveBtn = findSaveBtn();
    if (saveBtn && !saveBtn._cmsPlansWatched) {
      saveBtn._cmsPlansWatched = true;
      saveBtn.addEventListener('click', () => {
        sessionStorage.setItem(SS_PENDING, '1');
        sessionStorage.setItem(SS_LAST_ACTION, 'save');
        if (autoMode) startAjaxWatcher('save');
      });
    }
  }

  async function fillPlanForm(item) {
    setStatus('Filling Project Plans form…');
    const debug = [];

    const groupItems = getGroupItems(item);
    const desiredCount = getDesiredFileCount(item, groupItems);
    const rootCategory = getEffectiveCategory(item) || item.category || '';
    const categoryNorm = norm(rootCategory);

    const howManyEl = findHowManySelect();
    const typeEl = findImageTypeSelect();
    const sourceEl = findSourceSelect();
    const commentsEl = findCommentsInput();

    let howManyOk = false;
    if (howManyEl) {
      howManyOk = selectNumericOption(howManyEl, desiredCount);
      debug.push([howManyOk ? 'ok' : 'bad', howManyOk ? `How Many Files → ${desiredCount}` : `Could not set How Many Files → ${desiredCount}`]);
      if (howManyOk) {
        await sleep(600);
        await waitForFileInputs(Math.min(desiredCount, groupItems.length));
      }
    } else {
      debug.push(['bad', 'How Many Files dropdown not found']);
    }

    const syncOk = setRadioByAliases(findRadiosByLabel('image sync to'), ['pt + housing', 'pt+housing']);
    debug.push([syncOk ? 'ok' : 'bad', syncOk ? 'Image Sync → PT + Housing' : 'Image Sync radio not found']);

    const realityOk = setRadioByAliases(findRadiosByLabel('image reality'), [item.image_reality || 'actual', 'actual']);
    debug.push([realityOk ? 'ok' : 'bad', realityOk ? `Image Reality → ${item.image_reality || 'Actual'}` : 'Image Reality radio not found']);

    // Snapshot ALL visible selects before setting Image Type — after we set it, any
    // newly-visible select is the secondary dropdown (most reliable detection method).
    const selectsBeforeTypeSet = new Set(Array.from(document.querySelectorAll('select')).filter(isVisible));

    let typeOk = false;
    if (typeEl) {
      typeOk = selectByAliases(typeEl, typeAliasesFromItem(rootCategory));
      debug.push([typeOk ? 'ok' : 'bad', typeOk ? `Image Type → "${rootCategory}"` : `Type not found in dropdown for "${rootCategory}"`]);
    } else {
      debug.push(['bad', 'Image Type dropdown not found']);
    }

    let sourceOk = false;
    if (sourceEl) {
      sourceOk = selectByAliases(sourceEl, sourceAliasesFromItem(item.source));
      debug.push([sourceOk ? 'ok' : 'bad', sourceOk ? `Source → "${item.source}"` : `Source not found in dropdown for "${item.source}"`]);
    } else {
      debug.push(['bad', 'Source dropdown not found']);
    }

    if (commentsEl) {
      setInput(commentsEl, item.comments || '');
      debug.push(['ok', 'Comments handled']);
    }

    await sleep(500);

    const fileInputs = findVisibleFileInputs();
    const needsSecondary = categoryNorm === 'amenities' || categoryNorm === 'main other';

    if (!fileInputs.length) {
      debug.push(['bad', 'No visible file inputs found after count selection']);
      setDebug(debug);
      setStatus('⚠ File inputs not found');
      return false;
    }

    debug.push(['ok', `Rendered file inputs → ${fileInputs.length}`]);
    debug.push(['ok', `Queue group size → ${groupItems.length}`]);

    let allFilesOk = true;
    let allSecondaryOk = true;
    let allDatesOk = true;
    let allTowersOk = true;

    const enoughPayloads = groupItems.length >= desiredCount;
    const enoughFileSlots = fileInputs.length >= Math.min(desiredCount, groupItems.length);

    if (!enoughPayloads) debug.push(['warn', `Queue asked for ${desiredCount} file(s) but only ${groupItems.length} payload(s) returned`]);
    if (!enoughFileSlots) debug.push(['warn', `CMS rendered only ${fileInputs.length} file input(s)`]);

    const fillableCount = Math.min(groupItems.length, fileInputs.length);

    for (let i = 0; i < fillableCount; i++) {
      const groupItem = groupItems[i];
      const effectiveCategory = getEffectiveCategory(groupItem) || rootCategory;
      const effectiveCategoryNorm = norm(effectiveCategory);
      const fileEl = fileInputs[i];

      if (needsSecondary) {
        const subtypeValue = resolveSubtype(effectiveCategory, groupItem) || resolveSubtype(effectiveCategory, item);

        const subtypeOk = await retrySelect(
          () => findSecondaryTypeSelect(effectiveCategory, typeEl, selectsBeforeTypeSet),
          subtypeValue ? [subtypeValue] : [],
          15,
          350
        );

        allSecondaryOk = allSecondaryOk && subtypeOk;
        debug.push([
          subtypeOk ? 'ok' : 'bad',
          `${effectiveCategory} Type ${i + 1} → "${subtypeValue || 'N/A'}"`
        ]);
      }

      if (effectiveCategoryNorm === 'construction status') {
        const rawDate = getTaggedDateValue(groupItem) || getTaggedDateValue(item);
        const dateValue = normalizeDateForCms(rawDate);

        if (dateValue) {
          const dateOk = await retryInput(
            () => {
              const inputs = findTaggedDateInputs();
              return inputs[i] || inputs[inputs.length - 1] || null;
            },
            dateValue,
            10,
            250
          );
          allDatesOk = allDatesOk && dateOk;
          debug.push([dateOk ? 'ok' : 'bad', `Tagged Date ${i + 1} → "${dateValue}"`]);
        } else {
          allDatesOk = false;
          debug.push(['bad', `Tagged Date ${i + 1} missing from queue`]);
        }

        const towerValue = getTowerValue(groupItem) || getTowerValue(item);
        if (towerValue) {
          const towerOk = await retrySelect(
            () => {
              const selects = findTowerSelects();
              return selects[i] || selects[selects.length - 1] || null;
            },
            [towerValue],
            8,
            250
          );
          allTowersOk = allTowersOk && towerOk;
          debug.push([towerOk ? 'ok' : 'warn', `Tower ${i + 1} → "${towerValue}"`]);
        }
      }

      try {
        const rawBuffer = await fetchImageBuffer(groupItem.session_id, groupItem.id);
        const normalized = await normalizeFile(rawBuffer, groupItem.filename || `${groupItem.id}.jpg`);
        const fileOk = injectFile(fileEl, normalized.buffer, normalized.filename, normalized.mime);
        allFilesOk = allFilesOk && fileOk;

        if (normalized.converted) {
          debug.push(['ok', `Converted file ${i + 1} → ${normalized.filename}`]);
        }
        debug.push([fileOk ? 'ok' : 'bad', `File ${i + 1} ready → ${normalized.filename}`]);
      } catch (e) {
        allFilesOk = false;
        debug.push(['bad', `File ${i + 1} failed → ${e.message}`]);
      }
    }

    setDebug(debug);
    attachFormListeners();

    const allGood =
      howManyOk &&
      syncOk &&
      realityOk &&
      typeOk &&
      sourceOk &&
      allFilesOk &&
      enoughPayloads &&
      enoughFileSlots &&
      (!needsSecondary || allSecondaryOk) &&
      (categoryNorm !== 'construction status' || allDatesOk) &&
      allTowersOk;

    if (!allGood) {
      setStatus('⚠ Some fields were not filled correctly. Check debug lines.');
      return false;
    }

    const isLast = queueRemaining <= 1;
    const btn = isLast ? findSaveBtn() : findAddMoreBtn();
    const btnName = isLast ? 'Save' : 'Add More';

    if (autoMode && btn) {
      let secs = 3;
      setStatus(`Clicking "${btnName}" in ${secs}s — click Stop to cancel`);

      autoClickTimer = setInterval(() => {
        secs--;
        if (secs > 0) {
          setStatus(`Clicking "${btnName}" in ${secs}s — click Stop to cancel`);
        } else {
          clearAutoClickTimer();
          setStatus(`Clicking "${btnName}"…`);
          btn.click();
        }
      }, 1000);
    } else {
      setStatus(`Form filled — review once, then click "${btnName}"`);
    }

    return true;
  }

  async function init() {
    const inAutoMode = !!sessionStorage.getItem(SS_MODE);
    const justSaved = !!sessionStorage.getItem(SS_SAVED);
    sessionStorage.removeItem(SS_SAVED);

    if (!inAutoMode) {
      createLaunchButton();
      return;
    }

    autoMode = true;
    createPanel();

    if (justSaved) {
      await sleep(900);

      if (pageHasCmsError()) {
        clearSubmitFlags();
        setStatus('⚠ CMS save error detected — same item will be re-filled.');
        await fetchNext(true);
        return;
      }

      try {
        setStatus('✓ Previous save detected. Marking done…');
        await apiPost('/cms-queue/done');
        clearSubmitFlags();
      } catch (e) {
        setStatus('⚠ ' + e.message);
        return;
      }
    }

    await fetchNext(true);
  }

  window.runCmsPlanFill = async function () {
    autoMode = false;
    if (!panelEl) createPanel();

    const data = await apiGet('/cms-queue/next');
    if (data.done || !data.item) {
      setStatus('Queue empty');
      return;
    }

    currentItem = data.item;
    queueRemaining = data.remaining;
    updatePanelInfo(data.item, data.index, data.total);
    await fillPlanForm(data.item);
  };

  init();
})();
