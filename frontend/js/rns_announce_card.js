/**
 * Radio tab - Reticulum Announce Broadcast card (STUB).
 *
 * Mirror of the Meshtastic NodeInfo Broadcast card. Reticulum's
 * equivalent is the periodic identity ANNOUNCE that LXMF nodes send
 * to advertise their destination on the network. The actual transmit
 * loop requires a Reticulum identity (Tier 2 work) and a TX path
 * through the SX1302 with sync 0x42 (uses the per-packet TX sync
 * override added in Step 2).
 *
 * For now this card renders the layout and a clear "Tier 2 required"
 * notice so operators understand what's coming and how the setting
 * will surface once the backend lands.
 */
class RnsAnnounceCard {
    static PRESETS = [
        { minutes: 0,    label: 'Off', off: true },
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
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card');
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Announce Broadcast</h3>
                <span class="status-lamp status-lamp--off" id="rns-ann-lamp">
                    <span class="status-lamp__dot"></span>
                    <span class="status-lamp__label">DISABLED</span>
                </span>
            </div>
            <div class="r-countdown">
                <div class="r-countdown__label">Next announce in</div>
                <div class="r-countdown__value" id="rns-ann-countdown">--</div>
                <div class="r-countdown__sub">
                    <span class="r-countdown__sub-item">
                        Last sent <span>--</span>
                    </span>
                    <span class="r-countdown__sub-sep">|</span>
                    <span class="r-countdown__sub-item">
                        Interval <span id="rns-ann-interval-label">--</span>
                    </span>
                </div>
            </div>
            <div class="interval-chips">
                <div class="interval-chips__row">
                    <div class="interval-chips__chips" id="rns-ann-chips"></div>
                    <div class="r-input-with-unit">
                        <input type="number" id="rns-ann-input"
                               class="r-input r-input--mono r-input--narrow"
                               min="0" max="1440" disabled />
                        <span class="r-input-with-unit__suffix">MIN</span>
                    </div>
                </div>
                <p class="r-hint">
                    Reticulum announce broadcasts identify this node to the
                    LXMF network so peers can route messages to it. Requires
                    a provisioned Reticulum identity (Tier 2). Until then
                    this Meshpoint participates in receive-only mode.
                </p>
            </div>
            <div class="r-card__actions">
                <button class="r-btn r-btn--secondary"
                        id="rns-ann-send-now" disabled
                        title="Available in Tier 2">Send Now</button>
                <button class="r-btn r-btn--primary"
                        id="rns-ann-save" disabled
                        title="Available in Tier 2">Save Announce</button>
            </div>
        `;
        this._renderChips();
    }

    render(_config) {
        // No backend wiring yet; chip selection is read-only.
        // When Tier 2 lands, hook into config.reticulum.announce or
        // similar and mirror the RadioNodeInfoCard timer logic.
    }

    _renderChips() {
        const host = this._root.querySelector('#rns-ann-chips');
        host.innerHTML = RnsAnnounceCard.PRESETS.map((p) => `
            <button class="interval-chip"
                    data-min="${p.minutes}" disabled
                    title="Available in Tier 2">${p.label}</button>
        `).join('');
    }
}

window.RnsAnnounceCard = RnsAnnounceCard;
