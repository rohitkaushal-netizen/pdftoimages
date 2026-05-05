// ==UserScript==
// @name         PDF Tool → CMS Auto-Fill
// @namespace    https://housing.com
// @version      1.4
// @description  Reads images queued by the PDF extraction tool and auto-fills the CMS image upload form one by one — fully automatic.
// @author       Housing.com
// @match        https://cms.housing.com/project_img_add.php*
// @connect      localhost
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ── MAPS ──────────────────────────────────────────────────────────────────────
  const IMAGE_TYPE_MAP = {
    // ── Standard CMS categories ───────────────────────────────────────────────
    'Elevation':              'Elevation',
    'Amenities':              'Amenities',
    'Main Other':             'Main Other',
    'Location Plan':          'Location Plan',
    'Layout Plan':            'Layout Plan',
    'Site Plan':              'Site Plan',
    'Master Plan':            'Master Plan',
    'Cluster Plan':           'Cluster Plan',
    'Construction Status':    'Construction Status',
    'Creative Image':         'Creative Image',
    'Internal Road':          'Internal Road',
    'Entry Road':             'Entry Road',
    'Gate':                   'Gate',
    'Top View (Aerial View)': 'Top View',
    'Reception Area':         'Reception Area',
    'Payment Plan':           'Payment Plan',
    'Project Logo':           'Project Logo',
    'QR Code':                'QR Code',
    // ── 99Acres tuples type labels → CMS category ─────────────────────────────
    'Photos':                 'Elevation',
    'Floor Plan':             'Layout Plan',
    'Floor Plans':            'Layout Plan',
    'Unit Plan':              'Layout Plan',
    'Unit Plans':             'Layout Plan',
    'Master Plan':            'Master Plan',
    'Cluster Plan':           'Cluster Plan',
    'Site Plan':              'Site Plan',
    'Location Map':           'Location Plan',
    'Amenities':              'Amenities',
    'Construction Status':    'Construction Status',
    'Construction Progress':  'Construction Status',
    'Aerial View':            'Top View',
    'Aerial Photos':          'Top View',
    'Interior':               'Main Other',
    'Interior Photos':        'Main Other',
    '3D Render':              'Creative Image',
    '3D Renders':             'Creative Image',
    // Heuristic-based labels from _classify_a99_image fallback
    'Render / Elevation':     'Elevation',
    'Amenity Photo':          'Amenities',
    'Interior Photo':         'Main Other',
    'Construction Progress':  'Construction Status',
    'Location Map':           'Location Plan',
    'Photo':                  'Elevation',
    'Other':                  'Main Other',
  };

  const SOURCE_MAP = {
    'PDF':    'Brochure',
    'Enrich': 'Brochure',
    'Web':    'Developer Website',
    '99Ac':   '99 Acres',
  };

  const API          = 'http://localhost:8000';
  const SS_MODE      = '_cms_auto_fill';   // sessionStorage: auto mode active
  const SS_SAVED     = '_cms_just_saved';  // sessionStorage: form was submitted

  // ── STATE ─────────────────────────────────────────────────────────────────────
  let currentItem     = null;
  let panelEl         = null;
  let launchBtn       = null;
  let autoMode        = false;
  let queueRemaining  = 0;   // updated by fetchNext — used to decide Add More vs Save
  let autoClickTimer  = null; // cancelable timer for the auto-click countdown

  // ── STYLES ────────────────────────────────────────────────────────────────────
  GM_addStyle(`
    #_cms_launch_btn {
      position: fixed; bottom: 24px; right: 24px; z-index: 999998;
      background: #4f46e5; color: #fff; border: none; border-radius: 50px;
      padding: 12px 20px; font-size: 14px; font-weight: 700; cursor: pointer;
      box-shadow: 0 4px 20px rgba(79,70,229,.5);
      display: flex; align-items: center; gap: 8px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      transition: background .15s, transform .1s;
    }
    #_cms_launch_btn:hover { background: #4338ca; transform: translateY(-2px); }
    #_cms_launch_btn .lbadge { background: rgba(255,255,255,.25); border-radius: 99px; font-size: 11px; padding: 2px 7px; font-weight: 800; }

    #_cms_queue_panel {
      position: fixed; bottom: 24px; right: 24px; z-index: 999999;
      width: 340px; background: #1e1f26; color: #f0f1f5; border-radius: 14px;
      overflow: hidden; box-shadow: 0 8px 40px rgba(0,0,0,.5);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px;
    }
    #_cms_queue_panel header { background: #4f46e5; padding: 11px 14px; display: flex; align-items: center; gap: 8px; }
    #_cms_queue_panel header strong { flex: 1; font-size: 13px; }
    #_cms_queue_panel .hbadge { font-size: 10px; background: rgba(255,255,255,.2); border-radius: 99px; padding: 1px 7px; font-weight: 800; }
    #_cms_queue_panel header button { background: none; border: none; color: rgba(255,255,255,.85); cursor: pointer; font-size: 17px; line-height: 1; padding: 2px 5px; border-radius: 5px; }
    #_cms_queue_panel header button:hover { background: rgba(255,255,255,.2); }

    #_cms_panel_body { padding: 13px 15px 8px; }
    .q-row { margin-bottom: 7px; }
    .q-label { font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #6b7280; }
    .q-val { font-weight: 600; font-size: 12px; color: #e5e7eb; word-break: break-all; }
    #_cms_progress { font-size: 11px; color: #6b7280; margin-top: 2px; }
    #_cms_status_msg { font-size: 11px; padding: 5px 0 2px; min-height: 18px; color: #fbbf24; font-weight: 500; }

    #_cms_debug { font-size: 10px; color: #6b7280; padding: 6px 0 0; line-height: 1.8; border-top: 1px solid #2d3748; margin-top: 6px; }
    #_cms_debug .ok  { color: #34d399; }
    #_cms_debug .bad { color: #f87171; }

    #_cms_panel_footer { padding: 10px 14px 13px; border-top: 1px solid #2d3748; display: flex; gap: 7px; flex-wrap: wrap; }
    #_cms_panel_footer button { flex: 1; min-width: 60px; padding: 8px 0; border: none; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 700; transition: background .12s; }
    ._cms_btn_fill { background: #4f46e5; color: #fff; } ._cms_btn_fill:hover { background: #4338ca; }
    ._cms_btn_done { background: #059669; color: #fff; } ._cms_btn_done:hover { background: #047857; }
    ._cms_btn_skip { background: #374151; color: #9ca3af; } ._cms_btn_skip:hover { background: #4b5563; }
    ._cms_btn_stop { background: #7f1d1d; color: #fca5a5; } ._cms_btn_stop:hover { background: #991b1b; }
  `);

  // ── FIELD FINDER ──────────────────────────────────────────────────────────────
  // TreeWalker: find first eligible input AFTER a text node containing `needle`
  // within any matching container element. Works for both separate label cells
  // AND inline labels (e.g. "Title:* <input>", "Image URL: <input>" in same TD).
  function findInputAfterText(needle, containerSel) {
    needle = needle.toLowerCase().trim();
    const containers = document.querySelectorAll(containerSel || 'td,th,div,p');
    for (const el of containers) {
      if (!el.textContent.toLowerCase().includes(needle)) continue;
      const walker = document.createTreeWalker(
        el, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, null, false
      );
      let past = false;
      let node;
      while ((node = walker.nextNode())) {
        if (!past && node.nodeType === Node.TEXT_NODE && node.textContent.toLowerCase().includes(needle)) {
          past = true;
        } else if (past && node.nodeType === Node.ELEMENT_NODE) {
          const t = node.tagName;
          const type = (node.type || '').toLowerCase();
          if (t === 'SELECT') return node;
          if ((t === 'INPUT' || t === 'TEXTAREA') && type !== 'file' && type !== 'radio' && type !== 'checkbox' && type !== 'hidden') return node;
        }
      }
    }
    return null;
  }

  // Separate-cell lookup: label is in its own TD.
  // FIX: only skip cells that have VISIBLE inputs — not hidden inputs (CSRF tokens etc.)
  function findBySiblingCell(needle) {
    needle = needle.toLowerCase().trim();
    for (const td of document.querySelectorAll('td,th')) {
      // Allow cells that only have hidden inputs (e.g. CSRF tokens) — they're still label cells
      if (td.querySelector('input:not([type="hidden"]),select,textarea')) continue;
      if (!td.textContent.toLowerCase().includes(needle)) continue;
      const next = td.nextElementSibling;
      if (!next) continue;
      const el = next.querySelector('select, input:not([type="file"]):not([type="radio"]):not([type="checkbox"]):not([type="hidden"]), textarea');
      if (el) return el;
    }
    return null;
  }

  // Fallback: find an Image Type select by scanning for options we recognise.
  function findImageTypeSelectFallback() {
    const knownTypes = ['elevation','amenities','master plan','site plan','location plan','layout plan','construction status','creative image'];
    for (const sel of document.querySelectorAll('select')) {
      const opts = Array.from(sel.options).map(o => o.text.toLowerCase());
      if (knownTypes.some(t => opts.some(o => o.includes(t)))) return sel;
    }
    return null;
  }

  function findField(label) {
    return findBySiblingCell(label) || findInputAfterText(label);
  }

  function findRadiosByLabel(needle) {
    needle = needle.toLowerCase().trim();
    for (const el of document.querySelectorAll('td,th,div,p,tr')) {
      if (!el.textContent.toLowerCase().includes(needle)) continue;
      let radios = Array.from(el.querySelectorAll('input[type="radio"]'));
      if (radios.length) return radios;
      const sib = el.nextElementSibling;
      if (sib) { radios = Array.from(sib.querySelectorAll('input[type="radio"]')); if (radios.length) return radios; }
    }
    return Array.from(document.querySelectorAll('input[type="radio"][name*="reality"],input[type="radio"][name*="image_reality"]'));
  }

  // ── DATE HELPERS ──────────────────────────────────────────────────────────────
  const _MONTH_MAP = {
    jan:'01', feb:'02', mar:'03', apr:'04', may:'05', jun:'06',
    jul:'07', aug:'08', sep:'09', oct:'10', nov:'11', dec:'12',
  };
  function _monthNum(s) { return _MONTH_MAP[s.slice(0,3).toLowerCase()] || '01'; }

  /**
   * Parse a freeform date string from 99Acres into YYYY-MM-DD.
   * Handles: "November 2023", "Nov 2023", "15 Nov, 2023", "15 November 2023",
   *          "2023-11", "11/2023", "2023-11-15", etc.
   * Returns '' if unparseable.
   */
  function parseStatusDate(dateStr) {
    if (!dateStr) return '';
    const s = dateStr.trim();
    // Already ISO: 2023-11-15
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    // "15 Nov, 2023" or "15 November 2023"
    let m = /(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})/.exec(s);
    if (m) return `${m[3]}-${_monthNum(m[2])}-${m[1].padStart(2,'0')}`;
    // "November 2023" or "Nov, 2023"
    m = /([A-Za-z]+),?\s+(\d{4})/.exec(s);
    if (m) return `${m[2]}-${_monthNum(m[1])}-01`;
    // "11/2023" or "11-2023"
    m = /^(\d{1,2})[\/\-](\d{4})$/.exec(s);
    if (m) return `${m[2]}-${m[1].padStart(2,'0')}-01`;
    // "2023-11"
    m = /^(\d{4})-(\d{2})$/.exec(s);
    if (m) return `${m[1]}-${m[2]}-01`;
    return '';
  }

  // ── FORM HELPERS ──────────────────────────────────────────────────────────────
  function setSelect(el, value) {
    if (!el || !value || el.tagName !== 'SELECT') return false;
    const val = value.toLowerCase().trim();
    // Use selectedIndex (not el.value) — works even when option.value is "" or a numeric ID
    for (let i = 0; i < el.options.length; i++) {
      const opt = el.options[i];
      if (opt.text.toLowerCase().trim().includes(val) || (opt.value && opt.value.toLowerCase().trim().includes(val))) {
        el.selectedIndex = i;
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        // Verify it actually stuck
        return el.selectedIndex === i;
      }
    }
    return false;
  }

  function setRadio(radios, value) {
    const val = value.toLowerCase().trim();
    for (const r of radios) {
      const lbl = (r.labels?.[0]?.textContent || r.closest('label')?.textContent || r.parentElement?.textContent || r.value || '').toLowerCase();
      if (lbl.includes(val) || r.value.toLowerCase().includes(val)) {
        r.checked = true;
        r.dispatchEvent(new Event('change', {bubbles: true}));
        r.dispatchEvent(new Event('click',  {bubbles: true}));
        return true;
      }
    }
    return false;
  }

  function setInput(el, value) {
    if (!el) return false;
    try {
      const proto  = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value')?.set;
      if (setter) setter.call(el, value); else el.value = value;
    } catch (_) { el.value = value; }
    el.dispatchEvent(new Event('input',  {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }

  // Inject a File into a file input using DataTransfer (Chrome: direct .files assignment works).
  function injectFile(fileInputEl, arrayBuffer, filename) {
    const mime = /\.png$/i.test(filename) ? 'image/png'
               : /\.webp$/i.test(filename) ? 'image/webp'
               : 'image/jpeg';
    try {
      const file = new File([arrayBuffer], filename, {type: mime, lastModified: Date.now()});
      const dt   = new DataTransfer();
      dt.items.add(file);
      // Direct assignment (Chrome allows this and it updates browser UI)
      fileInputEl.files = dt.files;
      fileInputEl.dispatchEvent(new Event('change', {bubbles: true}));
      fileInputEl.dispatchEvent(new Event('input',  {bubbles: true}));
      return true;
    } catch (e) {
      // Fallback: Object.defineProperty
      try {
        const file = new File([arrayBuffer], filename, {type: mime});
        const dt   = new DataTransfer();
        dt.items.add(file);
        Object.defineProperty(fileInputEl, 'files', {get: () => dt.files, configurable: true});
        fileInputEl.dispatchEvent(new Event('change', {bubbles: true}));
        return true;
      } catch (_) { return false; }
    }
  }

  // Check if the CMS form looks blank/default (= save was successful last time)

  // ── API ───────────────────────────────────────────────────────────────────────
  function apiGet(path) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({ method: 'GET', url: API + path,
        onload:  r => { try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); } },
        onerror: () => reject(new Error('Network error — is the PDF tool server running?')) });
    });
  }

  function apiPost(path, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({ method: 'POST', url: API + path,
        headers: {'Content-Type': 'application/json'},
        data: body ? JSON.stringify(body) : '{}',
        onload:  r => { try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); } },
        onerror: () => reject(new Error('Network error')) });
    });
  }

  function fetchImageBuffer(sessionId, imageId) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({ method: 'GET', url: `${API}/image/${sessionId}/${imageId}`,
        responseType: 'arraybuffer',
        onload:  r => r.response ? resolve(r.response) : reject(new Error('Empty response')),
        onerror: () => reject(new Error('Network error fetching image')) });
    });
  }

  // ── QUEUE FLOW ────────────────────────────────────────────────────────────────
  async function fetchNext(autoFill) {
    setStatus('Loading next image…');
    try {
      const data = await apiGet('/cms-queue/next');
      if (data.done) {
        setStatus('✓ All done! Queue is empty.');
        sessionStorage.removeItem(SS_MODE);
        currentItem = null;
        if (panelEl) {
          ['_cms_qfile','_cms_qcat','_cms_qsrc','_cms_qreal','_cms_qtitle']
            .forEach(id => document.getElementById(id).textContent = '—');
          document.getElementById('_cms_progress').textContent = 'Queue complete ✓';
          document.getElementById('_cms_btn_fill').disabled = true;
          document.getElementById('_cms_btn_done').disabled = true;
          document.getElementById('_cms_btn_skip').disabled = true;
        }
        return;
      }
      currentItem    = data.item;
      queueRemaining = data.remaining; // track so fillForm knows Add More vs Save
      updatePanelInfo(data.item, data.index, data.total);
      if (autoFill) {
        await new Promise(r => setTimeout(r, 300)); // let DOM settle
        await fillForm(data.item);
      }
    } catch (e) {
      setStatus('⚠ ' + e.message);
    }
  }

  async function markDone() {
    setStatus('Marking done…');
    await apiPost('/cms-queue/done');
    await fetchNext(autoMode);
  }

  // ── WEBP → JPEG CONVERSION ────────────────────────────────────────────────────
  // CMS only accepts gif/png/jpg/jpeg — convert webp (and any other format) to JPEG.
  function convertToJpeg(arrayBuffer, filename) {
    return new Promise((resolve, reject) => {
      const blob = new Blob([arrayBuffer]); // let browser sniff mime
      const url  = URL.createObjectURL(blob);
      const img  = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const canvas = document.createElement('canvas');
        canvas.width  = img.naturalWidth;
        canvas.height = img.naturalHeight;
        canvas.getContext('2d').drawImage(img, 0, 0);
        canvas.toBlob(jpegBlob => {
          if (!jpegBlob) { reject(new Error('canvas.toBlob returned null')); return; }
          jpegBlob.arrayBuffer().then(buf => {
            resolve({ buffer: buf, filename: filename.replace(/\.[^.]+$/, '.jpg') });
          }).catch(reject);
        }, 'image/jpeg', 0.92);
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Image decode failed')); };
      img.src = url;
    });
  }

  // ── SECONDARY DROPDOWN ────────────────────────────────────────────────────────
  // After setting Image Type to Amenities/Main Other, the CMS may show a secondary
  // dropdown for the sub-type. Find it by excluding all known non-secondary selects.
  function findSecondaryDropdown(imageTypeEl) {
    const knownSelects = new Set([imageTypeEl]);
    // Add source select and display-order select to exclusion set
    const src = findField('source'); if (src) knownSelects.add(src);
    const disp = findInputAfterText('display order', 'td'); if (disp) knownSelects.add(disp);
    const nofiles = findInputAfterText('how many', 'td'); if (nofiles) knownSelects.add(nofiles);

    for (const sel of document.querySelectorAll('select')) {
      if (knownSelects.has(sel)) continue;
      if (!sel.offsetParent) continue;                        // hidden / display:none
      if (getComputedStyle(sel).display === 'none') continue;
      const opts = Array.from(sel.options);
      if (opts.length <= 1) continue;                         // empty / placeholder only
      // Skip pure-numeric selects (display order, file count)
      if (opts.every(o => o.value === '' || !isNaN(Number(o.value)) && Number(o.value) < 50)) continue;
      return sel;
    }
    return null;
  }

  // ── FORM FILLING ──────────────────────────────────────────────────────────────
  async function fillForm(item) {
    setStatus('Filling form…');
    const debug = [];

    // ── Step 1: Image Type first — CMS JS may show secondary dropdown and auto-fill Title
    const typeEl  = findField('image type') || findImageTypeSelectFallback();
    const cmsType = IMAGE_TYPE_MAP[item.category] || item.category;
    let typeOk = false;
    if (typeEl) {
      typeOk = setSelect(typeEl, cmsType);
      debug.push([typeOk, typeOk ? `Image Type → "${cmsType}"` : `"${cmsType}" not in dropdown — options: [${Array.from(typeEl.options).map(o=>o.text).join(', ')}]`]);

      // ── Step 2: Wait for CMS JS to react (secondary dropdown, title auto-fill)
      await new Promise(r => setTimeout(r, 500));

      // ── Step 3: Secondary dropdown (Amenities / Main Other sub-type) ──────────
      if (item.subtype) {
        const subEl = findSecondaryDropdown(typeEl);
        if (subEl) {
          const ok2 = setSelect(subEl, item.subtype);
          debug.push([ok2, ok2 ? `Sub-type → "${item.subtype}"` : `"${item.subtype}" not in secondary dropdown — options: [${Array.from(subEl.options).map(o=>o.text).join(', ')}]`]);
        } else {
          debug.push([false, `Secondary dropdown not visible yet for sub-type "${item.subtype}"`]);
        }
      }
    } else {
      debug.push([false, 'Image Type select not found on page']);
      await new Promise(r => setTimeout(r, 500));
    }

    // ── Step 4: Image URL (preview link from local server) ───────────────────────
    const imgUrlEl = findBySiblingCell('image url') || findInputAfterText('image url', 'td');
    if (imgUrlEl && item.session_id && item.id) {
      const previewUrl = `${API}/image/${item.session_id}/${item.id}`;
      const ok = setInput(imgUrlEl, previewUrl);
      debug.push([ok, ok ? `Image URL → "${previewUrl}"` : 'Image URL field not filled']);
    }

    // ── Step 5: Source ────────────────────────────────────────────────────────────
    const srcEl  = findField('source');
    const cmsSrc = SOURCE_MAP[item.source] || item.source;
    if (srcEl) {
      const ok = setSelect(srcEl, cmsSrc);
      debug.push([ok, ok ? `Source → "${cmsSrc}"` : `"${cmsSrc}" not in Source dropdown`]);
    } else {
      debug.push([false, 'Source field not found']);
    }

    // ── Step 6: Image Reality ─────────────────────────────────────────────────────
    const radios  = findRadiosByLabel('image reality');
    const reality = item.image_reality || 'Actual';
    if (radios.length) {
      const ok = setRadio(radios, reality);
      debug.push([ok, ok ? `Reality → "${reality}"` : `"${reality}" radio not matched`]);
    } else {
      debug.push([false, 'Image Reality radios not found']);
    }

    // ── Step 7: Title — set AFTER delay so it overrides any CMS auto-fill ────────
    const titleEl  = findInputAfterText('title', 'td') || findField('title');
    const titleVal = item.title || '';
    if (titleEl && titleEl.type !== 'file') {
      setInput(titleEl, titleVal);
      // Re-apply after another tick in case CMS JS overwrites it asynchronously
      setTimeout(() => { if (titleEl.value !== titleVal) setInput(titleEl, titleVal); }, 400);
      debug.push([true, `Title → "${titleVal}"`]);
    } else {
      debug.push([false, 'Title field not found']);
    }

    // ── Step 7.5: Tagged Date (Construction Status only) ─────────────────────────
    if (item.status_date) {
      const dateEl = findBySiblingCell('tagged date') || findInputAfterText('tagged date', 'td');
      if (dateEl) {
        const iso = parseStatusDate(item.status_date);
        const ok  = setInput(dateEl, iso || item.status_date);
        debug.push([ok, ok ? `Tagged Date → "${iso || item.status_date}"` : 'Tagged Date field not filled']);
      } else {
        debug.push([false, 'Tagged Date field not found']);
      }
    }

    // ── Step 8: Fetch image, convert webp→jpeg if needed, inject into file input ─
    const fileInputEl = document.querySelector('input[type="file"]');
    if (fileInputEl && item.session_id && item.id) {
      setStatus('Downloading image…');
      try {
        let buf      = await fetchImageBuffer(item.session_id, item.id);
        let filename = item.filename || (item.id + '.jpg');

        // Convert webp (and any unsupported format) to JPEG — CMS only accepts gif/png/jpg
        if (/\.webp$/i.test(filename) || /\.avif$/i.test(filename)) {
          setStatus('Converting to JPEG…');
          try {
            const conv = await convertToJpeg(buf, filename);
            buf      = conv.buffer;
            filename = conv.filename;
            debug.push([true, `Converted → ${filename}`]);
          } catch (e) {
            debug.push([false, `WebP→JPEG failed: ${e.message} — CMS may reject file`]);
          }
        }

        const ok = injectFile(fileInputEl, buf, filename);
        debug.push([ok, ok ? `File ready: ${filename}` : 'File inject failed — upload manually']);
        setStatus(ok ? 'Form filled — review & click Save' : '⚠ File inject failed — upload manually then click Save');
      } catch (e) {
        debug.push([false, `Image download failed: ${e.message}`]);
        setStatus('⚠ Image download failed — upload file manually');
      }
    } else {
      debug.push([false, 'No file input found on page']);
      setStatus('Form filled (no file input found)');
    }

    setDebug(debug);

    // ── Step 9: Auto-click Add More / Save ────────────────────────────────────────
    if (autoMode) {
      const fileOk  = debug.some(([ok, msg]) => ok && msg.includes('File'));
      const typeOk  = debug.some(([ok, msg]) => ok && msg.includes('Image Type'));
      const allGood = fileOk && typeOk;

      if (allGood) {
        const isLast  = queueRemaining <= 1;
        const btn     = isLast ? findSaveBtn() : findAddMoreBtn();
        const btnName = isLast ? 'Save' : 'Add More';

        if (btn) {
          let secs = 3;
          setStatus(`Clicking "${btnName}" in ${secs}s — click Stop to cancel`);
          autoClickTimer = setInterval(() => {
            secs--;
            if (secs > 0) {
              setStatus(`Clicking "${btnName}" in ${secs}s — click Stop to cancel`);
            } else {
              clearInterval(autoClickTimer);
              autoClickTimer = null;
              setStatus(`Clicking "${btnName}"…`);
              btn.click();
            }
          }, 1000);
        } else {
          setStatus(`Form filled — click "${isLast ? 'Save' : 'Add More'}" in CMS`);
        }
      } else {
        setStatus('⚠ Image Type or File failed — fix manually, then click Add More / Save');
      }
    }

    attachFormListeners();
  }

  // ── BUTTON FINDERS ────────────────────────────────────────────────────────────
  function findAddMoreBtn() {
    return Array.from(document.querySelectorAll('input, button')).find(b => {
      const txt = (b.value || b.textContent || '').toLowerCase().trim();
      return txt.includes('add more');
    }) || null;
  }

  function findSaveBtn() {
    return Array.from(document.querySelectorAll('input[type="submit"], button[type="submit"], input[type="button"], button')).find(b => {
      const txt = (b.value || b.textContent || '').toLowerCase().trim();
      return (txt === 'save' || txt.startsWith('save')) && !txt.includes('add');
    }) || null;
  }

  // ── FORM LISTENERS ────────────────────────────────────────────────────────────
  // Attach once per page-load. Handles both traditional page-reload forms (form submit event)
  // and AJAX forms (detect form reset after Add More click).
  function attachFormListeners() {
    const form = document.querySelector('form');
    if (!form || form._cmsWatched) return;
    form._cmsWatched = true;

    // Traditional submit (page reload) — keep sessionStorage flag alive
    form.addEventListener('submit', () => {
      sessionStorage.setItem(SS_SAVED, '1');
      sessionStorage.setItem(SS_MODE,  '1');
    });

    // AJAX "Add More": detect form reset without page navigation
    const addMoreBtn = findAddMoreBtn();
    if (addMoreBtn) {
      addMoreBtn.addEventListener('click', () => {
        if (!autoMode) return;
        // Watch for the Image Type select to be reset (= form cleared by AJAX)
        const typeEl = findField('image type') || findImageTypeSelectFallback();
        if (!typeEl) return;
        const originalIndex = typeEl.selectedIndex;
        const poll = setInterval(async () => {
          if (typeEl.selectedIndex !== originalIndex || typeEl.selectedIndex <= 0) {
            clearInterval(poll);
            if (!sessionStorage.getItem(SS_SAVED)) {
              // AJAX reset confirmed — mark done and fill next (no page reload)
              setStatus('Form submitted via AJAX — loading next…');
              await apiPost('/cms-queue/done');
              await fetchNext(true);
            }
            // If SS_SAVED is set the page is navigating — init() will handle it
          }
        }, 300);
        // Stop polling after 5s (page reload will take over)
        setTimeout(() => clearInterval(poll), 5000);
      });
    }
  }

  // ── PANEL ─────────────────────────────────────────────────────────────────────
  function setStatus(msg) {
    const el = document.getElementById('_cms_status_msg');
    if (el) el.textContent = msg;
  }

  function setDebug(lines) {
    const el = document.getElementById('_cms_debug');
    if (!el) return;
    el.innerHTML = lines.map(([ok, txt]) =>
      `<span class="${ok ? 'ok' : 'bad'}">${ok ? '✓' : '✗'} ${txt}</span><br>`
    ).join('');
  }

  function updatePanelInfo(item, index, total) {
    if (!panelEl) return;
    const catLabel = item.subtype ? `${item.category} › ${item.subtype}` : (item.category || '—');
    document.getElementById('_cms_qfile').textContent  = item.filename || '—';
    document.getElementById('_cms_qcat').textContent   = catLabel;
    document.getElementById('_cms_qsrc').textContent   = SOURCE_MAP[item.source] || item.source || '—';
    document.getElementById('_cms_qreal').textContent  = item.image_reality || 'Actual';
    document.getElementById('_cms_qtitle').textContent = item.title || '—';
    document.getElementById('_cms_progress').textContent = `Item ${index + 1} of ${total}`;
    document.getElementById('_cms_debug').innerHTML = '';
    setStatus('Auto-filling form…');
  }

  function createPanel() {
    panelEl = document.createElement('div');
    panelEl.id = '_cms_queue_panel';
    panelEl.innerHTML = `
      <header>
        <strong>⬆ CMS Queue <span class="hbadge" id="_cms_modebadge">AUTO</span></strong>
        <button id="_cms_toggle" title="Minimise">−</button>
        <button id="_cms_close"  title="Close">×</button>
      </header>
      <div id="_cms_panel_body">
        <div id="_cms_status_msg">Loading…</div>
        <div class="q-row"><div class="q-label">Image</div>    <div class="q-val" id="_cms_qfile">—</div></div>
        <div class="q-row"><div class="q-label">Category</div> <div class="q-val" id="_cms_qcat">—</div></div>
        <div class="q-row"><div class="q-label">Source</div>   <div class="q-val" id="_cms_qsrc">—</div></div>
        <div class="q-row"><div class="q-label">Reality</div>  <div class="q-val" id="_cms_qreal">—</div></div>
        <div class="q-row"><div class="q-label">Title</div>    <div class="q-val" id="_cms_qtitle">—</div></div>
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
      document.getElementById('_cms_panel_body').style.display   = minimised ? 'none' : '';
      document.getElementById('_cms_panel_footer').style.display = minimised ? 'none' : '';
      document.getElementById('_cms_toggle').textContent = minimised ? '+' : '−';
    });
    document.getElementById('_cms_close').addEventListener('click', () => {
      autoMode = false;
      sessionStorage.removeItem(SS_MODE);
      sessionStorage.removeItem(SS_SAVED);
      panelEl.remove(); panelEl = null;
      createLaunchButton();
    });
    document.getElementById('_cms_btn_fill').addEventListener('click', () => {
      if (autoClickTimer) { clearInterval(autoClickTimer); autoClickTimer = null; }
      if (currentItem) fillForm(currentItem);
    });
    document.getElementById('_cms_btn_done').addEventListener('click', () => markDone());
    document.getElementById('_cms_btn_skip').addEventListener('click', () => {
      apiPost('/cms-queue/skip').then(() => fetchNext(autoMode));
    });
    document.getElementById('_cms_btn_stop').addEventListener('click', () => {
      autoMode = false;
      sessionStorage.removeItem(SS_MODE);
      // Cancel any pending auto-click countdown
      if (autoClickTimer) { clearInterval(autoClickTimer); autoClickTimer = null; }
      setStatus('Auto-fill stopped — fill manually, then click Add More / Save yourself.');
      document.getElementById('_cms_modebadge').textContent = 'MANUAL';
    });
  }

  // ── LAUNCH BUTTON ─────────────────────────────────────────────────────────────
  function createLaunchButton() {
    launchBtn = document.createElement('button');
    launchBtn.id = '_cms_launch_btn';
    launchBtn.innerHTML = `⬆ Start CMS Queue <span class="lbadge" id="_cms_lcount">…</span>`;
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
      launchBtn.remove(); launchBtn = null;
      autoMode = true;
      sessionStorage.setItem(SS_MODE, '1');
      createPanel();
      fetchNext(true);
    });
  }

  // ── ERROR DETECTION ───────────────────────────────────────────────────────────
  // Returns true ONLY when the CMS shows the exact file-type rejection banner.
  // Deliberately narrow: broad checks ("please select", [class*="error"]) match
  // normal placeholder / label text on the form and cause an infinite loop.
  function pageHasCmsError() {
    const bodyText = document.body.innerText;
    // These are the only CMS error strings that are unambiguous on a fresh page-load
    const exactErrors = [
      'You can upload only',
      'Image type is required',
      'Invalid file type',
      'File type not allowed',
      'Could not save',
    ];
    return exactErrors.some(e => bodyText.includes(e));
  }

  // ── INIT ──────────────────────────────────────────────────────────────────────
  async function init() {
    const inAutoMode = !!sessionStorage.getItem(SS_MODE);
    const justSaved  = !!sessionStorage.getItem(SS_SAVED);
    sessionStorage.removeItem(SS_SAVED); // consume the flag

    if (!inAutoMode) {
      createLaunchButton();
      return;
    }

    autoMode = true;
    createPanel();

    if (justSaved) {
      // Wait for DOM to fully render (error banners appear after JS runs)
      await new Promise(r => setTimeout(r, 700));

      if (pageHasCmsError()) {
        // CMS showed a validation / file-type error — do NOT advance queue
        // Re-fill the SAME item so user can try again (or fix manually)
        setStatus('⚠ CMS save error detected — re-filling form. Fix & click Save again.');
        await fetchNext(true); // /next still returns same item (not marked done)
        return;
      } else {
        // No error banner → save was successful → advance queue
        setStatus('✓ Saved! Marking done…');
        await apiPost('/cms-queue/done');
      }
    }

    // Load and auto-fill next (or first) item
    await fetchNext(true);
  }

  init();

})();
