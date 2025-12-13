/**
 * Golden Dataset Creator
 * JavaScript application for creating curated golden dataset from multiple LLM analyses
 */

class GoldenDatasetApp {
    constructor() {
        this.currentOffset = 0;
        this.currentItem = null;
        this.currentAnalyses = [];
        this.totalItems = 0;
        this.reviewedCount = 0;
        this.autoSaveInterval = null;

        // Section navigation state
        this.sections = [
            'category',
            'extracted-text',
            'headline',
            'summary',
            'image-details',
            'metadata'
        ];
        this.currentSectionIndex = 0;
        this.sectionDataCache = {}; // Cache user selections per section

        // Track visual hierarchy state
        this.visualHierarchySourceAnalysisIndex = null;
        this.visualHierarchyManuallyEdited = false;
    }

    async init() {
        console.log('Initializing Golden Dataset App...');

        // Load first item
        await this.loadItem(this.currentOffset);

        // Setup event listeners
        this.setupEventListeners();

        // Setup auto-save
        this.setupAutoSave();

        console.log('App initialized');
    }

    setupEventListeners() {
        // Navigation buttons
        document.getElementById('btn-prev').addEventListener('click', () => this.prevItem());
        document.getElementById('btn-next').addEventListener('click', () => this.nextItem());
        document.getElementById('btn-skip').addEventListener('click', () => this.nextItem());

        // Action buttons
        document.getElementById('btn-save').addEventListener('click', () => this.saveEntry(false));
        document.getElementById('btn-save-next').addEventListener('click', () => this.saveEntry(true));

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                if (e.key === 'n') {
                    e.preventDefault();
                    this.nextItem();
                } else if (e.key === 'p') {
                    e.preventDefault();
                    this.prevItem();
                } else if (e.key === 's') {
                    e.preventDefault();
                    this.saveEntry(false);
                }
            }
        });

        // Add item buttons
        this.setupAddItemButtons();

        // Section navigation
        this.setupSectionNavigation();

        // Visual hierarchy drag-and-drop ranking
        this.setupVisualHierarchyRanking();

        // Listen for extracted text selection changes
        this.setupExtractedTextHierarchySync();

        // Alt+Arrow for section navigation
        document.addEventListener('keydown', (e) => {
            if (!e.target.matches('input, textarea')) {
                if (e.key === 'ArrowRight' && e.altKey) {
                    e.preventDefault();
                    if (this.currentSectionIndex < this.sections.length - 1) {
                        this.switchToSection(this.currentSectionIndex + 1);
                    }
                } else if (e.key === 'ArrowLeft' && e.altKey) {
                    e.preventDefault();
                    if (this.currentSectionIndex > 0) {
                        this.switchToSection(this.currentSectionIndex - 1);
                    }
                }
            }
        });

        // Analysis option clicks
        document.addEventListener('click', (e) => {
            if (e.target.closest('.analysis-option')) {
                const option = e.target.closest('.analysis-option');
                const radio = option.querySelector('input[type="radio"]');
                if (radio && e.target !== radio) {
                    radio.checked = true;
                }
            }
        });
    }

    setupAddItemButtons() {
        const addButtons = [
            { btnId: 'subcategory-add-btn', inputId: 'subcategory-add-input', listId: 'subcategory-options' },
            { btnId: 'objects-add-btn', inputId: 'objects-add-input', listId: 'objects-list' },
            { btnId: 'themes-add-btn', inputId: 'themes-add-input', listId: 'themes-list' },
            { btnId: 'emotions-add-btn', inputId: 'emotions-add-input', listId: 'emotions-list' },
            { btnId: 'vibes-add-btn', inputId: 'vibes-add-input', listId: 'vibes-list' },
            { btnId: 'visual-hierarchy-add-btn', inputId: 'visual-hierarchy-add-input', listId: 'visual-hierarchy-list', isRanking: true },
            { btnId: 'tagged-accounts-add-btn', inputId: 'tagged-accounts-add-input', listId: 'tagged-accounts-list' },
            { btnId: 'location-tags-add-btn', inputId: 'location-tags-add-input', listId: 'location-tags-list' },
            { btnId: 'hashtags-add-btn', inputId: 'hashtags-add-input', listId: 'hashtags-list' }
        ];

        addButtons.forEach(({ btnId, inputId, listId, isRanking }) => {
            const btn = document.getElementById(btnId);
            const input = document.getElementById(inputId);

            if (btn && input) {
                btn.addEventListener('click', () => {
                    const value = input.value.trim();
                    if (value) {
                        // Use ranking item for visual hierarchy, checkbox for others
                        if (isRanking) {
                            this.addRankingItem(value);
                        } else {
                            this.addCheckboxItem(listId, value);
                        }
                        input.value = '';
                    }
                });

                input.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        btn.click();
                    }
                });
            }
        });
    }

    setupSectionNavigation() {
        // Tab button clicks
        const tabButtons = document.querySelectorAll('.tab-btn');
        tabButtons.forEach((btn, index) => {
            btn.addEventListener('click', () => {
                this.switchToSection(index);
            });
        });

        // Keyboard navigation for tabs (Arrow keys)
        const tablist = document.querySelector('.section-tabs');
        if (tablist) {
            tablist.addEventListener('keydown', (e) => {
                let newIndex = this.currentSectionIndex;

                if (e.key === 'ArrowRight') {
                    e.preventDefault();
                    newIndex = Math.min(this.currentSectionIndex + 1, this.sections.length - 1);
                } else if (e.key === 'ArrowLeft') {
                    e.preventDefault();
                    newIndex = Math.max(this.currentSectionIndex - 1, 0);
                } else if (e.key === 'Home') {
                    e.preventDefault();
                    newIndex = 0;
                } else if (e.key === 'End') {
                    e.preventDefault();
                    newIndex = this.sections.length - 1;
                }

                if (newIndex !== this.currentSectionIndex) {
                    this.switchToSection(newIndex);
                    tabButtons[newIndex].focus();
                }
            });
        }

        // Previous/Next section buttons
        const prevBtn = document.getElementById('btn-prev-section');
        const nextBtn = document.getElementById('btn-next-section');

        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (this.currentSectionIndex > 0) {
                    this.switchToSection(this.currentSectionIndex - 1);
                }
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                if (this.currentSectionIndex < this.sections.length - 1) {
                    this.switchToSection(this.currentSectionIndex + 1);
                }
            });
        }
    }

    switchToSection(newIndex) {
        const oldIndex = this.currentSectionIndex;

        // Save current section state
        this.cacheSectionState(this.sections[oldIndex]);

        // Update index
        this.currentSectionIndex = newIndex;
        const sectionId = this.sections[newIndex];

        // Update tab UI
        document.querySelectorAll('.tab-btn').forEach((btn, i) => {
            btn.classList.toggle('active', i === newIndex);
            btn.setAttribute('aria-selected', i === newIndex ? 'true' : 'false');
        });

        // Update panels
        document.querySelectorAll('.tab-panel').forEach((panel, i) => {
            panel.classList.toggle('active', i === newIndex);
        });

        // Update progress
        const currentElem = document.getElementById('section-current');
        const totalElem = document.getElementById('section-total');
        if (currentElem) currentElem.textContent = newIndex + 1;
        if (totalElem) totalElem.textContent = this.sections.length;

        // Update nav buttons
        const prevBtn = document.getElementById('btn-prev-section');
        const nextBtn = document.getElementById('btn-next-section');
        if (prevBtn) prevBtn.disabled = newIndex === 0;
        if (nextBtn) nextBtn.disabled = newIndex === this.sections.length - 1;

        // Restore section state if cached
        this.restoreSectionState(sectionId);

        console.log(`Switched to section: ${sectionId}`);
    }

    cacheSectionState(sectionId) {
        const panel = document.getElementById(`section-${sectionId}`);
        if (!panel) return;

        const state = {};

        // Cache radio selections
        panel.querySelectorAll('input[type="radio"]:checked').forEach(radio => {
            state[radio.name] = radio.value;
        });

        // Cache checkbox selections
        panel.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            state[`checkbox_${cb.value}`] = cb.checked;
        });

        // Cache text inputs
        panel.querySelectorAll('input[type="text"], textarea').forEach(input => {
            state[input.id] = input.value;
        });

        this.sectionDataCache[sectionId] = state;
    }

    restoreSectionState(sectionId) {
        const state = this.sectionDataCache[sectionId];
        if (!state) return;

        const panel = document.getElementById(`section-${sectionId}`);
        if (!panel) return;

        Object.entries(state).forEach(([key, value]) => {
            if (key.startsWith('checkbox_')) {
                const checkbox = panel.querySelector(`input[type="checkbox"][value="${key.replace('checkbox_', '')}"]`);
                if (checkbox) checkbox.checked = value;
            } else {
                const radio = panel.querySelector(`input[name="${key}"][value="${value}"]`);
                if (radio) radio.checked = true;

                const input = panel.querySelector(`#${key}`);
                if (input) input.value = value;
            }
        });
    }

    setupVisualHierarchyRanking() {
        const list = document.getElementById('visual-hierarchy-list');
        if (!list) return;

        list.addEventListener('dragstart', (e) => {
            if (e.target.classList.contains('ranking-item')) {
                e.target.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            }
        });

        list.addEventListener('dragend', (e) => {
            if (e.target.classList.contains('ranking-item')) {
                e.target.classList.remove('dragging');
            }
            this.updateRankNumbers();

            // Mark as manually edited when user reorders
            this.visualHierarchyManuallyEdited = true;
        });

        list.addEventListener('dragover', (e) => {
            e.preventDefault();
            const dragging = list.querySelector('.dragging');
            if (!dragging) return;

            const afterElement = this.getDragAfterElement(list, e.clientY);

            if (afterElement == null) {
                list.appendChild(dragging);
            } else {
                list.insertBefore(dragging, afterElement);
            }
        });
    }

    setupExtractedTextHierarchySync() {
        // Listen for changes to extracted text radio buttons
        document.addEventListener('change', (e) => {
            if (e.target.name === 'text-choice' && e.target.value !== 'manual') {
                const analysisIndex = parseInt(e.target.value);

                // Only auto-sync if user hasn't manually edited hierarchy
                if (!this.visualHierarchyManuallyEdited) {
                    this.populateVisualHierarchy(analysisIndex);
                }
            }
        });
    }

    getDragAfterElement(container, y) {
        const draggableElements = [...container.querySelectorAll('.ranking-item:not(.dragging)')];

        return draggableElements.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;

            if (offset < 0 && offset > closest.offset) {
                return { offset: offset, element: child };
            } else {
                return closest;
            }
        }, { offset: Number.NEGATIVE_INFINITY }).element;
    }

    updateRankNumbers() {
        const items = document.querySelectorAll('#visual-hierarchy-list .ranking-item');
        items.forEach((item, index) => {
            const rankSpan = item.querySelector('.rank-number');
            if (rankSpan) {
                rankSpan.textContent = `${index + 1}.`;
            }
        });
    }

    addRankingItem(value) {
        const list = document.getElementById('visual-hierarchy-list');
        if (!list) return;

        // Check if already exists
        const existing = list.querySelector(`[data-value="${CSS.escape(value)}"]`);
        if (existing) return;

        // Mark as manually edited when user adds items
        this.visualHierarchyManuallyEdited = true;

        const item = document.createElement('div');
        item.className = 'ranking-item';
        item.setAttribute('data-value', value);
        item.setAttribute('draggable', 'true');

        const currentRank = list.children.length + 1;

        item.innerHTML = `
            <span class="drag-handle">≡</span>
            <span class="rank-number">${currentRank}.</span>
            <span class="rank-label">${this.escapeHtml(value)}</span>
            <button class="remove-btn" aria-label="Remove">×</button>
        `;

        // Remove button handler
        item.querySelector('.remove-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            item.remove();
            this.updateRankNumbers();

            // Mark as manually edited when user removes items
            this.visualHierarchyManuallyEdited = true;
        });

        list.appendChild(item);
    }

    populateVisualHierarchy(analysisIndex = null) {
        const list = document.getElementById('visual-hierarchy-list');
        if (!list) return;

        list.innerHTML = '';

        // If no analysis index provided, aggregate from all (fallback)
        if (analysisIndex === null) {
            const allItems = new Set();
            this.currentAnalyses.forEach(analysis => {
                const items = analysis.raw_response?.image_details?.visual_hierarchy || [];
                items.forEach(item => {
                    if (item) allItems.add(item);
                });
            });

            Array.from(allItems).forEach(item => {
                this.addRankingItem(item);
            });

            this.visualHierarchySourceAnalysisIndex = null;
            this.updateVisualHierarchySource();
            return;
        }

        // Use specific analysis
        const analysis = this.currentAnalyses[analysisIndex];
        if (!analysis) return;

        const items = analysis.raw_response?.image_details?.visual_hierarchy || [];
        items.forEach(item => {
            if (item) {
                this.addRankingItem(item);
            }
        });

        // Update state
        this.visualHierarchySourceAnalysisIndex = analysisIndex;
        this.visualHierarchyManuallyEdited = false;
        this.updateVisualHierarchySource();
    }

    updateVisualHierarchySource() {
        const indicator = document.getElementById('visual-hierarchy-source');
        if (!indicator) return;

        if (this.visualHierarchySourceAnalysisIndex === null) {
            indicator.textContent = '';
            indicator.style.display = 'none';
            return;
        }

        const analysis = this.currentAnalyses[this.visualHierarchySourceAnalysisIndex];
        if (!analysis) {
            indicator.textContent = '';
            indicator.style.display = 'none';
            return;
        }

        indicator.style.display = 'block';

        if (this.visualHierarchyManuallyEdited) {
            indicator.textContent = `Originally from Analysis v${analysis.version} (${analysis.provider_used}) — manually edited`;
            indicator.className = 'hierarchy-source-indicator manual-edit';
        } else {
            indicator.textContent = `Using hierarchy from Analysis v${analysis.version} (${analysis.provider_used}) — selected in Extracted Text`;
            indicator.className = 'hierarchy-source-indicator auto-synced';
        }
    }

    getVisualHierarchyRanked() {
        const items = document.querySelectorAll('#visual-hierarchy-list .ranking-item');
        return Array.from(items).map(item => item.getAttribute('data-value'));
    }

    setupAutoSave() {
        this.autoSaveInterval = setInterval(() => {
            if (this.currentItem) {
                console.log('Auto-saving...');
                this.saveEntry(false, true);
            }
        }, 30000); // 30 seconds
    }

    clearManualFields() {
        const manualInputs = [
            'category-manual',
            'text-manual',
            'headline-manual',
            'summary-manual',
            'key-interest-manual',
            'likely-source-manual',
            'original-poster-manual',
            'audio-source-manual',
            'subcategory-add-input',
            'objects-add-input',
            'themes-add-input',
            'emotions-add-input',
            'vibes-add-input',
            'visual-hierarchy-add-input',
            'tagged-accounts-add-input',
            'location-tags-add-input',
            'hashtags-add-input'
        ];

        manualInputs.forEach(id => {
            const input = document.getElementById(id);
            if (input) input.value = '';
        });

        // Reset visual hierarchy state on item change
        this.visualHierarchySourceAnalysisIndex = null;
        this.visualHierarchyManuallyEdited = false;
    }

    async loadItem(offset) {
        this.showLoading(true);

        try {
            const response = await fetch(`/golden-dataset/items?offset=${offset}&limit=1&skip_reviewed=true`);
            const data = await response.json();

            if (data.items && data.items.length > 0) {
                this.currentItem = data.items[0];
                this.currentAnalyses = data.items[0].analyses || [];
                this.totalItems = data.total;
                this.reviewedCount = data.reviewed_count;
                this.currentOffset = offset;

                // Clear cache and manual fields on item change
                this.sectionDataCache = {};
                this.clearManualFields();

                await this.displayItem();
                this.updateProgress();

                // Reset to first section
                this.switchToSection(0);

                this.showLoading(false);
            } else {
                alert('No more items to review!');
                this.showLoading(false);
            }
        } catch (error) {
            console.error('Error loading item:', error);
            alert('Failed to load item. Please try again.');
            this.showLoading(false);
        }
    }

    async displayItem() {
        // Display image
        const imgElement = document.getElementById('main-image');
        imgElement.src = `/images/${this.currentItem.filename}`;

        document.getElementById('item-id-display').textContent = `Item ID: ${this.currentItem.item_id}`;

        // Populate all sections
        await this.populateCategories();
        await this.populateSubcategories();
        await this.populateExtractedText();
        await this.populateHeadlines();
        await this.populateSummaries();
        this.populateImageDetails();
        this.populateMetadata();
    }

    async populateCategories() {
        const container = document.getElementById('category-options');
        container.innerHTML = '';

        // Collect all unique categories
        const categories = new Set();
        this.currentAnalyses.forEach(analysis => {
            const category = analysis.raw_response?.category;
            if (category) categories.add(category);
        });

        // Create radio buttons
        Array.from(categories).forEach((category, index) => {
            const label = document.createElement('label');
            label.className = 'checkbox-item';
            label.innerHTML = `
                <input type="radio" name="category-choice" value="${category}" ${index === 0 ? 'checked' : ''}>
                <span>${category}</span>
            `;
            container.appendChild(label);
        });

        if (categories.size === 0) {
            container.innerHTML = '<p class="empty-state">No categories found</p>';
        }
    }

    async populateSubcategories() {
        const container = document.getElementById('subcategory-options');
        container.innerHTML = '';

        // Use Set to store normalized values
        const normalizedSubcategories = new Set();

        this.currentAnalyses.forEach(analysis => {
            const subs = analysis.raw_response?.subcategories || [];
            subs.forEach(sub => {
                if (sub && typeof sub === 'string') {
                    const normalized = this.normalizeForDeduplication(sub);

                    // Add normalized value if not empty
                    if (normalized) {
                        normalizedSubcategories.add(normalized);
                    }
                }
            });
        });

        // Create checkboxes using normalized values
        Array.from(normalizedSubcategories).forEach(subcategory => {
            this.addCheckboxItem('subcategory-options', subcategory);
        });

        if (normalizedSubcategories.size === 0) {
            container.innerHTML = '<p class="empty-state">No subcategories found</p>';
        }
    }

    async populateExtractedText() {
        const container = document.getElementById('text-options');
        container.innerHTML = '';

        if (this.currentAnalyses.length === 0) {
            container.innerHTML = '<p class="empty-state">No analyses available</p>';
            return;
        }

        // Extract all text arrays
        const textArrays = this.currentAnalyses.map(a =>
            a.raw_response?.image_details?.extracted_text || []
        );

        if (this.currentAnalyses.length === 1) {
            // Single analysis - no comparison
            this.createRadioOption(container, 'text-choice', 0,
                `Analysis v${this.currentAnalyses[0].version}`,
                this.currentAnalyses[0].provider_used,
                textArrays[0].join(', ') || 'N/A',
                null,
                true
            );
            return;
        }

        // Multiple analyses - calculate similarity
        try {
            const response = await fetch('/golden-dataset/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    item_id: this.currentItem.item_id,
                    field_type: 'extracted_text',
                    values: textArrays
                })
            });
            const similarity = await response.json();

            // Create array with index, value, and avgSim, then sort by score descending
            const sortedAnalyses = textArrays.map((textArray, idx) => ({
                index: idx,
                textArray: textArray,
                avgSim: this.calculateAvgSimilarity(similarity.similarity_matrix, idx)
            })).sort((a, b) => b.avgSim - a.avgSim);

            // Create options in sorted order, default to first (highest score)
            sortedAnalyses.forEach((item, displayIndex) => {
                this.createRadioOption(container, 'text-choice', item.index,
                    `Analysis v${this.currentAnalyses[item.index].version}`,
                    this.currentAnalyses[item.index].provider_used,
                    item.textArray.join(', ') || 'N/A',
                    item.avgSim,
                    displayIndex === 0 // Default to highest score
                );
            });
        } catch (error) {
            console.error('Error comparing text:', error);
            // Fallback: show without similarity
            textArrays.forEach((textArray, idx) => {
                this.createRadioOption(container, 'text-choice', idx,
                    `Analysis v${this.currentAnalyses[idx].version}`,
                    this.currentAnalyses[idx].provider_used,
                    textArray.join(', ') || 'N/A',
                    null,
                    idx === 0
                );
            });
        }
    }

    async populateHeadlines() {
        const container = document.getElementById('headline-options');
        container.innerHTML = '';

        if (this.currentAnalyses.length === 0) {
            container.innerHTML = '<p class="empty-state">No analyses available</p>';
            return;
        }

        const headlines = this.currentAnalyses.map(a => a.raw_response?.headline || '');

        if (this.currentAnalyses.length === 1) {
            this.createRadioOption(container, 'headline-choice', 0,
                `Analysis v${this.currentAnalyses[0].version}`,
                this.currentAnalyses[0].provider_used,
                headlines[0] || 'N/A',
                null,
                true
            );
            return;
        }

        try {
            const response = await fetch('/golden-dataset/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    item_id: this.currentItem.item_id,
                    field_type: 'headline',
                    values: headlines
                })
            });
            const similarity = await response.json();

            // Create array with index, value, and avgSim, then sort by score descending
            const sortedAnalyses = headlines.map((headline, idx) => ({
                index: idx,
                headline: headline,
                avgSim: this.calculateAvgSimilarity(similarity.similarity_matrix, idx)
            })).sort((a, b) => b.avgSim - a.avgSim);

            // Create options in sorted order, default to first (highest score)
            sortedAnalyses.forEach((item, displayIndex) => {
                this.createRadioOption(container, 'headline-choice', item.index,
                    `Analysis v${this.currentAnalyses[item.index].version}`,
                    this.currentAnalyses[item.index].provider_used,
                    item.headline || 'N/A',
                    item.avgSim,
                    displayIndex === 0 // Default to highest score
                );
            });
        } catch (error) {
            console.error('Error comparing headlines:', error);
            headlines.forEach((headline, idx) => {
                this.createRadioOption(container, 'headline-choice', idx,
                    `Analysis v${this.currentAnalyses[idx].version}`,
                    this.currentAnalyses[idx].provider_used,
                    headline || 'N/A',
                    null,
                    idx === 0
                );
            });
        }
    }

    async populateSummaries() {
        const container = document.getElementById('summary-options');
        container.innerHTML = '';

        if (this.currentAnalyses.length === 0) {
            container.innerHTML = '<p class="empty-state">No analyses available</p>';
            return;
        }

        const summaries = this.currentAnalyses.map(a => a.summary || '');

        if (this.currentAnalyses.length === 1) {
            this.createRadioOption(container, 'summary-choice', 0,
                `Analysis v${this.currentAnalyses[0].version}`,
                this.currentAnalyses[0].provider_used,
                summaries[0] || 'N/A',
                null,
                true
            );
            return;
        }

        try {
            const response = await fetch('/golden-dataset/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    item_id: this.currentItem.item_id,
                    field_type: 'summary',
                    values: summaries
                })
            });
            const similarity = await response.json();

            // Create array with index, value, and avgSim, then sort by score descending
            const sortedAnalyses = summaries.map((summary, idx) => ({
                index: idx,
                summary: summary,
                avgSim: this.calculateAvgSimilarity(similarity.similarity_matrix, idx)
            })).sort((a, b) => b.avgSim - a.avgSim);

            // Create options in sorted order, default to first (highest score)
            sortedAnalyses.forEach((item, displayIndex) => {
                this.createRadioOption(container, 'summary-choice', item.index,
                    `Analysis v${this.currentAnalyses[item.index].version}`,
                    this.currentAnalyses[item.index].provider_used,
                    item.summary || 'N/A',
                    item.avgSim,
                    displayIndex === 0 // Default to highest score
                );
            });
        } catch (error) {
            console.error('Error comparing summaries:', error);
            summaries.forEach((summary, idx) => {
                this.createRadioOption(container, 'summary-choice', idx,
                    `Analysis v${this.currentAnalyses[idx].version}`,
                    this.currentAnalyses[idx].provider_used,
                    summary || 'N/A',
                    null,
                    idx === 0
                );
            });
        }
    }

    populateImageDetails() {
        // Objects
        this.populateListField('objects-list', 'image_details', 'objects');

        // Themes
        this.populateListField('themes-list', 'image_details', 'themes');

        // Emotions
        this.populateListField('emotions-list', 'image_details', 'emotions');

        // Vibes
        this.populateListField('vibes-list', 'image_details', 'vibes');

        // Visual Hierarchy - Sync to selected extracted text analysis
        const selectedTextRadio = document.querySelector('input[name="text-choice"]:checked');
        if (selectedTextRadio && selectedTextRadio.value !== 'manual' && !this.visualHierarchyManuallyEdited) {
            const analysisIndex = parseInt(selectedTextRadio.value);
            this.populateVisualHierarchy(analysisIndex);
        } else {
            // Fallback to old behavior if no selection or manually edited
            this.populateVisualHierarchy();
        }

        // Key Interest (radio)
        this.populateRadioField('key-interest-options', 'key-interest-choice', 'image_details', 'key_interest');

        // Likely Source (radio)
        this.populateRadioField('likely-source-options', 'likely-source-choice', 'image_details', 'likely_source');
    }

    populateMetadata() {
        // Original Poster (radio)
        this.populateRadioField('original-poster-options', 'original-poster-choice', 'media_metadata', 'original_poster');

        // Tagged Accounts (list)
        this.populateListField('tagged-accounts-list', 'media_metadata', 'tagged_accounts');

        // Location Tags (list)
        this.populateListField('location-tags-list', 'media_metadata', 'location_tags');

        // Audio Source (radio)
        this.populateRadioField('audio-source-options', 'audio-source-choice', 'media_metadata', 'audio_source');

        // Hashtags (list)
        this.populateListField('hashtags-list', 'media_metadata', 'hashtags');
    }

    populateListField(containerId, parentField, fieldName) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';

        // Use Set to store normalized values
        const normalizedItems = new Set();

        this.currentAnalyses.forEach(analysis => {
            const items = analysis.raw_response?.[parentField]?.[fieldName] || [];
            items.forEach(item => {
                if (item && typeof item === 'string') {
                    const normalized = this.normalizeForDeduplication(item);

                    // Add normalized value if not empty
                    if (normalized) {
                        normalizedItems.add(normalized);
                    }
                }
            });
        });

        // Create checkboxes using normalized values
        Array.from(normalizedItems).forEach(item => {
            this.addCheckboxItem(containerId, item);
        });

        if (normalizedItems.size === 0) {
            container.innerHTML = '<p class="empty-state">None found</p>';
        }
    }

    populateRadioField(containerId, radioName, parentField, fieldName) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';

        const allValues = new Set();
        this.currentAnalyses.forEach(analysis => {
            const value = analysis.raw_response?.[parentField]?.[fieldName];
            if (value) allValues.add(value);
        });

        Array.from(allValues).forEach((value, index) => {
            const label = document.createElement('label');
            label.className = 'checkbox-item';
            label.innerHTML = `
                <input type="radio" name="${radioName}" value="${value}" ${index === 0 ? 'checked' : ''}>
                <span>${value}</span>
            `;
            container.appendChild(label);
        });

        if (allValues.size === 0) {
            container.innerHTML = '<p class="empty-state">None found</p>';
        }
    }

    createRadioOption(container, name, index, title, provider, content, similarity, isDefault) {
        const div = document.createElement('div');
        div.className = 'analysis-option';

        let badgeHtml = '';
        if (similarity !== null) {
            const badgeClass = this.getSimilarityClass(similarity);
            badgeHtml = `<span class="similarity-badge ${badgeClass}">${Math.round(similarity * 100)}%</span>`;
        }

        div.innerHTML = `
            <div class="option-header">
                <input type="radio" name="${name}" value="${index}" ${isDefault ? 'checked' : ''}>
                <strong>${title}</strong>
                <span class="text-muted">(${provider})</span>
                ${badgeHtml}
            </div>
            <div class="option-content">${content}</div>
        `;

        container.appendChild(div);
    }

    addCheckboxItem(containerId, value, checked = true) {
        const container = document.getElementById(containerId);

        // Normalize for comparison
        const normalizedValue = this.normalizeForDeduplication(value);

        // Check if normalized version already exists
        const existing = Array.from(container.querySelectorAll('input[type="checkbox"]'))
            .find(cb => this.normalizeForDeduplication(cb.value) === normalizedValue);
        if (existing) return;

        const label = document.createElement('label');
        label.className = 'checkbox-item';
        label.innerHTML = `
            <input type="checkbox" value="${value}" ${checked ? 'checked' : ''}>
            <span>${value}</span>
        `;
        container.appendChild(label);
    }

    calculateAvgSimilarity(matrix, index) {
        if (!matrix || !matrix[index]) return 0;
        const row = matrix[index];
        const sum = row.reduce((acc, val) => acc + val, 0);
        return sum / row.length;
    }

    getSimilarityClass(score) {
        if (score >= 0.9) return 'similarity-high';
        if (score >= 0.7) return 'similarity-medium';
        return 'similarity-low';
    }

    collectGoldenEntry() {
        // Collect all user selections
        const entry = {
            item_id: this.currentItem.item_id,
            reviewed_at: new Date().toISOString(),
            source_analyses_count: this.currentAnalyses.length,
            source_analysis_ids: this.currentAnalyses.map(a => a.id),

            // Category
            category: this.getRadioValue('category-choice', 'category-manual', 'category-manual-radio'),

            // Subcategories
            subcategories: this.getCheckedValues('subcategory-options'),

            // Headline
            headline: this.getRadioOrManual('headline-choice', 'headline-manual', 'headline-manual-radio',
                this.currentAnalyses.map(a => a.raw_response?.headline || '')),

            // Summary
            summary: this.getRadioOrManual('summary-choice', 'summary-manual', 'summary-manual-radio',
                this.currentAnalyses.map(a => a.summary || '')),

            // Media Metadata
            media_metadata: {
                original_poster: this.getRadioValue('original-poster-choice', 'original-poster-manual', 'original-poster-manual-radio') || '',
                tagged_accounts: this.getCheckedValues('tagged-accounts-list'),
                location_tags: this.getCheckedValues('location-tags-list'),
                audio_source: this.getRadioValue('audio-source-choice', 'audio-source-manual', 'audio-source-manual-radio') || '',
                hashtags: this.getCheckedValues('hashtags-list')
            },

            // Image Details
            image_details: {
                extracted_text: this.getExtractedText(),
                objects: this.getCheckedValues('objects-list'),
                themes: this.getCheckedValues('themes-list'),
                emotions: this.getCheckedValues('emotions-list'),
                vibes: this.getCheckedValues('vibes-list'),
                visual_hierarchy: this.getVisualHierarchyRanked(), // Ordered array by rank
                key_interest: this.getRadioValue('key-interest-choice', 'key-interest-manual', 'key-interest-manual-radio') || '',
                likely_source: this.getRadioValue('likely-source-choice', 'likely-source-manual', 'likely-source-manual-radio') || ''
            }
        };

        return entry;
    }

    getRadioValue(radioName, manualInputId, manualRadioId) {
        const manualRadio = document.getElementById(manualRadioId);
        if (manualRadio && manualRadio.checked) {
            return document.getElementById(manualInputId).value.trim();
        }

        const selected = document.querySelector(`input[name="${radioName}"]:checked`);
        if (selected && selected.value !== 'manual') {
            return selected.value;
        }

        return '';
    }

    getRadioOrManual(radioName, manualInputId, manualRadioId, analysisValues) {
        const manualRadio = document.getElementById(manualRadioId);
        if (manualRadio && manualRadio.checked) {
            return document.getElementById(manualInputId).value.trim();
        }

        const selected = document.querySelector(`input[name="${radioName}"]:checked`);
        if (selected && selected.value !== 'manual') {
            const index = parseInt(selected.value);
            return analysisValues[index] || '';
        }

        return '';
    }

    getCheckedValues(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return [];

        const checkboxes = container.querySelectorAll('input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }

    getExtractedText() {
        const manualRadio = document.getElementById('text-manual-radio');
        if (manualRadio && manualRadio.checked) {
            const text = document.getElementById('text-manual').value.trim();
            return text ? text.split(',').map(s => s.trim()).filter(s => s) : [];
        }

        const selected = document.querySelector('input[name="text-choice"]:checked');
        if (selected && selected.value !== 'manual') {
            const index = parseInt(selected.value);
            return this.currentAnalyses[index]?.raw_response?.image_details?.extracted_text || [];
        }

        return [];
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    normalizeForDeduplication(text) {
        if (!text || typeof text !== 'string') return '';

        return text
            .toLowerCase()              // Case-insensitive: "Pasta" → "pasta"
            .trim()                     // Remove whitespace: " pasta " → "pasta"
            .replace(/[^\w\s-]/g, '')   // Remove punctuation except hyphens: "it's" → "its"
            .replace(/\s+/g, ' ');      // Normalize multiple spaces: "a  b" → "a b"
    }

    async saveEntry(navigateNext = false, isAutoSave = false) {
        const entry = this.collectGoldenEntry();

        try {
            const response = await fetch('/golden-dataset/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(entry)
            });

            if (response.ok) {
                const result = await response.json();

                if (!isAutoSave) {
                    console.log('Saved successfully:', result);
                }

                // Update auto-save status
                const now = new Date().toLocaleTimeString();
                document.getElementById('auto-save-time').textContent = now;

                // Update reviewed count
                this.reviewedCount = result.total_golden_count;
                this.updateProgress();

                if (navigateNext) {
                    await this.nextItem();
                }
            } else {
                throw new Error('Save failed');
            }
        } catch (error) {
            console.error('Error saving entry:', error);
            if (!isAutoSave) {
                alert('Failed to save entry. Please try again.');
            }
        }
    }

    async nextItem() {
        await this.loadItem(this.currentOffset + 1);
    }

    async prevItem() {
        if (this.currentOffset > 0) {
            await this.loadItem(this.currentOffset - 1);
        }
    }

    updateProgress() {
        document.getElementById('current-index').textContent = this.currentOffset + 1;
        document.getElementById('total-items').textContent = this.totalItems;
        document.getElementById('reviewed-count').textContent = this.reviewedCount;

        const percentage = this.totalItems > 0 ? (this.reviewedCount / this.totalItems * 100) : 0;
        document.getElementById('progress-pct').textContent = percentage.toFixed(1);
        document.getElementById('progress-fill').style.width = `${percentage}%`;
    }

    showLoading(show) {
        const loading = document.getElementById('loading');
        const main = document.getElementById('main-content');

        if (show) {
            loading.classList.remove('hidden');
            main.classList.add('hidden');
        } else {
            loading.classList.add('hidden');
            main.classList.remove('hidden');
        }
    }
}

// Initialize app when DOM loads
document.addEventListener('DOMContentLoaded', () => {
    const app = new GoldenDatasetApp();
    app.init();
});
