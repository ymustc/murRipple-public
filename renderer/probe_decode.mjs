/** base64 → Uint8Array。与 murripple.envelope.encode_u8 配对。 */
export function decodeU8(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** 命令行自检：node probe_decode.mjs <base64>，打印逗号分隔的字节。 */
if (typeof process !== "undefined" && process.argv && process.argv[2]) {
  console.log(Array.from(decodeU8(process.argv[2])).join(","));
}
