# Tarjim wire protocol v1

Laptop (client) to TV overlay app (server). Implemented in
`laptop/tarjim/protocol.py` + `tvlink.py` (client), `tv-app/.../Wire.kt` +
`OverlayServer.kt` (TV), and `laptop/tarjim/faketv.py` (test double).

## Transport

- TCP. The TV listens on port **47800**. One client at a time; a new
  connection replaces the old one and clears all layers.
- Frame: `uint32 BE json_len`, `uint32 BE bin_len`, JSON header (UTF-8),
  binary payload.
- Limits: `1 <= json_len <= 65536`, `bin_len <= 8 MiB`. The header is a JSON
  object with a string `type`.
- A malformed frame or message closes the connection. It never crashes the
  service; the server keeps accepting clients.
- Coordinates are overlay pixels of the target window (the size reported in
  `hello_ack`). The laptop does all mapping and calibration.
- TV timestamps (`tv_ts`, `t_recv`, `t_decoded`, `t_drawn`) are milliseconds
  of the TV's monotonic clock (`SystemClock.elapsedRealtime`). Laptop
  timestamps are `time.monotonic()` in ms.

## Messages

| type | direction | fields |
| --- | --- | --- |
| `hello` | laptop to TV | `v` (must be 1) |
| `hello_ack` | TV to laptop | `v`, `w`, `h`, `density`, `sdk`, `model`, `windows` (subset of `["A","B"]`, the windows that exist right now) |
| `ping` | laptop to TV | `ts` |
| `pong` | TV to laptop | `ts` (echo), `tv_ts` |
| `show` | laptop to TV | `seq`, `win` (`"A"` or `"B"`), `layers[]`; payload = the PNGs back to back |
| `keep` | laptop to TV | `ids[]` |
| `clear` | laptop to TV | `ids[]` or `all: true`; `fade_ms` |
| `ack` | TV to laptop | `seq`, `t_recv`, `t_decoded`, `t_drawn`, `status` |

Layer entry in `show`: `id` (non-empty string), `z`, `x`, `y`, `w`, `h`,
`ttl_ms` (> 0), `fade_ms` (fade-in), `offset`, `len` (byte range of its PNG in
the payload). The PNG must decode to exactly `w` x `h`; it is drawn 1:1.

## Rules

- Limits: 1 to 4 layers per `show`, at most 4 layers per window, each at most
  1920 x 480 px. Breaking a limit closes the connection.
- All layers of one `show` appear in the same draw.
- A layer id is replaced when shown again. An older `seq` never replaces a
  newer one; a `show` whose layers were all superseded while waiting to be
  decoded is acked with `status: "superseded"` and `t_drawn: null`.
- `ack.status`: `drawn`, `superseded`, or `no_window` (the target window does
  not exist on this TV; `t_drawn` is null).
- `keep` restarts the TTL of the listed layers without resending pixels.
- `clear` with `fade_ms > 0` fades the layers out, then removes them.

## Fail-safe

- Every layer has a TTL; expired layers are removed (checked every 100 ms).
- The laptop pings every 300 ms. If the TV receives no message for 1000 ms it
  clears everything.
- On disconnect, on a replaced connection and on service stop the TV clears
  everything; on service stop it also removes its window.

## Clock offset

`offset = tv_ts - (ts + rtt / 2)`, taken from the pong with the smallest round
trip. `t_tv_drawn` in laptop time is `t_drawn - offset`.
