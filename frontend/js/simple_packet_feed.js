/**
 * Simple live packet feed for the local Mesh Point dashboard.
 * Renders incoming packets via WebSocket with expand-on-click.
 */
class SimplePacketFeed {
    constructor(tbodyId, maxRows) {
        this._tbody = document.getElementById(tbodyId);
        this._maxRows = maxRows || 200;
        this._count = 0;
    }

    addPacket(packet) {
        const tr = document.createElement('tr');
        tr.classList.add('packet-row--new');
        tr.addEventListener('animationend', () => tr.classList.remove('packet-row--new'));

        const time = packet.rx_time
            ? new Date(packet.rx_time * 1000).toLocaleTimeString()
            : new Date().toLocaleTimeString();

        const srcShort = packet.source_id
            ? `!${packet.source_id.substring(0, 8)}`
            : '--';

        const rssi = packet.rssi != null ? `${Number(packet.rssi).toFixed(0)}` : '--';
        const snr = packet.snr != null ? `${Number(packet.snr).toFixed(1)}` : '--';
        const type = packet.packet_type || '--';
        const details = this._summarize(packet);

        tr.innerHTML = `
            <td>${time}</td>
            <td style="font-family:var(--font-mono);font-size:0.7rem;">${srcShort}</td>
            <td>${type}</td>
            <td style="font-family:var(--font-mono);">${rssi}</td>
            <td style="font-family:var(--font-mono);">${snr}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${this._esc(details)}</td>
        `;

        tr.addEventListener('click', () => this._toggleDetail(tr, packet));

        this._tbody.prepend(tr);
        this._count++;

        const countEl = document.getElementById('packet-count');
        if (countEl) countEl.textContent = this._count;

        while (this._tbody.children.length > this._maxRows * 2) {
            this._tbody.removeChild(this._tbody.lastChild);
        }
    }

    _toggleDetail(tr, packet) {
        const next = tr.nextElementSibling;
        if (next && next.classList.contains('packet-detail-row')) {
            next.remove();
            return;
        }

        const prev = this._tbody.querySelector('.packet-detail-row');
        if (prev) prev.remove();

        const detailTr = document.createElement('tr');
        detailTr.classList.add('packet-detail-row');
        const td = document.createElement('td');
        td.colSpan = 6;
        td.style.cssText = 'padding:0.5rem 0.75rem;font-size:0.7rem;font-family:var(--font-mono);color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;background:var(--bg-secondary);';

        const payload = packet.decoded_payload;
        if (payload && typeof payload === 'object') {
            td.textContent = JSON.stringify(payload, null, 2);
        } else {
            td.textContent = `Source: ${packet.source_id || '--'}\nType: ${packet.packet_type || '--'}\nRSSI: ${packet.rssi || '--'} dBm\nSNR: ${packet.snr || '--'} dB`;
        }

        detailTr.appendChild(td);
        tr.after(detailTr);
    }

    _summarize(packet) {
        const p = packet.decoded_payload;
        if (!p) return '--';

        switch (packet.packet_type) {
            case 'text': return p.text || '--';
            case 'position': {
                const parts = [];
                if (p.latitude != null) parts.push(`${p.latitude.toFixed(4)}`);
                if (p.longitude != null) parts.push(`${p.longitude.toFixed(4)}`);
                if (p.altitude != null) parts.push(`alt ${p.altitude}m`);
                return parts.join(', ') || '--';
            }
            case 'nodeinfo':
                return [p.long_name, p.short_name, p.hw_model].filter(Boolean).join(' ') || '--';
            case 'telemetry': {
                const parts = [];
                if (p.battery_level != null) parts.push(`batt=${p.battery_level}%`);
                if (p.voltage != null) parts.push(`${Number(p.voltage).toFixed(1)}V`);
                if (p.temperature != null) parts.push(`${Number(p.temperature).toFixed(0)}°C`);
                return parts.join(' ') || '--';
            }
            default: return '--';
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    }
}
