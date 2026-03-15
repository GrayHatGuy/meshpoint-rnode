/**
 * Simple node list for the local Mesh Point dashboard.
 * Shows nodes with name, protocol badge, RSSI, and time ago.
 */
class SimpleNodeList {
    constructor(containerId) {
        this._container = document.getElementById(containerId);
        this._nodes = [];
        this._searchQuery = '';
        this._initSearch();
    }

    _initSearch() {
        const input = document.getElementById('node-search');
        if (!input) return;
        let timer;
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                this._searchQuery = input.value.trim().toLowerCase();
                this._render();
            }, 200);
        });
    }

    loadNodes(nodes) {
        this._nodes = nodes.sort((a, b) => {
            const aTime = a.last_heard || a.last_seen || '';
            const bTime = b.last_heard || b.last_seen || '';
            return bTime.localeCompare(aTime);
        });
        this._render();
    }

    updateFromPacket(packet) {
        if (!packet.source_id) return;
        const existing = this._nodes.find(n => n.node_id === packet.source_id);
        if (existing) {
            existing.last_heard = new Date().toISOString();
            if (packet.rssi != null) existing.rssi = packet.rssi;
        }
        this._render();
    }

    _render() {
        let filtered = this._nodes;
        if (this._searchQuery) {
            filtered = filtered.filter(n => {
                const name = (n.long_name || n.name || '').toLowerCase();
                const id = (n.node_id || '').toLowerCase();
                return name.includes(this._searchQuery) || id.includes(this._searchQuery);
            });
        }

        if (filtered.length === 0) {
            this._container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);font-size:0.8rem;">No nodes found</div>';
            return;
        }

        this._container.innerHTML = filtered.map(n => {
            const name = this._esc(n.long_name || n.name || n.node_id || '--');
            const proto = n.protocol || 'meshtastic';
            const rssi = n.rssi != null ? `${n.rssi} dBm` : '--';
            const heard = n.last_heard || n.last_seen;
            const ago = heard ? this._timeAgo(heard) : '--';

            return `<div class="node-item">
                <div>
                    <span class="node-item__name">${name}</span>
                    <span class="node-item__proto node-item__proto--${proto}">${proto}</span>
                </div>
                <div class="node-item__meta">${rssi} &middot; ${ago}</div>
            </div>`;
        }).join('');
    }

    _timeAgo(isoStr) {
        const diff = Date.now() - new Date(isoStr).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'now';
        if (mins < 60) return `${mins}m`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h`;
        return `${Math.floor(hours / 24)}d`;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    }
}
