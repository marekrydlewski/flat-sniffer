// Świętego Michała · Interactive Dashboard App
(function() {
  'use strict';

  // --- State ---
  let allOffers = [];
  let selectedCategory = 'Mieszkanie';
  let histogramMode = 'total'; // 'total' | 'sqm'
  let includeSoldInHist = false;
  let selectedHistogramBin = null; // { min, max, label, isLast, isExact } or null

  // Table filters & sorting
  let catalogSearch = '';
  let catalogStatusFilter = 'all'; // 'all' | 'available' | 'reserved' | 'sold'
  let catalogRoomsFilter = 'all';  // 'all' | '2' | '3' | '4'
  let catalogStaircaseFilter = 'all'; // 'all' | '34' | '36' | '38' | '40'
  let catalogSpecialFilter = 'all'; // 'all' | 'drops'
  let catalogMaxPrice = null;
  let catalogMinArea = null;
  let catalogMaxArea = null;
  let catalogShowSold = false;
  let catalogSortCol = 'price';
  let catalogSortDir = 'asc';

  let isUpdatingFromHash = false;

  // Timeline scope
  let timelineScope = 'flats'; // 'flats' | 'all'

  // --- Helpers ---
  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function removeDiacritics(str) {
    return str
      ? String(str)
          .replace(/[łŁ]/g, 'l')
          .normalize('NFD')
          .replace(/[\u0300-\u036f]/g, '')
          .toLowerCase()
      : '';
  }

  function parseFloorNum(val) {
    if (!val) return -999;
    const s = String(val).toLowerCase();
    if (s.includes('parter')) return 0;
    const m = s.match(/-?\d+/);
    return m ? parseInt(m[0], 10) : -999;
  }

  function formatPrice(num) {
    if (num == null || isNaN(num)) return '—';
    return Math.round(num).toLocaleString('pl-PL') + ' zł';
  }

  // --- URL State / Deep Linking ---
  function updateUrlHash() {
    if (isUpdatingFromHash) return;
    const params = new URLSearchParams();
    if (selectedCategory && selectedCategory !== 'Mieszkanie') {
      params.set('cat', selectedCategory);
    }
    if (catalogStatusFilter && catalogStatusFilter !== 'all') {
      params.set('status', catalogStatusFilter);
    }
    if (catalogRoomsFilter && catalogRoomsFilter !== 'all') {
      params.set('rooms', catalogRoomsFilter);
    }
    if (catalogStaircaseFilter && catalogStaircaseFilter !== 'all') {
      params.set('staircase', catalogStaircaseFilter);
    }
    if (catalogSpecialFilter === 'drops') {
      params.set('drops', '1');
    }
    if (catalogShowSold) {
      params.set('sold', '1');
    }
    if (catalogSearch) {
      params.set('q', catalogSearch);
    }
    if (catalogMaxPrice) {
      params.set('max_p', String(catalogMaxPrice));
    }
    if (catalogMinArea) {
      params.set('min_a', String(catalogMinArea));
    }
    if (catalogMaxArea) {
      params.set('max_a', String(catalogMaxArea));
    }
    if (catalogSortCol !== 'price' || catalogSortDir !== 'asc') {
      params.set('sort', `${catalogSortCol}_${catalogSortDir}`);
    }

    const hashStr = params.toString();
    const newHash = hashStr ? '#' + hashStr : '';
    if (window.location.hash !== newHash) {
      const newUrl = newHash ? newHash : window.location.pathname + window.location.search;
      history.replaceState(null, '', newUrl);
    }
  }

  function loadStateFromUrlHash() {
    isUpdatingFromHash = true;

    // Reset to defaults first
    selectedCategory = 'Mieszkanie';
    catalogStatusFilter = 'all';
    catalogRoomsFilter = 'all';
    catalogStaircaseFilter = 'all';
    catalogSpecialFilter = 'all';
    catalogShowSold = false;
    catalogSearch = '';
    catalogMaxPrice = null;
    catalogMinArea = null;
    catalogMaxArea = null;
    catalogSortCol = 'price';
    catalogSortDir = 'asc';

    const searchInput = document.getElementById('table-search');
    if (searchInput) searchInput.value = '';
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');
    const maxPEl = document.getElementById('filter-max-price');
    if (maxPEl) maxPEl.value = '';
    const minAEl = document.getElementById('filter-min-area');
    if (minAEl) minAEl.value = '';
    const maxAEl = document.getElementById('filter-max-area');
    if (maxAEl) maxAEl.value = '';

    const rawHash = window.location.hash.replace(/^#/, '');
    if (rawHash) {
      const params = new URLSearchParams(rawHash);

      if (params.has('cat')) {
        selectedCategory = params.get('cat');
      }
      if (params.has('status')) {
        catalogStatusFilter = params.get('status');
      }
      if (params.has('rooms')) {
        catalogRoomsFilter = params.get('rooms');
      }
      if (params.has('staircase')) {
        catalogStaircaseFilter = params.get('staircase');
      }
      if (params.get('drops') === '1') {
        catalogSpecialFilter = 'drops';
      }
      if (params.get('sold') === '1') {
        catalogShowSold = true;
      }
      if (params.has('q')) {
        catalogSearch = params.get('q');
        if (searchInput) searchInput.value = catalogSearch;
        if (clearBtn) clearBtn.classList.remove('hidden');
      }
      if (params.has('max_p')) {
        catalogMaxPrice = parseInt(params.get('max_p'), 10) || null;
        if (maxPEl && catalogMaxPrice) maxPEl.value = catalogMaxPrice;
      }
      if (params.has('min_a')) {
        catalogMinArea = parseFloat(params.get('min_a')) || null;
        if (minAEl && catalogMinArea) minAEl.value = catalogMinArea;
      }
      if (params.has('max_a')) {
        catalogMaxArea = parseFloat(params.get('max_a')) || null;
        if (maxAEl && catalogMaxArea) maxAEl.value = catalogMaxArea;
      }
      if (params.has('sort')) {
        const sortVal = params.get('sort');
        const lastUnderscore = sortVal.lastIndexOf('_');
        if (lastUnderscore !== -1) {
          catalogSortCol = sortVal.slice(0, lastUnderscore);
          catalogSortDir = sortVal.slice(lastUnderscore + 1);
        }
      }
    }

    isUpdatingFromHash = false;
  }

  // --- Initialization ---
  function init() {
    const rawDataEl = document.getElementById('offers-data');
    if (rawDataEl) {
      try {
        allOffers = JSON.parse(rawDataEl.textContent || '[]');
      } catch (err) {
        console.error('Failed to parse offers data:', err);
      }
    }

    initTheme();
    loadStateFromUrlHash();
    initKeyboardAccessibility();
    renderAll();

    window.addEventListener('hashchange', () => {
      loadStateFromUrlHash();
      renderAll();
    });
  }

  function initKeyboardAccessibility() {
    document.querySelectorAll('.clickable[tabindex="0"]').forEach(el => {
      el.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          el.click();
        }
      });
    });
  }

  function renderAll() {
    updateCategoryTabs();
    renderHistogram();
    renderQuickFilters();
    renderTable();
    updateTimelineScope();
  }

  // --- Theme Toggle ---
  function initTheme() {
    const savedTheme = localStorage.getItem('sm_theme');
    if (savedTheme) {
      document.documentElement.setAttribute('data-theme', savedTheme);
    }
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
      themeBtn.addEventListener('click', toggleTheme);
    }
  }

  function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    let nextTheme = 'light';
    if (!currentTheme) {
      const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      nextTheme = prefersDark ? 'light' : 'dark';
    } else {
      nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    }
    document.documentElement.setAttribute('data-theme', nextTheme);
    localStorage.setItem('sm_theme', nextTheme);
  }

  // --- Category Switcher ---
  window.selectCategory = function(cat) {
    if (selectedCategory === cat) return;
    selectedCategory = cat;
    selectedHistogramBin = null;
    catalogSearch = '';
    const searchInput = document.getElementById('table-search');
    if (searchInput) searchInput.value = '';
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');

    catalogStatusFilter = 'all';
    catalogRoomsFilter = 'all';
    catalogStaircaseFilter = 'all';
    catalogSpecialFilter = 'all';
    catalogMaxPrice = null;
    catalogMinArea = null;
    catalogMaxArea = null;

    const maxPEl = document.getElementById('filter-max-price');
    if (maxPEl) maxPEl.value = '';
    const minAEl = document.getElementById('filter-min-area');
    if (minAEl) minAEl.value = '';
    const maxAEl = document.getElementById('filter-max-area');
    if (maxAEl) maxAEl.value = '';

    catalogShowSold = false;
    catalogSortCol = 'price';
    catalogSortDir = 'asc';

    renderAll();
    updateUrlHash();
  };

  function updateCategoryTabs() {
    document.querySelectorAll('.cat-tab-btn').forEach(btn => {
      const isMatch = btn.getAttribute('data-category') === selectedCategory;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-selected', isMatch ? 'true' : 'false');
    });

    const titleEl = document.getElementById('catalog-title');
    if (titleEl) {
      const catNames = {
        'Mieszkanie': 'Mieszkania',
        'Hala garażowa': 'Hala garażowa (miejsca postojowe)',
        'Komórka': 'Komórki lokatorskie',
        'Miejsce postojowe': 'Miejsca postojowe naziemne'
      };
      titleEl.textContent = '🏢 Tabela lokali: ' + (catNames[selectedCategory] || selectedCategory);
    }

    const modeWrap = document.getElementById('hist-mode-wrap');
    if (modeWrap) {
      modeWrap.style.display = selectedCategory === 'Mieszkanie' ? 'flex' : 'none';
    }

    const areaField = document.getElementById('filter-min-area')?.closest('.range-field');
    if (areaField) {
      areaField.style.display = (selectedCategory === 'Mieszkanie' || selectedCategory === 'Komórka') ? 'inline-flex' : 'none';
    }
  }

  // --- Histogram Controls ---
  window.setHistogramMode = function(mode) {
    if (histogramMode === mode) return;
    histogramMode = mode;
    selectedHistogramBin = null;
    document.getElementById('btn-mode-total')?.classList.toggle('active', mode === 'total');
    document.getElementById('btn-mode-sqm')?.classList.toggle('active', mode === 'sqm');
    renderHistogram();
    renderTable();
  };

  window.toggleIncludeSold = function() {
    const chk = document.getElementById('chk-include-sold');
    includeSoldInHist = chk ? chk.checked : false;
    renderHistogram();
    renderTable();
  };

  window.clearHistogramSelection = function() {
    selectedHistogramBin = null;
    renderHistogram();
    renderTable();
  };

  window.scrollToTable = function() {
    const catalogEl = document.getElementById('catalog-section');
    if (catalogEl) {
      catalogEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  // --- Histogram Generation ---
  function renderHistogram() {
    const container = document.getElementById('histogram-container');
    if (!container) return;

    let items = allOffers.filter(o => o.cat === selectedCategory);
    if (!includeSoldInHist) {
      items = items.filter(o => o.kind !== 'sold');
    }

    if (items.length === 0) {
      container.innerHTML = '<div class="empty-state">Brak danych cenowych dla wybranej konfiguracji.</div>';
      updateDrilldownBar();
      return;
    }

    let bins = [];

    if (selectedCategory === 'Mieszkanie') {
      if (histogramMode === 'total') {
        const step = 50000;
        const prices = items.map(o => o.price_num).filter(p => p && p > 0);
        if (prices.length > 0) {
          const minP = Math.floor(Math.min(...prices) / step) * step;
          const maxP = Math.ceil(Math.max(...prices) / step) * step;
          for (let b = minP; b < maxP; b += step) {
            const bMin = b;
            const bMax = b + step;
            const isLast = bMax >= maxP;
            const bItems = items.filter(o => {
              if (o.price_num == null) return false;
              return o.price_num >= bMin && (isLast ? o.price_num <= bMax : o.price_num < bMax);
            });
            if (bItems.length > 0) {
              const label = `${Math.round(bMin / 1000)}k–${Math.round(bMax / 1000)}k zł`;
              bins.push({ min: bMin, max: bMax, isLast: isLast, label: label, items: bItems });
            }
          }
        }
      } else {
        // SQM mode for flats
        const step = 250;
        const sqms = items.map(o => (o.price_num && o.area_num) ? Math.round(o.price_num / o.area_num) : null).filter(Boolean);
        if (sqms.length > 0) {
          const minS = Math.floor(Math.min(...sqms) / step) * step;
          const maxS = Math.ceil(Math.max(...sqms) / step) * step;
          for (let b = minS; b < maxS; b += step) {
            const bMin = b;
            const bMax = b + step;
            const isLast = bMax >= maxS;
            const bItems = items.filter(o => {
              const sqm = (o.price_num && o.area_num) ? (o.price_num / o.area_num) : null;
              return sqm != null && sqm >= bMin && (isLast ? sqm <= bMax : sqm < bMax);
            });
            if (bItems.length > 0) {
              const label = `${bMin.toLocaleString()}–${bMax.toLocaleString()} zł/m²`;
              bins.push({ min: bMin, max: bMax, isLast: isLast, label: label, items: bItems });
            }
          }
        }
      }
    } else {
      // Discrete prices for garage / storage / parking
      const priceMap = new Map();
      items.forEach(o => {
        const p = o.price_num || 0;
        if (!priceMap.has(p)) priceMap.set(p, []);
        priceMap.get(p).push(o);
      });

      const sortedPrices = Array.from(priceMap.keys()).sort((a, b) => a - b);
      sortedPrices.forEach(p => {
        const bItems = priceMap.get(p);
        bins.push({
          min: p,
          max: p,
          isExact: true,
          label: formatPrice(p),
          items: bItems
        });
      });
    }

    if (bins.length === 0) {
      container.innerHTML = '<div class="empty-state">Brak danych cenowych.</div>';
      updateDrilldownBar();
      return;
    }

    const maxCount = Math.max(...bins.map(b => b.items.length), 1);

    let chartHtml = '<div class="histogram-chart" role="region" aria-label="Histogram rozkładu cen">';
    let labelsHtml = '<div class="hist-labels-row">';

    bins.forEach((bin, idx) => {
      const count = bin.items.length;
      const heightPct = Math.max(Math.round((count / maxCount) * 100), 8);

      const countAvail = bin.items.filter(o => o.kind === 'available').length;
      const countRes = bin.items.filter(o => o.kind === 'reserved').length;
      const countSold = bin.items.filter(o => o.kind === 'sold').length;

      const pctAvail = (countAvail / count) * 100;
      const pctRes = (countRes / count) * 100;
      const pctSold = (countSold / count) * 100;

      const isSelected = selectedHistogramBin && selectedHistogramBin.label === bin.label;
      const activeCls = isSelected ? ' active' : '';

      const tooltip = `${bin.label}: ${count} lokali (${countAvail} wolnych, ${countRes} rezerwacji, ${countSold} sprzedanych)`;

      chartHtml += `
        <div class="hist-col${activeCls}" data-bin-idx="${idx}" role="button" tabindex="0" aria-pressed="${isSelected ? 'true' : 'false'}" aria-label="${escapeHtml(tooltip)}" onclick="handleHistBarClick(${idx})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();handleHistBarClick(${idx});}" title="${escapeHtml(tooltip)}">
          <span class="hist-bar-count">${count}</span>
          <div class="hist-bar" style="height: ${heightPct}%;">
            ${countSold > 0 ? `<div class="hist-seg hist-seg-sold" style="height: ${pctSold}%;"></div>` : ''}
            ${countRes > 0 ? `<div class="hist-seg hist-seg-res" style="height: ${pctRes}%;"></div>` : ''}
            ${countAvail > 0 ? `<div class="hist-seg hist-seg-avail" style="height: ${pctAvail}%;"></div>` : ''}
          </div>
        </div>
      `;

      labelsHtml += `
        <div class="hist-label" title="${escapeHtml(bin.label)}">${escapeHtml(bin.label)}</div>
      `;
    });

    chartHtml += '</div>';
    labelsHtml += '</div>';

    const minWidthPx = bins.length * 56;
    container.innerHTML = `<div class="histogram-scroll-inner" style="min-width: max(100%, ${minWidthPx}px);">${chartHtml}${labelsHtml}</div>`;

    window._currentHistogramBins = bins;
    updateDrilldownBar();
  }

  window.handleHistBarClick = function(idx) {
    const bins = window._currentHistogramBins;
    if (!bins || !bins[idx]) return;

    const clickedBin = bins[idx];
    if (selectedHistogramBin && selectedHistogramBin.label === clickedBin.label) {
      selectedHistogramBin = null;
    } else {
      selectedHistogramBin = clickedBin;
    }

    renderHistogram();
    renderTable();
  };

  function updateDrilldownBar() {
    const bar = document.getElementById('drilldown-bar');
    if (!bar) return;

    if (!selectedHistogramBin) {
      bar.classList.add('hidden');
      return;
    }

    bar.classList.remove('hidden');
    const labelEl = document.getElementById('drilldown-label');
    const countEl = document.getElementById('drilldown-count');

    if (labelEl) labelEl.textContent = selectedHistogramBin.label;
    if (countEl) {
      const items = selectedHistogramBin.items;
      const countAvail = items.filter(o => o.kind === 'available').length;
      const countRes = items.filter(o => o.kind === 'reserved').length;
      countEl.textContent = `(${items.length} pozycji: ${countAvail} wolnych, ${countRes} rezerwacji)`;
    }
  }

  // --- Quick Filter Pills ---
  function renderQuickFilters() {
    const container = document.getElementById('quick-filters');
    if (!container) return;

    let html = '';

    const catOffers = allOffers.filter(o => o.cat === selectedCategory);
    const countAvail = catOffers.filter(o => o.kind === 'available').length;
    const countRes = catOffers.filter(o => o.kind === 'reserved').length;
    const countSold = catOffers.filter(o => o.kind === 'sold').length;
    const countDrops = catOffers.filter(o => o.has_drop).length;
    const isAllActive = catalogStatusFilter === 'all' && catalogSpecialFilter === 'all' && catalogRoomsFilter === 'all' && catalogStaircaseFilter === 'all';
    const totalCount = catalogShowSold ? (countAvail + countRes + countSold) : (countAvail + countRes);

    html += `<button class="q-pill${isAllActive ? ' active' : ''}" onclick="setCatalogFilter('all')">Wszystkie (${totalCount})</button>`;
    html += `<button class="q-pill${catalogStatusFilter === 'available' ? ' active' : ''}" onclick="setCatalogFilter('status', 'available')">Wolne (${countAvail})</button>`;
    if (countRes > 0) {
      html += `<button class="q-pill${catalogStatusFilter === 'reserved' ? ' active' : ''}" onclick="setCatalogFilter('status', 'reserved')">Rezerwacje (${countRes})</button>`;
    }
    if (countSold > 0 && catalogStatusFilter === 'sold') {
      html += `<button class="q-pill active" onclick="setCatalogFilter('status', 'sold')">Sprzedane (${countSold})</button>`;
    }

    if (selectedCategory === 'Mieszkanie') {
      const statusMatch = o => {
        if (catalogStatusFilter !== 'all') return o.kind === catalogStatusFilter;
        return catalogShowSold ? true : o.kind !== 'sold';
      };
      const rooms2 = catOffers.filter(o => o.rooms === '2' && statusMatch(o)).length;
      const rooms3 = catOffers.filter(o => o.rooms === '3' && statusMatch(o)).length;
      const rooms4 = catOffers.filter(o => o.rooms === '4' && statusMatch(o)).length;

      if (rooms2 > 0) html += `<button class="q-pill${catalogRoomsFilter === '2' ? ' active' : ''}" onclick="setCatalogFilter('rooms', '2')">2 pokoje (${rooms2})</button>`;
      if (rooms3 > 0) html += `<button class="q-pill${catalogRoomsFilter === '3' ? ' active' : ''}" onclick="setCatalogFilter('rooms', '3')">3 pokoje (${rooms3})</button>`;
      if (rooms4 > 0) html += `<button class="q-pill${catalogRoomsFilter === '4' ? ' active' : ''}" onclick="setCatalogFilter('rooms', '4')">4 pokoje (${rooms4})</button>`;

      const staircases = ['34', '36', '38', '40'];
      staircases.forEach(sc => {
        const scCount = catOffers.filter(o => o.staircase === sc && statusMatch(o)).length;
        if (scCount > 0) {
          html += `<button class="q-pill${catalogStaircaseFilter === sc ? ' active' : ''}" onclick="setCatalogFilter('staircase', '${sc}')">Klatka ${sc} (${scCount})</button>`;
        }
      });

      if (countDrops > 0) {
        html += `<button class="q-pill${catalogSpecialFilter === 'drops' ? ' active' : ''}" onclick="setCatalogFilter('special', 'drops')">🔥 Obniżki cen (${countDrops})</button>`;
      }
    }

    if (countSold > 0) {
      html += `
        <label class="checkbox-label show-sold-wrap">
          <input type="checkbox" id="chk-show-sold" ${catalogShowSold ? 'checked' : ''} onchange="toggleShowSold()">
          <span>Pokaż sprzedane (${countSold})</span>
        </label>
      `;
    }

    container.innerHTML = html;
  }

  window.filterFlatsByStatus = function(status) {
    if (selectedCategory !== 'Mieszkanie') {
      selectedCategory = 'Mieszkanie';
      updateCategoryTabs();
      renderHistogram();
    }
    catalogRoomsFilter = 'all';
    catalogStaircaseFilter = 'all';
    catalogSpecialFilter = 'all';
    catalogStatusFilter = status;
    if (status === 'sold') {
      catalogShowSold = true;
    }
    renderQuickFilters();
    renderTable();
    updateUrlHash();
    scrollToTable();
  };

  window.filterFlatsByRooms = function(rooms) {
    if (selectedCategory !== 'Mieszkanie') {
      selectedCategory = 'Mieszkanie';
      updateCategoryTabs();
      renderHistogram();
    }
    catalogStatusFilter = 'available';
    catalogRoomsFilter = rooms;
    catalogStaircaseFilter = 'all';
    catalogSpecialFilter = 'all';
    renderQuickFilters();
    renderTable();
    updateUrlHash();
    scrollToTable();
  };

  window.setCatalogFilter = function(type, val) {
    // If called from hero metrics or room/staircase chips, ensure category is Mieszkanie
    if ((type === 'rooms' || type === 'staircase' || (type === 'special' && val === 'drops')) && selectedCategory !== 'Mieszkanie') {
      selectedCategory = 'Mieszkanie';
      updateCategoryTabs();
      renderHistogram();
    }

    if (type === 'all') {
      catalogStatusFilter = 'all';
      catalogRoomsFilter = 'all';
      catalogStaircaseFilter = 'all';
      catalogSpecialFilter = 'all';
    } else if (type === 'status') {
      catalogStatusFilter = catalogStatusFilter === val ? 'all' : val;
    } else if (type === 'rooms') {
      catalogRoomsFilter = catalogRoomsFilter === val ? 'all' : val;
    } else if (type === 'staircase') {
      catalogStaircaseFilter = catalogStaircaseFilter === val ? 'all' : val;
    } else if (type === 'special') {
      catalogSpecialFilter = catalogSpecialFilter === val ? 'all' : val;
    }

    renderQuickFilters();
    renderTable();
    updateUrlHash();
    scrollToTable();
  };

  window.toggleShowSold = function() {
    const chk = document.getElementById('chk-show-sold');
    catalogShowSold = chk ? chk.checked : false;
    renderTable();
    updateUrlHash();
  };

  // --- Search & Range Inputs ---
  window.handleSearchInput = function(val) {
    catalogSearch = (val || '').trim();
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) {
      clearBtn.classList.toggle('hidden', !catalogSearch);
    }
    renderTable();
    updateUrlHash();
  };

  window.clearSearch = function() {
    catalogSearch = '';
    const input = document.getElementById('table-search');
    if (input) input.value = '';
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');
    renderTable();
    updateUrlHash();
  };

  window.handleMaxPriceInput = function(val) {
    const num = parseInt(val, 10);
    catalogMaxPrice = !isNaN(num) && num > 0 ? num : null;
    renderTable();
    updateUrlHash();
  };

  window.handleMinAreaInput = function(val) {
    const num = parseFloat(val);
    catalogMinArea = !isNaN(num) && num > 0 ? num : null;
    renderTable();
    updateUrlHash();
  };

  window.handleMaxAreaInput = function(val) {
    const num = parseFloat(val);
    catalogMaxArea = !isNaN(num) && num > 0 ? num : null;
    renderTable();
    updateUrlHash();
  };

  window.resetAllCatalogFilters = function() {
    catalogSearch = '';
    const input = document.getElementById('table-search');
    if (input) input.value = '';
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');

    catalogStatusFilter = 'all';
    catalogRoomsFilter = 'all';
    catalogStaircaseFilter = 'all';
    catalogSpecialFilter = 'all';
    catalogMaxPrice = null;
    catalogMinArea = null;
    catalogMaxArea = null;

    const maxPEl = document.getElementById('filter-max-price');
    if (maxPEl) maxPEl.value = '';
    const minAEl = document.getElementById('filter-min-area');
    if (minAEl) minAEl.value = '';
    const maxAEl = document.getElementById('filter-max-area');
    if (maxAEl) maxAEl.value = '';

    catalogShowSold = false;
    selectedHistogramBin = null;

    renderHistogram();
    renderQuickFilters();
    renderTable();
    updateUrlHash();
  };

  // --- Table Sorting ---
  window.sortTableBy = function(col) {
    if (catalogSortCol === col) {
      catalogSortDir = catalogSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      catalogSortCol = col;
      catalogSortDir = 'asc';
    }
    renderTable();
    updateUrlHash();
  };

  // --- Table Rendering ---
  function renderTable() {
    const headEl = document.getElementById('data-table-head');
    const bodyEl = document.getElementById('data-table-body');
    const counterEl = document.getElementById('table-counter');
    const chipsBarEl = document.getElementById('active-filter-chips');
    const chipsContainerEl = document.getElementById('chips-container');

    if (!headEl || !bodyEl) return;

    let items = allOffers.filter(o => o.cat === selectedCategory);

    // Status filter
    if (catalogStatusFilter !== 'all') {
      items = items.filter(o => o.kind === catalogStatusFilter);
    } else if (!catalogShowSold && catalogSpecialFilter !== 'drops') {
      items = items.filter(o => o.kind !== 'sold');
    }

    // Rooms filter
    if (catalogRoomsFilter !== 'all') {
      items = items.filter(o => String(o.rooms).trim() === catalogRoomsFilter);
    }

    // Staircase filter
    if (catalogStaircaseFilter !== 'all') {
      items = items.filter(o => String(o.staircase).trim() === catalogStaircaseFilter);
    }

    // Special filter (drops)
    if (catalogSpecialFilter === 'drops') {
      items = items.filter(o => o.has_drop);
    }

    // Range filters: max price
    if (catalogMaxPrice != null && catalogMaxPrice > 0) {
      items = items.filter(o => o.price_num != null && o.price_num <= catalogMaxPrice);
    }

    // Range filters: min/max area
    if (catalogMinArea != null && catalogMinArea > 0) {
      items = items.filter(o => o.area_num != null && o.area_num >= catalogMinArea);
    }
    if (catalogMaxArea != null && catalogMaxArea > 0) {
      items = items.filter(o => o.area_num != null && o.area_num <= catalogMaxArea);
    }

    // Histogram bin filter
    if (selectedHistogramBin) {
      if (selectedHistogramBin.isExact) {
        items = items.filter(o => o.price_num === selectedHistogramBin.min);
      } else if (histogramMode === 'total') {
        items = items.filter(o => {
          if (o.price_num == null) return false;
          return o.price_num >= selectedHistogramBin.min &&
            (selectedHistogramBin.isLast ? o.price_num <= selectedHistogramBin.max : o.price_num < selectedHistogramBin.max);
        });
      } else {
        items = items.filter(o => {
          const sqm = (o.price_num && o.area_num) ? (o.price_num / o.area_num) : null;
          if (sqm == null) return false;
          return sqm >= selectedHistogramBin.min &&
            (selectedHistogramBin.isLast ? sqm <= selectedHistogramBin.max : sqm < selectedHistogramBin.max);
        });
      }
    }

    // Search query filter (with diacritics support)
    if (catalogSearch) {
      const normSearch = removeDiacritics(catalogSearch);
      items = items.filter(o => {
        const text = removeDiacritics([
          o.unit,
          o.cat,
          o.rooms ? o.rooms + ' pok' : '',
          o.floor || '',
          o.staircase ? 'kl ' + o.staircase : '',
          o.extras || '',
          o.area ? o.area + ' m2' : '',
          o.price || '',
          o.status || ''
        ].join(' '));
        return text.includes(normSearch);
      });
    }

    // Sort items
    items.sort((a, b) => {
      let vA, vB;
      if (catalogSortCol === 'unit') {
        vA = a.unit || '';
        vB = b.unit || '';
        return catalogSortDir === 'asc' ? vA.localeCompare(vB, undefined, { numeric: true }) : vB.localeCompare(vA, undefined, { numeric: true });
      } else if (catalogSortCol === 'price') {
        vA = a.price_num || 0;
        vB = b.price_num || 0;
      } else if (catalogSortCol === 'area') {
        vA = a.area_num || 0;
        vB = b.area_num || 0;
      } else if (catalogSortCol === 'rooms') {
        vA = parseInt(a.rooms, 10) || 0;
        vB = parseInt(b.rooms, 10) || 0;
      } else if (catalogSortCol === 'floor') {
        vA = parseFloorNum(a.floor);
        vB = parseFloorNum(b.floor);
      } else if (catalogSortCol === 'price_m2') {
        vA = (a.price_num && a.area_num) ? (a.price_num / a.area_num) : 0;
        vB = (b.price_num && b.area_num) ? (b.price_num / b.area_num) : 0;
      } else if (catalogSortCol === 'status') {
        vA = a.kind || '';
        vB = b.kind || '';
        return catalogSortDir === 'asc' ? vA.localeCompare(vB) : vB.localeCompare(vA);
      }
      return catalogSortDir === 'asc' ? vA - vB : vB - vA;
    });

    // Update Counter
    if (counterEl) {
      counterEl.textContent = `Wyświetlono ${items.length} lokali`;
    }

    // Active Filter Chips
    let activeChips = [];
    if (selectedHistogramBin) {
      activeChips.push({ label: `Przedział: ${selectedHistogramBin.label}`, clear: () => clearHistogramSelection() });
    }
    if (catalogStatusFilter !== 'all') {
      const labels = { available: 'Tylko wolne', reserved: 'Tylko rezerwacje', sold: 'Tylko sprzedane' };
      activeChips.push({ label: labels[catalogStatusFilter] || catalogStatusFilter, clear: () => { catalogStatusFilter = 'all'; renderQuickFilters(); renderTable(); updateUrlHash(); } });
    }
    if (catalogRoomsFilter !== 'all') {
      activeChips.push({ label: `${catalogRoomsFilter} pokoje`, clear: () => { catalogRoomsFilter = 'all'; renderQuickFilters(); renderTable(); updateUrlHash(); } });
    }
    if (catalogStaircaseFilter !== 'all') {
      activeChips.push({ label: `Klatka ${catalogStaircaseFilter}`, clear: () => { catalogStaircaseFilter = 'all'; renderQuickFilters(); renderTable(); updateUrlHash(); } });
    }
    if (catalogSpecialFilter === 'drops') {
      activeChips.push({ label: 'Tylko obniżki cen', clear: () => { catalogSpecialFilter = 'all'; renderQuickFilters(); renderTable(); updateUrlHash(); } });
    }
    if (catalogMaxPrice) {
      activeChips.push({
        label: `Cena do: ${catalogMaxPrice.toLocaleString('pl-PL')} zł`,
        clear: () => {
          catalogMaxPrice = null;
          const el = document.getElementById('filter-max-price');
          if (el) el.value = '';
          renderTable();
          updateUrlHash();
        }
      });
    }
    if (catalogMinArea || catalogMaxArea) {
      const label = catalogMinArea && catalogMaxArea
        ? `Metraż: ${catalogMinArea}–${catalogMaxArea} m²`
        : (catalogMinArea ? `Metraż od: ${catalogMinArea} m²` : `Metraż do: ${catalogMaxArea} m²`);
      activeChips.push({
        label: label,
        clear: () => {
          catalogMinArea = null;
          catalogMaxArea = null;
          const minEl = document.getElementById('filter-min-area');
          if (minEl) minEl.value = '';
          const maxEl = document.getElementById('filter-max-area');
          if (maxEl) maxEl.value = '';
          renderTable();
          updateUrlHash();
        }
      });
    }
    if (catalogSearch) {
      activeChips.push({ label: `Szukaj: "${catalogSearch}"`, clear: () => clearSearch() });
    }

    if (chipsBarEl && chipsContainerEl) {
      if (activeChips.length > 0) {
        chipsBarEl.classList.remove('hidden');
        chipsContainerEl.innerHTML = activeChips.map((chip, i) => `
          <span class="filter-chip-tag">
            ${escapeHtml(chip.label)}
            <button type="button" onclick="window._clearChip(${i})" title="Usuń ten filtr">✕</button>
          </span>
        `).join('');
        window._activeChips = activeChips;
        window._clearChip = function(idx) {
          if (window._activeChips && window._activeChips[idx]) {
            window._activeChips[idx].clear();
          }
        };
      } else {
        chipsBarEl.classList.add('hidden');
      }
    }

    // Render Table Header with full keyboard accessibility
    let theadHtml = '<tr>';
    const sortIcon = (col) => {
      if (catalogSortCol !== col) return '<span class="sort-icon" aria-hidden="true">⇅</span>';
      return `<span class="sort-icon" aria-hidden="true">${catalogSortDir === 'asc' ? '▲' : '▼'}</span>`;
    };
    const th = (col, label) => {
      const isSorted = catalogSortCol === col;
      const ariaSort = isSorted ? (catalogSortDir === 'asc' ? 'ascending' : 'descending') : 'none';
      return `<th class="sortable${isSorted ? ' sorted' : ''}" role="columnheader" tabindex="0" aria-sort="${ariaSort}" onclick="sortTableBy('${col}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();sortTableBy('${col}');}">${label} ${sortIcon(col)}</th>`;
    };

    if (selectedCategory === 'Mieszkanie') {
      theadHtml += th('unit', 'Nr lokalu');
      theadHtml += th('rooms', 'Pokoje');
      theadHtml += th('floor', 'Piętro');
      theadHtml += th('area', 'Metraż');
      theadHtml += th('price', 'Cena całkowita');
      theadHtml += th('price_m2', 'Cena za m²');
      theadHtml += th('status', 'Status');
      theadHtml += '<th role="columnheader">Karta i rzuty</th>';
    } else if (selectedCategory === 'Komórka') {
      theadHtml += th('unit', 'Nr komórki');
      theadHtml += th('area', 'Metraż');
      theadHtml += th('price', 'Cena');
      theadHtml += th('status', 'Status');
      theadHtml += '<th role="columnheader">Karta lokalu</th>';
    } else {
      theadHtml += th('unit', 'Nr miejsca');
      theadHtml += th('price', 'Cena');
      theadHtml += th('status', 'Status');
      theadHtml += '<th role="columnheader">Karta lokalu</th>';
    }
    theadHtml += '</tr>';
    headEl.innerHTML = theadHtml;

    // Render Table Body
    if (items.length === 0) {
      const colSpan = selectedCategory === 'Mieszkanie' ? 8 : (selectedCategory === 'Komórka' ? 5 : 4);
      bodyEl.innerHTML = `<tr><td colspan="${colSpan}" class="table-empty-state">Brak lokali spełniających wybrane kryteria wyszukiwania.</td></tr>`;
      return;
    }

    let tbodyHtml = '';
    items.forEach(o => {
      const kind = o.kind || 'available';
      const statusLabel = kind === 'available' ? 'Wolne' : (kind === 'reserved' ? 'Rezerwacja' : 'Sprzedane');
      const url = o.url && o.url !== '#' ? o.url : null;
      const crmUrl = o.crm_url && o.crm_url !== '#' ? o.crm_url : null;

      let priceHtml = escapeHtml(o.price || 'Cena niedostępna');
      if (o.has_drop && o.delta_amt) {
        const tooltip = o.history_tooltip ? o.history_tooltip : 'Obniżka względem ceny pierwotnej';
        priceHtml += ` <span class="price-drop-badge" title="${escapeHtml(tooltip)}">↓ -${Math.abs(o.delta_amt).toLocaleString()} zł</span>`;
      }

      let priceM2Html = '—';
      if (o.price_num && o.area_num) {
        priceM2Html = Math.round(o.price_num / o.area_num).toLocaleString('pl-PL') + ' zł/m²';
      }

      tbodyHtml += '<tr>';

      if (selectedCategory === 'Mieszkanie') {
        tbodyHtml += `<td class="td-unit"><span class="unit-status-dot dot-${kind}" aria-hidden="true"></span><strong>${escapeHtml(o.unit)}</strong></td>`;
        tbodyHtml += `<td>${escapeHtml(o.rooms || '—')} pok.</td>`;
        tbodyHtml += `<td>${escapeHtml(o.floor || '—')}</td>`;
        tbodyHtml += `<td>${escapeHtml(o.area ? o.area + ' m²' : '—')}</td>`;
        tbodyHtml += `<td class="price-cell">${priceHtml}</td>`;
        tbodyHtml += `<td class="price-m2-cell">${priceM2Html}</td>`;
        tbodyHtml += `<td><span class="status-pill pill-${kind}">${statusLabel}</span></td>`;
      } else if (selectedCategory === 'Komórka') {
        tbodyHtml += `<td class="td-unit"><span class="unit-status-dot dot-${kind}" aria-hidden="true"></span><strong>${escapeHtml(o.unit)}</strong></td>`;
        tbodyHtml += `<td>${escapeHtml(o.area ? o.area + ' m²' : '—')}</td>`;
        tbodyHtml += `<td class="price-cell">${priceHtml}</td>`;
        tbodyHtml += `<td><span class="status-pill pill-${kind}">${statusLabel}</span></td>`;
      } else {
        tbodyHtml += `<td class="td-unit"><span class="unit-status-dot dot-${kind}" aria-hidden="true"></span><strong>${escapeHtml(o.unit)}</strong></td>`;
        tbodyHtml += `<td class="price-cell">${priceHtml}</td>`;
        tbodyHtml += `<td><span class="status-pill pill-${kind}">${statusLabel}</span></td>`;
      }

      const actions = [];
      if (url) {
        actions.push(`<a class="table-btn" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">Karta ↗</a>`);
      }
      if (crmUrl) {
        actions.push(`<a class="table-btn table-btn-pdf" href="${escapeHtml(crmUrl)}" target="_blank" rel="noreferrer" title="Otwórz oficjalny rzut architektoniczny w formacie PDF">📄 Rzut PDF</a>`);
      }
      const actionsHtml = actions.length > 0 ? `<div class="table-actions-cell">${actions.join('')}</div>` : '—';
      tbodyHtml += `<td>${actionsHtml}</td>`;
      tbodyHtml += '</tr>';
    });

    bodyEl.innerHTML = tbodyHtml;
  }

  // --- Timeline Scope (Block 2) ---
  window.setTimelineScope = function(scope) {
    timelineScope = scope;
    document.querySelectorAll('.timeline-scope-toggle .pill-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-timeline-scope') === scope);
    });
    updateTimelineScope();
  };

  function updateTimelineScope() {
    const isFlatsOnly = timelineScope === 'flats';

    // Toggle entire week cards if they contain no flats
    document.querySelectorAll('.week-card').forEach(card => {
      const hasFlats = card.getAttribute('data-has-flats') === 'true';
      if (isFlatsOnly && !hasFlats) {
        card.classList.add('hidden-by-scope');
      } else {
        card.classList.remove('hidden-by-scope');
      }
    });

    // Toggle individual event rows within visible cards
    document.querySelectorAll('.week-event-row').forEach(row => {
      const cat = row.getAttribute('data-cat');
      if (isFlatsOnly && cat !== 'Mieszkanie') {
        row.classList.add('hidden-by-scope');
      } else {
        row.classList.remove('hidden-by-scope');
      }
    });
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
