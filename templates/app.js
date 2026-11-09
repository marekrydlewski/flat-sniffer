// Świętego Michała · Interactive Dashboard App
(function() {
  'use strict';

  // --- State ---
  let allOffers = [];
  let selectedCategory = 'Mieszkanie';
  let histogramMode = 'total'; // 'total' | 'sqm'
  let includeSoldInHist = false;
  let selectedHistogramBin = null; // { min, max, label } or null

  // Table filters & sorting
  let catalogSearch = '';
  let catalogStatusFilter = 'all'; // 'all' | 'available' | 'reserved' | 'sold'
  let catalogRoomsFilter = 'all';  // 'all' | '2' | '3' | '4'
  let catalogSpecialFilter = 'all'; // 'all' | 'drops'
  let catalogShowSold = false;
  let catalogSortCol = 'price';
  let catalogSortDir = 'asc';

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

  function formatPrice(num) {
    if (num == null || isNaN(num)) return '—';
    return Math.round(num).toLocaleString('pl-PL') + ' zł';
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
    renderAll();
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
    catalogSpecialFilter = 'all';
    catalogShowSold = false;
    catalogSortCol = 'price';
    catalogSortDir = 'asc';

    renderAll();
  };

  function updateCategoryTabs() {
    document.querySelectorAll('.cat-tab-btn').forEach(btn => {
      const isMatch = btn.getAttribute('data-category') === selectedCategory;
      btn.classList.toggle('active', isMatch);
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
      container.innerHTML = '<div style="text-align:center; padding: 2rem; color: var(--text-muted);">Brak danych cenowych dla wybranej konfiguracji.</div>';
      updateDrilldownBar();
      return;
    }

    let bins = [];

    if (selectedCategory === 'Mieszkanie') {
      if (histogramMode === 'total') {
        const step = 50000;
        // Find min and max price
        const prices = items.map(o => o.price_num).filter(p => p && p > 0);
        if (prices.length > 0) {
          const minP = Math.floor(Math.min(...prices) / step) * step;
          const maxP = Math.ceil(Math.max(...prices) / step) * step;
          for (let b = minP; b < maxP; b += step) {
            const bMin = b;
            const bMax = b + step;
            const bItems = items.filter(o => o.price_num >= bMin && (bMax >= maxP ? o.price_num <= bMax : o.price_num < bMax));
            if (bItems.length > 0) {
              const label = `${Math.round(bMin / 1000)}k–${Math.round(bMax / 1000)}k zł`;
              bins.push({ min: bMin, max: bMax, label: label, items: bItems });
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
            const bItems = items.filter(o => {
              const sqm = (o.price_num && o.area_num) ? (o.price_num / o.area_num) : null;
              return sqm != null && sqm >= bMin && (bMax >= maxS ? sqm <= bMax : sqm < bMax);
            });
            if (bItems.length > 0) {
              const label = `${bMin.toLocaleString()}–${bMax.toLocaleString()} zł/m²`;
              bins.push({ min: bMin, max: bMax, label: label, items: bItems });
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
      container.innerHTML = '<div style="text-align:center; padding: 2rem; color: var(--text-muted);">Brak danych cenowych.</div>';
      updateDrilldownBar();
      return;
    }

    // Find max count across bins for height scaling
    const maxCount = Math.max(...bins.map(b => b.items.length), 1);

    // Build chart HTML
    let chartHtml = '<div class="histogram-chart">';
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
        <div class="hist-col${activeCls}" data-bin-idx="${idx}" onclick="handleHistBarClick(${idx})" title="${escapeHtml(tooltip)}">
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

    container.innerHTML = chartHtml + labelsHtml;

    // Attach bin data to window for click handler
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
    const countTotal = catOffers.length;
    const countAvail = catOffers.filter(o => o.kind === 'available').length;
    const countRes = catOffers.filter(o => o.kind === 'reserved').length;
    const countSold = catOffers.filter(o => o.kind === 'sold').length;
    const countDrops = catOffers.filter(o => o.has_drop).length;

    html += `<button class="q-pill${catalogStatusFilter === 'all' && catalogSpecialFilter === 'all' && catalogRoomsFilter === 'all' ? ' active' : ''}" onclick="setCatalogFilter('all')">Wszystkie (${countAvail + countRes})</button>`;
    html += `<button class="q-pill${catalogStatusFilter === 'available' ? ' active' : ''}" onclick="setCatalogFilter('status', 'available')">Wolne (${countAvail})</button>`;
    if (countRes > 0) {
      html += `<button class="q-pill${catalogStatusFilter === 'reserved' ? ' active' : ''}" onclick="setCatalogFilter('status', 'reserved')">Rezerwacje (${countRes})</button>`;
    }

    if (selectedCategory === 'Mieszkanie') {
      const rooms2 = catOffers.filter(o => o.rooms === '2' && o.kind === 'available').length;
      const rooms3 = catOffers.filter(o => o.rooms === '3' && o.kind === 'available').length;
      const rooms4 = catOffers.filter(o => o.rooms === '4' && o.kind === 'available').length;

      if (rooms2 > 0) html += `<button class="q-pill${catalogRoomsFilter === '2' ? ' active' : ''}" onclick="setCatalogFilter('rooms', '2')">2 pokoje (${rooms2})</button>`;
      if (rooms3 > 0) html += `<button class="q-pill${catalogRoomsFilter === '3' ? ' active' : ''}" onclick="setCatalogFilter('rooms', '3')">3 pokoje (${rooms3})</button>`;
      if (rooms4 > 0) html += `<button class="q-pill${catalogRoomsFilter === '4' ? ' active' : ''}" onclick="setCatalogFilter('rooms', '4')">4 pokoje (${rooms4})</button>`;

      if (countDrops > 0) {
        html += `<button class="q-pill${catalogSpecialFilter === 'drops' ? ' active' : ''}" onclick="setCatalogFilter('special', 'drops')">🔥 Obniżki cen (${countDrops})</button>`;
      }
    }

    if (countSold > 0) {
      html += `
        <label class="checkbox-label" style="margin-left: 0.5rem; align-self: center;">
          <input type="checkbox" id="chk-show-sold" ${catalogShowSold ? 'checked' : ''} onchange="toggleShowSold()">
          <span>Pokaż sprzedane (${countSold})</span>
        </label>
      `;
    }

    container.innerHTML = html;
  }

  window.setCatalogFilter = function(type, val) {
    if (type === 'all') {
      catalogStatusFilter = 'all';
      catalogRoomsFilter = 'all';
      catalogSpecialFilter = 'all';
    } else if (type === 'status') {
      catalogStatusFilter = catalogStatusFilter === val ? 'all' : val;
    } else if (type === 'rooms') {
      catalogRoomsFilter = catalogRoomsFilter === val ? 'all' : val;
    } else if (type === 'special') {
      catalogSpecialFilter = catalogSpecialFilter === val ? 'all' : val;
    }

    renderQuickFilters();
    renderTable();
    scrollToTable();
  };

  window.toggleShowSold = function() {
    const chk = document.getElementById('chk-show-sold');
    catalogShowSold = chk ? chk.checked : false;
    renderTable();
  };

  // --- Search Input ---
  window.handleSearchInput = function(val) {
    catalogSearch = (val || '').trim().toLowerCase();
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) {
      clearBtn.classList.toggle('hidden', !catalogSearch);
    }
    renderTable();
  };

  window.clearSearch = function() {
    catalogSearch = '';
    const input = document.getElementById('table-search');
    if (input) input.value = '';
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');
    renderTable();
  };

  window.resetAllCatalogFilters = function() {
    catalogSearch = '';
    const input = document.getElementById('table-search');
    if (input) input.value = '';
    const clearBtn = document.getElementById('search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');

    catalogStatusFilter = 'all';
    catalogRoomsFilter = 'all';
    catalogSpecialFilter = 'all';
    catalogShowSold = false;
    selectedHistogramBin = null;

    renderHistogram();
    renderQuickFilters();
    renderTable();
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
  };

  // --- Table Rendering ---
  function renderTable() {
    const headEl = document.getElementById('data-table-head');
    const bodyEl = document.getElementById('data-table-body');
    const counterEl = document.getElementById('table-counter');
    const chipsBarEl = document.getElementById('active-filter-chips');
    const chipsContainerEl = document.getElementById('chips-container');

    if (!headEl || !bodyEl) return;

    // Filter offers
    let items = allOffers.filter(o => o.cat === selectedCategory);

    // Status filter
    if (catalogStatusFilter !== 'all') {
      items = items.filter(o => o.kind === catalogStatusFilter);
    } else if (!catalogShowSold) {
      // By default hide sold unless requested
      items = items.filter(o => o.kind !== 'sold');
    }

    // Rooms filter
    if (catalogRoomsFilter !== 'all') {
      items = items.filter(o => String(o.rooms).trim() === catalogRoomsFilter);
    }

    // Special filter (drops)
    if (catalogSpecialFilter === 'drops') {
      items = items.filter(o => o.has_drop);
    }

    // Histogram bin filter
    if (selectedHistogramBin) {
      if (selectedHistogramBin.isExact) {
        items = items.filter(o => o.price_num === selectedHistogramBin.min);
      } else if (histogramMode === 'total') {
        items = items.filter(o => o.price_num >= selectedHistogramBin.min && o.price_num <= selectedHistogramBin.max);
      } else {
        items = items.filter(o => {
          const sqm = (o.price_num && o.area_num) ? (o.price_num / o.area_num) : null;
          return sqm != null && sqm >= selectedHistogramBin.min && sqm <= selectedHistogramBin.max;
        });
      }
    }

    // Search query filter
    if (catalogSearch) {
      items = items.filter(o => {
        const text = [
          o.unit,
          o.cat,
          o.rooms ? o.rooms + ' pok' : '',
          o.floor ? o.floor + ' p' : '',
          o.area ? o.area + ' m2' : '',
          o.price
        ].join(' ').toLowerCase();
        return text.includes(catalogSearch);
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
        vA = parseInt(a.floor, 10) || 0;
        vB = parseInt(b.floor, 10) || 0;
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
      activeChips.push({ label: labels[catalogStatusFilter] || catalogStatusFilter, clear: () => { catalogStatusFilter = 'all'; renderQuickFilters(); renderTable(); } });
    }
    if (catalogRoomsFilter !== 'all') {
      activeChips.push({ label: `${catalogRoomsFilter} pokoje`, clear: () => { catalogRoomsFilter = 'all'; renderQuickFilters(); renderTable(); } });
    }
    if (catalogSpecialFilter === 'drops') {
      activeChips.push({ label: 'Tylko obniżki cen', clear: () => { catalogSpecialFilter = 'all'; renderQuickFilters(); renderTable(); } });
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

    // Render Table Header
    let theadHtml = '<tr>';
    const sortIcon = (col) => {
      if (catalogSortCol !== col) return '<span class="sort-icon">⇅</span>';
      return `<span class="sort-icon">${catalogSortDir === 'asc' ? '▲' : '▼'}</span>`;
    };
    const th = (col, label) => `<th class="sortable${catalogSortCol === col ? ' sorted' : ''}" onclick="sortTableBy('${col}')">${label} ${sortIcon(col)}</th>`;

    if (selectedCategory === 'Mieszkanie') {
      theadHtml += th('unit', 'Nr lokalu');
      theadHtml += th('rooms', 'Pokoje');
      theadHtml += th('floor', 'Piętro');
      theadHtml += th('area', 'Metraż');
      theadHtml += th('price', 'Cena całkowita');
      theadHtml += th('price_m2', 'Cena za m²');
      theadHtml += th('status', 'Status');
      theadHtml += '<th>Karta dewelopera</th>';
    } else if (selectedCategory === 'Komórka') {
      theadHtml += th('unit', 'Nr komórki');
      theadHtml += th('area', 'Metraż');
      theadHtml += th('price', 'Cena');
      theadHtml += th('status', 'Status');
      theadHtml += '<th>Karta dewelopera</th>';
    } else {
      // Hala garażowa & Parking
      theadHtml += th('unit', 'Nr miejsca');
      theadHtml += th('price', 'Cena');
      theadHtml += th('status', 'Status');
      theadHtml += '<th>Karta dewelopera</th>';
    }
    theadHtml += '</tr>';
    headEl.innerHTML = theadHtml;

    // Render Table Body
    if (items.length === 0) {
      bodyEl.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 2.5rem; color: var(--text-muted);">Brak lokali spełniających wybrane kryteria wyszukiwania.</td></tr>`;
      return;
    }

    let tbodyHtml = '';
    items.forEach(o => {
      const kind = o.kind || 'available';
      const statusLabel = kind === 'available' ? 'Wolne' : (kind === 'reserved' ? 'Rezerwacja' : 'Sprzedane');
      const url = o.url && o.url !== '#' ? o.url : null;

      let priceHtml = escapeHtml(o.price || 'Cena niedostępna');
      if (o.has_drop && o.delta_amt) {
        priceHtml += ` <span class="price-drop-badge" title="Obniżka względem ceny pierwotnej">↓ -${Math.abs(o.delta_amt).toLocaleString()} zł</span>`;
      }

      let priceM2Html = '—';
      if (o.price_num && o.area_num) {
        priceM2Html = Math.round(o.price_num / o.area_num).toLocaleString('pl-PL') + ' zł/m²';
      }

      tbodyHtml += '<tr>';

      if (selectedCategory === 'Mieszkanie') {
        tbodyHtml += `<td class="td-unit"><span class="unit-status-dot dot-${kind}"></span><strong>${escapeHtml(o.unit)}</strong></td>`;
        tbodyHtml += `<td>${escapeHtml(o.rooms || '—')} pok.</td>`;
        tbodyHtml += `<td>${escapeHtml(o.floor || '—')}</td>`;
        tbodyHtml += `<td>${escapeHtml(o.area ? o.area + ' m²' : '—')}</td>`;
        tbodyHtml += `<td class="price-cell">${priceHtml}</td>`;
        tbodyHtml += `<td class="price-m2-cell">${priceM2Html}</td>`;
        tbodyHtml += `<td><span class="status-pill pill-${kind}">${statusLabel}</span></td>`;
      } else if (selectedCategory === 'Komórka') {
        tbodyHtml += `<td class="td-unit"><span class="unit-status-dot dot-${kind}"></span><strong>${escapeHtml(o.unit)}</strong></td>`;
        tbodyHtml += `<td>${escapeHtml(o.area ? o.area + ' m²' : '—')}</td>`;
        tbodyHtml += `<td class="price-cell">${priceHtml}</td>`;
        tbodyHtml += `<td><span class="status-pill pill-${kind}">${statusLabel}</span></td>`;
      } else {
        tbodyHtml += `<td class="td-unit"><span class="unit-status-dot dot-${kind}"></span><strong>${escapeHtml(o.unit)}</strong></td>`;
        tbodyHtml += `<td class="price-cell">${priceHtml}</td>`;
        tbodyHtml += `<td><span class="status-pill pill-${kind}">${statusLabel}</span></td>`;
      }

      tbodyHtml += `<td>${url ? `<a class="table-btn" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">Karta ↗</a>` : '—'}</td>`;
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
    const rows = document.querySelectorAll('.week-event-row');
    rows.forEach(row => {
      const cat = row.getAttribute('data-cat');
      if (timelineScope === 'flats' && cat !== 'Mieszkanie') {
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
