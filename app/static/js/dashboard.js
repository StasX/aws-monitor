const search = document.querySelector('#resource-search');
if (search) {
    search.addEventListener('input', () => {
        const query = search.value.trim().toLocaleLowerCase();
        let matches = 0;
        document.querySelectorAll('.resource-panel').forEach(panel => {
            const rows = panel.querySelectorAll('[data-resource-row]');
            let visible = 0;
            rows.forEach(row => {
                row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
                if (!row.hidden) visible++;
            });
            matches += visible;
            const empty = panel.querySelector('.no-matches');
            if (empty) empty.hidden = !query || rows.length === 0 || visible > 0;
        });
        document.querySelector('#search-status').textContent = query
            ? `${matches} matching resource${matches === 1 ? '' : 's'} in the loaded inventory` : '';
    });
}


// Advance age from the server-provided duration, independent of browser clock skew.
const loadedAt = performance.now();
const ageLabels = [...document.querySelectorAll('[data-age-seconds]')];
function updateDataAges() {
    const elapsed = Math.floor((performance.now() - loadedAt) / 1000);
    ageLabels.forEach(label => {
        const seconds = Number(label.dataset.ageSeconds) + elapsed;
        const [value, unit] = seconds >= 86400 ? [Math.floor(seconds / 86400), 'day']
            : seconds >= 3600 ? [Math.floor(seconds / 3600), 'hour']
            : seconds >= 60 ? [Math.floor(seconds / 60), 'minute'] : [seconds, 'second'];
        label.textContent = `${value} ${unit}${value === 1 ? '' : 's'} ago`;
        const panel = label.closest('.resource-panel');
        if (panel && seconds >= Number(panel.dataset.maxAge) && !panel.dataset.expired) {
            panel.dataset.expired = 'true';
            panel.querySelector('.table-scroll')?.remove();
            panel.querySelector('.no-matches')?.remove();
            panel.querySelector('.error-message')?.remove();
            panel.querySelector('.count-badge').textContent = 'Unavailable';
            const status = panel.querySelector('.fetch-status');
            status.classList.add('stale');
            status.querySelector('span').textContent = 'Expired data';
            const message = document.createElement('div');
            message.className = 'error-message';
            message.setAttribute('role', 'alert');
            message.textContent = 'Previously fetched data is too old to display. Reload to check for fresh results.';
            panel.append(message);
            const card = document.querySelector(`.summary-card[href="#${panel.id}"]`);
            if (card) {
                card.querySelector('.resource-number').textContent = '\u2014';
                card.querySelector('.resource-description').textContent = 'Data unavailable';
            }
            const count = document.querySelector(`.nav-item[href="#${panel.id}"] .nav-count`);
            if (count) count.textContent = '\u2014';
            search?.dispatchEvent(new Event('input'));
        }
    });
}
updateDataAges();
if (ageLabels.length) setInterval(updateDataAges, 1000);
