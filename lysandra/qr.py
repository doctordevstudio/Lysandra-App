"""Small dependency-free QR code encoder (byte mode, ECC level M, versions 1-10)
plus a PNG writer. Used to attach the UPI payment QR to Telegram messages."""
import struct
import zlib

# (total codewords, ec codewords per block, [(num blocks, data cw per block), ...]) for level M
_EC_M = {
    1: (26, 10, [(1, 16)]), 2: (44, 16, [(1, 28)]), 3: (70, 26, [(1, 44)]),
    4: (100, 18, [(2, 32)]), 5: (134, 24, [(2, 43)]), 6: (172, 16, [(4, 27)]),
    7: (196, 18, [(4, 31)]), 8: (242, 22, [(2, 38), (2, 39)]),
    9: (292, 22, [(3, 36), (2, 37)]), 10: (346, 26, [(4, 43), (1, 44)]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
          7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n):
    g = [1]
    for i in range(n):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _gmul(c, _EXP[i])
        g = ng
    return g


def _rs_encode(data, n):
    gen = _rs_generator(n)
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        if f:
            for i in range(n):
                rem[i] ^= _gmul(gen[i + 1], f)
    return rem


def _bits_for(version, data):
    bits = [0, 1, 0, 0]
    cc = 8 if version < 10 else 16
    for i in range(cc - 1, -1, -1):
        bits.append((len(data) >> i) & 1)
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _pick_version(data):
    for v in range(1, 11):
        cap = sum(n * d for n, d in _EC_M[v][2]) * 8
        need = 4 + (8 if v < 10 else 16) + len(data) * 8
        if need <= cap:
            return v
    raise ValueError("data too long for built-in QR encoder")


def _codewords(version, data):
    total, ecn, blocks = _EC_M[version]
    cap = sum(n * d for n, d in blocks) * 8
    bits = _bits_for(version, data)
    bits += [0] * min(4, cap - len(bits))
    while len(bits) % 8:
        bits.append(0)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(cw) < cap // 8:
        cw.append(pad[i % 2])
        i += 1
    dblocks, eblocks, pos = [], [], 0
    for n, d in blocks:
        for _ in range(n):
            blk = cw[pos:pos + d]
            pos += d
            dblocks.append(blk)
            eblocks.append(_rs_encode(blk, ecn))
    out = []
    for i in range(max(len(b) for b in dblocks)):
        for b in dblocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ecn):
        for b in eblocks:
            out.append(b[i])
    return out


def _format_bits(mask):
    data = (0b00 << 3) | mask  # level M = 00
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def _version_bits(version):
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return (version << 12) | rem


def _build(version, codewords, mask):
    n = version * 4 + 17
    m = [[None] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def setf(x, y, v):
        if 0 <= x < n and 0 <= y < n:
            m[y][x] = v
            fn[y][x] = True

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                d = max(abs(dx), abs(dy))
                setf(cx + dx, cy + dy, d not in (2, 4))

    finder(3, 3); finder(n - 4, 3); finder(3, n - 4)
    for i in range(8, n - 8):
        setf(i, 6, i % 2 == 0)
        setf(6, i, i % 2 == 0)
    pos = _ALIGN[version]
    for ay in pos:
        for ax in pos:
            if (ax == 6 and ay == 6) or (ax == 6 and ay == n - 7) or (ax == n - 7 and ay == 6):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
    fb = _format_bits(mask)
    for i in range(15):
        bit = (fb >> i) & 1 == 1
        if i < 6:
            setf(8, i, bit)
        elif i < 8:
            setf(8, i + 1, bit)
        else:
            setf(8, n - 15 + i, bit)
        if i < 8:
            setf(n - 1 - i, 8, bit)
        elif i < 9:
            setf(15 - i, 8, bit)
        else:
            setf(14 - i, 8, bit)
    setf(8, n - 8, True)
    if version >= 7:
        vb = _version_bits(version)
        for i in range(18):
            bit = (vb >> i) & 1 == 1
            a, b = n - 11 + i % 3, i // 3
            setf(a, b, bit)
            setf(b, a, bit)
    bits = []
    for c in codewords:
        for i in range(7, -1, -1):
            bits.append((c >> i) & 1)
    idx = 0
    x = n - 1
    upward = True
    while x > 0:
        if x == 6:
            x -= 1
        ys = range(n - 1, -1, -1) if upward else range(n)
        for y in ys:
            for dx in (0, 1):
                xx = x - dx
                if not fn[y][xx]:
                    bit = bits[idx] == 1 if idx < len(bits) else False
                    idx += 1
                    inv = [(xx + y) % 2 == 0, y % 2 == 0, xx % 3 == 0, (xx + y) % 3 == 0,
                           (xx // 3 + y // 2) % 2 == 0, (xx * y) % 2 + (xx * y) % 3 == 0,
                           ((xx * y) % 2 + (xx * y) % 3) % 2 == 0, ((xx + y) % 2 + (xx * y) % 3) % 2 == 0][mask]
                    m[y][xx] = bit ^ inv
        x -= 2
        upward = not upward
    return [[bool(c) for c in row] for row in m]


def _penalty(m):
    n = len(m)
    score = 0
    for rows in (m, [list(r) for r in zip(*m)]):
        for row in rows:
            run = 1
            for i in range(1, n):
                if row[i] == row[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run = 1
            if run >= 5:
                score += run - 2
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    pat = [True, False, True, True, True, False, True, False, False, False, False]
    for rows in (m, [list(r) for r in zip(*m)]):
        for row in rows:
            for i in range(n - 10):
                seg = row[i:i + 11]
                if seg == pat or seg == pat[::-1]:
                    score += 40
    dark = sum(sum(r) for r in m)
    score += (abs(dark * 20 - n * n * 10) // (n * n)) * 10
    return score


def make_matrix(text):
    data = text.encode("utf-8")
    version = _pick_version(data)
    cws = _codewords(version, data)
    best = None
    for mask in range(8):
        m = _build(version, cws, mask)
        p = _penalty(m)
        if best is None or p < best[0]:
            best = (p, m)
    return best[1]


def make_png(text, scale=8, border=4):
    m = make_matrix(text)
    n = len(m)
    size = (n + border * 2) * scale
    rows = []
    for py in range(size):
        y = py // scale - border
        row = bytearray([0])
        for px in range(size):
            x = px // scale - border
            dark = 0 <= x < n and 0 <= y < n and m[y][x]
            row.append(0 if dark else 255)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
