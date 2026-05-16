/**
 * Radio tab - Reticulum Identity card (STUB).
 *
 * Mirrors the Meshtastic identity card layout but is read-only / stub
 * pending Tier 2 work that gives the Pi a real Reticulum identity
 * (Ed25519 + X25519 keypair persisted to data/reticulum/identity).
 *
 * Until Tier 2 lands, this card shows:
 *   - Display Name: from config.transmit.long_name (operator-visible
 *     name; will be the LXMF display name once a real identity exists)
 *   - Destination Hash: "--" (no identity yet, so no hash to show)
 *   - LXMF Address: "--" (LXMF requires an identity)
 *   - A clear "Tier 2 required" notice
 */
class RnsIdentityCard {
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
                <span class="r-badge r-badge--mono r-badge--muted"
                      id="rns-ident-source">STUB</span>
            </div>
            <div class="r-ident">
                <div class="r-ident__row">
                    <label class="r-ident__label" for="rns-display-name">Display Name</label>
                    <input class="r-input" id="rns-display-name"
                           maxlength="36"
                           placeholder="Meshpoint" disabled />
                </div>
                <div class="r-ident__row">
                    <label class="r-ident__label" for="rns-dest-hash">Dest Hash</label>
                    <input class="r-input r-input--mono" id="rns-dest-hash"
                           placeholder="-- (Tier 2)" disabled />
                </div>
                <div class="r-ident__row">
                    <label class="r-ident__label" for="rns-lxmf-addr">LXMF Addr</label>
                    <input class="r-input r-input--mono" id="rns-lxmf-addr"
                           placeholder="-- (Tier 2)" disabled />
                </div>
                <div class="r-ident__hint" id="rns-ident-hint">
                    Reticulum identity (Ed25519 + X25519 keypair) and LXMF
                    address are not yet provisioned. Tier 2 will generate
                    and persist a keypair to data/reticulum/identity, after
                    which this Meshpoint becomes a full Reticulum node with
                    its own discoverable address.
                </div>
            </div>
            <div class="r-card__actions">
                <button class="r-btn r-btn--primary"
                        id="rns-save-identity" disabled
                        title="Available in Tier 2">Save Identity</button>
            </div>
        `;
    }

    render(config) {
        const tx = config.transmit || {};
        this._root.querySelector('#rns-display-name').value = tx.long_name || '';
    }
}

window.RnsIdentityCard = RnsIdentityCard;
