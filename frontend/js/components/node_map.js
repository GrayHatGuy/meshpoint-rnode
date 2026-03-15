/**
 * Leaflet map with marker clustering for the local Mesh Point dashboard.
 * Displays captured nodes with protocol-colored markers.
 */
class NodeMap {
    constructor(containerId) {
        this._containerId = containerId;
        this._map = null;
        this._markerGroup = null;
        this._markers = {};
        this._initialized = false;
        this._init();
    }

    _init() {
        const el = document.getElementById(this._containerId);
        if (!el) return;

        this._map = L.map(this._containerId, {
            zoomControl: true,
            scrollWheelZoom: true,
        }).setView([44.0, -72.7], 10);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(this._map);

        this._markerGroup = L.markerClusterGroup({
            maxClusterRadius: 50,
            disableClusteringAtZoom: 13,
            spiderfyOnMaxZoom: true,
            showCoverageOnHover: false,
            iconCreateFunction: (cluster) => {
                const count = cluster.getChildCount();
                let size = 'small';
                if (count > 50) size = 'large';
                else if (count > 10) size = 'medium';
                return L.divIcon({
                    html: `<div><span>${count}</span></div>`,
                    className: `marker-cluster marker-cluster-${size}`,
                    iconSize: L.point(40, 40),
                });
            },
        });
        this._map.addLayer(this._markerGroup);
        this._initialized = true;
    }

    loadNodes(nodes, device) {
        if (!this._initialized) return;

        if (device && device.latitude && device.longitude) {
            this._map.setView([device.latitude, device.longitude], 11);
        }

        this._markerGroup.clearLayers();
        this._markers = {};

        for (const n of nodes) {
            const lat = n.latitude;
            const lon = n.longitude;
            if (lat == null || lon == null) continue;

            const isMeshtastic = (n.protocol || 'meshtastic') === 'meshtastic';
            const color = isMeshtastic ? '#06b6d4' : '#a855f7';

            const heard = n.last_heard || n.last_seen;
            const isRecent = heard && (Date.now() - new Date(heard).getTime()) < 60000;

            const marker = L.circleMarker([lat, lon], {
                radius: 6,
                fillColor: color,
                fillOpacity: 0.8,
                color: isRecent ? '#00ff88' : color,
                weight: isRecent ? 2 : 1,
                className: isRecent ? 'node-pulse' : '',
            });

            const name = n.long_name || n.name || n.node_id || '--';
            const rssi = n.rssi != null ? `${n.rssi} dBm` : '--';

            marker.bindPopup(
                `<strong>${this._esc(name)}</strong><br>` +
                `Protocol: ${n.protocol || 'meshtastic'}<br>` +
                `RSSI: ${rssi}`
            );

            this._markerGroup.addLayer(marker);
            this._markers[n.node_id] = marker;
        }
    }

    updateFromPacket(packet) {
        if (!packet.source_id || !this._initialized) return;
        const marker = this._markers[packet.source_id];
        if (marker) {
            marker.setStyle({ color: '#00ff88', weight: 2 });
            setTimeout(() => {
                const proto = (packet.protocol || 'meshtastic') === 'meshtastic' ? '#06b6d4' : '#a855f7';
                marker.setStyle({ color: proto, weight: 1 });
            }, 5000);
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    }
}
