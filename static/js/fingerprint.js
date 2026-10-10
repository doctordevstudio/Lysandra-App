/* Lightweight client fingerprint -- not cryptographically unique, just
   stable enough to key the 3-attempts/24h login lockout to "this device". */
function computeFingerprint() {
  const parts = [
    navigator.userAgent,
    navigator.language,
    screen.width + "x" + screen.height,
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    navigator.hardwareConcurrency || "",
  ];
  try {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    ctx.textBaseline = "top";
    ctx.font = "14px Arial";
    ctx.fillText("lysandra-fp", 2, 2);
    parts.push(canvas.toDataURL());
  } catch (e) { /* canvas blocked -- fine, rest of the signal is enough */ }

  let hash = 0;
  const str = parts.join("|");
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return "fp_" + Math.abs(hash).toString(36) + "_" + str.length;
}
