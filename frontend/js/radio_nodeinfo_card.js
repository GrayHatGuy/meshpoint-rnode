/**
 * Radio tab — NodeInfo Broadcast card.
 *
 * Shipped in v0.7.1. Three jobs:
 *   - Display a live countdown to the next NodeInfo broadcast.
 *   - Let the operator change the cadence via preset chips
 *     (5m / 30m / 1h / 3h / 6h / 12h / 24h / Off) or a numeric input.
 *   - Provide a "Send Now" button that pushes an immediate broadcast.
 *
 * Cadence is the single knob: setting it to 0 disables the broadcaster
 * entirely (the periodic loop, not TX itself). DMs and replies still
 * work in the disabled state. Cadence changes always require a service
 * restart to take effect, which the orchestrator surfaces via the
 * shared restart bar.
 */
class RadioNodeInfoCard {
    static PRESETS = [
        { minutes: 0,    label: 'Off', off: true },
        { minutes: 5,    label: '5m' },
        { minutes: 30,   label: '30m' },
        { minutes: 60,   label: '1h' },
        { minutes: 180,  label: '3h' },
        { minutes: 360,  label: '6h' },
        { minutes: 720,  label: '12h' },
        { minutes: 1440, label: '24h' },
    ];

    constructor(api) {
        this._api = api;
        this._root = null;
        this._timer = null;
        this._zeroSince = null;
        this._state = {
            interval_minutes: 0,
            running: false,
            last_sent_at: null,
            next_due_at: null,
        };
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card');
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">NodeInfo Broadcast</h3>
                <span class="status-lamp" id="r-ni-lamp">
                    <span class="status-lamp__dot"></span>
                    <span class="status-lamp__label">--</span>
                </span>
            </div>
            <div class="r-countdown">
                <div class="r-countdown__label">Next broadcast in</div>
                <div class="r-countdown__value" id="r-ni-countdown">--</div>
                <div class="r-countdown__sub">
                    <span class="r-countdown__sub-item" id="r-ni-last">
                        Last sent <span>--</span>
                    </span>
                    <span class="r-countdown__sub-sep">|</span>
                    <span class="r-countdown__sub-item">
                        Cadence <span id="r-ni-cadence">--</span>
                    </span>
                </div>
            </div>
            <div class="cadence">
                <div class="cadence__row">
                    <div class="cadence__chips" id="r-ni-chips"></div>
                    <div class="r-input-with-unit">
                        <input type="number" id="r-ni-input"
                               class="r-input r-input--mono r-input--narrow"
                               min="0" max="1440" />
                        <span class="r-input-with-unit__suffix">MIN</span>
                    </div>
                </div>
                <p class="r-hint">
                    0 disables periodic broadcasts (TX still works for DMs and replies).
                    Otherwise 5-1440 minutes. Cadence changes take effect on next service restart.
                </p>
            </div>
            <div class="r-card__actions">
                <button class="r-btn r-btn--secondary"
                        id="r-ni-send-now">Send Now</button>
                <button class="r-btn r-btn--primary"
                        id="r-ni-save">Save NodeInfo</button>
            </div>
        `;
        this._renderChips();
        this._wire();
    }

    render(config) {
        const ni = config.nodeinfo || {};
        this._state.interval_minutes = ni.interval_minutes || 0;
        this._state.running = !!ni.running;
        this._state.last_sent_at = _parseTimestamp(ni.last_sent_at);
        this._state.next_due_at = _parseTimestamp(ni.next_due_at);
        this._zeroSince = null;

        this._root.querySelector('#r-ni-input').value = String(this._state.interval_minutes);
        this._setActiveChip(this._state.interval_minutes);
        this._renderCadenceLabel();
        this._renderLamp();
        this._tick();
        this._startTimer();
    }

    destroy() {
        this._stopTimer();
    }

    _renderChips() {
        const chips = this._root.querySelector('#r-ni-chips');
        chips.innerHTML = RadioNodeInfoCard.PRESETS.map((p) => {
            const cls = p.off ? 'r-chip r-chip--off' : 'r-chip';
            return `<button type="button" class="${cls}" `
                + `data-minutes="${p.minutes}">${p.label}</button>`;
        }).join('');
    }

    _renderCadenceLabel() {
        const el = this._root.querySelector('#r-ni-cadence');
        const minutes = this._state.interval_minutes;
        el.textContent = minutes === 0 ? 'disabled' : _formatDuration(minutes * 60);
    }

    _renderLamp() {
        const lamp = this._root.querySelector('#r-ni-lamp');
        const label = lamp.querySelector('.status-lamp__label');
        lamp.classList.remove(
            'status-lamp--ready',
            'status-lamp--warn',
            'status-lamp--off',
        );
        if (this._state.interval_minutes === 0) {
            lamp.classList.add('status-lamp--off');
            label.textContent = 'PAUSED';
        } else if (this._state.running) {
            lamp.classList.add('status-lamp--ready');
            label.textContent = 'ACTIVE';
        } else {
            lamp.classList.add('status-lamp--warn');
            label.textContent = 'IDLE';
        }
    }

    _setActiveChip(minutes) {
        this._root.querySelectorAll('#r-ni-chips .r-chip').forEach((chip) => {
            const m = parseInt(chip.dataset.minutes, 10);
            chip.classList.toggle('r-chip--active', m === minutes);
        });
    }

    _wire() {
        this._root.querySelectorAll('#r-ni-chips .r-chip').forEach((chip) => {
            chip.addEventListener('click', (e) => {
                e.preventDefault();
                const minutes = parseInt(chip.dataset.minutes, 10);
                this._root.querySelector('#r-ni-input').value = String(minutes);
                this._state.interval_minutes = minutes;
                this._setActiveChip(minutes);
                this._renderCadenceLabel();
                this._renderLamp();
                this._tick();
            });
        });

        const input = this._root.querySelector('#r-ni-input');
        input.addEventListener('input', () => {
            const minutes = parseInt(input.value, 10);
            if (isNaN(minutes)) return;
            this._setActiveChip(minutes);
            if (minutes === 0 || (minutes >= 5 && minutes <= 1440)) {
                this._state.interval_minutes = minutes;
                this._renderCadenceLabel();
                this._renderLamp();
            }
        });

        this._root.querySelector('#r-ni-save').addEventListener(
            'click', async () => this._save(),
        );

        this._root.querySelector('#r-ni-send-now').addEventListener(
            'click', async () => this._sendNow(),
        );
    }

    async _save() {
        const minutes = parseInt(
            this._root.querySelector('#r-ni-input').value, 10,
        );
        if (isNaN(minutes) || (minutes !== 0 && (minutes < 5 || minutes > 1440))) {
            this._api.toast('Cadence must be 0 or 5-1440 minutes');
            return;
        }
        const result = await this._api.put(
            '/api/config/nodeinfo', { interval_minutes: minutes },
        );
        if (!result) return;
        this._api.toast(
            minutes === 0 ? 'NodeInfo broadcasts disabled' : 'Cadence saved',
        );
        if (result.restart_required) {
            this._api.signalRestart(
                'NodeInfo cadence changes take effect on next service restart.',
            );
        }
        await this._api.refresh();
    }

    async _sendNow() {
        const result = await this._api.post('/api/config/nodeinfo/send');
        if (!result) return;
        if (result.success) {
            this._api.toast('NodeInfo broadcast sent');
            this._state.last_sent_at = new Date();
            if (this._state.interval_minutes > 0) {
                this._state.next_due_at = new Date(
                    Date.now() + this._state.interval_minutes * 60 * 1000,
                );
            }
            this._tick();
        } else {
            this._api.toast(`Send failed: ${result.error || 'unknown'}`);
        }
    }

    _startTimer() {
        this._stopTimer();
        this._timer = setInterval(() => this._tick(), 1000);
    }

    _stopTimer() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
    }

    _tick() {
        const valueEl = this._root.querySelector('#r-ni-countdown');
        const lastEl = this._root.querySelector('#r-ni-last span');

        if (this._state.interval_minutes === 0) {
            valueEl.textContent = 'PAUSED';
            valueEl.style.opacity = '0.45';
            lastEl.textContent = this._state.last_sent_at
                ? _formatAgo(_secondsAgo(this._state.last_sent_at))
                : 'never';
            return;
        }

        valueEl.style.opacity = '1';
        const next = this._state.next_due_at;
        if (!next) {
            valueEl.textContent = 'awaiting first send';
        } else {
            const remaining = Math.max(
                0, Math.floor((next.getTime() - Date.now()) / 1000),
            );
            valueEl.textContent = remaining === 0
                ? 'broadcasting...'
                : _formatCountdown(remaining);
            if (remaining === 0) {
                this._scheduleBroadcastRefresh();
            }
        }

        lastEl.textContent = this._state.last_sent_at
            ? _formatAgo(_secondsAgo(this._state.last_sent_at))
            : 'never';
    }

    _scheduleBroadcastRefresh() {
        if (this._zeroSince !== null) return;
        this._zeroSince = Date.now();
        const refreshOnce = async () => {
            try {
                await this._api.refresh();
            } catch (_e) { /* swallow; backstop will retry */ }
        };
        // Wait ~2.5s for the backend broadcaster to complete TX (~700ms
        // airtime + Lambda/handler overhead), then re-fetch state. A
        // backstop refresh at +5s catches the rare case where the first
        // call races the backend's _last_sent_at write.
        setTimeout(refreshOnce, 2500);
        setTimeout(() => {
            if (this._zeroSince !== null) refreshOnce();
        }, 5000);
    }
}

function _parseTimestamp(value) {
    if (!value) return null;
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
}

function _secondsAgo(date) {
    return Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
}

function _formatCountdown(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
        return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
    }
    if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
    return `${s}s`;
}

function _formatAgo(seconds) {
    if (seconds < 60) return `${seconds} sec ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return m > 0 ? `${h} hr ${m} min ago` : `${h} hr ago`;
}

function _formatDuration(seconds) {
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
    const h = seconds / 3600;
    return Number.isInteger(h) ? `${h} hr` : `${h.toFixed(1)} hr`;
}

window.RadioNodeInfoCard = RadioNodeInfoCard;
