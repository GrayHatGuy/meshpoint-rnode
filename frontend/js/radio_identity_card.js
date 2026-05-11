/**
 * Radio tab — Identity card.
 *
 * Renders the Meshpoint's broadcast identity (long name, short name,
 * Meshtastic node ID) plus a hint explaining where the node ID came
 * from (pinned in local.yaml, auto-derived from device_id, or random
 * fallback). Identity edits always require a service restart to take
 * effect because they're baked into NodeInfo broadcasts at boot.
 */
class RadioIdentityCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card');
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Identity</h3>
                <span class="r-badge r-badge--mono"
                      id="r-ident-source">--</span>
            </div>
            <div class="r-ident">
                <div class="r-ident__row">
                    <label class="r-ident__label" for="r-long-name">Long</label>
                    <input class="r-input" id="r-long-name"
                           maxlength="36"
                           placeholder="Meshpoint" />
                </div>
                <div class="r-ident__row">
                    <label class="r-ident__label" for="r-short-name">Short</label>
                    <input class="r-input r-input--short" id="r-short-name"
                           maxlength="4"
                           placeholder="MPNT" />
                </div>
                <div class="r-ident__row">
                    <label class="r-ident__label" for="r-node-id">Node ID</label>
                    <input class="r-input r-input--mono r-input--narrow"
                           id="r-node-id" maxlength="10"
                           placeholder="!aabbccdd" />
                </div>
                <div class="r-ident__hint" id="r-ident-hint"></div>
            </div>
            <div class="r-card__actions">
                <button class="r-btn r-btn--primary"
                        id="r-save-identity">Save Identity</button>
            </div>
        `;
        this._wire();
    }

    render(config) {
        const tx = config.transmit || {};
        this._root.querySelector('#r-long-name').value = tx.long_name || '';
        this._root.querySelector('#r-short-name').value = tx.short_name || '';
        this._root.querySelector('#r-node-id').value = tx.node_id_hex || '';

        const source = tx.node_id_source;
        const sourceLabel = this._sourceLabel(source);
        const badge = this._root.querySelector('#r-ident-source');
        badge.textContent = sourceLabel;

        const hint = this._root.querySelector('#r-ident-hint');
        hint.textContent = this._sourceHint(source);
    }

    _sourceLabel(source) {
        if (source === 'config') return 'PINNED';
        if (source === 'derived') return 'AUTO';
        if (source === 'random') return 'RANDOM';
        return 'UNSET';
    }

    _sourceHint(source) {
        if (source === 'config') {
            return 'Pinned in local.yaml. Edit above to override.';
        }
        if (source === 'derived') {
            return 'Auto-derived from device ID. '
                + 'Stable across reboots; saving below pins the value to local.yaml.';
        }
        if (source === 'random') {
            return 'Random fallback (no device ID configured). '
                + 'Set a value above and save for a stable identity.';
        }
        return '';
    }

    _wire() {
        this._root.querySelector('#r-save-identity').addEventListener(
            'click', async () => {
                const longName = this._root.querySelector('#r-long-name').value.trim();
                const shortName = this._root.querySelector('#r-short-name').value.trim();
                const nodeIdRaw = this._root.querySelector('#r-node-id').value.trim();

                const payload = { long_name: longName, short_name: shortName };

                if (nodeIdRaw) {
                    const hex = nodeIdRaw.replace(/^!/, '');
                    if (!/^[0-9a-fA-F]{1,8}$/.test(hex)) {
                        this._api.toast('Node ID must be 1-8 hex characters');
                        return;
                    }
                    const parsed = parseInt(hex, 16);
                    if (parsed > 0) payload.node_id = parsed;
                }

                const result = await this._api.put(
                    '/api/config/identity', payload,
                );
                if (result) {
                    this._api.toast('Identity saved');
                    if (result.restart_required) {
                        this._api.signalRestart(
                            'Identity changes take effect on next service restart.',
                        );
                    }
                    await this._api.refresh();
                }
            },
        );
    }
}

window.RadioIdentityCard = RadioIdentityCard;
