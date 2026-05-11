/**
 * Radio tab — MeshCore Companion card.
 *
 * Renders the current state of the USB-attached MeshCore companion
 * (Heltec V3/V4, T-Beam, etc.) when one is plugged in. Empty-state
 * copy when not connected so users know it's not a missing card,
 * just an absent device.
 */
class RadioCompanionCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card');
    }

    render(config) {
        const mc = config.meshcore || {};
        if (!mc.connected) {
            this._renderOffline();
            return;
        }
        this._renderOnline(mc);
    }

    _renderOffline() {
        this._root.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">MeshCore Companion</h3>
                <span class="status-lamp status-lamp--off">
                    <span class="status-lamp__dot"></span>
                    <span class="status-lamp__label">NONE</span>
                </span>
            </div>
            <div class="companion-empty">
                Plug in a MeshCore USB companion (Heltec V3/V4, T-Beam, ...)
                and restart to enable MC messaging.
            </div>
        `;
    }

    _renderOnline(mc) {
        const radio = mc.radio || {};
        const name = this._api.escape(mc.companion_name || 'Connected');
        this._root.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">MeshCore Companion</h3>
                <span class="status-lamp status-lamp--ready">
                    <span class="status-lamp__dot"></span>
                    <span class="status-lamp__label">${name}</span>
                </span>
            </div>
            <div class="companion-grid">
                <div class="r-readout">
                    <span class="r-readout__label">Frequency</span>
                    <span class="r-readout__value">
                        ${this._fmtFreq(radio.frequency_mhz)}
                    </span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">Bandwidth</span>
                    <span class="r-readout__value">
                        ${this._fmtBw(radio.bandwidth_khz)}
                    </span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">SF</span>
                    <span class="r-readout__value">
                        ${this._fmtSf(radio.spreading_factor)}
                    </span>
                </div>
                <div class="r-readout">
                    <span class="r-readout__label">TX Power</span>
                    <span class="r-readout__value">
                        ${this._fmtTxPower(radio.tx_power)}
                    </span>
                </div>
            </div>
            <div class="r-card__actions">
                <button class="r-btn r-btn--secondary" id="r-mc-advert">
                    Send Advert
                </button>
                <button class="r-btn r-btn--secondary" id="r-mc-refresh">
                    Refresh
                </button>
            </div>
        `;
        this._wire();
    }

    _wire() {
        const advert = this._root.querySelector('#r-mc-advert');
        if (advert) {
            advert.addEventListener('click', async () => {
                advert.disabled = true;
                try {
                    const result = await this._api.post(
                        '/api/messages/advert',
                        {},
                    );
                    if (result && result.success) {
                        this._api.toast('Advert sent');
                    } else if (result) {
                        this._api.toast(
                            'Advert failed' + (result.error ? `: ${result.error}` : ''),
                        );
                    }
                } finally {
                    advert.disabled = false;
                }
            });
        }
        const refresh = this._root.querySelector('#r-mc-refresh');
        if (refresh) {
            refresh.addEventListener('click', () => this._api.refresh());
        }
    }

    _fmtFreq(v) { return v ? `${v} MHz` : '--'; }
    _fmtBw(v)   { return v ? `${v} kHz` : '--'; }
    _fmtSf(v)   { return v ? `SF${v}` : '--'; }
    _fmtTxPower(v) { return v != null ? `${v} dBm` : '--'; }
}

window.RadioCompanionCard = RadioCompanionCard;
