    // --- Global Filter Functions & Stubs ---
    window.setCategoryFilter = function(cat) {
      if (window._catalogSetCategory) window._catalogSetCategory(cat);
    };
    window.setPriceFilter = function(filter) {
      if (window._catalogSetPrice) window._catalogSetPrice(filter);
    };
    window.setStatusFilter = function(status) {
      if (window._catalogSetStatus) window._catalogSetStatus(status);
    };
    window.resetAllFilters = function() {
      if (window._catalogResetFilters) window._catalogResetFilters();
    };

    // --- Global Tab Switching ---
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(btn => {
        const isActive = btn.dataset.target === tabId;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', isActive);
      });
      document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === tabId);
      });
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function filterCatalogByStatus(statusKey) {
      switchTab('tab-catalog');
      window.setStatusFilter(statusKey);
    }

    function filterCatalogByPriceDrops() {
      switchTab('tab-catalog');
      window.setPriceFilter('drops');
    }

    function filterCatalogByGroup(groupName) {
      switchTab('tab-catalog');
      const catMap = {
        'Mieszkania': 'Mieszkanie',
        'Parkowanie': 'Hala garażowa,Miejsce postojowe',
        'Komórki lokatorskie': 'Komórka'
      };
      window.setCategoryFilter(catMap[groupName] || 'all');
    }

    // --- Trend View Switcher ---
    function switchTrendView(mode) {
      document.querySelectorAll('.trend-toggle-group .pill-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.trendBtn === mode);
      });
      const weeksWrap = document.getElementById('trend-view-weeks');
      const daysWrap = document.getElementById('trend-view-days');
      if (weeksWrap && daysWrap) {
        weeksWrap.style.display = mode === 'weeks' ? '' : 'none';
        daysWrap.style.display = mode === 'days' ? '' : 'none';
      }
    }

    // --- Copy Offer Link ---
    function copyOfferLink(event, url) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      const btn = event ? event.currentTarget : null;
      if (!url || url === '#' || url === 'None') return;

      const finishCopy = () => {
        if (btn) {
          btn.textContent = '✓';
          btn.classList.add('copied');
          btn.title = 'Skopiowano link!';
          setTimeout(() => {
            btn.textContent = '🔗';
            btn.classList.remove('copied');
            btn.title = 'Kopiuj link do schowka';
          }, 1800);
        }
      };

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(finishCopy).catch(() => {
          fallbackCopy(url);
          finishCopy();
        });
      } else {
        fallbackCopy(url);
        finishCopy();
      }
    }

    function fallbackCopy(text) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch(e) {}
      document.body.removeChild(ta);
    }

    // --- Timeline Grouping Switcher ---
    function switchTimelineGrouping(mode) {
      document.querySelectorAll('.group-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.timelineView === mode);
      });
      document.querySelectorAll('.timeline-view-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === 'timeline-view-' + mode);
      });
    }

    // --- Theme Toggle ---
    const themeBtn = document.getElementById('theme-toggle');
    function applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      try { localStorage.setItem('theme', theme); } catch(e) {}
      themeBtn.textContent = theme === 'dark' ? '☀️' : '🌓';
    }
    const savedTheme = (() => {
      try { return localStorage.getItem('theme'); } catch(e) { return null; }
    })();
    if (savedTheme) applyTheme(savedTheme);
    themeBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });

    // --- Timeline Event Type Filtering ---
    document.querySelectorAll('#timeline-event-filters .pill-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#timeline-event-filters .pill-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const filterType = btn.dataset.timelineType;

        document.querySelectorAll('.event-item').forEach(item => {
          if (filterType === 'all' || item.dataset.eventType === filterType) {
            item.style.display = '';
          } else {
            item.style.display = 'none';
          }
        });

        // Open timeline groups that have visible items
        document.querySelectorAll('.timeline-group').forEach(group => {
          const hasVisible = Array.from(group.querySelectorAll('.event-item')).some(i => i.style.display !== 'none');
          if (!hasVisible && filterType !== 'all') {
            group.style.display = 'none';
          } else {
            group.style.display = '';
            if (filterType !== 'all' && hasVisible) group.open = true;
          }
        });
      });
    });

    // --- Catalog Live Search, Filter & Infinite / Chunking Render ---
    (function() {
      const rawOffers = JSON.parse(document.getElementById('offers-data').textContent);
      const grid = document.getElementById('catalog-grid');
      const searchInput = document.getElementById('catalog-search');
      const searchClearBtn = document.getElementById('search-clear-btn');
      const sortSelect = document.getElementById('catalog-sort');
      const loadMoreBtn = document.getElementById('load-more-btn');
      const paginationWrap = document.getElementById('pagination-wrap');
      const visibleCountEl = document.getElementById('visible-count');
      const totalCountEl = document.getElementById('total-count');
      const viewModeBtn = document.getElementById('view-mode-toggle');
      const activeFiltersBar = document.getElementById('active-filters-bar');
      const activeFiltersCountEl = document.getElementById('active-filters-count');
      const activeFilterTagsEl = document.getElementById('active-filter-tags');
      const resetFiltersBtn = document.getElementById('reset-filters-btn');

      let currentCat = 'all';
      let currentStatus = 'all';
      let currentPriceFilter = 'all';
      let currentQuery = '';
      let currentSort = 'default';
      let isCompact = false;

      const PAGE_SIZE = 32;
      let displayedCount = PAGE_SIZE;

      viewModeBtn.addEventListener('click', () => {
        isCompact = !isCompact;
        grid.classList.toggle('compact-mode', isCompact);
        viewModeBtn.textContent = isCompact ? 'Widok: Lista' : 'Widok: Kafelki';
      });

      function updateActiveFilters() {
        const chips = [];
        if (currentPriceFilter === 'drops') {
          chips.push({ text: '🔥 Obniżki cen', action: "setPriceFilter('all')" });
        }
        if (currentCat !== 'all') {
          const catMap = {
            'Mieszkanie': 'Mieszkania',
            'Hala garażowa,Miejsce postojowe': 'Parkowanie',
            'Komórka': 'Komórki'
          };
          chips.push({ text: catMap[currentCat] || currentCat, action: "setCategoryFilter('all')" });
        }
        if (currentStatus !== 'all') {
          const statusMap = {
            'available': 'Wolne',
            'reserved': 'Rezerwacja',
            'sold': 'Sprzedane'
          };
          chips.push({ text: statusMap[currentStatus] || currentStatus, action: "setStatusFilter('all')" });
        }
        if (currentQuery) {
          chips.push({ text: `"${currentQuery}"`, action: "clearSearchFilter()" });
        }

        if (chips.length > 0) {
          activeFiltersBar.style.display = 'flex';
          activeFiltersCountEl.textContent = chips.length;
          activeFilterTagsEl.innerHTML = chips.map(c =>
            `<button type="button" class="active-filter-chip" onclick="${c.action}" title="Usuń ten filtr">${c.text} ✕</button>`
          ).join('');
        } else {
          activeFiltersBar.style.display = 'none';
        }

        if (searchClearBtn) {
          searchClearBtn.style.display = (searchInput && searchInput.value) ? 'flex' : 'none';
        }
      }

      function filterAndSortOffers() {
        let list = rawOffers.filter(item => {
          if (currentPriceFilter === 'drops' && !item.has_drop) {
            return false;
          }
          if (currentCat !== 'all') {
            const allowed = currentCat.split(',');
            if (!allowed.includes(item.cat)) return false;
          }
          if (currentStatus !== 'all' && item.kind !== currentStatus) {
            return false;
          }
          if (currentQuery) {
            const q = currentQuery.toLowerCase();
            const text = `${item.cat} ${item.unit} ${item.group} ${item.price} ${item.area} ${item.rooms} ${item.floor} ${item.has_drop ? 'obniżka obnizka rabat taniej' : ''}`.toLowerCase();
            if (!text.includes(q)) return false;
          }
          return true;
        });

        if (currentSort === 'drop-desc') {
          list.sort((a, b) => (a.delta_amt || 0) - (b.delta_amt || 0));
        } else if (currentSort === 'drop-pct-desc') {
          list.sort((a, b) => (a.delta_pct || 0) - (b.delta_pct || 0));
        } else if (currentSort === 'price-asc') {
          list.sort((a, b) => (a.price_num ?? Infinity) - (b.price_num ?? Infinity));
        } else if (currentSort === 'price-desc') {
          list.sort((a, b) => (b.price_num ?? 0) - (a.price_num ?? 0));
        } else if (currentSort === 'area-desc') {
          list.sort((a, b) => (b.area_num ?? 0) - (a.area_num ?? 0));
        } else if (currentSort === 'area-asc') {
          list.sort((a, b) => (a.area_num ?? Infinity) - (b.area_num ?? Infinity));
        } else if (currentSort === 'unit-asc') {
          list.sort((a, b) => (a.cat + a.unit).localeCompare(b.cat + b.unit, undefined, { numeric: true }));
        }

        return list;
      }

      function renderCatalog(reset = false) {
        if (reset) displayedCount = PAGE_SIZE;
        updateActiveFilters();
        const filtered = filterAndSortOffers();
        totalCountEl.textContent = filtered.length;

        const slice = filtered.slice(0, displayedCount);
        visibleCountEl.textContent = slice.length;

        if (slice.length === 0) {
          grid.innerHTML = '<div class="empty-state empty-state-full">Brak ofert spełniających kryteria.</div>';
          paginationWrap.style.display = 'none';
          return;
        }

        grid.innerHTML = slice.map(offer => {
          const metaParts = [];
          if (offer.area) metaParts.push(offer.area + ' m²');
          if (offer.rooms) metaParts.push(offer.rooms + ' pok.');
          if (offer.floor) metaParts.push(offer.floor);
          if (offer.staircase) metaParts.push('kl. ' + offer.staircase);
          const metaText = metaParts.join(' · ') || offer.group;
          const statusLabels = { available: 'Wolne', reserved: 'Rezerwacja', sold: 'Sprzedane', unavailable: 'Niedostępne' };
          const label = statusLabels[offer.kind] || offer.status;

          let priceContent = '';
          if (offer.has_drop || offer.has_rise) {
            const isDrop = offer.has_drop;
            const deltaStr = Math.abs(offer.delta_amt).toLocaleString('pl-PL');
            const pillCls = isDrop ? 'price-drop-pill' : 'price-rise-pill';
            const sign = isDrop ? '↓ -' : '↑ +';
            const pctStr = Math.abs(offer.delta_pct);
            const tooltipAttr = offer.history_tooltip ? ` title="${offer.history_tooltip}"` : '';
            priceContent = `
              <div class="card-price-col">
                <div class="card-price-topline">
                  <span class="card-old-price">${offer.initial_price}</span>
                  <span class="${pillCls}"${tooltipAttr}>${sign}${deltaStr} zł (${pctStr}%)</span>
                </div>
                <strong class="card-price">${offer.price}</strong>
              </div>`;
          } else if (!offer.price && offer.last_known_price) {
            priceContent = `
              <div class="card-price-col">
                <strong class="card-price price-muted">Cena ukryta</strong>
                <span class="card-last-known">ostatnio: ${offer.last_known_price}</span>
              </div>`;
          } else {
            priceContent = `<strong class="card-price">${offer.price || 'Cena niedostępna'}</strong>`;
          }

          const recentBadge = offer.recent
            ? '<span class="badge-recent-change" title="Pozycja zmieniła się w ostatnim sprawdzeniu">✦ Ostatnia zmiana</span>'
            : '';
          const copyBtn = `<button class="card-copy-btn" type="button" title="Kopiuj link do schowka" onclick="copyOfferLink(event, '${offer.url}')">🔗</button>`;

          return `<a class="flat-card status-border-${offer.kind}" href="${offer.url}" target="_blank" rel="noreferrer">
            <div class="card-header">
              <div class="card-title-wrap">
                <span class="status-dot dot-${offer.kind}" aria-hidden="true"></span>
                <span class="card-unit">${offer.cat} ${offer.unit}</span>
                ${recentBadge}
              </div>
              <div class="card-header-actions">
                ${copyBtn}
                <span class="status-pill pill-${offer.kind}">${label}</span>
              </div>
            </div>
            <div class="card-body">
              <span class="card-meta">${metaText}</span>
              <div class="card-price-row">
                ${priceContent}
                <span class="card-link-icon" aria-hidden="true">↗</span>
              </div>
            </div>
          </a>`;
        }).join('');

        paginationWrap.style.display = displayedCount >= filtered.length ? 'none' : 'flex';
      }

      loadMoreBtn.addEventListener('click', () => {
        displayedCount += PAGE_SIZE;
        renderCatalog(false);
      });

      let debounceTimer;
      searchInput.addEventListener('input', e => {
        if (searchClearBtn) {
          searchClearBtn.style.display = e.target.value ? 'flex' : 'none';
        }
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          currentQuery = e.target.value.trim();
          renderCatalog(true);
        }, 180);
      });

      if (searchClearBtn) {
        searchClearBtn.addEventListener('click', () => {
          searchInput.value = '';
          currentQuery = '';
          searchClearBtn.style.display = 'none';
          renderCatalog(true);
          searchInput.focus();
        });
      }

      sortSelect.addEventListener('change', e => {
        currentSort = e.target.value;
        renderCatalog(true);
      });

      window._catalogSetCategory = function(cat) {
        currentCat = cat || 'all';
        document.querySelectorAll('#category-filters .pill-btn').forEach(b => {
          const val = b.getAttribute('data-cat-filter') || b.dataset.catFilter;
          b.classList.toggle('active', val === currentCat);
        });
        renderCatalog(true);
      };

      window._catalogSetPrice = function(filter) {
        currentPriceFilter = filter || 'all';
        document.querySelectorAll('#price-filters .pill-btn').forEach(b => {
          const val = b.getAttribute('data-price-filter') || b.dataset.priceFilter;
          b.classList.toggle('active', val === currentPriceFilter);
        });
        renderCatalog(true);
      };

      window._catalogSetStatus = function(status) {
        currentStatus = status || 'all';
        document.querySelectorAll('#status-filters .pill-btn').forEach(b => {
          const val = b.getAttribute('data-status-filter') || b.dataset.statusFilter;
          b.classList.toggle('active', val === currentStatus);
        });
        renderCatalog(true);
      };

      window._catalogResetFilters = function() {
        currentPriceFilter = 'all';
        currentCat = 'all';
        currentStatus = 'all';
        currentQuery = '';
        currentSort = 'default';

        document.querySelectorAll('#price-filters .pill-btn').forEach(b => {
          b.classList.toggle('active', (b.getAttribute('data-price-filter') || b.dataset.priceFilter) === 'all');
        });
        document.querySelectorAll('#category-filters .pill-btn').forEach(b => {
          b.classList.toggle('active', (b.getAttribute('data-cat-filter') || b.dataset.catFilter) === 'all');
        });
        document.querySelectorAll('#status-filters .pill-btn').forEach(b => {
          b.classList.toggle('active', (b.getAttribute('data-status-filter') || b.dataset.statusFilter) === 'all');
        });

        if (searchInput) searchInput.value = '';
        if (searchClearBtn) searchClearBtn.style.display = 'none';
        if (sortSelect) sortSelect.value = 'default';

        renderCatalog(true);
      };

      window.clearSearchFilter = function() {
        if (searchInput) searchInput.value = '';
        currentQuery = '';
        if (searchClearBtn) searchClearBtn.style.display = 'none';
        renderCatalog(true);
      };

      // Event delegation on catalog filter container to catch all clicks
      const catalogBar = document.querySelector('.catalog-bar');
      if (catalogBar) {
        catalogBar.addEventListener('click', e => {
          const btn = e.target.closest('.pill-btn');
          if (!btn) return;
          if (btn.hasAttribute('data-cat-filter')) {
            window.setCategoryFilter(btn.getAttribute('data-cat-filter'));
          } else if (btn.hasAttribute('data-price-filter')) {
            window.setPriceFilter(btn.getAttribute('data-price-filter'));
          } else if (btn.hasAttribute('data-status-filter')) {
            window.setStatusFilter(btn.getAttribute('data-status-filter'));
          }
        });
      }

      if (resetFiltersBtn) {
        resetFiltersBtn.addEventListener('click', () => window.resetAllFilters());
      }

      renderCatalog(true);
    })();
