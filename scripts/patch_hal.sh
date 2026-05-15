#!/usr/bin/env bash
#
# Patch and recompile the SX1302 HAL.
#
# Two idempotent patches are applied in sequence:
#
#  1) TX sync word patch (legacy): the stock HAL hardcodes TX sync words to
#     LoRaWAN values (0x12/0x34). This patch makes TX use the sync word
#     configured for RX (e.g. 0x2B for Meshtastic).
#
#  2) Pair-sync + TX-override patch (Step 2): adds two new C symbols:
#       sx1302_lora_syncword_pair(uint8_t multi_sf_sw, uint8_t single_sf_sw)
#         -> writes the multi-SF demod group sync word independently of
#            the single-SF (LoRa Service) demod sync word, enabling
#            simultaneous capture of two protocols at different sync words
#            (e.g. Meshtastic on single-SF + Reticulum on multi-SF).
#       sx1302_set_tx_syncword(uint8_t sw)
#         -> overrides the next TX packet's sync word for per-packet TX
#            of multiple protocols. Updates the same sx1302_tx_sw_peak1/2
#            globals the TX path reads from.
#
# Run once after updating to enable Step 2 features. Both patches are
# idempotent and skip if already applied. Requires HAL source at
# /opt/sx1302_hal (preserved from install.sh).
#
# Usage:
#   sudo /opt/meshpoint/scripts/patch_hal.sh
#

set -euo pipefail

HAL_SRC="/opt/sx1302_hal/libloragw/src/loragw_sx1302.c"
HAL_DIR="/opt/sx1302_hal"
LIB_DEST="/usr/local/lib/libloragw.so"

info()  { echo "[patch_hal] $*"; }
fail()  { echo "[patch_hal] ERROR: $*" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
    fail "Must run as root (sudo)"
fi

if [ ! -f "$HAL_SRC" ]; then
    fail "HAL source not found at $HAL_SRC. Run install.sh for a fresh build."
fi

if grep -q "PEAK1_POS.*sx1302_tx_sw_peak1" "$HAL_SRC"; then
    info "TX sync word patch already applied"
else
    info "Applying TX sync word patch..."
    python3 - "$HAL_SRC" <<'TXPATCH'
import re, sys
from pathlib import Path

f = Path(sys.argv[1])
s = f.read_text()

if "sx1302_tx_sw_peak1" not in s:
    s = s.replace(
        "int sx1302_lora_syncword(",
        "static uint8_t sx1302_tx_sw_peak1 = 2;\n"
        "static uint8_t sx1302_tx_sw_peak2 = 4;\n\n"
        "int sx1302_lora_syncword(",
        1
    )

if "sx1302_tx_sw_peak1 = sw_reg1" not in s:
    s = s.replace(
        "    sw_reg2 = 4;\n    }\n\n    err |= lgw_reg_w("
        "SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5",
        "    sw_reg2 = 4;\n    }\n\n"
        "    sx1302_tx_sw_peak1 = sw_reg1;\n"
        "    sx1302_tx_sw_peak2 = sw_reg2;\n\n"
        "    err |= lgw_reg_w("
        "SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5",
        1
    )

tx_re = re.compile(
    r'([ \t]*)/\* Syncword \*/\n'
    r'[ \t]*if \(\(lwan_public == false\)[^\n]*\{\n'
    r'[^\n]*Setting LoRa syncword 0x12[^\n]*\n'
    r'[^\n]*FRAME_SYNCH_0_PEAK1_POS[^\n]*,\s*2\)[^\n]*\n'
    r'[^\n]*CHECK_ERR[^\n]*\n'
    r'[^\n]*FRAME_SYNCH_1_PEAK2_POS[^\n]*,\s*4\)[^\n]*\n'
    r'[^\n]*CHECK_ERR[^\n]*\n'
    r'[ \t]*\} else \{[^\n]*\n'
    r'[^\n]*Setting LoRa syncword 0x34[^\n]*\n'
    r'[^\n]*FRAME_SYNCH_0_PEAK1_POS[^\n]*,\s*6\)[^\n]*\n'
    r'[^\n]*CHECK_ERR[^\n]*\n'
    r'[^\n]*FRAME_SYNCH_1_PEAK2_POS[^\n]*,\s*8\)[^\n]*\n'
    r'[^\n]*CHECK_ERR[^\n]*\n'
    r'[ \t]*\}'
)

def repl(m):
    ws = m.group(1)
    return (
        f"{ws}/* Syncword */\n"
        f"{ws}err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_0_PEAK1_POS"
        f"(pkt_data->rf_chain), sx1302_tx_sw_peak1);\n"
        f"{ws}CHECK_ERR(err);\n"
        f"{ws}err = lgw_reg_w(SX1302_REG_TX_TOP_FRAME_SYNCH_1_PEAK2_POS"
        f"(pkt_data->rf_chain), sx1302_tx_sw_peak2);\n"
        f"{ws}CHECK_ERR(err);"
    )

new_s, n = tx_re.subn(repl, s, count=1)
if n == 0:
    print("FAIL: TX sync word section not found")
    sys.exit(1)

Path(sys.argv[1]).write_text(new_s)
print("OK: all patches applied")
TXPATCH
fi

# ── Step 2: pair-sync + TX-override patch ──────────────────────────────
if grep -q "sx1302_lora_syncword_pair" "$HAL_SRC"; then
    info "Step 2 pair-sync patch already applied"
else
    info "Applying Step 2 pair-sync + TX-override patch..."
    python3 - "$HAL_SRC" <<'STEP2PATCH'
import sys
from pathlib import Path

f = Path(sys.argv[1])
s = f.read_text()

# Sanity: the legacy TX sync word patch must already be in place
# (it adds the sx1302_tx_sw_peak1/2 globals we extend below).
if "sx1302_tx_sw_peak1" not in s:
    print("FAIL: legacy TX sync word patch missing; run install.sh first")
    sys.exit(1)

# Insert the two new functions immediately AFTER the existing
# sx1302_lora_syncword body. The cleanest anchor is the closing
# brace + blank line that follows it. We find the function header
# and walk to its matching close brace.
anchor = "int sx1302_lora_syncword("
idx = s.find(anchor)
if idx < 0:
    print("FAIL: sx1302_lora_syncword definition not found")
    sys.exit(1)

# Walk from anchor to find matching close brace at column 0
depth = 0
i = s.find("{", idx)
if i < 0:
    print("FAIL: opening brace of sx1302_lora_syncword not found")
    sys.exit(1)
end = -1
while i < len(s):
    c = s[i]
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0:
            end = i + 1
            break
    i += 1
if end < 0:
    print("FAIL: closing brace of sx1302_lora_syncword not found")
    sys.exit(1)

INSERT = """

/* ── Meshpoint Step 2 additions ──────────────────────────────────────
 *
 * sx1302_lora_syncword_pair(): write the multi-SF (SF5/6/7-12) demod
 * group sync word independently of the single-SF (LoRa Service) demod
 * sync word, enabling simultaneous capture of two protocols at different
 * sync words on the same SX1302.
 *
 * Sync word byte -> peak position encoding (matches Semtech LoRaWAN
 * private/public mapping): peak1 = (sw>>4) * 2, peak2 = (sw & 0x0F) * 2.
 *   0x12 -> 2,4   (LoRaWAN private)
 *   0x34 -> 6,8   (LoRaWAN public)
 *   0x2B -> 4,22  (Meshtastic)
 *   0x42 -> 8,4   (Reticulum)
 *
 * sx1302_set_tx_syncword(): update the sx1302_tx_sw_peak1/2 globals
 * that the (already patched) TX path reads from. Call immediately
 * before each lgw_send() to override the sync word for that packet.
 */

int sx1302_lora_syncword_pair(uint8_t multi_sf_sw, uint8_t single_sf_sw) {
    int err = 0;
    uint8_t multi_p1  = ((multi_sf_sw  >> 4) & 0x0F) * 2;
    uint8_t multi_p2  =  (multi_sf_sw        & 0x0F) * 2;
    uint8_t single_p1 = ((single_sf_sw >> 4) & 0x0F) * 2;
    uint8_t single_p2 =  (single_sf_sw       & 0x0F) * 2;

    /* Default TX uses the multi-SF sync word; per-packet override via
     * sx1302_set_tx_syncword() if the caller needs a different value. */
    sx1302_tx_sw_peak1 = multi_p1;
    sx1302_tx_sw_peak2 = multi_p2;

    /* Multi-SF demod groups (SF5, SF6, SF7-SF12) all share one sync */
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF5_PEAK1_POS_SF5,        multi_p1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF5_PEAK2_POS_SF5,        multi_p2);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF6_PEAK1_POS_SF6,        multi_p1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF6_PEAK2_POS_SF6,        multi_p2);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH0_SF7TO12_PEAK1_POS_SF7TO12, multi_p1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_FRAME_SYNCH1_SF7TO12_PEAK2_POS_SF7TO12, multi_p2);

    /* Single-SF (LoRa Service) demod with potentially different sync */
    err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS, single_p1);
    err |= lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH1_PEAK2_POS, single_p2);

    return err;
}

int sx1302_set_tx_syncword(uint8_t sw) {
    sx1302_tx_sw_peak1 = ((sw >> 4) & 0x0F) * 2;
    sx1302_tx_sw_peak2 = ( sw       & 0x0F) * 2;
    return 0;
}
"""

new_s = s[:end] + INSERT + s[end:]
Path(sys.argv[1]).write_text(new_s)
print("OK: Step 2 pair-sync + TX-override patch applied")
STEP2PATCH
fi

# Add forward declarations to the public HAL header so callers (and
# our Python wrapper via ctypes) can use the new symbols.
HAL_HDR="$HAL_DIR/libloragw/inc/loragw_sx1302.h"
if [ -f "$HAL_HDR" ] && ! grep -q "sx1302_lora_syncword_pair" "$HAL_HDR"; then
    info "Adding Step 2 prototypes to $HAL_HDR"
    python3 - "$HAL_HDR" <<'HDRPATCH'
import sys
from pathlib import Path

f = Path(sys.argv[1])
s = f.read_text()

DECL = (
    "\n/* Meshpoint Step 2: pair-sync RX + per-packet TX sync override */\n"
    "int sx1302_lora_syncword_pair(uint8_t multi_sf_sw, uint8_t single_sf_sw);\n"
    "int sx1302_set_tx_syncword(uint8_t sw);\n"
)

# Insert just before the include guard's closing #endif
end_idx = s.rfind("#endif")
if end_idx < 0:
    print("FAIL: no #endif found in header")
    sys.exit(1)

new_s = s[:end_idx] + DECL + "\n" + s[end_idx:]
Path(sys.argv[1]).write_text(new_s)
print("OK: prototypes added to header")
HDRPATCH
fi

info "Compiling libloragw (this takes a few minutes)..."
cd "$HAL_DIR"
mkdir -p pic_obj

for src in libtools/src/*.c; do
    gcc -c -O2 -fPIC -Wall -Wextra -std=c99 \
        -Ilibtools/inc -Ilibtools \
        "$src" -o "pic_obj/$(basename "${src%.c}.o")"
done

for src in libloragw/src/*.c; do
    gcc -c -O2 -fPIC -Wall -Wextra -std=c99 \
        -Ilibloragw/inc -Ilibloragw -Ilibtools/inc \
        "$src" -o "pic_obj/$(basename "${src%.c}.o")"
done

gcc -shared -o libloragw/libloragw.so pic_obj/*.o -lrt -lm -lpthread

cp libloragw/libloragw.so "$LIB_DEST"
ldconfig

info "Done. Restart meshpoint: sudo systemctl restart meshpoint"
