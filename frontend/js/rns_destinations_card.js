/**
 * Radio tab - Reticulum Channels card.
 *
 * Titled "Channels" to mirror the Meshtastic Channels card. In
 * Reticulum terminology these rows are *destinations* (identity
 * hashes), but presenting them under the "Channels" label keeps the
 * UI parallel to the MT side and matches operator expectations.
 *
 * Until Tier 2 lands the local destination row is a stub. The peer
 * rows below it are populated from the existing nodes table filtered
 * to protocol = "reticulum", so they reflect what we have actually
 * heard on the air. This gives the operator something useful to look
 * at today while still mirroring the Channels card's visual layout.
 */
class RnsDestinationsCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card');
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Channels</h3>
                <span class="r-card__subtitle" id="rns-dest-subtitle">
                    -- discovered
                </span>
            </div>
            <table class="ch-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Name</th>
                        <th>Destination Hash</th>
                        <th>Last Heard</th>
                        <th>RSSI</th>
                    </tr>
                </thead>
                <tbody id="rns-dest-body"></tbody>
            </table>
            <div class="r-card__actions">
                <button class="r-btn r-btn--secondary"
                        id="rns-dest-refresh">Refresh</button>
                <button class="r-btn r-btn--primary"
                        id="rns-dest-add" disabled
                        title="Available in Tier 2">+ Add Destination</button>
            </div>
            <p class="r-hint">
                Reticulum's "channels" are destinations: each row is an
                identity hash heard on the air. The local node will appear
                here once Tier 2 provisions a Reticulum identity for this
                Meshpoint.
            </p>
        `;
        this._wire();
    }

    render(_config) {
        // Initial render - kick off a peers fetch.
        this._loadPeers();
    }

    _wire() {
        this._root.querySelector('#rns-dest-refresh').addEventListener(
            'click', () => this._loadPeers(),
        );
    }

    async _loadPeers() {
        const body = this._root.querySelector('#rns-dest-body');
        const subtitle = this._root.querySelector('#rns-dest-subtitle');
        const localRow = this._renderLocalRow();

        try {
            // Reuse the existing /api/nodes endpoint and filter client-side
            // to reticulum protocol. Saves a backend route until Tier 2.
            const res = await fetch('/api/nodes?protocol=reticulum&limit=50');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const peers = Array.isArray(data) ? data : (data.nodes || []);

            const peerRows = peers.map((n, i) => this._peerRow(n, i + 1)).join('');
            body.innerHTML = localRow + peerRows;
            subtitle.textContent = `${peers.length} peer(s) heard`;
        } catch (e) {
            body.innerHTML = localRow + `
                <tr><td colspan="5" class="ch-table__hash">
                    No peer data yet. Reticulum nodes appear here as their
                    ANNOUNCE frames are received.
                </td></tr>
            `;
            subtitle.textContent = 'no peers';
        }
    }

    _renderLocalRow() {
        // Stub local-identity row. Reticulum hash = "--" until Tier 2.
        return `
            <tr class="ch-table__row" data-local="1">
                <td class="ch-table__idx">0</td>
                <td><em>(this Meshpoint)</em></td>
                <td class="ch-table__hash">-- (Tier 2)</td>
                <td>--</td>
                <td>--</td>
            </tr>
        `;
    }

    _peerRow(node, idx) {
        const name = node.long_name || node.short_name || '';
        const hash = node.node_id || '--';
        const lastHeard = this._fmtTime(node.last_heard);
        const rssi = (node.signal && node.signal.rssi !== undefined)
            ? `${node.signal.rssi.toFixed(1)} dBm`
            : '--';
        return `
            <tr class="ch-table__row">
                <td class="ch-table__idx">${idx}</td>
                <td>${this._esc(name) || '<em>unknown</em>'}</td>
                <td class="ch-table__hash" title="${this._esc(hash)}">
                    ${this._esc(hash.length > 16 ? hash.slice(0, 16) + '...' : hash)}
                </td>
                <td>${lastHeard}</td>
                <td>${rssi}</td>
            </tr>
        `;
    }

    _fmtTime(iso) {
        if (!iso) return '--';
        try {
            const t = new Date(iso);
            const ago = Math.floor((Date.now() - t.getTime()) / 1000);
            if (ago < 60) return `${ago}s ago`;
            if (ago < 3600) return `${Math.floor(ago / 60)}m ago`;
            if (ago < 86400) return `${Math.floor(ago / 3600)}h ago`;
            return `${Math.floor(ago / 86400)}d ago`;
        } catch (e) {
            return '--';
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.RnsDestinationsCard = RnsDestinationsCard;
